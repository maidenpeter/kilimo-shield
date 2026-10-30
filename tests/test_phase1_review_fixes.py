"""Remaining brief, Phase 1: the approved review fixes.

1. M-Pesa payments left unconfirmed are re-checked with backoff until confirmed or failed, flagged for a person
   if still unknown, and a payment started before the sales close still counts toward cover.
2. Weather advisories: a SACCO manager approves or withdraws only their own SACCO's; the ones shown to every
   SACCO belong to the new AgroShield operations role (ops).
3. Session cookies: Secure (with HttpOnly and SameSite=Lax) when the deployment runs over HTTPS.
4. Settlement: collected is gross, refunds owed and paid are tracked separately, remittance is gross, and the
   receiving paybill is a per-insurer setting.

All people are fictional.
"""
import dataclasses
import html
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from agroshield_platform import mpesa as mp
from agroshield_platform import services as sv
from agroshield_platform import settlement as stl
from agroshield_platform import weather as wx
from agroshield_platform.crypto import hash_password
from agroshield_platform.db import transaction
from agroshield_platform.models import (AuditEvent, Insurer, MpesaRequest, Officer, Payment, Policy, Refund, Sacco,
                                        WeatherItem)
from agroshield_platform.web.app import create_app

from conftest import REPO
from test_platform import PASSWORD, TODAY, app, book, csrf_of, db, inp, login, settings, vault  # noqa: F401

PDF = b"%PDF-1.4\n% fictional test advisory\n"


@pytest.fixture
def ctx(cfg, book, vault):  # noqa: F811
    return sv.Context(cfg, book, vault, today=TODAY, mpesa=mp.SimulatedDaraja())


def _enrol(ctx, s, **over):
    sacco = s.scalar(select(Sacco).where(Sacco.code == "TST01"))
    if sacco is None:
        sacco = Sacco(code="TST01", name="Test SACCO", is_demo=True)
        s.add(sacco)
        s.flush()
    return sv.enrol(ctx, s, sacco, None, inp(**over))


def _at(ctx, day, minutes=0):
    """A context whose "now" is a given day, plus a time we control."""
    c = dataclasses.replace(ctx, today=day)
    return c, datetime.combine(day, datetime.min.time(), tzinfo=sv.NAIROBI) + timedelta(hours=9, minutes=minutes)


class AnsweringDaraja(mp.SimulatedDaraja):
    """STK query answers we choose: None (no answer yet), 0 (paid) or a failure code. Can also raise."""
    def __init__(self, answers=None, boom=False):
        super().__init__()
        self.answers, self.boom, self.asked = list(answers or []), boom, 0

    def stk_query(self, checkout_request_id):
        self.asked += 1
        if self.boom:
            raise ConnectionError("Safaricom down")
        code = self.answers.pop(0) if self.answers else None
        return {"result_code": code, "result_desc": "test"}


# ------------------------------------------------------------------ 1. M-Pesa re-check
def test_no_answer_is_rechecked_with_backoff_then_flagged(ctx, db):
    ctx.mpesa = AnsweringDaraja()
    with transaction(db) as s:
        pol = _enrol(ctx, s)
        req = mp.request_premium(ctx, s, pol, 800, "officer")
        start = mp._aware(req.created_at)
        assert mp._aware(req.next_query_at) == start + timedelta(minutes=mp.RECHECK_MINUTES[0])
        assert mp.recheck(ctx, s, now=start + timedelta(minutes=1))["checked"] == 0          # not due yet
        for i, minutes in enumerate(mp.RECHECK_MINUTES, start=1):
            res = mp.recheck(ctx, s, now=start + timedelta(minutes=minutes))
            assert res["checked"] == 1 and req.query_attempts == i
            if i < len(mp.RECHECK_MINUTES):
                assert res["waiting"] == 1 and req.status == "pending"
                assert mp._aware(req.next_query_at) == start + timedelta(minutes=mp.RECHECK_MINUTES[i])
        assert req.status == "unconfirmed" and res["flagged"] == 1 and req.next_query_at is None
        assert ctx.mpesa.asked == len(mp.RECHECK_MINUTES)
        assert mp.recheck(ctx, s, now=start + timedelta(days=3))["checked"] == 0            # no endless retries
        assert pol.paid_kes == 0
        assert mp.unconfirmed(s, pol.sacco_id) == [req]
        assert s.scalar(select(AuditEvent).where(AuditEvent.action == "mpesa.unconfirmed_flagged"))


