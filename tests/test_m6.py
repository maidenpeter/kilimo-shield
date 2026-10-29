"""Decisions of 2026-10-29 and milestone 6: sales windows and instalments, consent gate,
discount funder, insurer policy numbers, the EXPERIMENTAL advance, M-Pesa (simulated and
Daraja), USSD and English / Kiswahili SMS. All personal values are fictional."""
import json
import re
from datetime import date, datetime

import httpx
import numpy as np
import pandas as pd
import pytest
import yaml
from fastapi.testclient import TestClient
from sqlalchemy import select

from agroshield_pricing import advance as adv
from agroshield_pricing.config import load_config
from agroshield_platform import locale as L
from agroshield_platform import mpesa as mp
from agroshield_platform import services as sv
from agroshield_platform import sms as smsmod
from agroshield_platform import ussd
from agroshield_platform.db import transaction
from agroshield_platform.models import MpesaRequest, Payment, Policy, Sacco, SmsMessage
from agroshield_platform.settings import Mpesa, Sms, load_dotenv
from agroshield_platform.web.app import create_app

from conftest import REPO
from test_platform import (NID, NID2, PHONE, PHONE2, TODAY, assert_no_pii, book, csrf_of, db, inp, login,  # noqa: F401
                           settings, vault)


@pytest.fixture
def ctx(cfg, book, vault):
    return sv.Context(cfg, book, vault, today=TODAY, mpesa=mp.SimulatedDaraja())


def _sacco(s, demo=True, code="TST01"):
    sacco = Sacco(code=code, name="Test SACCO", is_demo=demo)
    s.add(sacco)
    s.flush()
    return sacco


def _enrolled(ctx, s, **over):
    sacco = s.scalar(select(Sacco)) or _sacco(s)
    return sv.enrol(ctx, s, sacco, None, inp(**over))


# ------------------------------------------------------------------ sales windows
def test_sales_windows_from_config(cfg):
    a, b = cfg.calendar("ward-a", "LR"), cfg.calendar("ward-b", "LR")
    assert a.sales_window_for(2027) == (date(2026, 9, 15), date(2027, 2, 14))
    assert a.open_sales_year(date(2026, 10, 29)) == 2027
    assert b.open_sales_year(date(2026, 10, 29)) is None and b.open_sales_year(date(2026, 12, 1)) == 2027
    assert a.open_sales_year(date(2027, 2, 15)) is None             # closed the day after
    for cal in (a, b):                                              # at least 14 days before the planting window
        assert (cal.planting_window_opens(2027) - cal.sales_window_for(2027)[1]).days >= 14


def test_sales_must_close_14_days_before_planting(config_copy):
    p = config_copy / "phenology.yaml"
    d = yaml.safe_load(p.read_text())
    d["wards"]["ward-a"]["LR"]["sales_window"]["closes"] = "02-20"
    p.write_text(yaml.safe_dump(d))
    with pytest.raises(ValueError, match="at least 14 days"):
        load_config(config_copy)


def test_enrolment_outside_the_window_is_refused(cfg, book, vault, db):
    ctx = sv.Context(cfg, book, vault, today=date(2027, 3, 1))
    with transaction(db) as s:
        with pytest.raises(sv.EnrolmentError, match="closed"):
            sv.enrol(ctx, s, _sacco(s), None, inp(year=None))
    ctx = sv.Context(cfg, book, vault, today=date(2026, 10, 29))
    with transaction(db) as s:
        pv = sv.preview(ctx, s, inp(year=None, ward_id="ward-b"))
        assert "opens 01 Dec 2026" in pv["errors"]["ward_id"]
        pv = sv.preview(ctx, s, inp(year=2028))
        assert "not 2028" in pv["errors"]["ward_id"]


def test_policy_carries_window_due_amount_and_funder(ctx, db):
    with transaction(db) as s:
        pol = _enrolled(ctx, s, year=None)
        assert (pol.year, pol.sales_closes_on) == (2027, date(2027, 2, 14))
        assert pol.amount_due_kes == 2000 and pol.discount_funder == "platform"
        assert re.fullmatch(r"AG[A-Z2-9]{8}", pol.pay_ref) and pol.insurer_policy_number is None


