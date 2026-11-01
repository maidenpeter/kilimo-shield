"""Remaining brief, Phase 3 (milestone 8): the crop photo app, checks, human review and the farmer weather tab.

Brief tests: the offline queue (test_offline_queue_in_a_real_browser, plus server-side idempotency), the GPS
distance check, duplicate detection, EXIF stripping before any external call, the consent gate, reviewer-decides
logging, and the queue working with no key. All people and photos are fictional (generated images).
"""
import dataclasses
import io
import json
import random
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
from sqlalchemy import func, select

from agroshield_platform import photos as ph
from agroshield_platform import services as sv
from agroshield_platform import weather as wx
from agroshield_platform.crypto import hash_password
from agroshield_platform.db import transaction
from agroshield_platform.models import (AppUser, AuditEvent, Consent, Insurer, Officer, Payout, Photo, PhotoReview,
                                        PhotoSuggestion, Plot, Policy, Sacco, SmsMessage, WeatherItem)
from agroshield_platform.web.app import create_app

from conftest import REPO
from test_platform import NID, NID2, PASSWORD, PHONE, PHONE2, TODAY, assert_no_pii, book, csrf_of, inp, settings  # noqa: F401

LAT, LON = -0.170, 35.860                     # inside Ward A's box (fictional plot)
NAIROBI = timezone(timedelta(hours=3))


def jpeg(seed: int, exif: dict | None = None, size=(640, 480)) -> bytes:
    """A distinct fictional 'field' picture per seed; optional EXIF time and GPS like a phone camera writes."""
    rnd = random.Random(seed)
    img = Image.new("RGB", size, (rnd.randrange(40, 90), rnd.randrange(100, 160), rnd.randrange(30, 70)))
    d = ImageDraw.Draw(img)
    for _ in range(40):
        x, y = rnd.randrange(size[0]), rnd.randrange(size[1])
        d.rectangle([x, y, x + rnd.randrange(20, 160), y + rnd.randrange(20, 120)],
                    fill=(rnd.randrange(256), rnd.randrange(256), rnd.randrange(256)))
    buf = io.BytesIO()
    if exif:
        ex = Image.Exif()
        if "time" in exif:
            ex[0x0132] = exif["time"].strftime("%Y:%m:%d %H:%M:%S")             # DateTime, as many phones write it
        if "gps" in exif:
            lat, lon = exif["gps"]
            def dms(v):
                v = abs(v)
                return (int(v), int(v * 60 % 60), round(v * 3600 % 60, 2))
            ex[0x8825] = {1: "S" if lat < 0 else "N", 2: dms(lat), 3: "E" if lon > 0 else "W", 4: dms(lon)}
        ex[0x010F] = "FictionalPhone"
        img.save(buf, "JPEG", exif=ex.tobytes())
    else:
        img.save(buf, "JPEG")
    return buf.getvalue()


@pytest.fixture
def world(settings, book, cfg, tmp_path):  # noqa: F811
    calls = []

    def fake_ai(jpeg_bytes, model, timeout, key):
        calls.append(jpeg_bytes)
        return {"tag": "pest", "reason": "Holes in the leaves.", "model": "test-model"}
    s2 = dataclasses.replace(settings, photo_dir=tmp_path / "photos")
    app = create_app(s2, book, today=TODAY, ai_caller=fake_ai)
    ctx = sv.Context(cfg, book, app.state.vault, today=TODAY, mpesa=app.state.state["mpesa"])
    with transaction(app.state.factory) as s:
        ins = Insurer(code="UWP", name="Partner insurer (to be named)", is_demo=True)
        s.add(ins)
        s.flush()
        sacco = Sacco(code="PHO01", name="Photo SACCO (fictional)", is_demo=True, insurer_id=ins.id)
        other = Sacco(code="OTH01", name="Other SACCO (fictional)", is_demo=True, insurer_id=ins.id)
        s.add_all([sacco, other])
        s.flush()
        s.add_all([Officer(sacco_id=sacco.id, username="officer", display_name="Officer One", role="officer",
                           password_hash=hash_password(PASSWORD)),
                   Officer(sacco_id=sacco.id, username="manager", display_name="Manager One", role="manager",
                           password_hash=hash_password(PASSWORD)),
                   Officer(insurer_id=ins.id, username="uw", display_name="Agronomist", role="underwriter",
                           password_hash=hash_password(PASSWORD))])
        a = sv.enrol(ctx, s, sacco, None, inp(lat=LAT, lon=LON))
        b = sv.enrol(ctx, s, sacco, None, inp(member_no="M-0200", national_id=NID2, phone=PHONE2, lat=LAT + 0.01, lon=LON))
        sv.record_payment(ctx, s, a, a.amount_due_kes, "sacco_deduction", "DED-PH-1", "manager")
        ids = {"a": a.id, "b": b.id, "farmer_a": a.farmer_id, "farmer_b": b.farmer_id, "plot_a": a.plot_id,
               "plot_b": b.plot_id, "sacco": sacco.id, "other": other.id}
    app.state.ids, app.state.ai_calls, app.state.ctx = ids, calls, ctx
    return app


