"""Low-risk fixes from the overnight review (docs/overnight/REVIEW.md, "fixed")."""
import base64
import csv
import io
import json
import logging
import math
import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from agroshield_platform import enquiries as enq
from agroshield_platform.crypto import CallbackTokenFilter, ScrubFilter
from agroshield_platform.csvsafe import cell, writer
from agroshield_platform.db import transaction
from agroshield_platform.models import AuditEvent, Policy, PublicEnquiry

from test_platform import app, book, csrf_of, enrol_form, enrol_via_portal, login, settings, vault  # noqa: F401

HTML = {"accept": "text/html"}


def session_payload(client: TestClient) -> str:
    raw = client.cookies.get("session")
    body = raw.split(".")[0]
    return base64.b64decode(body + "=" * (-len(body) % 4)).decode("utf-8", "replace")


def test_flash_messages_carry_no_farmer_names_in_the_cookie(app):  # noqa: F811
    c = TestClient(app)
    tok = login(c)
    enrol_via_portal(c, tok)
    pid = re.search(r'action="/policies/([0-9a-f]{32})/remind"', c.get("/dashboard").text).group(1)
    r = c.post(f"/policies/{pid}/remind", data={"csrf_token": tok}, follow_redirects=False)
    assert r.status_code == 303
    payload = session_payload(c)
    assert "flash" in payload and "Reminder sent for policy" in payload
    with transaction(app.state.factory) as s:
        name = s.get(Policy, pid).farmer.full_name
    assert name not in payload and name.split()[0] not in payload


@pytest.mark.parametrize("value, expected", [
    ("=HYPERLINK(\"http://x.example\",\"Jane\")", "'=HYPERLINK(\"http://x.example\",\"Jane\")"),
    ("+cmd", "'+cmd"), ("@SUM(A1)", "'@SUM(A1)"), ("-x", "'-x"), ("\tTab", "'\tTab"),
    ("-1500.00", "-1500.00"), ("-12", "-12"), ("Jane Wanjiru", "Jane Wanjiru"), (-1500.0, -1500.0), (0, 0),
])
def test_csv_cells_cannot_become_formulas(value, expected):
    assert cell(value) == expected


def test_policy_export_neutralises_formula_names(app):  # noqa: F811
    c = TestClient(app)
    tok = login(c, "manager")
    enrol_via_portal(c, tok, full_name="=HYPERLINK(\"http://x.example\",\"Jane\")")
    rows = list(csv.reader(io.StringIO(c.get("/export/policies.csv").text)))
    names = [r[rows[0].index("full_name")] for r in rows[1:]]
    assert names and all(n.startswith("'=") for n in names)
    b = io.StringIO()
    writer(b, lineterminator="\n").writerow(["=1+1", -5, "-5"])
    assert b.getvalue() == "'=1+1,-5,-5\n"


def test_uploads_over_the_limit_are_refused(app):  # noqa: F811
    c = TestClient(app)
    tok = login(c, "manager")
    big = b"member_no\n" + b"x" * (5_000_001)
    r = c.post("/bulk/check", data={"csrf_token": tok}, files={"file": ("big.csv", big, "text/csv")})
    assert r.status_code == 413 and "too large" in r.text


def test_scrub_filter_still_masks_numbers_passed_as_ints():
    rec = logging.LogRecord("x", logging.INFO, __file__, 1, "id %s code %d", (31415926, 200), None)
    ScrubFilter().filter(rec)
    assert rec.getMessage() == "id *****926 code 200"


def test_callback_token_is_redacted_and_ids_scrubbed_in_access_logs():
    rec = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d',
                            ("127.0.0.1:5000", "POST", "/mpesa/callback/s3cr3t-token-value", "1.1", 200), None)
    for f in (CallbackTokenFilter(), ScrubFilter()):
        assert f.filter(rec)
    line = rec.getMessage()                                            # still formats: the status code stays a number
    assert line.endswith(" 200") and "s3cr3t" not in line and "/mpesa/callback/[token]" in line
    rec = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, '"%s %s"', ("POST", "/ussd/abc123?x=1"), None)
    CallbackTokenFilter().filter(rec)
    assert "abc123" not in rec.getMessage()
    from agroshield_platform.cli import _uvicorn_log_config
    cfg = _uvicorn_log_config()
    assert all(h["filters"] == ["token", "scrub"] for h in cfg["handlers"].values())