# ------------------------------------------------------------------ consent gate
def test_live_enrolment_blocked_until_consent_reviewed(cfg, book, vault, db, config_copy):
    ctx = sv.Context(cfg, book, vault, today=TODAY)
    with transaction(db) as s:
        live = _sacco(s, demo=False, code="LIVE1")
        with pytest.raises(sv.EnrolmentError, match="pending legal and Kiswahili review"):
            sv.enrol(ctx, s, live, None, inp())
    c = config_copy / "consent.yaml"
    d = yaml.safe_load(c.read_text())
    d["version"] = "C-TEST-REVIEWED"
    d["review"].update(legal={"reviewer": "Test Counsel", "date": "2026-11-15"},
                       kiswahili={"reviewer": "Test Reviewer", "date": "2026-11-15"})
    c.write_text(yaml.safe_dump(d, allow_unicode=True))
    ctx2 = sv.Context(load_config(config_copy), book, vault, today=TODAY)
    with transaction(db) as s:
        pol = sv.enrol(ctx2, s, s.scalar(select(Sacco).where(Sacco.code == "LIVE1")), None, inp())
        assert {c.wording_version for c in pol.farmer.consents} == {"C-TEST-REVIEWED"}


def test_consent_text_is_marked_pending_review(cfg):
    w = sv.load_consent_wording(cfg)
    assert w["reviewed"] is False and w["review"]["status"] == "pending legal and Kiswahili review"


# ------------------------------------------------------------------ instalments
def test_instalments_activate_cover_only_when_fully_paid(ctx, db):
    with transaction(db) as s:
        pol = _enrolled(ctx, s)
        sv.record_payment(ctx, s, pol, 500, "mpesa", "R1", "t")
        assert (pol.status, pol.payment_status, pol.balance_kes) == ("pending_payment", "part_paid", 1500)
        sv.record_payment(ctx, s, pol, 1500, "sacco_deduction", "D1", "t")
        assert (pol.status, pol.payment_status, pol.refund_due_kes) == ("active", "paid", 0)
        assert pol.cover_active_from is not None
        with pytest.raises(sv.PaymentError, match="already recorded"):
            sv.record_payment(ctx, s, pol, 10, "mpesa", "R1", "t")
        sv.record_payment(ctx, s, pol, 200, "mpesa", "R2", "t")      # paid again after full payment
        assert pol.refund_due_kes == 200 and pol.status == "active"


def test_payment_after_close_does_not_start_cover(ctx, db):
    with transaction(db) as s:
        pol = _enrolled(ctx, s)
        sv.record_payment(ctx, s, pol, 1000, "mpesa", "R1", "t")
        late = datetime(2027, 2, 15, 9, 0, tzinfo=sv.NAIROBI)
        sv.record_payment(ctx, s, pol, 1000, "mpesa", "R2", "t", received_at=late)
        assert (pol.status, pol.refund_due_kes) == ("lapsed_unpaid", 2000)
        assert s.scalar(select(Payment).where(Payment.reference == "R2")).within_window is False


def test_daily_job_lapses_unpaid_and_reminds_once(cfg, book, vault, db):
    ctx = sv.Context(cfg, book, vault, today=TODAY)
    with transaction(db) as s:
        pol = _enrolled(ctx, s)
        sv.record_payment(ctx, s, pol, 300, "mpesa", "R1", "t")
    week = sv.Context(cfg, book, vault, today=date(2027, 2, 7))
    with transaction(db) as s:
        assert sv.close_sales_windows(week, s)["reminders"] == 1
        assert sv.close_sales_windows(week, s)["reminders"] == 0       # deduplicated
    after = sv.Context(cfg, book, vault, today=date(2027, 2, 15))
    with transaction(db) as s:
        assert sv.close_sales_windows(after, s)["lapsed"] == 1
        pol = s.scalar(select(Policy))
        assert (pol.status, pol.refund_due_kes) == ("lapsed_unpaid", 300)
        assert {m.template for m in s.scalars(select(SmsMessage))} >= {"enrolled", "payment_received", "reminder", "lapsed"}