def _user(app, farmer_key="farmer_a", role="farmer"):
    with transaction(app.state.factory) as s:
        u, pin = ph.set_up_user(s, s.get(sv.Farmer, app.state.ids[farmer_key]), "officer", role)
        return u.id, pin


def _submit(app, uid, plot_key="plot_a", data=None, now=None, **meta):
    pcfg = ph.config(REPO / "config")
    with transaction(app.state.factory) as s:
        pol = s.get(Policy, app.state.ids["a" if plot_key == "plot_a" else "b"])
        start, _ = ph.stage_window(pcfg, app.state.ctx.cfg, pol, meta.get("stage", "emergence"))
        when = datetime.combine(start + timedelta(days=2), datetime.min.time(), tzinfo=NAIROBI) + timedelta(hours=9)
        m = {"client_id": meta.pop("client_id", None) or f"cid-{random.random():.12f}", "stage": "emergence",
             "taken_at": when.isoformat(), "lat": LAT + 0.0002, "lon": LON, "accuracy_m": 8, "source": "camera", **meta}
        p = ph.submit(s, app.state.ctx.cfg, pcfg, s.get(AppUser, uid), app.state.ids[plot_key], data or jpeg(1), m,
                      app.state.photo_store, now or (when + timedelta(hours=1)).astimezone(timezone.utc))
        return p.id


# ------------------------------------------------------------------ checks
def test_gps_distance_check(world):
    uid, _ = _user(world)
    near = _submit(world, uid, data=jpeg(1))
    far = _submit(world, uid, data=jpeg(2), lat=LAT + 0.01)                   # about 1.1 km away
    with transaction(world.state.factory) as s:
        n, f = s.get(Photo, near), s.get(Photo, far)
        assert n.status == "in_review" and n.distance_m < 50 and n.photo_point_id
        assert f.status == "rejected" and "m from the registered farm" in f.reject_reason and f.photo_point_id is None
        assert f.id not in {p.id for p in ph.queue_for(s, {world.state.ids["a"]})}


def test_duplicate_and_reused_pictures_are_flagged(world):
    uid, _ = _user(world, role="champion")
    with transaction(world.state.factory) as s:
        champ = s.get(AppUser, uid)
        ph.assign(s, champ, s.get(Plot, world.state.ids["plot_b"]), "officer")
    first = _submit(world, uid, data=jpeg(7))
    again = _submit(world, uid, data=jpeg(7))                                   # same picture, same farm
    img = Image.open(io.BytesIO(jpeg(7)))
    smaller = io.BytesIO()
    img.resize((480, 360)).save(smaller, "JPEG", quality=60)                    # resized and recompressed
    other_farm = _submit(world, uid, "plot_b", data=smaller.getvalue(), lat=LAT + 0.01)
    fresh = _submit(world, uid, data=jpeg(8))
    with transaction(world.state.factory) as s:
        assert s.get(Photo, first).flags == []
        assert "duplicate" in s.get(Photo, again).flags
        assert "reused" in s.get(Photo, other_farm).flags
        assert "duplicate" not in s.get(Photo, fresh).flags and "reused" not in s.get(Photo, fresh).flags


