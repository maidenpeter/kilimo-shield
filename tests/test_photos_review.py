"""Regression tests for the independent review of the Phase 3 commit (docs/remaining/REVIEW_PHASE3.md).
All people and photos are fictional (generated images)."""
import io
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select

from agroshield_platform import photos as ph
from agroshield_platform import services as sv
from agroshield_platform.db import transaction
from agroshield_platform.models import AppAssignment, AppUser, Photo, PhotoReview, Plot, Policy

from conftest import REPO
from test_photos import LAT, LON, NAIROBI, _app_login, _ref, _submit, _user, jpeg, world  # noqa: F401
from test_platform import PASSWORD, PHONE, PHONE2, book, csrf_of, settings  # noqa: F401


def _with_comment(text: bytes) -> bytes:
    img = Image.open(io.BytesIO(jpeg(5)))
    buf = io.BytesIO()
    img.save(buf, "JPEG", comment=text)
    return buf.getvalue()


def test_jpeg_comments_never_survive_and_are_caught(world):
    raw = _with_comment(b"Farmer ID 12345678 phone 0712345678")
    assert ph.has_metadata(raw)                                               # the check sees comments now
    uid, _ = _user(world)
    pid = _submit(world, uid, data=raw)
    with transaction(world.state.factory) as s:
        p = s.get(Photo, pid)
        stored = Path(p.file_path).read_bytes()
        assert b"12345678" not in stored and not ph.has_metadata(stored)
        sent = []
        ph.record_consent(s, p.farmer, "photo_ai", True, sv.load_consent_wording(world.state.ctx.cfg), "app", "t")
        ph.suggest(s, ph.config(REPO / "config"), p, caller=lambda b, *a: sent.append(b) or {"tag": "healthy", "reason": "x"},
                   api_key="k")
    assert sent and b"12345678" not in sent[0] and not ph.has_metadata(sent[0])


def test_photo_point_needs_a_verified_location(world):
    uid, _ = _user(world)
    pcfg = ph.config(REPO / "config")
    ids = [_submit(world, uid, data=jpeg(200 + i), stage=st, lat=None, lon=None) for i, st in enumerate(pcfg["stages"])]
    with transaction(world.state.factory) as s:
        pol = s.get(Policy, world.state.ids["a"])
        assert all("no_gps" in s.get(Photo, i).flags for i in ids)
        assert not ph.photo_point_earned(s, pcfg, pol)["earned"]                # no location, no point
        for i in ids:
            s.add(PhotoReview(photo_id=i, reviewer="uw", tag="healthy", extent="none", flags_cleared=True))
        s.flush()
        assert ph.photo_point_earned(s, pcfg, pol)["earned"]                    # an agronomist cleared them


def test_gallery_pictures_keep_their_camera_time_for_the_checks(world):
    uid, _ = _user(world)
    base = datetime(2027, 4, 15, 9, tzinfo=NAIROBI)
    old = jpeg(301, {"time": (base - timedelta(days=40)).replace(tzinfo=None)})
    pid = _submit(world, uid, data=old, source="picker", taken_at=base.isoformat(), now=base.astimezone(timezone.utc))
    bare = _submit(world, uid, data=jpeg(302), source="picker")
    with transaction(world.state.factory) as s:
        assert "time_mismatch" in s.get(Photo, pid).flags                      # an old gallery photo is caught
        assert "no_camera_time" in s.get(Photo, bare).flags
    js = (REPO / "src/agroshield_platform/web/static/app/photoapp.js").read_text(encoding="utf-8")
    assert 'keep(f, "picker")' in js                                             # the original file is uploaded


