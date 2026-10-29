"""Milestone 5: farmer, policy and SACCO data model and the SACCO officer portal.

Every personal value used here is fictional. The privacy tests look for the raw
national ID and phone digits anywhere they must never appear: database rows,
rendered pages, URLs, audit events and logs.
"""
import base64
import logging
import re
import secrets
import sqlite3
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from agroshield_pricing.quote import RateBook, WardRates
from agroshield_platform import services as sv
from agroshield_platform.crypto import (PIIError, ScrubFilter, Vault, hash_password, mask_national_id, mask_phone,
                                        normalise_national_id, normalise_phone, scrub, verify_password)
from agroshield_platform.db import audit, init_db, make_engine, transaction
from agroshield_platform.kiamis import CsvKiamis
from agroshield_platform.models import AuditEvent, Consent, KiamisRecord, Officer, Policy, Sacco
from agroshield_platform.settings import Settings
from agroshield_platform.web.app import create_app

from conftest import REPO

NID, PHONE = "31415926", "0722 718 281"          # fictional
NID2, PHONE2 = "27182818", "0733 141 592"
PASSWORD = "correct horse battery"
TODAY = date(2026, 12, 15)                       # both long-rains sales windows open (2027 season)


@pytest.fixture
def book(cfg):
    return RateBook(
        rates={
            ("ward-a", "LR"): WardRates("ward-a", "Ward A", "LR", {5000.0: 1000.0, 10000.0: 2000.0, 15000.0: 3000.0},
                                        1000.0, 2000.0, {"layer_b": "B-test", "layer_a": "A-test"}, ["ILLUSTRATIVE"]),
            ("ward-b", "LR"): WardRates("ward-b", "Ward B", "LR", {5000.0: 500.0, 10000.0: 800.0, 15000.0: 900.0},
                                        None, None, {"layer_b": "B-test"}, ["ILLUSTRATIVE"]),
        },
        config_sha256=cfg.file_hashes, built_at="test")


@pytest.fixture
def settings(tmp_path):
    return Settings(database_url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
                    encryption_key=secrets.token_bytes(32), lookup_key=secrets.token_bytes(32),
                    session_secret=base64.b64encode(secrets.token_bytes(32)).decode(),
                    config_dir=REPO / "config", dev_keys=False)


@pytest.fixture
def vault(settings):
    return Vault(settings.encryption_key, settings.lookup_key)


@pytest.fixture
def app(settings, book):
    app = create_app(settings, book, today=TODAY)
    with transaction(app.state.factory) as s:
        sacco = Sacco(code="TST01", name="Test SACCO", is_demo=True)
        other = Sacco(code="OTH01", name="Other SACCO", is_demo=True)
        s.add_all([sacco, other])
        s.flush()
        s.add_all([Officer(sacco_id=sacco.id, username="officer", display_name="Officer One",
                           password_hash=hash_password(PASSWORD), role="officer"),
                   Officer(sacco_id=sacco.id, username="manager", display_name="Manager One",
                           password_hash=hash_password(PASSWORD), role="manager"),
                   Officer(sacco_id=other.id, username="other", display_name="Other Officer",
                           password_hash=hash_password(PASSWORD), role="manager")])
    return app


def csrf_of(html: str) -> str:
    return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)


def login(client: TestClient, username: str = "officer") -> str:
    tok = csrf_of(client.get("/login").text)
    r = client.post("/login", data={"username": username, "password": PASSWORD, "csrf_token": tok},
                    follow_redirects=False)
    assert r.status_code == 303
    return csrf_of(client.get("/dashboard").text)


def enrol_form(**over) -> dict:
    form = {"member_no": "M-0100", "full_name": "Test Farmer (fictional)", "national_id": NID, "phone": PHONE,
            "gender": "female", "ward_id": "ward-a", "acreage": "2", "layer_B": "1", "sum_insured_kes_per_acre": "10000",
            "consent_data_processing": "1", "consent_sms": "1", "res_certified_seed_verified": "1"}
    form.update(over)
    return {k: v for k, v in form.items() if v is not None}