# ------------------------------------------------------------------ EXPERIMENTAL advance
def test_advance_is_never_clawed_back_and_only_extra_is_priced():
    proj = pd.Series([90.0, 99.0, 70.0, 94.0], index=[1, 2, 3, 4])
    final = pd.Series([0.50, 0.0, 0.10, 0.0])
    final.index = proj.index
    o = adv.outcomes(proj, final, 95, 0.20)
    assert o["fired"].tolist() == [True, False, True, True]
    assert o["farmer_receives_share"].tolist() == [0.50, 0.0, 0.20, 0.20]       # max(advance, final)
    assert o["extra_share"].round(6).tolist() == [0.0, 0.0, 0.10, 0.20]         # false alarm costs the advance
    v = adv.verify(o["fired"].to_numpy(), o["event"].to_numpy())
    assert (v["hits"], v["false_alarms"], v["misses"]) == (2, 1, 0)


def test_leave_one_out_holds_each_season_out():
    rng = np.random.default_rng(1)
    proj = pd.Series(rng.uniform(70, 100, 30), index=range(1990, 2020))
    final = pd.Series(np.where(proj < 88, 0.3, 0.0), index=proj.index)
    r = adv.leave_one_out(proj, final, [80, 85, 88, 90, 95], 95, 0.2)
    assert r["out_of_sample"]["seasons"] == 30 and len(r["history"]) == 30
    assert r["out_of_sample"]["false_alarms"] <= 3


def test_experimental_advance_cannot_be_quoted(config_copy):
    p = config_copy / "product.yaml"
    d = yaml.safe_load(p.read_text())
    d["layer_b"]["advance"]["included_in_quotes"] = True
    p.write_text(yaml.safe_dump(d))
    with pytest.raises(ValueError, match="EXPERIMENTAL"):
        load_config(config_copy)


def test_advance_research_results_match_config(cfg):
    r = json.loads((REPO / "data" / "raw" / "research" / "advance_results.json").read_text())
    assert r["terms"]["projected_wrsi_below"] == cfg.product.layer_b.advance.projected_wrsi_below
    assert list(r["wards"]) == cfg.product.layer_b.advance.offered_wards == ["ward-a"]
    w = r["wards"]["ward-a"]
    assert w["loocv"]["out_of_sample"]["seasons"] == w["seasons"] >= 20


# ------------------------------------------------------------------ M-Pesa
def test_simulated_stk_push_and_callback(ctx, db):
    with transaction(db) as s:
        pol = _enrolled(ctx, s)
        req = mp.request_premium(ctx, s, pol, 800, "officer")
        assert req.status == "pending" and req.phone_masked == "+254 7** *** 281"
        body = ctx.mpesa.simulate_callback(req, success=True)
        assert mp.handle_callback(ctx, s, body)["outcome"] == "paid"
        assert mp.handle_callback(ctx, s, body)["outcome"] == "duplicate"      # Safaricom retries are harmless
        assert pol.paid_kes == 800 and pol.payment_status == "part_paid"
        bad = mp.request_premium(ctx, s, pol, 100, "officer")
        cb = ctx.mpesa.simulate_callback(bad, success=True)
        cb["Body"]["stkCallback"]["CallbackMetadata"]["Item"][0]["Value"] = 1  # amount does not match
        assert mp.handle_callback(ctx, s, cb)["outcome"] == "rejected" and pol.paid_kes == 800
        cancel = mp.request_premium(ctx, s, pol, 100, "officer")
        assert mp.handle_callback(ctx, s, ctx.mpesa.simulate_callback(cancel, success=False))["outcome"] == "failed"
        assert mp.handle_callback(ctx, s, {"Body": {"stkCallback": {"CheckoutRequestID": "nope"}}})["outcome"] == "unknown_request"
        with pytest.raises(sv.PaymentError, match="whole number"):
            mp.request_premium(ctx, s, pol, 5000, "officer")