def test_query_confirms_a_push_whose_callback_never_came(ctx, db):
    ctx.mpesa = AnsweringDaraja([None, 0])
    with transaction(db) as s:
        pol = _enrol(ctx, s)
        req = mp.request_premium(ctx, s, pol, pol.amount_due_kes, "officer")
        start = mp._aware(req.created_at)
        mp.recheck(ctx, s, now=start + timedelta(minutes=2))
        assert mp.recheck(ctx, s, now=start + timedelta(minutes=5))["paid"] == 1
        assert req.status == "paid" and pol.status == "active" and pol.paid_kes == pol.amount_due_kes
        pay = s.scalar(select(Payment).where(Payment.policy_id == pol.id))
        assert pay.reference == req.checkout_request_id and pay.method == "mpesa"
        assert "no receipt number" in req.result_desc


def test_query_refusal_fails_the_push(ctx, db):
    ctx.mpesa = AnsweringDaraja([1032])
    with transaction(db) as s:
        pol = _enrol(ctx, s)
        req = mp.request_premium(ctx, s, pol, 800, "officer")
        assert mp.recheck(ctx, s, now=mp._aware(req.created_at) + timedelta(minutes=2))["failed"] == 1
        assert req.status == "failed" and req.result_code == 1032 and pol.paid_kes == 0


def test_query_errors_count_as_no_answer(ctx, db):
    ctx.mpesa = AnsweringDaraja(boom=True)
    with transaction(db) as s:
        pol = _enrol(ctx, s)
        req = mp.request_premium(ctx, s, pol, 800, "officer")
        assert mp.recheck(ctx, s, now=mp._aware(req.created_at) + timedelta(minutes=2))["waiting"] == 1
        assert req.status == "pending" and "query error" in req.last_query_result


def test_unconfirmed_success_callback_is_kept_and_credited_later(ctx, db):
    client = AnsweringDaraja([None, 0])          # the callback's own check: no answer; the re-check: paid
    client.confirm_with_query = True
    ctx.mpesa = client
    with transaction(db) as s:
        pol = _enrol(ctx, s)
        req = mp.request_premium(ctx, s, pol, 800, "officer")
        cb = mp.SimulatedDaraja().simulate_callback(req, success=True)
        receipt = cb["Body"]["stkCallback"]["CallbackMetadata"]["Item"][1]["Value"]
        assert mp.handle_callback(ctx, s, cb)["outcome"] == "unconfirmed"
        assert req.status == "pending" and req.callback_receipt == receipt and pol.paid_kes == 0
        assert mp.recheck(ctx, s, now=mp._aware(req.created_at) + timedelta(minutes=2))["paid"] == 1
        assert pol.paid_kes == 800 and s.scalar(select(Payment.reference)) == receipt


def test_a_callback_the_query_contradicts_is_flagged_not_failed(ctx, db):
    client = AnsweringDaraja([None] + [1032] * len(mp.RECHECK_MINUTES))
    client.confirm_with_query = True
    ctx.mpesa = client
    with transaction(db) as s:
        pol = _enrol(ctx, s)
        req = mp.request_premium(ctx, s, pol, 800, "officer")
        mp.handle_callback(ctx, s, mp.SimulatedDaraja().simulate_callback(req, success=True))
        start = mp._aware(req.created_at)
        for minutes in mp.RECHECK_MINUTES:
            mp.recheck(ctx, s, now=start + timedelta(minutes=minutes))
        assert req.status == "unconfirmed" and pol.paid_kes == 0          # a person decides, nothing silent


