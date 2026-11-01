"""Milestone 7: ward monitoring, Payout Tracker, missed-payout reports, weather (display only).

Seasons replayed here are real CHIRPS history at the placeholder Ward A: 2008 (drought,
final WRSI 67.99 at B-1.2.1; 67.58 with the placeholder soil) and 2007 (germination dry spell). Farmers are fictional.
"""
import dataclasses
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from agroshield_pricing.engine import price_ward
from agroshield_pricing.monitor import ward_status
from agroshield_pricing.pet import make_pet_source
from agroshield_pricing.rainfall import make_source
from agroshield_platform import monitoring as mon
from agroshield_platform import mpesa as mp
from agroshield_platform import services as sv
from agroshield_platform import ussd
from agroshield_platform import weather as wx
from agroshield_platform.db import transaction
from agroshield_platform.models import AuditEvent, MissedPayoutReport, Payout, Policy, Sacco, SmsMessage, WardStatus
from agroshield_platform.web.app import create_app

from conftest import REPO
from test_m6b import assert_plain
from test_platform import NID2, PHONE, PHONE2, PASSWORD, assert_no_pii, book, db, inp, login, settings, vault  # noqa: F401


@pytest.fixture(scope="module")
def history(cfg):
    rs, ps = make_source(cfg, allow_download=False), make_pet_source(cfg, allow_download=False)
    w = cfg.ward("ward-a")
    return rs.daily(w, 1981, 2025), ps.daily(w, 1981, 2025), price_ward(cfg, "ward-a", rs, ps).seasons["LR"].table


# ------------------------------------------------------------------ monitoring (pure)
def test_season_timeline_2008(cfg, history):
    rain, pet, table = history
    before = ward_status(cfg, "ward-a", "LR", 2008, date(2008, 2, 10), rain, pet)
    assert before["phase"] == "before_season" and before["confirmed"] == []
    mid = ward_status(cfg, "ward-a", "LR", 2008, date(2008, 6, 1), rain, pet)
    assert mid["phase"] == "in_season" and mid["confirmed"] == [] and mid["level"] in ("watch", "alert")
    final = ward_status(cfg, "ward-a", "LR", 2008, date(2008, 9, 1), rain, pet)
    assert final["phase"] == "complete" and final["confirmed"] == ["wrsi_final"]
    assert final["projected_wrsi"] == pytest.approx(table.loc[2008, "wrsi"])          # the pricing engine's number
    assert final["projected_share"] == pytest.approx(table.loc[2008, "wrsi_share"], abs=1e-6)
    assert final["level"] == "payout" and final["index_version"] == cfg.product.layer_b.version


def test_monitoring_never_looks_ahead(cfg, history):
    rain, pet, _ = history
    as_of = date(2008, 5, 1)
    full = ward_status(cfg, "ward-a", "LR", 2008, as_of, rain, pet)
    # The season's own rain after the as-of date must make no difference (other years are climatology).
    hidden = rain.drop(rain.loc["2008-05-01":"2008-12-31"].index)
    cut = ward_status(cfg, "ward-a", "LR", 2008, as_of, hidden, pet)
    keys = ("phase", "level", "projected_wrsi", "projected_share", "sos", "confirmed", "rain_pct_of_normal", "inputs_sha256")
    assert {k: full[k] for k in keys} == {k: cut[k] for k in keys}
    assert full["data_through"] == "2008-04-30"


def test_germination_dry_spell_confirmed_only_after_its_check(cfg, history):
    rain, pet, table = history
    assert bool(table.loc[2007, "germination_failed"])
    early = ward_status(cfg, "ward-a", "LR", 2007, date(2007, 3, 25), rain, pet)
    assert "germination_dry_spell" not in early["confirmed"]
    later = ward_status(cfg, "ward-a", "LR", 2007, date(2007, 4, 20), rain, pet)
    assert "germination_dry_spell" in later["confirmed"] and later["level"] == "payout"