def _daraja_transport(log: list, query_code: int = 0):
    def handler(req: httpx.Request) -> httpx.Response:
        log.append(req)
        if req.url.path == "/oauth/v1/generate":
            return httpx.Response(200, json={"access_token": "tok", "expires_in": "3599"})
        if req.url.path == "/mpesa/stkpush/v1/processrequest":
            return httpx.Response(200, json={"MerchantRequestID": "M1", "CheckoutRequestID": "ws_CO_1",
                                             "ResponseCode": "0", "ResponseDescription": "Success"})
        if req.url.path == "/mpesa/stkpushquery/v1/query":
            return httpx.Response(200, json={"ResultCode": str(query_code), "ResultDesc": "x"})
        return httpx.Response(404)
    return httpx.MockTransport(handler)


def test_daraja_client_requests(ctx, db):
    log = []
    cfg = Mpesa(env="sandbox", consumer_key="k", consumer_secret="s", shortcode="174379", passkey="pk",
                callback_base_url="https://example.org")
    client = mp.DarajaClient(cfg, "https://example.org/mpesa/callback/T", http=httpx.Client(transport=_daraja_transport(log)))
    ctx.mpesa = client
    with transaction(db) as s:
        pol = _enrolled(ctx, s)
        mp.request_premium(ctx, s, pol, 2000, "officer")
    push = json.loads(next(r for r in log if r.url.path.endswith("processrequest")).content)
    assert push["PartyA"] == push["PhoneNumber"] == "254722718281" and push["Amount"] == 2000
    assert push["AccountReference"] == pol.pay_ref and len(push["AccountReference"]) <= 12
    assert push["CallBackURL"].startswith("https://") and "254722718281" not in push["CallBackURL"]
    import base64
    assert base64.b64decode(push["Password"]).decode() == "174379pk" + push["Timestamp"]
    with pytest.raises(mp.MpesaError, match="https"):
        mp.DarajaClient(cfg, "http://insecure/cb")


def test_unconfirmed_callback_is_not_credited(ctx, db):
    log = []
    cfg = Mpesa(env="sandbox", consumer_key="k", consumer_secret="s", shortcode="174379", passkey="pk")
    ctx.mpesa = mp.DarajaClient(cfg, "https://example.org/cb", http=httpx.Client(transport=_daraja_transport(log, 1032)))
    with transaction(db) as s:
        pol = _enrolled(ctx, s)
        req = mp.request_premium(ctx, s, pol, 2000, "officer")
        forged = mp.SimulatedDaraja().simulate_callback(req, success=True)
        assert mp.handle_callback(ctx, s, forged)["outcome"] == "unconfirmed"
        assert pol.paid_kes == 0 and req.status == "pending"


# ------------------------------------------------------------------ USSD
def test_ussd_menus(ctx, db):
    with transaction(db) as s:
        pol = _enrolled(ctx, s)
        assert ussd.handle(ctx, s, "+254700999999", "").startswith("END This number is not registered")
        main = ussd.handle(ctx, s, PHONE, "")
        assert main.startswith("CON Habari Test!") and "2. Pay premium" in main
        cover = ussd.handle(ctx, s, "+254722718281", "1")
        assert pol.policy_no in cover and "awaiting payment" in cover and "14/02/2027" in cover
        assert ussd.handle(ctx, s, PHONE, "2").startswith("CON Pay for")
        assert "Enter amount" in ussd.handle(ctx, s, PHONE, "2*2")
        assert "whole number" in ussd.handle(ctx, s, PHONE, "2*2*10")
        assert ussd.handle(ctx, s, PHONE, "2*2*500").startswith("END An M-Pesa request for KES 500")
        assert ussd.handle(ctx, s, PHONE, "2*1").startswith("END An M-Pesa request for KES 2,000")
        assert [r.amount_kes for r in s.scalars(select(MpesaRequest))] == [500, 2000]
        assert ussd.handle(ctx, s, PHONE, "4*2") == "END Lugha imewekwa Kiswahili."
        assert ussd.handle(ctx, s, PHONE, "").startswith("CON Habari Test! AgroShield\n1. Bima yangu")
        assert ussd.handle(ctx, s, PHONE, "9").startswith("END Chaguo si sahihi")