def test_metadata_that_does_not_add_up_is_flagged(world):
    uid, _ = _user(world)
    base = datetime(2027, 4, 15, 9, tzinfo=NAIROBI)
    t1 = _submit(world, uid, data=jpeg(11, {"time": (base - timedelta(hours=5)).replace(tzinfo=None)}),
                 taken_at=base.isoformat(), now=base.astimezone(timezone.utc))
    t2 = _submit(world, uid, data=jpeg(12, {"gps": (LAT + 0.05, LON)}), taken_at=base.isoformat(),
                 now=base.astimezone(timezone.utc))
    t3 = _submit(world, uid, data=jpeg(13), taken_at=(base + timedelta(days=1)).isoformat(), now=base.astimezone(timezone.utc))
    t4 = _submit(world, uid, data=jpeg(14), taken_at=(base - timedelta(days=30)).isoformat(), now=base.astimezone(timezone.utc))
    t5 = _submit(world, uid, data=jpeg(15), accuracy_m=400)
    with transaction(world.state.factory) as s:
        assert "time_mismatch" in s.get(Photo, t1).flags
        assert "gps_mismatch" in s.get(Photo, t2).flags
        assert "future_time" in s.get(Photo, t3).flags
        assert "old_photo" in s.get(Photo, t4).flags
        assert "low_gps_accuracy" in s.get(Photo, t5).flags


def test_exif_and_gps_are_stripped_before_storage_and_before_any_external_call(world):
    uid, _ = _user(world)
    raw = jpeg(21, {"gps": (LAT, LON), "time": datetime(2027, 4, 15, 9)})
    assert ph.process_image(raw, 1600).exif_lat is not None                     # the phone's file carries GPS
    assert ph.has_metadata(raw)
    with transaction(world.state.factory) as s:
        ph.record_consent(s, s.get(sv.Farmer, world.state.ids["farmer_a"]), "photo_ai", True,
                          sv.load_consent_wording(world.state.ctx.cfg), "app", "test")
    pid = _submit(world, uid, data=raw)
    with transaction(world.state.factory) as s:
        p = s.get(Photo, pid)
        stored = Path(p.file_path).read_bytes()
        assert not ph.has_metadata(stored) and b"FictionalPhone" not in stored
        sug = ph.suggest(s, ph.config(REPO / "config"), p, caller=lambda b, *a: (world.state.ai_calls.append(b) or
                                                                                   {"tag": "healthy", "reason": "Green."}),
                         api_key="test-key")
        assert sug.status == "ok"
    sent = world.state.ai_calls[-1]
    assert not ph.has_metadata(sent) and b"FictionalPhone" not in sent
    with transaction(world.state.factory) as s:
        f = s.get(sv.Farmer, world.state.ids["farmer_a"])
        for secret in (f.full_name.encode(), f.member_no.encode(), NID.encode(), b"0722", f"{LAT}".encode()):
            assert secret not in sent                                           # image only: no identifiers
        import hashlib
        assert s.scalar(select(PhotoSuggestion)).sent_sha256 == hashlib.sha256(sent).hexdigest()


def test_consent_gate(world):
    uid, _ = _user(world)
    pid = _submit(world, uid)
    pcfg = ph.config(REPO / "config")
    calls = []
    with transaction(world.state.factory) as s:
        p = s.get(Photo, pid)
        assert ph.suggest(s, pcfg, p, caller=lambda *a: calls.append(1), api_key="k").status == "no_consent"
    assert calls == []                                                          # nothing sent at all
    with transaction(world.state.factory) as s:
        f = s.get(sv.Farmer, world.state.ids["farmer_a"])
        w = sv.load_consent_wording(world.state.ctx.cfg)
        ph.record_consent(s, f, "photo_ai", True, w, "app", "test")
        ph.record_consent(s, f, "photo_ai", False, w, "app", "test")          # changed their mind
        assert not ph.consent_granted(s, f.id, "photo_ai")
        assert [c.granted for c in s.scalars(select(Consent).where(Consent.purpose == "photo_ai"))] == [True, False]
        c = s.scalar(select(Consent).where(Consent.purpose == "photo_ai"))
        assert c.wording_version == w["version"] and c.wording_sha256 == w["purposes"]["photo_ai"]["sha256"]