def test_stale_data_says_unavailable(cfg, history):
    rain, pet, _ = history
    st = ward_status(cfg, "ward-a", "LR", 2026, date(2026, 5, 1), rain, pet)     # history ends 2025
    assert st["phase"] == "data_unavailable" and st["level"] == "none"


def test_season_to_watch(cfg):
    assert mon.season_for(cfg, "ward-a", "LR", date(2026, 10, 29)) == 2027
    assert mon.season_for(cfg, "ward-a", "LR", date(2027, 5, 1)) == 2027


# ------------------------------------------------------------------ payouts
@pytest.fixture
def replay(cfg, book, vault, db):
    """A demo SACCO with four LR 2008 policies at Ward A: three paid in time (one loan-linked), one never paid."""
    ctx = sv.Context(cfg, book, vault, today=date(2007, 12, 15), mpesa=mp.SimulatedDaraja())
    with transaction(db) as s:
        sacco = Sacco(code="TST01", name="Test SACCO", is_demo=True)
        s.add(sacco)
        s.flush()
        people = [inp(year=2008), inp(year=2008, member_no="M-2", national_id=NID2, phone=PHONE2, acreage=3.0,
                                      loan_linked=True, loan_ref="LN-9", consent_loan_linked_payout=True),
                  inp(year=2008, member_no="M-3", national_id="44444444", phone="0744 444 444", consent_sms=False),
                  inp(year=2008, member_no="M-4", national_id="55555555", phone="0755 555 555")]
        pols = [sv.enrol(ctx, s, sacco, None, x) for x in people]
        for i, p in enumerate(pols[:3]):
            sv.record_payment(ctx, s, p, p.amount_due_kes, "sacco_deduction", f"R{i}", "t",
                              received_at=datetime(2008, 1, 10, tzinfo=sv.NAIROBI))
        sv.close_sales_windows(dataclasses.replace(ctx, today=date(2008, 2, 15)), s)
        ids = [p.id for p in pols]
    return ctx, ids


def _run(ctx, s, as_of, year=2008):
    return mon.run_monitoring(dataclasses.replace(ctx, today=as_of), s, as_of=as_of, mode="replay", year=year,
                              wards=["ward-a"])


def test_payouts_only_from_confirmed_triggers_and_active_cover(cfg, replay, db):
    ctx, ids = replay
    with transaction(db) as s:
        _run(ctx, s, date(2008, 6, 1))
        assert s.scalar(select(Payout)) is None                                   # projected, not confirmed
        [st] = _run(ctx, s, date(2008, 9, 1))
        pays = s.scalars(select(Payout).order_by(Payout.id)).all()
        assert sorted(p.policy_id for p in pays) == sorted(ids[:3])               # the lapsed policy gets nothing
        share = st.projected_share
        by = {p.policy_id: p for p in pays}
        assert by[ids[0]].amount_kes == pytest.approx(round(share * 10000 * 2, 2))
        assert by[ids[1]].method == "sacco_loan" and by[ids[0]].method == "mpesa"
        assert all(p.due_by == date(2008, 9, 1) + timedelta(days=cfg.monitoring.payout_within_days) for p in pays)
        _run(ctx, s, date(2008, 9, 2))
        assert len(s.scalars(select(Payout)).all()) == 3                          # re-running never duplicates
        acts = [a.action for a in s.scalars(select(AuditEvent))]
        assert acts.count("trigger.calculated") == 3 and acts.count("payout.calculated") == 3
        assert s.scalar(select(Policy).where(Policy.id == ids[3])).status == "lapsed_unpaid"
        assert s.scalar(select(SmsMessage).where(SmsMessage.template == "payout_calculated")) is None   # not before approval
        assert {p.status for p in pays} == {"calculated"}
        with pytest.raises(mon.PayoutError, match="approval"):
            mon.pay(ctx, s, pays[0], "manager")
        for p in pays:
            mon.approve(ctx, s, p, "underwriter")
        sms = [m.template for m in s.scalars(select(SmsMessage).where(SmsMessage.template == "payout_calculated"))]
        assert len(sms) == 2                                                      # the farmer without SMS consent gets none