def test_payment_started_before_close_and_confirmed_after_counts_toward_cover(ctx, db):
    ctx.mpesa = AnsweringDaraja([None, None, 0])
    with transaction(db) as s:
        pol = _enrol(ctx, s)
        close = pol.sales_closes_on
        on_close, _ = _at(ctx, close)
        req = mp.request_premium(on_close, s, pol, pol.amount_due_kes, "officer")      # started on the close day
        start = mp._aware(req.created_at)
        after, _ = _at(ctx, close + timedelta(days=1))
        mp.recheck(after, s, now=start + timedelta(minutes=2))
        # The daily lapse job runs the day after close while the answer is still unknown: it waits.
        assert sv.close_sales_windows(after, s)["lapse_deferred"] == 1 and pol.status == "pending_payment"
        mp.recheck(after, s, now=start + timedelta(minutes=5))
        assert mp.recheck(after, s, now=start + timedelta(minutes=15))["paid"] == 1
        pay = s.scalar(select(Payment).where(Payment.policy_id == pol.id))
        assert pay.within_window and pol.status == "active" and pol.refund_due_kes == 0
        assert pay.received_at.date() > close if pay.received_at.tzinfo is None else \
            pay.received_at.astimezone(sv.NAIROBI).date() > close


def test_failed_push_after_close_lets_the_lapse_happen(ctx, db):
    ctx.mpesa = AnsweringDaraja([1032])
    with transaction(db) as s:
        pol = _enrol(ctx, s)
        close = pol.sales_closes_on
        on_close, _ = _at(ctx, close)
        req = mp.request_premium(on_close, s, pol, 800, "officer")
        after, _ = _at(ctx, close + timedelta(days=1))
        assert sv.close_sales_windows(after, s)["lapse_deferred"] == 1
        mp.recheck(after, s, now=mp._aware(req.created_at) + timedelta(minutes=2))
        res = sv.close_sales_windows(dataclasses.replace(after, today=close + timedelta(days=2)), s)
        assert res["lapsed"] == 1 and pol.status == "lapsed_unpaid"


def test_late_push_cannot_be_started(ctx, db):
    with transaction(db) as s:
        pol = _enrol(ctx, s)
        after, _ = _at(ctx, pol.sales_closes_on + timedelta(days=1))
        with pytest.raises(sv.PaymentError, match="sales closed"):
            mp.request_premium(after, s, pol, 800, "officer")


def _flagged(app):
    """One fictional member at TST01 with an M-Pesa payment flagged unconfirmed."""
    from agroshield_pricing.config import load_config
    cfg = load_config(REPO / "config")
    ctx = sv.Context(cfg, app.state.state["book"], app.state.vault, today=TODAY, mpesa=app.state.state["mpesa"])
    with transaction(app.state.factory) as s:
        sacco = s.scalar(select(Sacco).where(Sacco.code == "TST01"))
        pol = sv.enrol(ctx, s, sacco, None, inp())
        req = mp.request_premium(ctx, s, pol, 800, "officer")
        req.status, req.next_query_at, req.query_attempts = "unconfirmed", None, len(mp.RECHECK_MINUTES)
        return req.id, pol.id, pol.farmer_id


def test_flag_shows_on_officer_home_and_manager_reports(app):  # noqa: F811
    rid, pid, fid = _flagged(app)
    c = TestClient(app)
    login(c, "officer")
    home = c.get("/dashboard").text
    assert "Payment not confirmed: check with the farmer" in home and f"/mpesa/{rid}/resolve" not in home
    m = TestClient(app)
    login(m, "manager")
    rep = m.get("/reports").text
    assert "Payment not confirmed: check with the farmer" in rep and f"/mpesa/{rid}/resolve" in rep
    o = TestClient(app)
    login(o, "other")                                                        # another SACCO's manager
    assert "Payment not confirmed" not in o.get("/reports").text


def test_manager_resolves_with_the_farmers_receipt(app):  # noqa: F811
    rid, pid, fid = _flagged(app)
    m = TestClient(app)
    tok = login(m, "manager")
    m.post(f"/mpesa/{rid}/resolve", data={"csrf_token": tok, "outcome": "paid", "receipt": "bad"})
    with transaction(app.state.factory) as s:
        assert s.get(MpesaRequest, rid).status == "unconfirmed"                 # receipt format refused
    r = m.post(f"/mpesa/{rid}/resolve", data={"csrf_token": tok, "outcome": "paid", "receipt": "skl2abc3de"},
               follow_redirects=False)
    assert r.status_code == 303
    with transaction(app.state.factory) as s:
        req = s.get(MpesaRequest, rid)
        assert req.status == "paid" and req.resolution == "paid" and req.resolved_by == "manager"
        assert s.scalar(select(Payment.reference).where(Payment.policy_id == pid)) == "SKL2ABC3DE"
        assert s.scalar(select(AuditEvent).where(AuditEvent.action == "mpesa.resolved")).details["outcome"] == "paid"
    assert "Payment not confirmed" not in m.get("/reports").text