def test_the_queue_works_with_no_key_and_when_the_ai_fails(world):
    uid, _ = _user(world)
    pcfg = ph.config(REPO / "config")
    p1, p2 = _submit(world, uid, data=jpeg(31)), _submit(world, uid, data=jpeg(32))
    with transaction(world.state.factory) as s:
        f = s.get(sv.Farmer, world.state.ids["farmer_a"])
        ph.record_consent(s, f, "photo_ai", True, sv.load_consent_wording(world.state.ctx.cfg), "app", "test")
        assert ph.suggest(s, pcfg, s.get(Photo, p1), api_key="").status == "no_key"

        def broken(*a):
            raise TimeoutError("no answer")
        bad = ph.suggest(s, pcfg, s.get(Photo, p2), caller=broken, api_key="k")
        assert bad.status == "error" and bad.error == "TimeoutError" and bad.tag is None
    c = TestClient(world)
    _login_uw(c)
    page = c.get("/uw/photos").text
    assert "none (no key)" in page and "none (error)" in page
    ref = _ref(world, p1)
    tok = csrf_of(c.get(f"/uw/photos/{ref}").text)
    assert c.post(f"/uw/photos/{ref}/review", data={"csrf_token": tok, "tag": "healthy", "extent": "none"},
                  follow_redirects=False).status_code == 303
    with transaction(world.state.factory) as s:
        r = s.scalar(select(PhotoReview))
        assert r.tag == "healthy" and r.suggestion_tag is None and r.agreed_with_suggestion is None


def _login_uw(c):
    tok = csrf_of(c.get("/login").text)
    assert c.post("/login", data={"username": "uw", "password": PASSWORD, "csrf_token": tok},
                  follow_redirects=False).status_code == 303


def _ref(app, pid):
    with transaction(app.state.factory) as s:
        return s.get(Photo, pid).ref


def test_reviewer_decides_and_the_suggestion_is_logged_beside_it(world):
    uid, _ = _user(world)
    with transaction(world.state.factory) as s:
        ph.record_consent(s, s.get(sv.Farmer, world.state.ids["farmer_a"]), "photo_ai", True,
                          sv.load_consent_wording(world.state.ctx.cfg), "app", "test")
    pid = _submit(world, uid, data=jpeg(41))
    with transaction(world.state.factory) as s:
        ph.suggest(s, ph.config(REPO / "config"), s.get(Photo, pid), caller=lambda *a: {"tag": "pest", "reason": "Holes."},
                   api_key="k")
        payouts_before = s.scalar(select(func.count()).select_from(Payout))
    c = TestClient(world)
    _login_uw(c)
    ref = _ref(world, pid)
    page = c.get(f"/uw/photos/{ref}").text
    assert "Suggestion" in page and "Holes." in page and "A hint, not a decision" in page
    tok = csrf_of(page)
    c.post(f"/uw/photos/{ref}/review", data={"csrf_token": tok, "tag": "drought_stress", "extent": "25_50",
                                             "note": "Leaves rolled."})
    with transaction(world.state.factory) as s:
        r = s.scalar(select(PhotoReview))
        assert (r.tag, r.extent, r.suggestion_tag, r.agreed_with_suggestion, r.reviewer) == \
            ("drought_stress", "25_50", "pest", False, "uw")
        ev = s.scalar(select(AuditEvent).where(AuditEvent.action == "photo.reviewed"))
        assert ev.details["suggestion"] == "pest" and ev.details["tag"] == "drought_stress"
        msg = s.scalar(select(SmsMessage).where(SmsMessage.template == "photo_drought_stress"))
        assert msg is not None and msg.status in ("queued", "logged")              # recorded, never sent in tests
        assert s.scalar(select(func.count()).select_from(Payout)) == payouts_before   # a photo never makes a payout
        assert s.get(Photo, pid).status == "reviewed"