def test_replanting_voucher_and_cap(cfg, book, vault, db):
    ctx = sv.Context(cfg, book, vault, today=date(2006, 12, 15))
    with transaction(db) as s:
        sacco = Sacco(code="TST01", name="Test SACCO", is_demo=True)
        s.add(sacco)
        s.flush()
        p = sv.enrol(ctx, s, sacco, None, inp(year=2007))
        sv.record_payment(ctx, s, p, p.amount_due_kes, "mpesa", "R1", "t", received_at=datetime(2007, 1, 5, tzinfo=sv.NAIROBI))
        _run(ctx, s, date(2007, 4, 20), year=2007)
        [v] = s.scalars(select(Payout)).all()
        assert v.kind == "replant_voucher" and v.status == "calculated" and v.voucher_code is None
        mon.approve(ctx, s, v, "underwriter")
        assert v.status == "issued" and re.fullmatch(r"V-[A-Z2-9]{6}", v.voucher_code)
        assert v.amount_kes == cfg.product.layer_b.germination_dry_spell.replant_cost_kes_per_acre * 2
        _run(ctx, s, date(2007, 9, 1), year=2007)                                # final WRSI 100: no cash payout
        assert [x.kind for x in s.scalars(select(Payout))] == ["replant_voucher"]
        with pytest.raises(mon.PayoutError, match="agro-dealer"):
            mon.pay(ctx, s, v, "manager")
        mon.pay(ctx, s, v, "manager", "AGRO-77")
        assert v.status == "redeemed"


def test_paying(cfg, replay, db):
    ctx, ids = replay
    with transaction(db) as s:
        _run(ctx, s, date(2008, 9, 1))
        cash = s.scalar(select(Payout).where(Payout.policy_id == ids[0]))
        loan = s.scalar(select(Payout).where(Payout.policy_id == ids[1]))
        for p in (cash, loan):
            mon.approve(ctx, s, p, "underwriter")
        mon.pay(ctx, s, cash, "manager")
        assert cash.status == "paid" and cash.reference.startswith("SIMB2C")
        with pytest.raises(mon.PayoutError):
            mon.pay(ctx, s, cash, "manager")
        with pytest.raises(mon.PayoutError, match="SACCO reference"):
            mon.pay(ctx, s, loan, "manager")
        mon.pay(ctx, s, loan, "manager", "SACCO-CR-1")
        msgs = {m.template: m.body for m in s.scalars(select(SmsMessage))}
        assert "sent to your M-Pesa" in msgs["payout_paid"] and "SACCO loan LN-9" in msgs["payout_paid_loan"]
        for body in msgs.values():
            assert_no_pii(body)
        assert mon.overdue(s.scalar(select(Payout).where(Payout.policy_id == ids[2])), date(2008, 9, 20))


def test_daraja_b2c_is_refused_until_configured():
    from agroshield_platform.settings import Mpesa
    c = mp.DarajaClient(Mpesa(env="sandbox", consumer_key="k", consumer_secret="s", shortcode="1", passkey="p"),
                        "https://example.org/cb")
    with pytest.raises(mp.MpesaError, match="initiator"):
        c.b2c("+254700000000", 100, "x")


