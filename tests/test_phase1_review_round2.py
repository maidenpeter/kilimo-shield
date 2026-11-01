"""Regression tests for the independent review of the Phase 1 commit (docs/remaining/REVIEW_PHASE1.md).

The M-Pesa tests commit and reload between steps, like the real callback, cron and daily runs do, so a value that
only survives in the session's memory cannot hide a bug. All people are fictional.
"""
import dataclasses
from datetime import datetime, time, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from agroshield_platform import mpesa as mp
from agroshield_platform import services as sv
from agroshield_platform import weather as wx
from agroshield_platform.db import transaction
from agroshield_platform.models import AuditEvent, MpesaRequest, Payment, Policy, Sacco, WeatherItem

from conftest import REPO
from test_phase1_review_fixes import PDF, AnsweringDaraja, _enrol, ctx, money, wapp, _upload, _login_any  # noqa: F401
from test_platform import TODAY, app, book, csrf_of, db, inp, login, settings, vault  # noqa: F401


def _push(ctx, db, at: datetime, amount=None, monkeypatch=None):
    """Enrol and send a push at a given Nairobi time; returns ids (everything committed)."""
    monkeypatch.setattr(sv.Context, "now", lambda self: datetime.combine(self.date(), at.timetz()))
    with transaction(db) as s:
        pol = _enrol(ctx, s)
        c = dataclasses.replace(ctx, today=at.date()) if at.date() != ctx.date() else ctx
        req = mp.request_premium(c, s, pol, amount or pol.amount_due_kes, "officer")
        return pol.id, req.id, pol.sales_closes_on


def test_late_evening_push_on_the_close_day_counts_after_reload(ctx, db, monkeypatch):
    # Enrol first (today), then push at 22:00 Nairobi time on the close day.
    with transaction(db) as s:
        close = _enrol(ctx, s, member_no="M-0001").sales_closes_on
    at = datetime.combine(close, time(22, 0), tzinfo=sv.NAIROBI)
    monkeypatch.setattr(sv.Context, "now", lambda self: datetime.combine(self.date(), at.timetz()))
    on_close = dataclasses.replace(ctx, today=close)
    with transaction(db) as s:
        pol = s.scalar(select(Policy))
        rid = mp.request_premium(on_close, s, pol, pol.amount_due_kes, "officer").id
    with transaction(db) as s:
        stored = s.get(MpesaRequest, rid).created_at
        assert mp._aware(stored) == at                               # stored in UTC, read back as the same instant
    after = dataclasses.replace(ctx, today=close + timedelta(days=1))
    with transaction(db) as s:
        assert sv.close_sales_windows(after, s)["lapse_deferred"] == 1
    with transaction(db) as s:
        req = s.get(MpesaRequest, rid)
        body = mp.SimulatedDaraja().simulate_callback(req, success=True)
    with transaction(db) as s:
        assert mp.handle_callback(after, s, body)["outcome"] == "paid"
    with transaction(db) as s:
        pol = s.scalar(select(Policy))
        pay = s.scalar(select(Payment))
        assert pay.within_window and pol.status == "active" and pol.refund_due_kes == 0


def test_recheck_is_due_on_time_after_reload(ctx, db):
    ctx.mpesa = AnsweringDaraja([None, 0])
    with transaction(db) as s:
        rid = mp.request_premium(ctx, s, _enrol(ctx, s), 800, "officer").id
    with transaction(db) as s:
        start = mp._aware(s.get(MpesaRequest, rid).created_at)
    with transaction(db) as s:
        assert mp.recheck(ctx, s, now=start + timedelta(minutes=1))["checked"] == 0
    with transaction(db) as s:
        assert mp.recheck(ctx, s, now=start + timedelta(minutes=2))["waiting"] == 1
    with transaction(db) as s:
        assert mp._aware(s.get(MpesaRequest, rid).next_query_at) == start + timedelta(minutes=5)
    assert mp.run_recheck(ctx, db, now=start + timedelta(minutes=5))["paid"] == 1     # one transaction per request
    with transaction(db) as s:
        assert s.get(MpesaRequest, rid).status == "paid"


class CallbackDuringQuery(mp.SimulatedDaraja):
    """Safaricom's callback lands (in its own transaction) while the re-check is waiting on the status query."""
    def __init__(self, ctx, db):
        super().__init__()
        self.ctx, self.db = ctx, db

    def stk_query(self, checkout_request_id):
        with transaction(self.db) as s:
            req = s.scalar(select(MpesaRequest).where(MpesaRequest.checkout_request_id == checkout_request_id))
            assert mp.handle_callback(self.ctx, s, mp.SimulatedDaraja().simulate_callback(req, True))["outcome"] == "paid"
        return {"result_code": 0, "result_desc": "paid"}