def test_ussd_screens_fit_and_languages_match():
    en, sw = L.strings("en"), L.strings("sw")
    for section in ("ussd", "sms", "status", "season", "ward"):
        assert set(en[section]) == set(sw[section]), section
    values = {"first_name": "Wanjikuuuuuuu", "cert": "AGS-NKR01-LR27-00001", "season": "long rains 2027",
              "acres": "12.5", "status": "not started (not fully paid)", "paid": "123,456", "due": "123,456",
              "closes": "14/02/2027", "refund": "123,456", "balance": "123,456", "min": 50, "amount": "123,456",
              "sacco": "Example Farmers Cooperative SACCO", "ussd": "*384*12345#", "ward": "Molo Highlands",
              "code": "V-ABCDEF", "by": "11/09/2027", "on": "05/09/2027", "expires": "01/05/2027",
              "ref": "MP-ABCDEF", "loan": "LN-0000107"}
    for lang in ("en", "sw"):
        values["season"] = max((L.season(lang, sc, 2027) for sc in ("LR", "SR")), key=len)   # longest label
        values["status"] = max(L.strings(lang)["status"].values(), key=len)
        for key in L.strings(lang)["ussd"]:
            text = L.t(lang, f"ussd.{key}", **values)
            assert len("CON " + text) <= L.USSD_MAX, (lang, key, len(text))
        cover = L.t(lang, "ussd.cover", **values) + L.t(lang, "ussd.cover_due", **values) + L.t(lang, "ussd.cover_refund", **values)
        assert len("END " + cover) <= L.USSD_MAX, (lang, len(cover))
        for key in L.strings(lang)["ward"]:                  # Payouts screen: heading, ward line, two payouts
            screen = "\n".join([L.t(lang, "ussd.payouts_head", **values), L.t(lang, f"ward.{key}"),
                                 L.t(lang, "ussd.payout_due", **values), L.t(lang, "ussd.voucher", **values)])
            assert len("END " + screen) <= L.USSD_MAX, (lang, key, len(screen))
        for key in L.strings(lang)["sms"]:
            text = L.t(lang, f"sms.{key}", **values)
            assert len(text) <= L.SMS_MAX and L.is_gsm7(text), (lang, key, len(text))


# ------------------------------------------------------------------ SMS
def test_sms_only_with_consent_in_the_farmers_language(ctx, db, vault):
    with transaction(db) as s:
        yes = _enrolled(ctx, s, language="sw")
        no = _enrolled(ctx, s, member_no="M-0101", national_id=NID2, phone=PHONE2, consent_sms=False)
        msgs = s.scalars(select(SmsMessage)).all()
        assert [(m.farmer_id, m.template, m.language) for m in msgs] == [(yes.farmer_id, "enrolled", "sw")]
        assert msgs[0].body.startswith("AgroShield: Test, umesajiliwa") and yes.policy_no in msgs[0].body
        assert_no_pii(msgs[0].body)
        sv.record_payment(ctx, s, no, 2000, "mpesa", "R9", "t")
        assert s.scalar(select(SmsMessage).where(SmsMessage.farmer_id == no.farmer_id)) is None
        assert smsmod.send_pending(s, smsmod.LogOnlySender(), vault) == {"logged": 1}


def test_africastalking_sender(ctx, db, vault):
    sent = []

    def handler(req: httpx.Request) -> httpx.Response:
        sent.append(req)
        return httpx.Response(201, json={"SMSMessageData": {"Recipients": [{"status": "Success", "messageId": "ATX1"}]}})
    sender = smsmod.AfricasTalkingSender(Sms(mode="sandbox", api_key="key", username="sandbox"),
                                         client=httpx.Client(transport=httpx.MockTransport(handler)))
    with transaction(db) as s:
        _enrolled(ctx, s)
        assert smsmod.send_pending(s, sender, vault) == {"sent": 1}
        m = s.scalar(select(SmsMessage))
        assert (m.status, m.provider_message_id) == ("sent", "ATX1")
    req = sent[0]
    assert req.url.host == "api.sandbox.africastalking.com" and req.headers["apiKey"] == "key"
    form = dict(x.split("=", 1) for x in req.content.decode().split("&"))
    assert form["to"] == "%2B254722718281" and "254722718281" not in str(req.url)