def test_resilience_photo_point_needs_every_stage_on_schedule_and_clean(world):
    uid, _ = _user(world)
    pcfg = ph.config(REPO / "config")
    ids = [_submit(world, uid, data=jpeg(50 + i), stage=st) for i, st in enumerate(pcfg["stages"])]
    with transaction(world.state.factory) as s:
        pol = s.get(Policy, world.state.ids["a"])
        assert ph.photo_point_earned(s, pcfg, pol)["earned"]
        p = s.get(Photo, ids[0])
        p.flags = ["reused"]                                                     # a fraud flag on one stage
        assert not ph.photo_point_earned(s, pcfg, pol)["earned"]
        s.add(PhotoReview(photo_id=p.id, reviewer="uw", tag="healthy", extent="none", flags_cleared=True))
        s.flush()
        assert ph.photo_point_earned(s, pcfg, pol)["earned"]                     # cleared by a reviewer: counts again
        late = s.get(Photo, ids[1])
        late.on_schedule = False
        assert not ph.photo_point_earned(s, pcfg, pol)["earned"]


def test_earned_point_shows_in_next_seasons_price(world, cfg):
    uid, _ = _user(world)
    pcfg = ph.config(REPO / "config")
    for i, st in enumerate(pcfg["stages"]):
        _submit(world, uid, data=jpeg(60 + i), stage=st)
    nxt = dataclasses.replace(world.state.ctx, today=date(2027, 12, 15))           # long rains 2028 sales open
    with transaction(world.state.factory) as s:
        sacco = s.get(Sacco, world.state.ids["sacco"])
        pv = sv.preview(nxt, s, inp(lat=LAT, lon=LON, year=2028), sacco)
        assert pv["ok"], pv["errors"]
        assert pv["resilience_used"].get("photos_on_schedule") is True
        assert pv["quote"]["resilience"]["points"] >= 4
        pv_new = sv.preview(nxt, s, inp(member_no="NEW-1", national_id="40000001", phone="0711 000 999", year=2028), sacco)
        assert "photos_on_schedule" not in pv_new["resilience_used"]


def test_picture_rider_is_off_in_quotes_and_assessments_are_illustrative(world, cfg):
    pcfg = ph.config(REPO / "config")
    assert ph.rider_offered(pcfg) is False
    with transaction(world.state.factory) as s:
        q = sv.preview(world.state.ctx, s, inp(member_no="Q-1", national_id="40000002", phone="0711 000 998"), None)["quote"]
    assert "rider" not in json.dumps(q).lower()                                  # quotes never carry the rider
    uid, _ = _user(world)
    pid = _submit(world, uid, data=jpeg(71))
    with transaction(world.state.factory) as s:
        u, pol = s.get(AppUser, uid), s.get(Policy, world.state.ids["a"])
        claim = ph.report_damage(s, pcfg, u, pol, "drought", "dry", [s.get(Photo, pid).ref])
        before = s.scalar(select(func.count()).select_from(Payout))
        ph.assess(s, pcfg, claim, "uw", "50_75", datetime.now(timezone.utc))
        assert claim.illustrative_amount_kes == round(pol.sum_insured_per_acre * pol.acres * 0.5, 2)
        assert s.scalar(select(func.count()).select_from(Payout)) == before
        ev = s.scalar(select(AuditEvent).where(AuditEvent.action == "rider.assessed"))
        assert ev.details["label"] == "ILLUSTRATIVE"


# ------------------------------------------------------------------ the app over HTTP
def _app_login(c, phone=PHONE, pin=None):
    tok = csrf_of(c.get("/app/login").text)
    return c.post("/app/login", data={"phone": phone, "pin": pin, "csrf_token": tok}, follow_redirects=False)


def test_officer_sets_up_the_app_and_the_pin_is_shown_once(world):
    c = TestClient(world)
    tok = csrf_of(c.get("/login").text)
    c.post("/login", data={"username": "officer", "password": PASSWORD, "csrf_token": tok})
    tok = csrf_of(c.get("/dashboard").text)
    r = c.post(f"/members/{world.state.ids['farmer_a']}/app-user", data={"csrf_token": tok, "role": "farmer"})
    pin = re.search(r'class="pin">(\d{6})<', r.text).group(1)
    assert pin not in r.headers.get("set-cookie", "")
    assert pin not in c.get(f"/members/{world.state.ids['farmer_a']}").text       # shown once
    a = TestClient(world)
    assert _app_login(a, pin="000000" if pin != "000000" else "111111").status_code == 401
    assert _app_login(a, pin=pin).status_code == 303
    me = a.get("/app/api/me").json()
    assert me["user"]["role"] == "farmer" and len(me["plots"]) == 1 and me["csrf"]
    assert_no_pii(json.dumps(me))
    assert len(me["plots"][0]["stages"]) == 5