def test_quote_breakdown_shows_the_amount_actually_asked_for(app):  # noqa: F811
    c = TestClient(app)
    login(c)
    page = c.post("/quote", data={"csrf_token": csrf_of(c.get("/quote").text), "ward_id": "ward-a", "acreage": "1.5",
                                  "sum_insured_kes_per_acre": "10000"}).text
    lead = re.search(r"Farmer pays KES ([\d,]+) for", page)
    tot = re.search(r'<span class="tot">Farmer pays</span><span class="tot num">KES ([\d,]+)</span>', page)
    assert lead and tot and lead.group(1) == tot.group(1)             # one figure, rounded up, in both places


def test_kaip_receivable_excludes_lapsed_cover_on_sacco_reports(app):  # noqa: F811
    c = TestClient(app)
    tok = login(c, "manager")
    enrol_via_portal(c, tok)
    with transaction(app.state.factory) as s:
        p = s.scalar(select(Policy))
        share = p.government_share_kes
        assert share > 0
        p.status = "lapsed_unpaid"
    page = c.get("/reports").text
    m = re.search(r"KAIP subsidy receivable</div><div class=\"v\">KES ([\d,]+)<", page)
    assert m and m.group(1) == "0"


def test_field_errors_are_tied_to_their_inputs_and_radios_are_grouped(app):  # noqa: F811
    c = TestClient(app)
    tok = login(c)
    token = re.search(r'name="token" value="([^"]+)"', c.get("/enrol").text).group(1)
    r = c.post("/enrol/step", data={"csrf_token": tok, "token": token, "step": 1, "nav": "next", "member_no": "",
                                    "full_name": "", "national_id": "12", "phone": "123"})
    html = r.text
    assert 'aria-invalid="true" aria-describedby="phone-err"' in html and 'id="phone-err"' in html
    assert '<fieldset class="choice-group"><legend>Language for SMS and phone menus</legend>' in html
    q = c.get("/quote").text
    assert '<fieldset class="choice-group"><legend>Bought certified seed last season?</legend>' in q


def test_enquiry_can_be_deleted_on_request(app, vault):  # noqa: F811
    with transaction(app.state.factory) as s:
        e = enq.record(s, vault, "demo", {"name": "Test Person (fictional)", "email": "t@example.org", "org_type": "insurer",
                                          "consent": "yes"})
        ref = e.ref
    with transaction(app.state.factory) as s:
        assert enq.delete(s, ref.lower(), "cli") is True
        assert enq.delete(s, "NOPE0000", "cli") is False
    with transaction(app.state.factory) as s:
        assert s.scalar(select(PublicEnquiry)) is None
        ev = s.scalar(select(AuditEvent).where(AuditEvent.action == "enquiry.deleted"))
        assert ev.entity_id == ref and "example.org" not in json.dumps(ev.details)


def test_input_borders_meet_non_text_contrast():
    from pathlib import Path
    tokens = (Path(__file__).resolve().parents[1] / "src" / "agroshield_platform" / "web" / "static" / "tokens.css").read_text()

    def lum(h):
        c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        c = [x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
        return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]

    def ratio(a, b):
        a, b = lum(a), lum(b)
        return (max(a, b) + .05) / (min(a, b) + .05)
    light, dark = re.findall(r"--input-border: (#[0-9A-Fa-f]{6})", tokens)[:2]
    assert min(ratio(light, "#F3EFE6"), ratio(light, "#FFFFFF")) >= 3
    assert min(ratio(dark, "#20232E"), ratio(dark, "#1A1D26")) >= 3
    assert math.isfinite(ratio(light, dark))


def test_scrub_filter_keeps_dict_arguments(caplog):
    """The M-Pesa re-check logs a dict of counts; the scrubber once turned it into a tuple of keys (a logging error)."""
    import logging
    from agroshield_platform.crypto import ScrubFilter
    rec = logging.LogRecord("t", logging.INFO, __file__, 1, "M-Pesa re-check: %s", ({"checked": 2, "paid": 1},), None)
    ScrubFilter().filter(rec)
    assert rec.getMessage() == "M-Pesa re-check: {'checked': 2, 'paid': 1}"
    rec = logging.LogRecord("t", logging.INFO, __file__, 1, "phone %(p)s", ({"p": "0722 718 281"},), None)
    ScrubFilter().filter(rec)
    assert "718 281" not in rec.getMessage()