def enrol_via_portal(client: TestClient, tok: str, confirm: dict | None = None, **over):
    r = client.post("/enrol/review", data={**enrol_form(**over), "csrf_token": tok})
    assert r.status_code == 200, r.text
    token = re.search(r'name="token" value="([^"]+)"', r.text).group(1)
    data = {"csrf_token": tok, "token": token, "payment_route": "sacco_deduction", **(confirm or {})}
    return r, client.post("/enrol/confirm", data=data)


def pii_variants(nid: str, phone: str) -> list[str]:
    p = normalise_phone(phone)
    return [nid, p, p[1:], "0" + p[4:], phone]


def assert_no_pii(text: str, nid: str = NID, phone: str = PHONE) -> None:
    for v in pii_variants(nid, phone):
        assert v not in text, f"personal data {v[:2]}... leaked"


# ------------------------------------------------------------------ crypto and masking
def test_normalising_and_masking():
    assert normalise_phone("0712 345 678") == normalise_phone("+254712345678") == "+254712345678"
    assert normalise_phone("254 110 123 456") == "+254110123456"
    for bad in ("0812 345 678", "12345", ""):
        with pytest.raises(PIIError):
            normalise_phone(bad)
    assert normalise_national_id(" 12345678 ") == "12345678"
    with pytest.raises(PIIError):
        normalise_national_id("A1234567")
    assert mask_national_id("12345678") == "*****678"
    assert mask_phone("+254712345678") == "+254 7** *** 678"


def test_encryption_round_trip_and_purpose_binding(vault):
    tok = vault.encrypt("12345678", "national_id")
    assert "12345678" not in tok and vault.decrypt(tok, "national_id") == "12345678"
    assert vault.encrypt("12345678", "national_id") != tok                     # random nonce
    with pytest.raises(Exception):
        vault.decrypt(tok, "phone")                                            # purpose is bound
    assert vault.lookup_hash("12345678", "national_id") == vault.lookup_hash("12345678", "national_id")
    assert vault.lookup_hash("12345678", "national_id") != vault.lookup_hash("12345678", "phone")


def test_passwords():
    h = hash_password(PASSWORD)
    assert PASSWORD not in h and verify_password(PASSWORD, h)
    assert not verify_password("wrong password", h) and not verify_password(PASSWORD, "garbage")


def test_scrub_masks_ids_and_phones_in_logs(caplog):
    assert scrub(f"farmer {NID} phone +254722718281 acres 2") == "farmer *****926 phone *********281 acres 2"
    log = logging.getLogger("agroshield.test")
    log.addFilter(ScrubFilter())
    with caplog.at_level(logging.INFO):
        log.info("lookup %s", NID)
    assert NID not in caplog.text and "*****926" in caplog.text


# ------------------------------------------------------------------ services
@pytest.fixture
def ctx(cfg, book, vault):
    return sv.Context(cfg, book, vault, CsvKiamis(vault), today=TODAY)


@pytest.fixture
def db(settings):
    return init_db(make_engine(settings.database_url))


def inp(**over) -> sv.EnrolmentInput:
    base = dict(member_no="M-0100", full_name="Test Farmer (fictional)", phone=PHONE, national_id=NID,
                ward_id="ward-a", acreage=2.0, consent_data_processing=True, consent_sms=True, year=2027)
    base.update(over)
    return sv.EnrolmentInput(**base)