def test_coarse_gps_is_flagged_not_refused(world):
    uid, _ = _user(world)
    coarse = _submit(world, uid, data=jpeg(311), lat=LAT + 0.0030, accuracy_m=200)    # about 330 m, +-200 m
    clear = _submit(world, uid, data=jpeg(312), lat=LAT + 0.0030, accuracy_m=10)      # about 330 m, +-10 m
    with transaction(world.state.factory) as s:
        c, f = s.get(Photo, coarse), s.get(Photo, clear)
        assert c.status == "in_review" and "far_or_low_accuracy" in c.flags and c.photo_point_id is None
        assert f.status == "rejected"


def test_photos_lined_up_with_the_ghost_are_not_duplicates(world):
    uid, _ = _user(world)
    first = _submit(world, uid, data=jpeg(321), stage="emergence")
    img = Image.open(io.BytesIO(jpeg(321))).point(lambda v: min(255, v + 4))         # same framing, a little brighter
    buf = io.BytesIO()
    img.save(buf, "JPEG")
    next_stage = _submit(world, uid, data=buf.getvalue(), stage="vegetative")        # the next stage, lined up
    with transaction(world.state.factory) as s:
        assert "duplicate" not in s.get(Photo, next_stage).flags and s.get(Photo, first).flags == []


def test_a_refused_picture_resent_is_flagged(world):
    uid, _ = _user(world)
    refused = _submit(world, uid, data=jpeg(331), lat=LAT + 0.01)
    again = _submit(world, uid, data=jpeg(331))
    with transaction(world.state.factory) as s:
        assert s.get(Photo, refused).status == "rejected"
        assert "previously_rejected" in s.get(Photo, again).flags


def test_pin_reset_and_turn_off_sign_phones_out(world):
    uid, pin = _user(world)
    a = TestClient(world)
    _app_login(a, pin=pin)
    assert a.get("/app/api/me").status_code == 200
    _, pin2 = _user(world)                                                       # the officer resets the PIN
    assert a.get("/app/api/me").status_code == 401
    b = TestClient(world)
    _app_login(b, pin=pin2)
    assert b.get("/app/api/me").status_code == 200
    with transaction(world.state.factory) as s:
        ph.disable_user(s, s.get(AppUser, uid), "officer")
    assert b.get("/app/api/me").status_code == 401
    assert _app_login(TestClient(world), pin=pin2).status_code == 401


def test_officer_turns_off_the_app_and_removes_a_champions_farm(world):
    uid, _ = _user(world, role="champion")
    with transaction(world.state.factory) as s:
        ph.assign(s, s.get(AppUser, uid), s.get(Plot, world.state.ids["plot_b"]), "officer")
    c = TestClient(world)
    tok = csrf_of(c.get("/login").text)
    c.post("/login", data={"username": "officer", "password": PASSWORD, "csrf_token": tok})
    tok = csrf_of(c.get("/dashboard").text)
    fid = world.state.ids["farmer_a"]
    c.post(f"/members/{fid}/app-unassign/{world.state.ids['plot_b']}", data={"csrf_token": tok})
    with transaction(world.state.factory) as s:
        assert s.scalar(select(AppAssignment)) is None
    c.post(f"/members/{fid}/app-disable", data={"csrf_token": tok})
    with transaction(world.state.factory) as s:
        assert s.get(AppUser, uid).active is False


def test_champion_reset_to_farmer_loses_assignments(world):
    uid, _ = _user(world, role="champion")
    with transaction(world.state.factory) as s:
        ph.assign(s, s.get(AppUser, uid), s.get(Plot, world.state.ids["plot_b"]), "officer")
    _user(world, role="farmer")
    with transaction(world.state.factory) as s:
        assert s.scalar(select(AppAssignment)) is None


def test_shared_phone_household_members_each_sign_in(world):
    _, pin_a = _user(world)
    with transaction(world.state.factory) as s:
        fb = s.get(sv.Farmer, world.state.ids["farmer_b"])
        fa = s.get(sv.Farmer, world.state.ids["farmer_a"])
        fb.phone_hash, fb.phone_enc = fa.phone_hash, fa.phone_enc             # the same family phone (fictional)
        _, pin_b = ph.set_up_user(s, fb, "officer")
    a, b = TestClient(world), TestClient(world)
    assert _app_login(a, pin=pin_a).status_code == 303
    assert _app_login(b, pin=pin_b).status_code == 303
    assert a.get("/app/api/me").json()["user"]["key"] != b.get("/app/api/me").json()["user"]["key"]


