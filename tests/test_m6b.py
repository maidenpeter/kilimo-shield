"""Milestone 6b: officer-first portal. Same features and rules; plain words, one step per screen."""
import dataclasses
import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from agroshield_platform.db import transaction
from agroshield_platform.models import SmsMessage
from agroshield_platform.web.app import create_app

from test_platform import (NID, PHONE, TODAY, app, assert_no_pii, book, enrol_form, enrol_via_portal, login,  # noqa: F401
                           settings)

# Jargon that must not appear on officer screens outside a "Details" toggle.
JARGON = [r"\bLayer [AB]\b", r"\bWRSI\b", r"\bLR\b", r"\bindex version", r"[Mm]ilestone", r"extraction area",
          r"discount funder", r"\bfunded by\b", r"\bIllustrative Ward\b"]


def visible(html: str) -> str:
    """Page text an officer sees without opening Details (and without the development banner)."""
    html = re.sub(r"<details class=\"more\">.*?</details>", "", html, flags=re.S)
    html = re.sub(r'<div class="devbar">.*?</div>', "", html, flags=re.S)
    html = re.sub(r"<(script|style)\b.*?</\1>", "", html, flags=re.S)
    return re.sub(r"<[^>]+>", " ", html)


def assert_plain(html: str, where: str) -> None:
    text = visible(html)
    for pat in JARGON:
        assert not re.search(pat, text), f"{where}: {pat!r} on an officer screen"


def token_of(html: str) -> str:
    return re.search(r'name="token" value="([^"]+)"', html).group(1)


def test_wizard_one_step_per_screen(app):
    c = TestClient(app)
    tok = login(c)
    screens = []
    r = c.get("/enrol")
    screens.append(r.text)
    assert "Step 1 of 5" in r.text and 'name="layer_' not in r.text      # one product: no layer checkboxes
    token = token_of(r.text)
    form = {"csrf_token": tok, "token": token, "nav": "next"}
    r = c.post("/enrol/step", data={**form, "step": 1, "member_no": "M-0100", "full_name": "Test Farmer (fictional)",
                                     "national_id": NID, "phone": PHONE, "language": "sw", "gender": "female"})
    screens.append(r.text)
    assert "Step 2 of 5" in r.text and "Use this phone's location" in r.text and 'type="number" step="any"' not in r.text
    r = c.post("/enrol/step", data={**form, "step": 2, "ward_id": "ward-a", "acreage": "2",
                                     "res_certified_seed_verified": "1"})
    screens.append(r.text)
    assert "Step 3 of 5" in r.text
    r = c.post("/enrol/step", data={**form, "step": 3, "consent_data_processing": "1", "consent_sms": "1"})
    screens.append(r.text)
    assert "Step 4 of 5" in r.text
    lead = re.search(r'<p class="lead">(.*?)</p>', r.text, re.S).group(1)
    assert " ".join(lead.split()) == "Farmer pays KES 1,900 for 2 acres (KES 950 per acre)."   # 2000 less 5% seed discount
    assert "Covers up to KES 20,000 if the rains fail" in r.text
    r = c.post("/enrol/confirm", data={**form, "payment_route": "mpesa", "sum_insured_kes_per_acre": "10000"})
    screens.append(r.text)
    assert r.status_code == 200 and "Step 5 of 5" in r.text and "is enrolled" in r.text
    assert len(screens) == 5
    for i, html in enumerate(screens, 1):
        assert_no_pii(html)
        assert_plain(html, f"enrol screen {i}")


def test_wizard_checks_each_step_and_keeps_answers_on_back(app):
    c = TestClient(app)
    tok = login(c)
    token = token_of(c.get("/enrol").text)
    base = {"csrf_token": tok, "token": token}
    r = c.post("/enrol/step", data={**base, "step": 1, "nav": "next", "member_no": "M-1", "full_name": "A B",
                                     "national_id": "12", "phone": "0800"})
    assert r.status_code == 422 and "Step 1 of 5" in r.text and "6 to 9 digits" in r.text
    r = c.post("/enrol/step", data={**base, "step": 1, "nav": "next", "national_id": NID, "phone": PHONE})
    assert "Step 2 of 5" in r.text
    r = c.post("/enrol/step", data={**base, "step": 2, "nav": "back", "acreage": "3"})
    assert "Step 1 of 5" in r.text and 'value="M-1"' in r.text and "Saved: +254 7** *** 281" in r.text
    assert_no_pii(r.text)


def test_change_cover_amount_on_the_price_step(app):
    c = TestClient(app)
    tok = login(c)
    review = c.post("/enrol/review", data={**enrol_form(), "csrf_token": tok})
    r = c.post("/enrol/step", data={"csrf_token": tok, "token": token_of(review.text), "step": 4, "nav": "reprice",
                                     "sum_insured_kes_per_acre": "15000"})
    assert "Covers up to KES 30,000" in r.text and "Step 4 of 5" in r.text