def test_enrol_stores_only_encrypted_pii(ctx, db, settings):
    with transaction(db) as s:
        sacco = Sacco(code="TST01", name="Test SACCO", is_demo=True)
        s.add(sacco)
        s.flush()
        pol = sv.enrol(ctx, s, sacco, None, inp())
        assert pol.policy_no == "AGS-TST01-LR27-00001"
        assert (pol.gross_kes, pol.government_share_kes, pol.farmer_pays_kes) == (4000.0, 2000.0, 2000.0)
        assert pol.subsidy_status == "not yet received" and pol.status == "pending_payment"
        f = pol.farmer
        assert f.national_id_masked == "*****926" and f.phone_masked == "+254 7** *** 281"
        assert ctx.vault.decrypt(f.national_id_enc, "national_id") == NID
    # Read the raw database file: no column anywhere holds the clear values.
    con = sqlite3.connect(settings.database_url.removeprefix("sqlite:///"))
    dump = "\n".join(con.iterdump())
    con.close()
    assert_no_pii(dump)


def test_consent_is_required_and_recorded_per_purpose(ctx, db, cfg):
    with transaction(db) as s:
        sacco = Sacco(code="TST01", name="Test SACCO", is_demo=True)
        s.add(sacco)
        s.flush()
        with pytest.raises(sv.EnrolmentError) as e:
            sv.enrol(ctx, s, sacco, None, inp(consent_data_processing=False))
        assert "consent_data_processing" in e.value.errors
        pol = sv.enrol(ctx, s, sacco, None, inp())
        consents = {c.purpose: c for c in s.scalars(select(Consent).where(Consent.farmer_id == pol.farmer_id))}
        wording = sv.load_consent_wording(cfg)
        assert set(consents) == {"data_processing", "sms", "loan_linked_payout"}
        assert consents["data_processing"].granted and consents["sms"].granted
        assert not consents["loan_linked_payout"].granted
        assert all(c.wording_version == wording["version"] for c in consents.values())
        assert consents["sms"].wording_sha256 == wording["purposes"]["sms"]["sha256"]


def test_loan_linked_payout_needs_its_own_consent_and_a_loan(ctx, db):
    with transaction(db) as s:
        sacco = Sacco(code="TST01", name="Test SACCO", is_demo=True)
        s.add(sacco)
        s.flush()
        with pytest.raises(sv.EnrolmentError) as e:
            sv.enrol(ctx, s, sacco, None, inp(loan_linked=True))
        assert {"consent_loan_linked_payout", "loan_ref"} <= set(e.value.errors)
        pol = sv.enrol(ctx, s, sacco, None, inp(loan_linked=True, loan_ref="LN-1", consent_loan_linked_payout=True))
        assert pol.loan_linked and pol.loan_ref == "LN-1"


def test_duplicates_are_rejected(ctx, db):
    with transaction(db) as s:
        sacco = Sacco(code="TST01", name="Test SACCO", is_demo=True)
        s.add(sacco)
        s.flush()
        sv.enrol(ctx, s, sacco, None, inp())
        with pytest.raises(sv.EnrolmentError, match="already has cover for long rains 2027 in Rongai West"):
            sv.enrol(ctx, s, sacco, None, inp())
        with pytest.raises(sv.EnrolmentError, match="another member number"):
            sv.enrol(ctx, s, sacco, None, inp(member_no="M-0999"))
        with pytest.raises(sv.EnrolmentError, match="different national ID"):
            sv.enrol(ctx, s, sacco, None, inp(national_id=NID2, phone=PHONE2))


def test_layer_a_refused_where_not_offered(ctx, db):
    with transaction(db) as s:
        pv = sv.preview(ctx, s, inp(ward_id="ward-b", layers=["A", "B"]))
        assert not pv["ok"] and "not part of the product" in pv["errors"]["layers"]


def test_kiamis_import_and_checks(ctx, db):
    csv_text = ("national_id,registered_acreage,certified_seed_purchased,subsidy_eligible\n"
                f"{NID},2.2,yes,yes\n{NID2},10,no,\nnot-an-id,1,no,\n")
    with transaction(db) as s:
        res = ctx.kiamis.import_csv(s, csv_text)
        assert (res["added"], res["updated"], len(res["errors"])) == (2, 0, 1)
        pv = sv.preview(ctx, s, inp(resilience={}))
        assert pv["kiamis"]["status"] == "verified"
        assert pv["resilience_used"]["certified_seed_verified"]           # added from KIAMIS
        assert pv["quote"]["resilience"]["points"] == 5
        assert ctx.kiamis.check(s, NID2, 2.0).status == "acreage_mismatch"
        assert ctx.kiamis.check(s, "11111111", 2.0).status == "not_found"
        assert ctx.kiamis.import_csv(s, csv_text)["updated"] == 2
        stored = " ".join(str(r) for r in s.execute(select(*KiamisRecord.__table__.columns)).all())
    assert NID not in stored and NID2 not in stored