def test_callback_and_recheck_racing_credit_once(ctx, db):
    with transaction(db) as s:
        rid = mp.request_premium(ctx, s, _enrol(ctx, s), 800, "officer").id
    with transaction(db) as s:
        start = mp._aware(s.get(MpesaRequest, rid).created_at)
    plain = dataclasses.replace(ctx, mpesa=mp.SimulatedDaraja())
    ctx.mpesa = CallbackDuringQuery(plain, db)
    assert mp.run_recheck(ctx, db, now=start + timedelta(minutes=2))["checked"] == 0      # it saw the callback won
    with transaction(db) as s:
        assert s.scalar(select(func.count()).select_from(Payment)) == 1
        assert s.scalar(select(Policy)).paid_kes == 800


def test_claim_is_compare_and_set(ctx, db):
    with transaction(db) as s:
        req = mp.request_premium(ctx, s, _enrol(ctx, s), 800, "officer")
        assert mp._credit(ctx, s, req, 800.0, "SKL2ABC3DE", None, "x", "t")["outcome"] == "paid"
        assert mp._credit(ctx, s, req, 800.0, "SKL2ABC3DF", None, "x", "t")["outcome"] == "duplicate"
        assert s.scalar(select(func.count()).select_from(Payment)) == 1


def test_still_processing_is_not_a_failure(ctx, db):
    ctx.mpesa = AnsweringDaraja([4999] * len(mp.RECHECK_MINUTES))
    with transaction(db) as s:
        req = mp.request_premium(ctx, s, _enrol(ctx, s), 800, "officer")
        start = mp._aware(req.created_at)
        assert mp.recheck(ctx, s, now=start + timedelta(minutes=2))["waiting"] == 1 and req.status == "pending"
        for minutes in mp.RECHECK_MINUTES[1:]:
            mp.recheck(ctx, s, now=start + timedelta(minutes=minutes))
        assert req.status == "unconfirmed"


def test_late_callback_fills_the_receipt_and_the_receipt_cannot_be_reused(ctx, db):
    ctx.mpesa = AnsweringDaraja([0])
    with transaction(db) as s:
        pol = _enrol(ctx, s)
        req = mp.request_premium(ctx, s, pol, 800, "officer")
        mp.recheck(ctx, s, now=mp._aware(req.created_at) + timedelta(minutes=2))
        assert req.status == "paid" and req.receipt == req.checkout_request_id[:30]
        body = mp.SimulatedDaraja().simulate_callback(req, success=True)
        receipt = body["Body"]["stkCallback"]["CallbackMetadata"]["Item"][1]["Value"]
        assert mp.handle_callback(ctx, s, body)["outcome"] == "receipt_recorded"
        assert req.receipt == receipt and pol.paid_kes == 800                  # not credited again
        other = mp.request_premium(ctx, s, pol, 100, "officer")
        other.status = "unconfirmed"
        with pytest.raises(mp.ResolveError, match="already recorded"):
            mp.resolve(ctx, s, other, "manager", "paid", receipt)


def test_success_callback_after_a_query_failure_is_flagged_not_dropped(ctx, db):
    ctx.mpesa = AnsweringDaraja([1037])
    with transaction(db) as s:
        pol = _enrol(ctx, s)
        req = mp.request_premium(ctx, s, pol, 800, "officer")
        mp.recheck(ctx, s, now=mp._aware(req.created_at) + timedelta(minutes=2))
        assert req.status == "failed"
        assert mp.handle_callback(ctx, s, mp.SimulatedDaraja().simulate_callback(req, True))["outcome"] == "flagged"
        assert req.status == "unconfirmed" and req.callback_receipt and pol.paid_kes == 0
        assert mp.unconfirmed(s, pol.sacco_id) == [req]


def test_same_pdf_can_be_held_for_a_sacco_and_for_every_sacco(db, tmp_path):
    _, sources = wx.load_sources(REPO / "config")
    with transaction(db) as s:
        a, b = Sacco(code="A1", name="A", is_demo=True), Sacco(code="B1", name="B", is_demo=True)
        s.add_all([a, b])
        s.flush()
        src = sources["kmd_nakuru"]
        assert wx.store_pdf(s, tmp_path, src, PDF, "t", None, "uploaded", sacco_id=a.id)
        assert wx.store_pdf(s, tmp_path, src, PDF, "t", None, "fetched") is not None         # every-SACCO copy
        assert wx.store_pdf(s, tmp_path, src, PDF, "t", None, "uploaded", sacco_id=b.id)     # another SACCO
        assert wx.store_pdf(s, tmp_path, src, PDF, "t", None, "uploaded", sacco_id=a.id) is None   # same audience
        assert s.scalar(select(func.count()).select_from(WeatherItem)) == 3