def test_navigation_by_role(app):
    off, man = TestClient(app), TestClient(app)
    login(off)
    login(man, "manager")
    home = off.get("/dashboard").text
    nav = re.search(r'<nav class="primary full" aria-label="Main">.*?</nav>', home, re.S).group(0)
    assert [x for x in re.findall(r">([^<>]+)</a>", nav)] == ["Home", "Enrol a farmer", "Members"]   # brief section 3
    assert 'href="/payouts"' in home                                    # Payouts stays one tap away from Home
    assert 'href="/quote"' in home                                        # Quick price stays on Home
    mnav = re.search(r'<nav class="primary full" aria-label="Main">.*?</nav>', man.get("/dashboard").text, re.S).group(0)
    assert re.findall(r">([^<>]+)</a>", mnav) == ["Home", "Enrol a farmer", "Members", "Reports", "Import", "Weather"]
    assert off.get("/reports").status_code == 403 and off.get("/import").status_code == 403
    assert man.get("/reports").status_code == 200 and "KAIP subsidy receivable" in man.get("/reports").text
    imp = man.get("/import").text
    assert "spreadsheet" in imp and "KIAMIS records" in imp
    assert 'id="kiamis"' not in off.get("/bulk").text                     # KIAMIS stays manager-only
    assert "Developer" not in home                                         # tests run without development keys


def test_developer_menu_only_in_development(settings, book):
    dev = create_app(dataclasses.replace(settings, dev_keys=True), book, today=TODAY)
    from test_platform import Officer, Sacco, hash_password, PASSWORD
    with transaction(dev.state.factory) as s:
        sacco = Sacco(code="DEV01", name="Dev SACCO", is_demo=True)
        s.add(sacco)
        s.flush()
        s.add(Officer(sacco_id=sacco.id, username="devman", display_name="Dev", password_hash=hash_password(PASSWORD),
                      role="manager"))
    c = TestClient(dev)
    login(c, "devman")
    html = c.get("/dashboard").text
    assert "Developer" in html and 'href="/sms"' in html and 'href="/dev/mpesa"' in html
    assert 'class="btn ghost small menu-btn"' in html and 'id="sheet"' in html   # single Menu button on phones
    assert 'id="dev-menu"' in html


def test_officer_home_tasks_and_reminder(app):
    c = TestClient(app)
    tok = login(c)
    enrol_via_portal(c, tok)
    home = c.get("/dashboard").text
    assert re.search(r"1 farmer still owes KES 1,900\.\s+Sales close 14 Feb\.", visible(home))
    assert "Rongai West" in home and "no rainfall alerts" in home
    assert "Gross premium" not in home and "KAIP" not in home and 'class="map"' not in home   # portfolio lives in Reports
    pid = re.search(r'action="/policies/([0-9a-f]{32})/remind"', home).group(1)
    r = c.post(f"/policies/{pid}/remind", data={"csrf_token": tok}, follow_redirects=True)
    assert "Reminder sent for policy AGS-" in r.text
    r = c.post(f"/policies/{pid}/remind", data={"csrf_token": tok}, follow_redirects=True)
    assert "already sent" in r.text
    with transaction(app.state.factory) as s:
        assert [m.template for m in s.scalars(select(SmsMessage))].count("reminder") == 1
    assert_plain(home, "home")
    assert_no_pii(home)


def test_officer_screens_use_plain_words(app):
    c = TestClient(app)
    tok = login(c)
    review, done = enrol_via_portal(c, tok)
    member_url = re.search(r'href="(/members/[0-9a-f]{32})"', c.get("/members").text).group(1)
    q = c.post("/quote", data={"csrf_token": tok, "ward_id": "ward-a", "acreage": "2"})
    for name, html in [("price step", review.text), ("done", done.text), ("members", c.get("/members").text),
                       ("member", c.get(member_url).text), ("quick price", q.text), ("enrol", c.get("/enrol").text),
                       ("home", c.get("/dashboard").text)]:
        assert_plain(html, name)
    assert "Details" in q.text and "Quote Q-" in q.text                   # technical detail is still there, folded


def test_ward_display_names(cfg):
    assert cfg.ward("ward-a").label == "Rongai West" and cfg.ward("ward-b").label == "Molo Highlands"
    assert cfg.ward("ward-a").illustrative is True


def test_demo_farms_are_smallholdings():
    from agroshield_platform.cli import DEMO_CSV
    import csv
    import io
    rows = list(csv.DictReader(io.StringIO(DEMO_CSV)))
    assert rows and all(0.5 <= float(r["acreage"]) <= 5 for r in rows)