def _bulk_csv(*rows: list[str]) -> str:
    lines = [",".join(sv.BULK_COLUMNS)]
    for member_no, nid, phone, ward, acres in rows:
        lines.append(f"{member_no},Bulk Farmer (fictional),{phone},{nid},female,{ward},{acres},,,B,10000,"
                     "sacco_deduction,no,,yes,no,no,sacco_good_standing")
    return "\n".join(lines) + "\n"


def test_bulk_check_reports_every_problem_and_commit_is_all_or_nothing(ctx, db):
    good = _bulk_csv(["B-1", NID, PHONE, "ward-a", "2"], ["B-2", NID2, PHONE2, "ward-b", "1"])
    bad = _bulk_csv(["B-1", NID, PHONE, "ward-a", "2"], ["B-1", NID2, PHONE2, "ward-a", "1"],
                    ["B-3", "12", "0700", "ward-z", "0"])
    with transaction(db) as s:
        sacco = Sacco(code="TST01", name="Test SACCO", is_demo=True)
        s.add(sacco)
        s.flush()
        rep = sv.bulk_check(ctx, s, bad, sacco)
        assert not rep["ok"] and len(rep["valid"]) == 1
        errs = {p["row"]: p["errors"] for p in rep["problems"]}
        assert "duplicate of row 2" in errs[3]["member_no"]
        assert {"national_id", "phone", "ward_id", "acreage"} <= set(errs[4])
        with pytest.raises(sv.EnrolmentError):
            sv.bulk_commit(ctx, s, sacco, Officer(id=None, username="t"), bad)
        assert s.scalar(select(Policy)) is None
        rep = sv.bulk_check(ctx, s, good, sacco)
        assert rep["ok"] and len(rep["valid"]) == 2
    with transaction(db) as s:
        sacco = s.scalar(select(Sacco))
        officer = Officer(sacco_id=sacco.id, username="bulk", display_name="Bulk", password_hash="x")
        s.add(officer)
        s.flush()
        assert len(sv.bulk_commit(ctx, s, sacco, officer, good)) == 2
        assert {c.channel for c in s.scalars(select(Consent))} == {"csv"}
        assert not sv.bulk_check(ctx, s, good, sacco)["ok"]                    # already enrolled now


def test_bulk_format_errors_do_not_echo_cells(ctx, db):
    text = _bulk_csv(["B-1", NID, PHONE, "ward-a", NID])                      # ID typed into the acreage column
    with transaction(db) as s:
        rep = sv.bulk_check(ctx, s, text)
    assert NID not in str(rep["problems"])


def test_audit_details_are_scrubbed(db):
    with transaction(db) as s:
        audit(s, "t", "x", "farmer", None, note=f"called {PHONE} about id {NID}", quote_id="Q-20261029-ab12cd34")
    with transaction(db) as s:
        ev = s.scalar(select(AuditEvent))
        assert_no_pii(str(ev.details))
        assert ev.details["quote_id"] == "Q-20261029-ab12cd34"


