"""Underwriter workspace (milestone 7): the insurer's view of its own book, and only its own.

Two insurers, each with one SACCO and a replayed 2008 long-rains season at Ward A
(a confirmed drought payout). All people are fictional.
"""
import hashlib
import io
import json
import re
import zipfile
from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from agroshield_platform import monitoring as mon
from agroshield_platform import services as sv
from agroshield_platform.crypto import hash_password
from agroshield_platform.db import transaction
from agroshield_platform.models import AuditEvent, Insurer, Officer, Payout, Sacco
from agroshield_platform.web.app import create_app

from conftest import REPO
from test_platform import PASSWORD, assert_no_pii, book, inp, login, settings  # noqa: F401

PEOPLE = {"UW1": [("A-1", "31415926", "0722 718 281"), ("A-2", "27182818", "0733 141 592")],
          "UW2": [("OTHER-77", "16180339", "0711 618 033")]}


@pytest.fixture
def world(settings, book, cfg):
    app = create_app(settings, book, today=date(2008, 9, 3))
    past = sv.Context(cfg, book, app.state.vault, today=date(2007, 12, 15), mpesa=app.state.state["mpesa"])
    with transaction(app.state.factory) as s:
        for code, people in PEOPLE.items():
            ins = Insurer(code=code, name=f"Insurer {code}", is_demo=True)
            s.add(ins)
            s.flush()
            sacco = Sacco(code=f"S{code}", name=f"SACCO of {code}", is_demo=True, insurer_id=ins.id)
            s.add(sacco)
            s.flush()
            s.add_all([Officer(insurer_id=ins.id, username=f"uw-{code}", display_name=f"UW {code}", role="underwriter",
                               password_hash=hash_password(PASSWORD)),
                       Officer(sacco_id=sacco.id, username=f"man-{code}", display_name="Manager", role="manager",
                               password_hash=hash_password(PASSWORD)),
                       Officer(sacco_id=sacco.id, username=f"off-{code}", display_name="Officer", role="officer",
                               password_hash=hash_password(PASSWORD))])
            for member, nid, phone in people:
                p = sv.enrol(past, s, sacco, None, inp(year=2008, member_no=member, national_id=nid, phone=phone,
                                                        full_name=f"Farmer {member} (fictional)"))
                assert p.insurer_id == ins.id
                sv.record_payment(past, s, p, p.amount_due_kes, "mpesa", f"R-{member}", "t",
                                  received_at=datetime(2008, 1, 5, tzinfo=sv.NAIROBI))
        replay = sv.Context(cfg, book, app.state.vault, today=date(2008, 9, 1), mpesa=app.state.state["mpesa"])
        mon.run_monitoring(replay, s, as_of=date(2008, 9, 1), mode="replay", year=2008, wards=["ward-a"])
    return app


def _ids(app, code):
    with transaction(app.state.factory) as s:
        ins = s.scalar(select(Insurer).where(Insurer.code == code))
        return [p.id for p in s.scalars(select(Payout)) if p.policy.insurer_id == ins.id]


def test_underwriter_sees_only_its_own_book(world):
    c = TestClient(world)
    tok = login(c, "uw-UW1")
    pages = {path: c.get(path).text for path in ("/uw", "/uw/triggers", "/uw/money", "/uw/bordereaux", "/uw/pricing",
                                                 "/uw/reinsurer")}
    assert "SACCO of UW1" in pages["/uw"] and "SACCO of UW1" in pages["/uw/money"]
    for path, html in pages.items():
        assert "SACCO of UW2" not in html and "OTHER-77" not in html and "SUW2" not in html, path
        assert_no_pii(html)
    assert re.search(r"Policies written</div><div class=\"v\">2<", pages["/uw"])
    other = _ids(world, "UW2")[0]
    assert c.post(f"/uw/payouts/{other}/approve", data={"csrf_token": tok}).status_code == 404
    assert c.post(f"/uw/payouts/{other}/hold", data={"csrf_token": tok, "reason": "x"}).status_code == 404
    month = c.get("/uw/bordereaux").text
    zips = re.findall(r'href="/uw/bordereaux/(\d{4}-\d{2})\.zip"', month)
    for m in zips:
        z = zipfile.ZipFile(io.BytesIO(c.get(f"/uw/bordereaux/{m}.zip").content))
        body = z.read("premium.csv").decode() + z.read("payouts.csv").decode()
        assert "OTHER-77" not in body and "SUW2" not in body