def test_resolve_not_paid_and_access_rules(app):  # noqa: F811
    rid, pid, fid = _flagged(app)
    off = TestClient(app)
    tok = login(off, "officer")
    assert off.post(f"/mpesa/{rid}/resolve", data={"csrf_token": tok, "outcome": "not_paid"}).status_code == 403
    other = TestClient(app)
    tok = login(other, "other")
    assert other.post(f"/mpesa/{rid}/resolve", data={"csrf_token": tok, "outcome": "not_paid"}).status_code == 404
    m = TestClient(app)
    tok = login(m, "manager")
    m.post(f"/mpesa/{rid}/resolve", data={"csrf_token": tok, "outcome": "not_paid", "note": "farmer had no balance"})
    with transaction(app.state.factory) as s:
        req = s.get(MpesaRequest, rid)
        assert req.status == "failed" and req.resolution == "not_paid" and s.get(Policy, pid).paid_kes == 0


# ------------------------------------------------------------------ 2. weather approval scope
@pytest.fixture
def wapp(app):  # noqa: F811
    with transaction(app.state.factory) as s:
        s.add(Officer(username="ops", display_name="Ops One", role="ops", password_hash=hash_password(PASSWORD)))
    return app


def _login_any(c, username):
    tok = csrf_of(c.get("/login").text)
    assert c.post("/login", data={"username": username, "password": PASSWORD, "csrf_token": tok},
                  follow_redirects=False).status_code == 303
    return tok


def _upload(c, tok, title):
    valid = {"valid_from": (TODAY - timedelta(days=1)).isoformat(), "valid_to": (TODAY + timedelta(days=5)).isoformat()}
    return c.post("/weather/upload", data={"csrf_token": tok, "title": title, **valid},
                  files={"file": ("a.pdf", PDF + title.encode(), "application/pdf")}, follow_redirects=False)


def _approve(c, tok, item_id):
    return c.post(f"/weather/{item_id}/approve", data={"csrf_token": tok, "summary_en": "Light rain this week.",
                                                        "summary_sw": "Mvua kidogo wiki hii."}, follow_redirects=False)


def test_managers_approve_only_their_own_saccos_advisories(wapp):
    m, other = TestClient(wapp), TestClient(wapp)
    tok, otok = login(m, "manager"), login(other, "other")
    assert _upload(m, tok, "TST01 forecast").status_code == 303
    with transaction(wapp.state.factory) as s:
        item = s.scalar(select(WeatherItem))
        tst = s.scalar(select(Sacco).where(Sacco.code == "TST01"))
        assert item.sacco_id == tst.id
    assert "TST01 forecast" not in other.get("/weather").text                     # another SACCO cannot see a draft
    assert _approve(other, otok, item.id).status_code == 404
    assert other.post(f"/weather/{item.id}/withdraw", data={"csrf_token": otok}).status_code == 404
    assert _approve(m, tok, item.id).status_code == 303
    off = TestClient(wapp)
    login(off, "officer")
    assert "Light rain this week." in off.get("/dashboard").text                  # own SACCO's officers see it
    assert "Light rain this week." not in other.get("/dashboard").text             # the other SACCO does not
    assert m.post(f"/weather/{item.id}/withdraw", data={"csrf_token": tok}, follow_redirects=False).status_code == 303