# ------------------------------------------------------------------ farmer channel (USSD) and missed-payout reports
def test_ussd_payouts_and_crop_loss_report(cfg, replay, db):
    ctx, ids = replay
    with transaction(db) as s:
        _run(ctx, s, date(2008, 9, 1))
        screen = ussd.handle(ctx, s, PHONE, "3")
        assert "being checked by the insurer" in screen and "Payout KES" not in screen     # nothing promised yet
        mon.approve(ctx, s, s.scalar(select(Payout).where(Payout.policy_id == ids[0])), "underwriter")
        screen = ussd.handle(ctx, s, PHONE, "3")
        assert screen.startswith("END Rongai West, long rains 2008:") and "Dry season confirmed" in screen
        assert "Payout KES" in screen and len(screen) <= 182
        lapsed = ussd.handle(ctx, s, "0755 555 555", "3")
        assert "Payouts are only for cover that was fully paid" in lapsed
        assert ussd.handle(ctx, s, PHONE, "5").startswith("CON Did your maize fail")
        done = ussd.handle(ctx, s, PHONE, "5*1")
        ref = re.search(r"ref (MP-[A-Z2-9]{6})", done).group(1)
        assert "does not change a payout" in done and len(done) <= 182
        r = s.scalar(select(MissedPayoutReport).where(MissedPayoutReport.ref == ref))
        assert (r.category, r.channel, r.year, r.status) == ("failed_no_payout", "ussd", 2008, "open")
        assert r.index_snapshot["level"] == "payout"
        before = [(p.id, p.amount_kes, p.status) for p in s.scalars(select(Payout))]
        mon.review_missed(s, r, "basis_risk_recorded", f"Farmer {PHONE} says hail", "manager")
        assert r.status == "reviewed" and PHONE not in r.review_note
        assert [(p.id, p.amount_kes, p.status) for p in s.scalars(select(Payout))] == before   # reports never move money
        assert ussd.handle(ctx, s, PHONE, "5*0") == "END OK. Nothing was recorded."


# ------------------------------------------------------------------ portal
def _seed_app(app, cfg, book):
    from agroshield_platform.crypto import hash_password
    from agroshield_platform.models import Officer
    ctx = sv.Context(cfg, book, app.state.vault, today=date(2007, 12, 15), mpesa=app.state.state["mpesa"])
    with transaction(app.state.factory) as s:
        sacco = s.scalar(select(Sacco)) or Sacco(code="TST01", name="Test SACCO", is_demo=True)
        s.add(sacco)
        s.flush()
        s.add_all([Officer(sacco_id=sacco.id, username="officer", display_name="Officer One", role="officer",
                           password_hash=hash_password(PASSWORD)),
                   Officer(sacco_id=sacco.id, username="manager", display_name="Manager One", role="manager",
                           password_hash=hash_password(PASSWORD))])
        p = sv.enrol(ctx, s, sacco, None, inp(year=2008))
        sv.record_payment(ctx, s, p, p.amount_due_kes, "mpesa", "R1", "t", received_at=datetime(2008, 1, 5, tzinfo=sv.NAIROBI))
        return ctx, p.id


def test_home_alert_on_top_only_when_there_is_one(settings, book, cfg):
    app = create_app(settings, book, today=date(2008, 9, 3))
    ctx, pid = _seed_app(app, cfg, book)
    c = TestClient(app)
    login(c)
    quiet = c.get("/dashboard").text
    assert "ward-alert-top" not in quiet and "no rainfall alerts" in quiet
    with transaction(app.state.factory) as s:
        _run(ctx, s, date(2008, 9, 1))
    home = c.get("/dashboard").text
    assert "ward-alert-top" in home and "no rainfall alerts" not in home
    assert home.index("ward-alert-top") < home.index("Enrol a farmer") + 10_000
    assert "Dry season confirmed: payouts are due." in home
    if "Still to pay" in home:
        assert home.index("ward-alert-top") < home.index("Still to pay")