def test_wrong_pins_lock_the_app_for_a_while(world):
    _, pin = _user(world)
    a = TestClient(world)
    for _ in range(5):
        assert _app_login(a, pin="999999" if pin != "999999" else "888888").status_code == 401
    r = _app_login(a, pin=pin)                                                  # the right PIN, but locked
    assert r.status_code == 401 and "wait 30 minutes" in r.text
    assert _app_login(TestClient(world), phone="0799 999 999", pin=pin).text.count("wait 30 minutes") == 1   # same answer


def test_upload_over_http_is_idempotent_and_private(world):
    uid, pin = _user(world)
    _user(world, "farmer_b")
    a = TestClient(world)
    _app_login(a, pin=pin)
    me = a.get("/app/api/me").json()
    meta = {"client_id": "queue-item-0001", "stage": "emergence", "taken_at": datetime.now(timezone.utc).isoformat(),
            "lat": LAT, "lon": LON, "accuracy_m": 9, "source": "camera"}
    send = lambda: a.post("/app/api/photos", files={"file": ("p.jpg", jpeg(81), "image/jpeg")},  # noqa: E731
                          data={"plot_id": world.state.ids["plot_a"], "meta": json.dumps(meta)},
                          headers={"X-CSRF-Token": me["csrf"]})
    r1, r2 = send(), send()                                                     # the offline queue resent it
    assert r1.status_code == 200 and r1.json()["ref"] == r2.json()["ref"]
    with transaction(world.state.factory) as s:
        assert s.scalar(select(func.count()).select_from(Photo)) == 1
    assert a.post("/app/api/photos", files={"file": ("p.jpg", jpeg(82), "image/jpeg")},
                  data={"plot_id": world.state.ids["plot_a"], "meta": json.dumps(meta)}).status_code == 403   # no token
    ref = r1.json()["ref"]
    assert a.get(f"/app/photos/{ref}.jpg").status_code == 200
    b = TestClient(world)                                                       # another farmer
    with transaction(world.state.factory) as s:
        _, pin_b = ph.set_up_user(s, s.get(sv.Farmer, world.state.ids["farmer_b"]), "officer")
    _app_login(b, phone=PHONE2, pin=pin_b)
    assert b.get(f"/app/photos/{ref}.jpg").status_code == 404
    bad = b.post("/app/api/photos", files={"file": ("p.jpg", jpeg(83), "image/jpeg")},
                 data={"plot_id": world.state.ids["plot_a"], "meta": json.dumps({**meta, "client_id": "other-0002"})},
                 headers={"X-CSRF-Token": b.get("/app/api/me").json()["csrf"]})
    assert bad.status_code == 422 and "cannot send photos for that farm" in bad.json()["error"]


def test_ghost_of_the_last_photo_from_the_same_spot(world):
    uid, pin = _user(world)
    first = _submit(world, uid, data=jpeg(91))
    a = TestClient(world)
    _app_login(a, pin=pin)
    tok = a.get("/app/api/me").json()["csrf"]
    g = a.post(f"/app/api/ghost/{world.state.ids['plot_a']}", json={"lat": LAT + 0.0002, "lon": LON},
               headers={"X-CSRF-Token": tok}).json()
    assert g["url"] == f"/app/photos/{_ref(world, first)}.jpg"