def test_resolve_errors_render_html_for_browsers(app):  # noqa: F811
    m = TestClient(app)
    tok = login(m, "manager")
    r = m.post("/mpesa/999/resolve", data={"csrf_token": tok, "outcome": "paid"}, headers={"accept": "text/html"})
    assert r.status_code == 404 and "<html" in r.text


@pytest.mark.parametrize("amount", ["nan", "NaN", "inf"])
def test_non_numbers_are_form_errors_not_crashes(app, money, amount):  # noqa: F811
    m = TestClient(app)
    tok = login(m, "manager")
    r = m.post(f"/policies/{money['policy_id']}/refund", data={"csrf_token": tok, "amount": amount, "paid_on": TODAY.isoformat(),
                                                               "method": "mpesa", "reference": "RFND-NAN"})
    assert r.status_code == 200 and "Enter the amount in shillings" in r.text
    r = m.post("/reports/premium", data={"csrf_token": tok, "amount": amount, "remitted_on": TODAY.isoformat(),
                                         "method": "bank_transfer", "reference": "BANK-NAN"})
    assert r.status_code == 422 and "Enter the amount in shillings" in r.text


def test_refund_form_prefills_an_amount_it_accepts(app, money):  # noqa: F811
    from agroshield_platform import settlement as stl
    with transaction(app.state.factory) as s:
        pol = s.get(Policy, money["policy_id"])
        pol.refund_due_kes = 300.4
    m = TestClient(app)
    tok = login(m, "manager")
    page = m.get(f"/members/{money['farmer_id']}").text
    assert 'value="300.40"' in page
    m.post(f"/policies/{money['policy_id']}/refund", data={"csrf_token": tok, "amount": "300.40", "paid_on": TODAY.isoformat(),
                                                           "method": "mpesa", "reference": "RFND-2"})
    with transaction(app.state.factory) as s:
        assert sv.refund_outstanding(s, s.get(Policy, money["policy_id"])) == 0
    assert stl._shillings(12.5) == "12.50" and stl._shillings(12.0) == "12"


def test_set_paybill_refuses_long_values_and_keeps_the_old_one_readable(app, money, monkeypatch, capsys):  # noqa: F811
    from agroshield_platform import cli
    monkeypatch.setenv("DATABASE_URL", str(app.state.factory.kw["bind"].url))
    with pytest.raises(SystemExit, match="60 characters"):
        cli.main(["set-paybill", "--insurer", "UWX", "--paybill", "x" * 61])
    assert cli.main(["set-paybill", "--insurer", "UWX", "--paybill", "Bank account 0123456789012 (fictional)"]) == 0
    assert "set to: Bank account 0123456789012 (fictional)" in capsys.readouterr().out
    assert cli.main(["set-paybill", "--insurer", "UWX", "--paybill", "Paybill 000111, account AGRO"]) == 0
    with transaction(app.state.factory) as s:
        last = s.scalars(select(AuditEvent).where(AuditEvent.action == "insurer.paybill_set").order_by(AuditEvent.id)).all()[-1]
        assert last.details["paybill_old"] == "Bank account 0123456789012 (fictional)"   # recoverable, not masked
    assert cli.main(["set-paybill", "--insurer", "UWX", "--paybill", "M-Pesa 0722 718 281"]) == 0
    with transaction(app.state.factory) as s:
        last = s.scalars(select(AuditEvent).where(AuditEvent.action == "insurer.paybill_set").order_by(AuditEvent.id)).all()[-1]
        assert "718 281" not in last.details["paybill_new"]                                # a phone number stays masked


def test_settlement_page_without_an_insurer_still_names_the_paybill(app):  # noqa: F811
    import html
    m = TestClient(app)
    login(m, "manager")
    assert "the insurer's paybill (to be configured)" in html.unescape(m.get("/reports/premium").text)


def test_signed_in_users_can_open_public_pages(app):  # noqa: F811
    m = TestClient(app)
    login(m, "manager")
    for page in ("/", "/crops", "/learn"):
        r = m.get(page)
        assert r.status_code == 200 and "Manager One" in r.text, page