def test_parallel_guesses_cannot_beat_the_lockout(world):
    uid, pin = _user(world)
    cfg = ph.config(REPO / "config")
    now = datetime.now(timezone.utc)
    wrong = "000000" if pin != "000000" else "111111"
    for _ in range(cfg["app"]["max_pin_attempts"]):
        with transaction(world.state.factory) as s:
            with pytest.raises(ph.PhotoError):
                ph.authenticate(s, world.state.vault if hasattr(world.state, "vault") else world.state.ctx.vault,
                                PHONE, wrong, cfg, now)
    with transaction(world.state.factory) as s:
        u = s.get(AppUser, uid)
        assert u.locked_until is not None
        with pytest.raises(ph.PhotoError):
            ph.authenticate(s, world.state.ctx.vault, PHONE, pin, cfg, now)    # the right PIN, still locked


def test_hostile_upload_input_is_a_form_error(world):
    _, pin = _user(world)
    a = TestClient(world)
    _app_login(a, pin=pin)
    tok = a.get("/app/api/me").json()["csrf"]
    for meta in ("[]", json.dumps({"client_id": "x" * 20, "stage": "emergence", "taken_at": "2027-04-15T09:00:00+03:00",
                                    "lat": "NaN", "lon": 35.86})):
        r = a.post("/app/api/photos", files={"file": ("p.jpg", jpeg(401), "image/jpeg")},
                   data={"plot_id": world.state.ids["plot_a"], "meta": meta}, headers={"X-CSRF-Token": tok})
        assert r.status_code == 422, meta
    r = a.post(f"/app/api/ghost/{world.state.ids['plot_a']}", json={"lat": "inf", "lon": 1}, headers={"X-CSRF-Token": tok})
    assert r.status_code == 422
    big = Image.new("RGB", (8000, 7000))
    buf = io.BytesIO()
    big.save(buf, "PNG")
    with pytest.raises(ph.PhotoError, match="too large"):
        ph.process_image(buf.getvalue(), 1600)


def test_kiswahili_words_cover_the_app_and_flags():
    from agroshield_platform.web.photo_app import WORDS
    assert set(WORDS["en"]) == set(WORDS["sw"])
    assert set(ph.FLAG_WORDS["en"]) == set(ph.FLAG_WORDS["sw"])
    js = (REPO / "src/agroshield_platform/web/static/app/photoapp.js").read_text(encoding="utf-8")
    for key in ("acres", "no_farm", "gps_off", "remove", "could_not_send", "saved"):
        assert f'words("{key}"' in js, key


def test_service_worker_never_stores_personal_responses():
    sw = (REPO / "src/agroshield_platform/web/static/app/sw.js").read_text(encoding="utf-8")
    assert '"/app/api' not in sw and '"/app/photos' not in sw                    # not in any cached list
    assert "res.redirected" in sw and "res.ok" in sw


def test_ghost_prefers_the_nearest_point_and_skips_flagged_photos(world):
    uid, _ = _user(world)
    near = _submit(world, uid, data=jpeg(501), stage="emergence")
    far = _submit(world, uid, data=jpeg(502), stage="vegetative", lat=LAT + 0.0015)   # another point, newer
    with transaction(world.state.factory) as s:
        plot = s.get(Plot, world.state.ids["plot_a"])
        g = ph.ghost(s, plot, LAT + 0.0002, LON, 30)
        assert g.id == near
        s.get(Photo, near).flags = ["reused"]
        g = ph.ghost(s, plot, LAT + 0.0002, LON, 30)
        assert g is None or g.id != near
    assert far