def test_sacco_users_cannot_open_the_workspace_and_underwriters_skip_sacco_pages(world):
    for user in ("man-UW1", "off-UW1"):
        c = TestClient(world)
        login(c, user)
        for path in ("/uw", "/uw/triggers", "/uw/money", "/uw/bordereaux", "/uw/pricing", "/uw/reinsurer",
                     "/uw/bordereaux/2007-12.zip"):
            assert c.get(path).status_code == 403, (user, path)
        assert c.post(f"/uw/payouts/{_ids(world, 'UW1')[0]}/approve",
                      data={"csrf_token": re.search(r'name="csrf_token" value="([^"]+)"', c.get("/dashboard").text).group(1)}
                      ).status_code == 403
    u = TestClient(world)
    tok = re.search(r'name="csrf_token" value="([^"]+)"', u.get("/login").text).group(1)
    r = u.post("/login", data={"username": "uw-UW1", "password": PASSWORD, "csrf_token": tok}, follow_redirects=False)
    assert r.headers["location"] == "/uw"
    for path in ("/dashboard", "/members", "/enrol", "/payouts", "/reports"):
        r = u.get(path, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/uw", path


def test_approve_and_hold_are_audited_and_gate_payment(world):
    c = TestClient(world)
    tok = login(c, "uw-UW1")
    a, b = _ids(world, "UW1")
    r = c.post(f"/uw/payouts/{b}/hold", data={"csrf_token": tok, "reason": ""}, follow_redirects=True)
    assert "a reason is required" in r.text
    c.post(f"/uw/payouts/{b}/hold", data={"csrf_token": tok, "reason": "Check ward data for dekad 2"})
    c.post(f"/uw/payouts/{a}/approve", data={"csrf_token": tok})
    with transaction(world.state.factory) as s:
        pa, pb = s.get(Payout, a), s.get(Payout, b)
        assert (pa.status, pa.approved_by) == ("approved", "uw-UW1")
        assert (pb.status, pb.hold_reason) == ("held", "Check ward data for dekad 2")
        acts = {(e.action, e.actor) for e in s.scalars(select(AuditEvent))}
        assert ("payout.approved", "uw-UW1") in acts and ("payout.held", "uw-UW1") in acts
    m = TestClient(world)
    mtok = login(m, "man-UW1")
    page = m.get("/payouts").text
    assert "held by the insurer" in page and "Check ward data for dekad 2" in page
    assert f'action="/payouts/{b}/pay"' not in page and f'action="/payouts/{a}/pay"' in page
    r = m.post(f"/payouts/{b}/pay", data={"csrf_token": mtok}, follow_redirects=True)
    assert "held by the insurer" in r.text
    # approve everything still calculated for the event, then the held one can be approved too
    with transaction(world.state.factory) as s:
        sid = s.get(Payout, a).ward_status_id
    c.post(f"/uw/payouts/approve-event/{sid}", data={"csrf_token": tok})
    c.post(f"/uw/payouts/{b}/approve", data={"csrf_token": tok})
    with transaction(world.state.factory) as s:
        assert s.get(Payout, b).status == "approved"
        assert s.scalar(select(Payout).where(Payout.id == _ids(world, "UW2")[0])).status == "calculated"   # untouched


def test_triggers_page_shows_the_clock(world):
    c = TestClient(world)
    login(c, "uw-UW1")
    html = c.get("/uw/triggers").text
    # Ward A 2008 WRSI: 67.99 at B-1.2.1 (SoilGrids soil); was 67.58 with the placeholder.
    assert "Payout clock per event" in html and "67.99 (final)" in html
    assert re.search(r"<td class=\"num\">\s*\d+\s*</td>", html)                     # days left on the replay calendar
    assert "Waiting for approval (2)" in html


def test_bordereaux_zip_manifest_and_masking(world):
    c = TestClient(world)
    login(c, "uw-UW1")
    months = re.findall(r'href="/uw/bordereaux/(\d{4}-\d{2})\.zip"', c.get("/uw/bordereaux").text)
    assert "2008-09" in months
    z = zipfile.ZipFile(io.BytesIO(c.get("/uw/bordereaux/2008-09.zip").content))
    manifest = json.loads(z.read("manifest.json"))
    for name, meta in manifest["files"].items():
        data = z.read(name)
        assert hashlib.sha256(data).hexdigest() == meta["sha256"]
        assert data.decode().count("\n") == meta["rows"] + 1
    payouts = z.read("payouts.csv").decode()
    assert manifest["files"]["payouts.csv"]["rows"] == 2 and "*****926" in payouts
    for nid, phone in (("31415926", "0722 718 281"), ("27182818", "0733 141 592")):
        assert_no_pii(payouts, nid, phone)
    assert c.get("/uw/bordereaux/../../etc.zip").status_code == 404
    with transaction(world.state.factory) as s:
        assert s.scalar(select(AuditEvent).where(AuditEvent.action == "bordereaux.exported")) is not None


def test_pricing_runs_and_reports(world):
    c = TestClient(world)
    login(c, "uw-UW1")
    html = c.get("/uw/pricing").text
    runs = re.findall(r'href="/uw/runs/([^/]+)/report.html"', html)
    assert runs and "B-1.2.1" in html
    assert c.get(f"/uw/runs/{runs[0]}/report.html").status_code == 200
    assert c.get("/uw/runs/..%2F..%2Fconfig/report.html").status_code == 404
    assert "trigger.calculated" in html


def test_reinsurer_summary(world, cfg):
    c = TestClient(world)
    login(c, "uw-UW1")
    html = c.get("/uw/reinsurer").text
    for words in ("Expected annual loss", "1-in-10 annual loss", "1-in-20 annual loss", "reporting only, never pricing",
                  "Climate risk (TCFD)", "Smallholders"):
        assert words in html
    assert_no_pii(html)


def test_esg_never_feeds_pricing():
    for f in (REPO / "src" / "agroshield_pricing").rglob("*.py"):
        assert not re.search(r"^\s*(from|import)\s+\S*(underwriting|agroshield_platform)", f.read_text(encoding="utf-8"), re.M), f