def test_payout_tracker(settings, book, cfg):
    app = create_app(settings, book, today=date(2008, 9, 3))
    ctx, pid = _seed_app(app, cfg, book)
    with transaction(app.state.factory) as s:
        _run(ctx, s, date(2008, 9, 1))
        payout_id = s.scalar(select(Payout)).id
    off, man = TestClient(app), TestClient(app)
    otok = login(off)
    page = off.get("/payouts").text
    assert "Waiting for the insurer's approval" in page
    with transaction(app.state.factory) as s:
        mon.approve(ctx, s, s.get(Payout, payout_id), "underwriter")
    page = off.get("/payouts").text
    assert "Rongai West, long rains 2008" in page and "Drought payout" in page and "To pay by" in page
    assert_plain(page, "payout tracker")
    assert "WRSI" in page                                                   # ... but only inside Details
    assert off.post(f"/payouts/{payout_id}/pay", data={"csrf_token": otok}).status_code == 403
    mtok = login(man, "manager")
    r = man.post(f"/payouts/{payout_id}/pay", data={"csrf_token": mtok}, follow_redirects=True)
    assert "recorded as paid" in r.text and "Paid " in r.text
    member_url = re.search(r'href="(/members/[0-9a-f]{32})"', page).group(1)
    r = off.post(member_url + "/missed", data={"csrf_token": otok, "category": "payout_too_small",
                                               "note": f"call {PHONE}"}, follow_redirects=True)
    assert re.search(r"Recorded as MP-[A-Z2-9]{6}", r.text)
    assert_no_pii(off.get("/payouts").text)
    assert_no_pii(r.text)


# ------------------------------------------------------------------ weather
LISTING = '<a href="/our-products/county-forecasts/nakuru-county-weekly-weather-forecast-valid-27th-october-to-2nd-november-2026/">N</a>'
PAGE = ('<title>Nakuru County weekly weather forecast valid 27th October to 2nd November 2026</title>'
        '<a href="/documents/5450/Nakuru_County_weekly_weather_forecast_valid_27th__October_to_2nd_November_2026.pdf">pdf</a>')
PDF = b"%PDF-1.4\n% test fixture\n1 0 obj << /Type /Catalog >> endobj\ntrailer << /Root 1 0 R >>\n%%EOF\n"


def _kmd(log, robots_status=404, robots_body=""):
    def handler(req: httpx.Request) -> httpx.Response:
        log.append(str(req.url))
        assert req.headers["user-agent"].startswith("AgroShield-weather/")       # identifies itself
        if req.url.path == "/robots.txt":
            return httpx.Response(robots_status, text=robots_body)
        if req.url.path == "/our-products/county-forecasts/":
            return httpx.Response(200, text=LISTING)
        if req.url.path.endswith(".pdf"):
            return httpx.Response(200, content=PDF)
        if "nakuru" in req.url.path:
            return httpx.Response(200, text=PAGE)
        return httpx.Response(404)
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_validity_dates():
    assert wx.validity("Nakuru County weekly weather forecast valid 27th October to 2nd November 2026") == \
        (date(2026, 10, 27), date(2026, 11, 2))
    assert wx.validity("Nakuru_County_weekly_weather_forecast_valid_27th__October_to_2nd_November_2026.pdf") == \
        (date(2026, 10, 27), date(2026, 11, 2))
    assert wx.validity("valid 29th December to 4th January 2027") == (date(2026, 12, 29), date(2027, 1, 4))
    assert wx.validity("no dates here") == (None, None)


def test_polite_fetch(db, tmp_path, monkeypatch):
    log = []
    now = datetime(2026, 10, 29, 8, 0, tzinfo=timezone.utc)
    with transaction(db) as s:
        res = wx.fetch(s, REPO / "config", tmp_path, http=_kmd(log), now=now)
        assert res == {"kmd_nakuru": "1 new", "tuko": "off", "kna": "off"}
        assert not any("tuko" in u or "kenyanews" in u for u in log)               # disabled sources never contacted
        [item] = s.scalars(select(wx.WeatherItem)).all()
        assert (item.valid_from, item.valid_to, item.status, item.source_label) == \
            (date(2026, 10, 27), date(2026, 11, 2), "draft", "Source: KMD")
        assert Path(item.pdf_path).read_bytes() == PDF and item.pdf_sha256 == wx.hashlib.sha256(PDF).hexdigest()
    n = len(log)
    with transaction(db) as s:
        wx.fetch(s, REPO / "config", tmp_path, http=_kmd(log), now=now + timedelta(hours=5))
        assert len(log) == n                                                         # nothing re-requested within 6 h
        assert "skipped_interval" in {f.status for f in s.scalars(select(wx.WeatherFetch))}
    with transaction(db) as s:
        wx.fetch(s, REPO / "config", tmp_path, http=_kmd(log), now=now + timedelta(hours=7))
        assert len(s.scalars(select(wx.WeatherItem)).all()) == 1                     # same PDF is not stored twice