def test_farmer_weather_tab_shows_only_approved_kmd_summaries_for_their_sacco(world, tmp_path):
    _, sources = wx.load_sources(REPO / "config")
    with transaction(world.state.factory) as s:
        valid = dict(valid_from=TODAY - timedelta(days=1), valid_to=TODAY + timedelta(days=5))
        mine = wx.store_pdf(s, tmp_path, sources["kmd_nakuru"], b"%PDF-1.4 a", "a", None, "uploaded", **valid,
                            sacco_id=world.state.ids["sacco"])
        every = wx.store_pdf(s, tmp_path, sources["kmd_nakuru"], b"%PDF-1.4 b", "b", None, "fetched", **valid)
        theirs = wx.store_pdf(s, tmp_path, sources["kmd_nakuru"], b"%PDF-1.4 c", "c", None, "uploaded", **valid,
                              sacco_id=world.state.ids["other"])
        wx.store_pdf(s, tmp_path, sources["kmd_nakuru"], b"%PDF-1.4 d", "draft", None, "fetched", **valid)
        wx.approve(s, mine, "Light rain on Tuesday.", "Mvua kidogo Jumanne.", "manager")
        wx.approve(s, every, "Dry and warm this week.", "Kavu na joto wiki hii.", "ops")
        wx.approve(s, theirs, "Other SACCO text.", "Maandishi ya SACCO nyingine.", "other")
    _, pin = _user(world)
    a = TestClient(world)
    _app_login(a, pin=pin)
    page = a.get("/app/weather").text
    assert "Light rain on Tuesday." in page and "Dry and warm this week." in page
    assert "Mvua kidogo Jumanne." in page and "Source: KMD" in page
    assert "Other SACCO text." not in page


def test_pwa_manifest_and_service_worker(world):
    c = TestClient(world)
    m = c.get("/app/manifest.webmanifest")
    assert m.status_code == 200 and m.json()["start_url"] == "/app" and m.json()["display"] == "standalone"
    sw = c.get("/app/sw.js")
    assert sw.headers["service-worker-allowed"] == "/app" and "caches.open" in sw.text
    assert c.get("/static/app/icon-192.png").status_code == 200
    assert c.get("/app", follow_redirects=False).headers["location"] == "/app/login"


def test_pricing_and_payouts_never_import_the_photo_module():
    for pkg in ("agroshield_pricing",):
        for f in (REPO / "src" / pkg).rglob("*.py"):
            assert "photos" not in f.read_text(encoding="utf-8"), f
    mon = (REPO / "src" / "agroshield_platform" / "monitoring.py").read_text(encoding="utf-8")
    assert "photos" not in mon and "anthropic" not in mon


# ------------------------------------------------------------------ the offline queue in a real browser
def test_offline_queue_in_a_real_browser(world, tmp_path):
    pw = pytest.importorskip("playwright.sync_api")
    import socket
    import threading
    import time
    import uvicorn
    _, pin = _user(world)
    with socket.socket() as sk:
        sk.bind(("127.0.0.1", 0))
        port = sk.getsockname()[1]
    srv = uvicorn.Server(uvicorn.Config(world, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=srv.run, daemon=True).start()
    for _ in range(100):
        if srv.started:
            break
        time.sleep(0.05)
    base = f"http://127.0.0.1:{port}"
    pic = tmp_path / "field.jpg"
    pic.write_bytes(jpeg(99))
    try:
        with pw.sync_playwright() as p:
            try:
                browser = p.chromium.launch(channel="chrome")
            except Exception:
                try:
                    browser = p.chromium.launch()
                except Exception:
                    pytest.skip("no Chromium for Playwright")
            ctx = browser.new_context(geolocation={"latitude": LAT + 0.0002, "longitude": LON},
                                      permissions=["geolocation"], viewport={"width": 375, "height": 800})
            page = ctx.new_page()
            page.goto(base + "/app/login")
            page.fill("#phone", PHONE)
            page.fill("#pin", pin)
            page.click("button[type=submit]")
            page.wait_for_selector("[data-farm]")
            ctx.set_offline(True)                                               # signal gone
            page.click("[data-farm]")
            page.set_input_files("#pick", str(pic))
            page.wait_for_function("document.getElementById('q-count').textContent === '1'")
            with transaction(world.state.factory) as s:
                assert s.scalar(select(func.count()).select_from(Photo)) == 0       # waiting on the phone
            ctx.set_offline(False)                                              # signal back: it sends by itself
            page.wait_for_function("document.getElementById('q-count').textContent === '0'", timeout=20000)
            browser.close()
    finally:
        srv.should_exit = True
    with transaction(world.state.factory) as s:
        photos = s.scalars(select(Photo)).all()
        assert len(photos) == 1 and photos[0].lat is not None and photos[0].distance_m < 100
        assert not ph.has_metadata(Path(photos[0].file_path).read_bytes())