def test_portfolio_and_export(ctx, db):
    with transaction(db) as s:
        sacco = Sacco(code="TST01", name="Test SACCO", is_demo=True)
        s.add(sacco)
        s.flush()
        sv.enrol(ctx, s, sacco, None, inp())
        sv.enrol(ctx, s, sacco, None, inp(member_no="M-0101", national_id=NID2, phone=PHONE2, ward_id="ward-b",
                                          acreage=25, loan_linked=True, loan_ref="LN-9", consent_loan_linked_payout=True))
        pf = sv.portfolio(ctx, s, sacco)
        assert (pf["members"], pf["policies"], pf["loan_linked"]) == (2, 2, 1)
        assert pf["subsidy_receivable_kes"] == 2000.0                         # 25 acres is outside the band
        assert pf["sum_insured_kes"] == 10000 * 2 + 10000 * 25
        assert [w["ward_id"] for w in pf["by_ward"]] == ["ward-a", "ward-b"]
        body = sv.export_policies_csv(s, sacco)
    assert_no_pii(body)
    assert_no_pii(body, NID2, PHONE2)
    assert "*****926" in body and "+254 7** *** 281" in body


# ------------------------------------------------------------------ portal
def test_pages_need_sign_in(app):
    c = TestClient(app)
    assert c.get("/").status_code == 200
    for path in ("/dashboard", "/enrol", "/quote", "/members", "/bulk", "/export/policies.csv"):
        r = c.get(path, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/login", path


def test_login_failure_and_csrf(app):
    c = TestClient(app)
    tok = csrf_of(c.get("/login").text)
    assert c.post("/login", data={"username": "officer", "password": "nope", "csrf_token": tok}).status_code == 401
    assert c.post("/login", data={"username": "officer", "password": PASSWORD, "csrf_token": "forged"}).status_code == 403
    tok = login(c)
    assert c.post("/enrol/review", data={**enrol_form(), "csrf_token": "forged"}).status_code == 403


def test_portal_enrolment_wizard_end_to_end(app):
    c = TestClient(app)
    tok = login(c)
    review, done = enrol_via_portal(c, tok)
    assert "*****926" in review.text and "+254 7** *** 281" in review.text
    assert done.status_code == 200 and "AGS-TST01-LR" in done.text
    assert_no_pii(review.text)
    assert_no_pii(done.text)
    for page, shown in (("/dashboard", "AGS-TST01-LR"), ("/members", "*****926")):
        r = c.get(page)
        assert r.status_code == 200 and shown in r.text
        assert_no_pii(r.text)
    member_url = re.search(r'href="(/members/[0-9a-f]{32})"', c.get("/members").text).group(1)
    r = c.get(member_url)
    assert "data processing" in r.text and "C-2026-10-29" in r.text
    assert_no_pii(r.text)
    export = c.get("/export/policies.csv")
    assert export.status_code == 200 and "*****926" in export.text
    assert_no_pii(export.text)


def test_wizard_errors_drop_typed_id_and_phone(app):
    c = TestClient(app)
    tok = login(c)
    r = c.post("/enrol/review", data={**enrol_form(consent_data_processing=None), "csrf_token": tok})
    assert r.status_code == 422 and "must agree to data processing" in r.text
    assert_no_pii(r.text)
    token = re.search(r'name="token" value="([^"]+)"', r.text).group(1)
    for step in (3, 2):                                                  # Back to the first screen
        r = c.post("/enrol/step", data={"csrf_token": tok, "token": token, "step": step, "nav": "back"})
    assert "Step 1 of 5" in r.text and 'value="M-0100"' in r.text       # non-personal fields are kept
    assert "Saved: *****926" in r.text                                   # ID only ever shown masked
    assert_no_pii(r.text)


def test_loan_link_without_consent_is_refused_at_confirm(app):
    c = TestClient(app)
    tok = login(c)
    _, done = enrol_via_portal(c, tok, confirm={"loan_linked": "1", "loan_ref": "LN-7"})
    assert done.status_code == 422 and "explicit consent" in done.text
    _, done = enrol_via_portal(c, tok, confirm={"loan_linked": "1", "loan_ref": "LN-7", "consent_loan_linked_payout": "1"},
                               member_no="M-0101", national_id=NID2, phone=PHONE2)
    assert done.status_code == 200 and "to loan LN-7 first" in done.text


def test_wizard_token_is_tied_to_the_officer(app):
    a, b = TestClient(app), TestClient(app)
    tok_a = login(a)
    r = a.post("/enrol/review", data={**enrol_form(), "csrf_token": tok_a})
    token = re.search(r'name="token" value="([^"]+)"', r.text).group(1)
    tok_b = login(b, "manager")
    assert b.post("/enrol/confirm", data={"csrf_token": tok_b, "token": token}).status_code == 400


def test_officers_only_see_their_own_sacco(app):
    a = TestClient(app)
    enrol_via_portal(a, login(a))
    member_url = re.search(r'href="(/members/[0-9a-f]{32})"', a.get("/members").text).group(1)
    other = TestClient(app)
    login(other, "other")
    assert other.get(member_url).status_code == 404
    assert "M-0100" not in other.get("/members").text


def test_member_search_is_post_only(app):
    c = TestClient(app)
    tok = login(c)
    enrol_via_portal(c, tok)
    r = c.post("/members", data={"q": "M-0100", "csrf_token": tok})
    assert r.status_code == 200 and "M-0100" in r.text
    assert "M-0100" not in c.post("/members", data={"q": "nobody", "csrf_token": tok}).text


def test_kiamis_page_is_manager_only(app):
    c = TestClient(app)
    tok = login(c)
    assert c.get("/kiamis").status_code == 403
    m = TestClient(app)
    tok = login(m, "manager")
    csv_text = f"national_id,registered_acreage,certified_seed_purchased,subsidy_eligible\n{NID},2,yes,yes\n"
    r = m.post("/kiamis", data={"csrf_token": tok}, files={"file": ("k.csv", csv_text, "text/csv")})
    assert r.status_code == 200 and "1 added" in r.text
    assert NID not in r.text


def test_portal_bulk_check_then_commit(app):
    c = TestClient(app)
    tok = login(c)
    text = _bulk_csv(["B-1", NID, PHONE, "ward-a", "2"], ["B-2", NID2, PHONE2, "ward-b", "1"])
    r = c.post("/bulk/check", data={"csrf_token": tok}, files={"file": ("m.csv", text, "text/csv")})
    assert r.status_code == 200 and "2 rows ready" in r.text
    assert_no_pii(r.text)
    assert_no_pii(r.text, NID2, PHONE2)
    token = re.search(r'name="token" value="([^"]+)"', r.text).group(1)
    r = c.post("/bulk/commit", data={"csrf_token": tok, "token": token})
    assert r.status_code == 200 and "2 policies saved" in r.text
    assert c.post("/bulk/commit", data={"csrf_token": tok, "token": token}).status_code == 400   # single use


def test_quote_page(app):
    c = TestClient(app)
    tok = login(c)
    r = c.post("/quote", data={"csrf_token": tok, "ward_id": "ward-a", "acreage": "2", "layer_B": "1",
                               "sum_insured_kes_per_acre": "10000"})
    assert r.status_code == 200 and "KES 2,000" in r.text and "ILLUSTRATIVE" in r.text


def test_no_personal_data_in_urls_or_audit(app):
    """Every link and form action in the rendered pages, and every audit row, is free of IDs and phones."""
    c = TestClient(app)
    tok = login(c)
    review, done = enrol_via_portal(c, tok)
    pages = [review.text, done.text] + [c.get(p).text for p in ("/dashboard", "/members", "/enrol", "/quote", "/bulk")]
    for html in pages:
        for url in re.findall(r'(?:href|action)="([^"]*)"', html):
            assert_no_pii(url)
            assert "?" not in url or url.startswith("/static/")
    with transaction(app.state.factory) as s:
        for ev in s.scalars(select(AuditEvent)):
            assert_no_pii(f"{ev.actor} {ev.entity_id} {ev.details}")
        actions = {ev.action for ev in s.scalars(select(AuditEvent))}
    assert {"login", "farmer.created", "policy.created"} <= actions