def test_robots_disallow_is_respected(db, tmp_path):
    log = []
    with transaction(db) as s:
        wx.fetch(s, REPO / "config", tmp_path, http=_kmd(log, 200, "User-agent: *\nDisallow: /our-products/\n"))
        assert [u for u in log if not u.endswith("/robots.txt")] == []
        assert {f.status for f in s.scalars(select(wx.WeatherFetch))} == {"disallowed"}


def test_shown_only_after_approval_and_never_sent(db, tmp_path):
    _, sources = wx.load_sources(REPO / "config")
    with transaction(db) as s:
        item = wx.store_pdf(s, tmp_path, sources["kmd_nakuru"], PDF, "Nakuru forecast valid 27th October to 2nd November 2026",
                            None, "uploaded")
        assert wx.visible_items(s, date(2026, 10, 29)) == []
        with pytest.raises(wx.WeatherError, match="Kiswahili"):
            wx.approve(s, item, "Light rain expected.", "", "manager")
        wx.approve(s, item, "Light rain expected mid-week.", "Mvua kidogo katikati ya wiki.", "manager")
        assert wx.visible_items(s, date(2026, 10, 29)) == [item]
        assert wx.visible_items(s, date(2026, 11, 3)) == []                         # expired after its validity
        assert "written permission" in wx.sms_blocked(item, sources)                 # approved, still no SMS
        with pytest.raises(wx.WeatherError, match="not a PDF"):
            wx.store_pdf(s, tmp_path, sources["kmd_nakuru"], b"<html>", "x", None, "uploaded")
    # even with permission, an unapproved item may not go out
    allowed = {**sources, "kmd_nakuru": dataclasses.replace(sources["kmd_nakuru"], sms_distribution_allowed=True)}
    draft = wx.WeatherItem(source="kmd_nakuru", source_label="Source: KMD", title="t", origin="uploaded", status="draft")
    assert "not been approved" in wx.sms_blocked(draft, allowed)


def test_weather_is_display_only():
    """Pricing, triggers, monitoring, payouts and payments never import the weather module, and it never sends."""
    for f in list((REPO / "src" / "agroshield_pricing").rglob("*.py")) + \
            [REPO / "src" / "agroshield_platform" / n for n in ("monitoring.py", "mpesa.py", "services.py", "sms.py", "ussd.py")]:
        assert not re.search(r"^\s*(from|import)\s+\S*weather", f.read_text(encoding="utf-8"), re.M), f.name
    src = (REPO / "src" / "agroshield_platform" / "weather.py").read_text(encoding="utf-8")
    assert "sms.queue" not in src and "import sms" not in src and "from . import sms" not in src


def test_tracker_renders_before_the_season_starts(settings, book, cfg):
    """A 'before season' run has no rainfall figures yet; every page must still render."""
    app = create_app(settings, book, today=date(2007, 12, 20))
    ctx, _ = _seed_app(app, cfg, book)
    with transaction(app.state.factory) as s:
        [st] = _run(ctx, s, date(2007, 12, 20))
        assert st.phase == "before_season"
    c = TestClient(app)
    login(c, "manager")
    for path in ("/payouts", "/dashboard", "/reports"):
        r = c.get(path)
        assert r.status_code == 200, path
    assert "Season not started yet." in c.get("/payouts").text