def test_every_sacco_advisories_need_agroshield_operations(wapp):
    ops, m, other = TestClient(wapp), TestClient(wapp), TestClient(wapp)
    otok = _login_any(ops, "ops")
    assert ops.get("/dashboard", follow_redirects=False).headers["location"] == "/weather"   # not a SACCO page
    otok = csrf_of(ops.get("/weather").text)
    assert _upload(ops, otok, "Every SACCO forecast").status_code == 303
    with transaction(wapp.state.factory) as s:
        item = s.scalar(select(WeatherItem))
        assert item.sacco_id is None
    tok = login(m, "manager")
    assert _approve(m, tok, item.id).status_code == 404                          # a draft is not shown to managers
    assert _approve(ops, otok, item.id).status_code == 303
    r = _approve(m, tok, item.id)
    assert r.status_code == 403
    assert m.post(f"/weather/{item.id}/withdraw", data={"csrf_token": tok}).status_code == 403
    assert m.post("/weather/fetch", data={"csrf_token": tok}).status_code == 403    # fetched items are every-SACCO
    for c, who in ((m, "manager"), (other, "other")):
        if who == "other":
            login(c, who)
        assert "Light rain this week." in c.get("/dashboard").text                # shown in every SACCO
    page = m.get("/weather").text
    assert "Looked after by AgroShield operations" in page
    assert ops.post(f"/weather/{item.id}/withdraw", data={"csrf_token": otok}, follow_redirects=False).status_code == 303
    with transaction(wapp.state.factory) as s:
        assert s.get(WeatherItem, item.id).status == "withdrawn"
        assert s.scalar(select(AuditEvent).where(AuditEvent.action == "weather.withdrawn")).actor == "ops"


def test_visible_items_scope(db, tmp_path):
    _, sources = wx.load_sources(REPO / "config")
    with transaction(db) as s:
        a, b = Sacco(code="A1", name="A", is_demo=True), Sacco(code="B1", name="B", is_demo=True)
        s.add_all([a, b])
        s.flush()
        every = wx.store_pdf(s, tmp_path, sources["kmd_nakuru"], PDF + b"1", "every", None, "fetched")
        only_a = wx.store_pdf(s, tmp_path, sources["kmd_nakuru"], PDF + b"2", "a", None, "uploaded", sacco_id=a.id)
        for i in (every, only_a):
            wx.approve(s, i, "x", "y", "t")
        today = every.approved_at.date()
        assert set(wx.visible_items(s, today, [a.id])) == {every, only_a}
        assert wx.visible_items(s, today, [b.id]) == [every]
        assert wx.visible_items(s, today) == [every]


# ------------------------------------------------------------------ 3. session cookie
def _cookie_after_login(app):
    c = TestClient(app, base_url="https://testserver")
    tok = csrf_of(c.get("/login").text)
    r = c.post("/login", data={"username": "officer", "password": PASSWORD, "csrf_token": tok}, follow_redirects=False)
    return r.headers["set-cookie"].lower()


def test_session_cookie_is_secure_over_https(settings, book):  # noqa: F811
    app = create_app(dataclasses.replace(settings, https=True), book, today=TODAY)
    with transaction(app.state.factory) as s:
        sacco = Sacco(code="TST01", name="Test SACCO", is_demo=True)
        s.add(sacco)
        s.flush()
        s.add(Officer(sacco_id=sacco.id, username="officer", display_name="O", role="officer",
                      password_hash=hash_password(PASSWORD)))
    cookie = _cookie_after_login(app)
    assert "secure" in cookie and "httponly" in cookie and "samesite=lax" in cookie


def test_session_cookie_without_https_is_still_httponly_and_lax(app):  # noqa: F811
    cookie = _cookie_after_login(app)
    assert "httponly" in cookie and "samesite=lax" in cookie and "secure" not in cookie


def test_https_setting_from_the_environment(monkeypatch):
    from agroshield_platform.settings import load_settings
    monkeypatch.setenv("AGROSHIELD_HTTPS", "true")
    assert load_settings().https is True
    monkeypatch.setenv("AGROSHIELD_HTTPS", "false")
    assert load_settings().https is False


# ------------------------------------------------------------------ 4. settlement: gross, refunds, paybill
@pytest.fixture
def money(app, cfg):  # noqa: F811
    """TST01 linked to an insurer; one member overpays by KES 300, so 300 is owed back."""
    ctx = sv.Context(cfg, app.state.state["book"], app.state.vault, today=TODAY, mpesa=app.state.state["mpesa"])
    with transaction(app.state.factory) as s:
        ins = Insurer(code="UWX", name="Insurer X (fictional)", is_demo=True)
        s.add(ins)
        s.flush()
        sacco = s.scalar(select(Sacco).where(Sacco.code == "TST01"))
        sacco.insurer_id = ins.id
        s.add(Officer(insurer_id=ins.id, username="uw", display_name="UW", role="underwriter",
                      password_hash=hash_password(PASSWORD)))
        pol = sv.enrol(ctx, s, sacco, None, inp())
        sv.record_payment(ctx, s, pol, pol.amount_due_kes + 300, "sacco_deduction", "DED-1", "manager")
        assert pol.refund_due_kes == 300
        return {"policy_id": pol.id, "farmer_id": pol.farmer_id, "paid": pol.amount_due_kes + 300, "ins": ins.id}