# ------------------------------------------------------------------ portal and callbacks
@pytest.fixture
def m6app(settings, book):
    app = create_app(settings, book, today=TODAY)
    with transaction(app.state.factory) as s:
        from agroshield_platform.crypto import hash_password
        from agroshield_platform.models import Officer
        sacco = _sacco(s)
        s.add_all([Officer(sacco_id=sacco.id, username="officer", display_name="Officer One",
                           password_hash=hash_password("correct horse battery"), role="officer"),
                   Officer(sacco_id=sacco.id, username="manager", display_name="Manager One",
                           password_hash=hash_password("correct horse battery"), role="manager")])
        ctx = sv.Context(load_config(settings.config_dir), book, app.state.vault, today=TODAY)
        sv.enrol(ctx, s, sacco, None, inp())
    return app


def test_callbacks_need_the_secret_token(m6app, settings):
    c = TestClient(m6app)
    assert c.post("/ussd/wrong", data={"phoneNumber": PHONE, "text": ""}).status_code == 404
    assert c.post("/mpesa/callback/wrong", json={}).status_code == 404
    r = c.post(f"/ussd/{settings.callback_token}", data={"sessionId": "s1", "serviceCode": "*384*000#",
                                                          "phoneNumber": "+254722718281", "text": "1"})
    assert r.status_code == 200 and r.text.startswith("END AGS-TST01-LR27-")
    r = c.post(f"/mpesa/callback/{settings.callback_token}", json={"Body": {"stkCallback": {"CheckoutRequestID": "x"}}})
    assert r.json() == {"ResultCode": 0, "ResultDesc": "Accepted"}


def test_portal_payments_flow(m6app):
    c = TestClient(m6app)
    tok = login(c, "manager")
    member_url = re.search(r'href="(/members/[0-9a-f]{32})"', c.get("/members").text).group(1)
    page = c.get(member_url).text
    pid = re.search(r'action="/policies/([0-9a-f]{32})/stk"', page).group(1)
    c.post(f"/policies/{pid}/deduction", data={"csrf_token": tok, "amount": "500", "reference": "DED-1"})
    r = c.post(f"/policies/{pid}/stk", data={"csrf_token": tok, "amount": "1500"}, follow_redirects=True)
    assert "M-Pesa request for KES 1,500 sent" in r.text
    sim = c.get("/dev/mpesa").text
    rid = re.search(r'action="/dev/mpesa/(\d+)/success"', sim).group(1)
    c.post(f"/dev/mpesa/{rid}/success", data={"csrf_token": tok})
    page = c.get(member_url).text
    assert ">active<" in page and "DED-1" in page and "SIM" in page
    c.post(f"/policies/{pid}/insurer-number", data={"csrf_token": tok, "insurer_policy_number": "UW/2027/000123"})
    assert "UW/2027/000123" in c.get(member_url).text
    sms_page = c.get("/sms").text
    assert "premium paid in full" in sms_page and "+254 7** *** 281" in sms_page
    for html in (page, sms_page, sim):
        assert_no_pii(html)
    officer = TestClient(m6app)
    otok = login(officer, "officer")
    assert officer.post(f"/policies/{pid}/insurer-number", data={"csrf_token": otok, "insurer_policy_number": "x"}).status_code == 403
    assert officer.get("/sms").status_code == 403


def test_layer_a_not_offered_in_the_portal(m6app):
    c = TestClient(m6app)
    login(c)
    assert 'name="layer_A"' not in c.get("/enrol").text and 'name="layer_A"' not in c.get("/quote").text


# ------------------------------------------------------------------ settings
def test_dotenv_never_overrides_the_environment(tmp_path, monkeypatch):
    f = tmp_path / ".env"
    f.write_text("AGS_TEST_A=from-file\nAGS_TEST_B=from-file  # comment\n# AGS_TEST_C=x\nANTHROPIC_API_KEY=\n")
    monkeypatch.setenv("AGS_TEST_A", "from-env")
    monkeypatch.delenv("AGS_TEST_B", raising=False)
    load_dotenv(f)
    import os
    assert os.environ["AGS_TEST_A"] == "from-env" and os.environ["AGS_TEST_B"] == "from-file"
    assert "AGS_TEST_C" not in os.environ
    monkeypatch.delenv("AGS_TEST_B")