def test_collected_stays_gross_and_refunds_are_separate(app, money):  # noqa: F811
    with transaction(app.state.factory) as s:
        st = stl.summary(s, money["ins"])
        row = st["rows"][0]
        assert row["collected_kes"] == money["paid"]                             # gross: the 300 owed back is not netted
        assert row["outstanding_kes"] == money["paid"]                           # remit gross, no fee deducted first
        assert (row["refunds_owed_kes"], row["refunds_paid_kes"], row["refunds_outstanding_kes"]) == (300, 0, 300)
        assert st["paybill"] == "the insurer's paybill (to be configured)"
    m = TestClient(app)
    tok = login(m, "manager")
    page = html.unescape(m.get("/reports/premium").text)
    assert "the insurer's paybill (to be configured)" in page and "settled" in page and "separately" in page
    r = m.post(f"/policies/{money['policy_id']}/refund", data={"csrf_token": tok, "amount": "400", "paid_on": TODAY.isoformat(),
                                                               "method": "mpesa", "reference": "RFND-001"})
    assert r.status_code == 200 or r.status_code == 303
    with transaction(app.state.factory) as s:
        assert s.scalar(select(Refund)) is None                                  # more than owed: refused
    m.post(f"/policies/{money['policy_id']}/refund", data={"csrf_token": tok, "amount": "300", "paid_on": TODAY.isoformat(),
                                                           "method": "mpesa", "reference": "RFND-001"})
    with transaction(app.state.factory) as s:
        rf = s.scalar(select(Refund))
        assert rf.amount_kes == 300 and rf.recorded_by == "manager"
        row = stl.summary(s, money["ins"])["rows"][0]
        assert row["collected_kes"] == money["paid"] and row["refunds_paid_kes"] == 300
        assert row["refunds_outstanding_kes"] == 0
        assert s.get(Policy, money["policy_id"]).refund_due_kes == 300           # owed stays as recorded
        assert s.scalar(select(AuditEvent).where(AuditEvent.action == "refund.recorded"))
    assert "Refund paid in full" in m.get(f"/members/{money['farmer_id']}").text
    csv_text = m.get("/reports/premium.csv").text
    assert "refunds_owed_kes" in csv_text and "refunds_paid_kes" in csv_text


def test_only_the_saccos_manager_records_refunds(app, money):  # noqa: F811
    off, other = TestClient(app), TestClient(app)
    tok = login(off, "officer")
    data = {"amount": "100", "paid_on": TODAY.isoformat(), "method": "mpesa", "reference": "RFND-9"}
    assert off.post(f"/policies/{money['policy_id']}/refund", data={**data, "csrf_token": tok}).status_code == 403
    otok = login(other, "other")
    assert other.post(f"/policies/{money['policy_id']}/refund", data={**data, "csrf_token": otok}).status_code == 404


def test_paybill_is_a_per_insurer_setting(app, money, monkeypatch, tmp_path):  # noqa: F811
    from agroshield_platform import cli
    monkeypatch.setenv("DATABASE_URL", str(app.state.factory.kw["bind"].url))
    assert cli.main(["set-paybill", "--insurer", "UWX", "--paybill", "Paybill 000000, account AGRO (fictional)"]) == 0
    with transaction(app.state.factory) as s:
        assert stl.summary(s, money["ins"])["paybill"] == "Paybill 000000, account AGRO (fictional)"
        assert s.scalar(select(AuditEvent).where(AuditEvent.action == "insurer.paybill_set"))
    uw = TestClient(app)
    tok = csrf_of(uw.get("/login").text)
    uw.post("/login", data={"username": "uw", "password": PASSWORD, "csrf_token": tok})
    page = uw.get("/uw/money").text
    assert "Paybill 000000" in page and "Refunds owed" in page
