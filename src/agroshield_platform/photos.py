"""Milestone 8: crop photos from farmers and champion farmers (the photo app), checks, and human review.

    set_up_user() / authenticate()   the officer sets up a farmer (or champion) with a PIN; the farmer signs in
    submit()                         one photo: GPS distance, duplicates and reused pictures (perceptual hash),
                                     metadata that does not add up; stored without EXIF or GPS in the file
    ghost()                          the previous photo from the same photo point, to keep the framing
    suggest()                        an AI "Suggestion" for the reviewer: only with the farmer's photo_ai consent,
                                     image only (EXIF and GPS stripped, no identifiers); none without a key
    review()                         the agronomist decides (tag and damage extent), logged next to the suggestion;
                                     then an advisory SMS (consent-gated, recorded, not sent while simulated)
    photo_point_earned()             the Resilience Score photo point: every stage photographed on schedule
    report_damage() / assess()       the picture-based rider (ILLUSTRATIVE, switched off in quotes)

Nothing here changes a price, a trigger or a payout. Settings live in config/photo.yaml.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import math
import os
import secrets
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

import yaml
from PIL import ExifTags, Image, ImageOps, UnidentifiedImageError
from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from . import sms
from .crypto import PIIError, hash_password, normalise_phone, scrub, verify_password
from .db import audit
from .models import (AppAssignment, AppUser, Consent, Farmer, Photo, PhotoPoint, PhotoReview, PhotoSuggestion, Plot,
                     Policy, RiderClaim)

log = logging.getLogger("agroshield.photos")

TAGS = {"healthy": "Healthy", "drought_stress": "Drought stress", "pest": "Pest", "disease": "Disease",
        "flood": "Flood", "other": "Other"}
EXTENTS = {"none": "No damage", "lt25": "Under a quarter of the plot", "25_50": "A quarter to half",
           "50_75": "Half to three quarters", "gt75": "More than three quarters"}
FRAUD_FLAGS = {"duplicate", "reused", "time_mismatch", "gps_mismatch", "future_time", "old_photo", "previously_rejected"}
# Not fraud, but the photo's place or time could not be confirmed: it is still reviewed, and it counts toward the
# Resilience photo point only once a reviewer clears it.
UNVERIFIED_FLAGS = {"no_gps", "no_plot_location", "far_or_low_accuracy", "no_camera_time"}
FLAG_WORDS = {
    "en": {"duplicate": "Same picture sent before for this plot", "reused": "Same picture as another plot's photo",
           "previously_rejected": "Same picture as one refused before", "time_mismatch": "Camera time and app time disagree",
           "gps_mismatch": "Camera location and app location disagree", "future_time": "Taken in the future",
           "old_photo": "Taken long before it was sent", "low_gps_accuracy": "Weak GPS fix",
           "no_plot_location": "The plot has no recorded location", "no_gps": "No location from the phone",
           "far_or_low_accuracy": "Far from the farm, with a weak GPS fix", "no_camera_time": "Picked from the gallery with no camera time"},
    "sw": {"duplicate": "Picha ileile imetumwa awali kwa shamba hili", "reused": "Picha ileile ya shamba jingine",
           "previously_rejected": "Picha ileile iliyokataliwa awali", "time_mismatch": "Saa ya kamera na ya programu hazilingani",
           "gps_mismatch": "Mahali pa kamera na pa programu hapalingani", "future_time": "Imepigwa siku za usoni",
           "old_photo": "Ilipigwa muda mrefu kabla ya kutumwa", "low_gps_accuracy": "GPS dhaifu",
           "no_plot_location": "Shamba halina mahali palipoandikwa", "no_gps": "Simu haikutoa mahali",
           "far_or_low_accuracy": "Mbali na shamba, GPS dhaifu", "no_camera_time": "Imechaguliwa kwenye picha bila saa ya kamera"},
}
MAX_PIXELS = 50_000_000                  # larger uploads are refused before decoding (decompression bombs)


class PhotoError(ValueError):
    """A problem the person can fix; the message is shown to them."""


@lru_cache(maxsize=4)
def _config(path: str) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def config(config_dir: Path) -> dict:
    return _config(str(Path(config_dir) / "photo.yaml"))


# ------------------------------------------------------------------ helpers
def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres (haversine)."""
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def dhash(img: Image.Image, size: int = 8) -> str:
    """64-bit difference hash: survives resizing and recompression, so a re-sent picture is still recognised."""
    g = img.convert("L").resize((size + 1, size), Image.LANCZOS)
    px = list(g.getdata())
    bits = 0
    for row in range(size):
        for col in range(size):
            bits = (bits << 1) | (px[row * (size + 1) + col] > px[row * (size + 1) + col + 1])
    return f"{bits:016x}"


def hamming(a: str, b: str) -> int:
    return bin(int(a, 16) ^ int(b, 16)).count("1")


def _utc(d: datetime | None) -> datetime | None:
    if d is None:
        return None
    return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d.astimezone(timezone.utc)


@dataclass
class Processed:
    jpeg: bytes            # re-encoded, no EXIF, no GPS, orientation applied
    width: int
    height: int
    phash: str
    exif_time: datetime | None
    exif_lat: float | None
    exif_lon: float | None


def _exif_gps(exif) -> tuple[float | None, float | None]:
    try:
        gps = exif.get_ifd(ExifTags.IFD.GPSInfo)
        if not gps:
            return None, None

        def deg(v, ref):
            d = float(v[0]) + float(v[1]) / 60 + float(v[2]) / 3600
            return -d if ref in ("S", "W") else d
        return deg(gps[2], gps.get(1, "N")), deg(gps[4], gps.get(3, "E"))
    except Exception:                      # odd or partial GPS blocks are common: treat as absent
        return None, None


def _exif_time(exif) -> datetime | None:
    """Camera time, read as Nairobi wall time (phones in Kenya), returned in UTC."""
    try:
        raw = exif.get_ifd(ExifTags.IFD.Exif).get(ExifTags.Base.DateTimeOriginal) or exif.get(ExifTags.Base.DateTime)
        if not raw:
            return None
        return datetime.strptime(str(raw), "%Y:%m:%d %H:%M:%S").replace(tzinfo=timezone(timedelta(hours=3))) \
            .astimezone(timezone.utc)
    except Exception:
        return None


def process_image(data: bytes, max_side: int) -> Processed:
    """Read EXIF for the checks, then re-encode without any metadata. The stored and sent copies are this one."""
    try:
        img = Image.open(io.BytesIO(data))
        if img.size[0] * img.size[1] > MAX_PIXELS:
            raise PhotoError("That photo is too large. Take the photo again.")
        img.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise PhotoError("That file is not a photo we can read. Take the photo again.") from None
    if img.format not in ("JPEG", "PNG", "WEBP"):
        raise PhotoError("Send a JPEG, PNG or WebP photo.")
    exif = img.getexif()
    lat, lon = _exif_gps(exif)
    when = _exif_time(exif)
    img = ImageOps.exif_transpose(img).convert("RGB")
    img.thumbnail((max_side, max_side), Image.LANCZOS)
    jpeg = pixels_only_jpeg(img)
    return Processed(jpeg, img.width, img.height, dhash(img), when, lat, lon)


def pixels_only_jpeg(img: Image.Image) -> bytes:
    """Rebuild the picture from its pixels, so no EXIF, GPS, comment, XMP or ICC data can ride along."""
    clean = Image.frombytes("RGB", img.size, img.convert("RGB").tobytes())
    out = io.BytesIO()
    clean.save(out, "JPEG", quality=85, optimize=True)
    return out.getvalue()


def has_metadata(jpeg: bytes) -> bool:
    """True if the JPEG carries anything but pixels: EXIF or GPS, a comment (COM), or any APP1 to APP15 segment
    (XMP, MPF, ICC and the like). Only JFIF (APP0) is allowed. Checked before anything leaves the server."""
    img = Image.open(io.BytesIO(jpeg))
    if img.getexif() or {"exif", "comment", "icc_profile", "xmp"} & set(img.info):
        return True
    i = 2
    while i + 4 <= len(jpeg) and jpeg[i] == 0xFF:
        marker = jpeg[i + 1]
        if marker in (0xD9, 0xDA):                   # end of image, or start of scan: no more metadata segments
            return False
        if marker == 0xFE or 0xE1 <= marker <= 0xEF:
            return True
        i += 2 + int.from_bytes(jpeg[i + 2:i + 4], "big")
    return False


# ------------------------------------------------------------------ app users (farmers and champions)
def set_up_user(s: Session, farmer: Farmer, actor: str, role: str = "farmer") -> tuple[AppUser, str]:
    """Create or reset a farmer's photo app sign-in. Returns the new 6-digit PIN, shown once to read out.
    A reset signs the phone out everywhere (session_version), and a champion who becomes a farmer loses their
    assigned farms."""
    if role not in ("farmer", "champion"):
        raise PhotoError("Choose farmer or champion farmer.")
    pin = f"{secrets.randbelow(10**6):06d}"
    user = s.scalar(select(AppUser).where(AppUser.farmer_id == farmer.id))
    if user is None:
        user = AppUser(farmer_id=farmer.id, role=role, pin_hash=hash_password(pin), created_by=actor, session_version=0)
        s.add(user)
    else:
        if user.role == "champion" and role != "champion":
            for a in s.scalars(select(AppAssignment).where(AppAssignment.user_id == user.id)):
                audit(s, actor, "app.plot_unassigned", "plot", a.plot_id, champion=user.id)
                s.delete(a)
        user.role, user.pin_hash, user.active, user.failed_attempts, user.locked_until = role, hash_password(pin), True, 0, None
        user.session_version = (user.session_version or 0) + 1
    s.flush()
    audit(s, actor, "app.user_set_up", "farmer", farmer.id, role=role, member_no=farmer.member_no)
    return user, pin


def disable_user(s: Session, user: AppUser, actor: str) -> None:
    """Stop a photo app sign-in (a lost phone, a champion who left). Every open session ends at once."""
    user.active, user.session_version = False, (user.session_version or 0) + 1
    audit(s, actor, "app.user_disabled", "farmer", user.farmer_id)


_DUMMY_HASH = hash_password(secrets.token_hex(8))     # same scrypt cost when the phone is unknown or locked


def authenticate(s: Session, vault, phone: str, pin: str, cfg: dict, now: datetime) -> AppUser:
    """Phone number and PIN. The answer and its cost are the same whether the phone is unknown, the PIN is wrong or
    the account is locked, so the page cannot be used to find out who is registered. The failure counter is
    raised in the database before the PIN is checked, so parallel guesses cannot get round the limit. Several
    farmers may share one phone (a household): each keeps their own PIN."""
    wrong = PhotoError("That phone number and PIN do not match. After several wrong tries, wait 30 minutes or ask "
                       "your SACCO officer to reset your PIN.")
    try:
        h = vault.lookup_hash(normalise_phone(phone), "phone")
    except PIIError:
        verify_password(pin or "", _DUMMY_HASH)
        raise wrong from None
    users = list(s.scalars(select(AppUser).join(Farmer, AppUser.farmer_id == Farmer.id)
                           .where(Farmer.phone_hash == h, AppUser.active.is_(True)).order_by(AppUser.id)))
    ok, tried = None, 0
    for u in users:
        # Count the attempt first, atomically, and only while not locked.
        n = s.execute(update(AppUser).where(AppUser.id == u.id, or_(AppUser.locked_until.is_(None), AppUser.locked_until <= now))
                      .values(failed_attempts=AppUser.failed_attempts + 1).execution_options(synchronize_session=False)).rowcount
        s.flush()
        if n != 1:
            continue                                      # locked: not tried
        tried += 1
        s.refresh(u)
        if ok is None and verify_password(pin or "", u.pin_hash):
            ok = u
        elif u.failed_attempts >= cfg["app"]["max_pin_attempts"]:
            u.locked_until, u.failed_attempts = now + timedelta(minutes=cfg["app"]["lockout_minutes"]), 0
    if tried == 0:
        verify_password(pin or "", _DUMMY_HASH)
    if ok is None:
        for u in users:
            audit(s, "app", "app.login_failed", "app_user", str(u.id))
        raise wrong
    ok.failed_attempts, ok.locked_until, ok.last_login_at = 0, None, now
    audit(s, "app", "app.login", "app_user", str(ok.id))
    return ok


def assign(s: Session, champion: AppUser, plot: Plot, actor: str) -> AppAssignment:
    if champion.role != "champion":
        raise PhotoError("Only a champion farmer can photograph other farmers' plots.")
    if plot.farmer.sacco_id != champion.farmer.sacco_id:
        raise PhotoError("A champion farmer works within their own SACCO.")
    a = s.scalar(select(AppAssignment).where(AppAssignment.user_id == champion.id, AppAssignment.plot_id == plot.id))
    if a is None:
        a = AppAssignment(user_id=champion.id, plot_id=plot.id, created_by=actor)
        s.add(a)
        s.flush()
        audit(s, actor, "app.plot_assigned", "plot", plot.id, champion=champion.id)
    return a


def unassign(s: Session, champion: AppUser, plot: Plot, actor: str) -> bool:
    a = s.scalar(select(AppAssignment).where(AppAssignment.user_id == champion.id, AppAssignment.plot_id == plot.id))
    if a is None:
        return False
    s.delete(a)
    audit(s, actor, "app.plot_unassigned", "plot", plot.id, champion=champion.id)
    return True


def plots_for(s: Session, user: AppUser) -> list[Plot]:
    own = list(s.scalars(select(Plot).where(Plot.farmer_id == user.farmer_id)))
    if user.role != "champion":
        return own
    extra = [a.plot for a in s.scalars(select(AppAssignment).where(AppAssignment.user_id == user.id))]
    return own + [p for p in extra if p.id not in {o.id for o in own}]


def latest_policy(s: Session, plot: Plot) -> Policy | None:
    return s.scalar(select(Policy).where(Policy.plot_id == plot.id, Policy.status != "cancelled")
                    .order_by(Policy.year.desc(), Policy.created_at.desc()))


# ------------------------------------------------------------------ consent (photo_ai is its own purpose)
def consent_granted(s: Session, farmer_id: str, purpose: str) -> bool:
    c = s.scalar(select(Consent).where(Consent.farmer_id == farmer_id, Consent.purpose == purpose)
                 .order_by(Consent.captured_at.desc(), Consent.id.desc()))
    return bool(c and c.granted)


def record_consent(s: Session, farmer: Farmer, purpose: str, granted: bool, wording: dict, channel: str,
                   actor: str, captured_by: int | None = None) -> Consent:
    """A new record every time (never overwritten), with the exact wording version and hash."""
    c = Consent(farmer_id=farmer.id, purpose=purpose, granted=bool(granted), wording_version=wording["version"],
                wording_sha256=wording["purposes"][purpose]["sha256"], channel=channel, captured_by=captured_by)
    s.add(c)
    s.flush()
    audit(s, actor, "consent.recorded", "farmer", farmer.id, purpose=purpose, granted=bool(granted), channel=channel)
    return c


# ------------------------------------------------------------------ schedule and the Resilience photo point
def stage_window(pcfg: dict, appcfg, policy: Policy, stage: str) -> tuple[date, date]:
    cal = appcfg.calendar(policy.ward_id, policy.season)
    m, d = cal.planting_month_day
    start = date(policy.year, m, d)
    st = pcfg["stages"][stage]
    return start + timedelta(days=st["from_day"]), start + timedelta(days=st["to_day"])


def passes_checks(p: Photo, review: PhotoReview | None = None) -> bool:
    """Not rejected, place and time confirmed, and no fraud flag; or a reviewer looked and cleared the flags."""
    blocking = set(p.flags or []) & (FRAUD_FLAGS | UNVERIFIED_FLAGS)
    return p.status != "rejected" and (not blocking or bool(review and review.flags_cleared))


def photo_point_earned(s: Session, pcfg: dict, policy: Policy) -> dict:
    """Per stage: is there an on-schedule photo that passed the checks? The point is earned when all are."""
    photos = list(s.scalars(select(Photo).where(Photo.policy_id == policy.id)))
    reviews = {r.photo_id: r for r in s.scalars(select(PhotoReview).where(PhotoReview.photo_id.in_([p.id for p in photos] or [-1])))}
    done = {}
    for stage in pcfg["stages"]:
        ok = []
        for p in photos:
            if p.stage == stage and p.on_schedule and passes_checks(p, reviews.get(p.id)):
                ok.append(p)
        done[stage] = bool(ok)
    need = pcfg["resilience"]["stages_needed"]
    return {"stages": done, "earned": sum(done.values()) >= need}


def earned_for_farmer(s: Session, pcfg: dict, farmer: Farmer, before_year: int, season: str) -> bool:
    """The photo point carries into the next season: earned on the farmer's most recent earlier policy."""
    prev = s.scalar(select(Policy).where(Policy.farmer_id == farmer.id, Policy.status == "active",
                                         Policy.year < before_year, Policy.season == season)
                    .order_by(Policy.year.desc()))
    return bool(prev and photo_point_earned(s, pcfg, prev)["earned"])


# ------------------------------------------------------------------ submit
def _point(s: Session, plot: Plot, lat: float | None, lon: float | None, radius: float) -> PhotoPoint | None:
    if lat is None or lon is None:
        return None
    points = list(s.scalars(select(PhotoPoint).where(PhotoPoint.plot_id == plot.id)))
    near = min(points, key=lambda pt: distance_m(lat, lon, pt.lat, pt.lon), default=None)
    if near and distance_m(lat, lon, near.lat, near.lon) <= radius:
        return near
    pt = PhotoPoint(plot_id=plot.id, label=f"Point {len(points) + 1}", lat=lat, lon=lon)
    s.add(pt)
    s.flush()
    return pt


def submit(s: Session, appcfg, pcfg: dict, user: AppUser, plot_id: str, data: bytes, meta: dict, store: Path,
           now: datetime) -> Photo:
    """Store one photo after the checks. meta: client_id, taken_at (ISO, with offset), lat, lon, accuracy_m, stage.
    Idempotent on client_id, so the offline queue can resend safely."""
    client_id = str(meta.get("client_id") or "").strip()[:64]
    if len(client_id) < 8:
        raise PhotoError("Missing photo id. Update the app and try again.")
    existing = s.scalar(select(Photo).where(Photo.client_id == client_id))
    if existing:
        if existing.taken_by != user.id:
            raise PhotoError("Missing photo id. Update the app and try again.")
        return existing
    plot = s.get(Plot, plot_id)
    if plot is None or plot.id not in {p.id for p in plots_for(s, user)}:
        raise PhotoError("You cannot send photos for that farm.")
    stage = meta.get("stage")
    if stage not in pcfg["stages"]:
        raise PhotoError("Choose the growth stage.")
    if len(data) > pcfg["max_upload_mb"] * 1_000_000:
        raise PhotoError(f"The photo is too large. The limit is {pcfg['max_upload_mb']} MB.")
    try:
        taken = _utc(datetime.fromisoformat(str(meta.get("taken_at"))))
    except (TypeError, ValueError):
        raise PhotoError("Missing photo time. Check the phone's date and time.") from None
    lat, lon, acc = (number(meta.get(k), lo, hi) for k, lo, hi in (("lat", -90, 90), ("lon", -180, 180),
                                                                    ("accuracy_m", 0, 1e6)))
    if (lat is None) != (lon is None):
        lat = lon = None
    source = meta.get("source") if meta.get("source") in ("camera", "picker") else "picker"

    img = process_image(data, pcfg["max_side_px"])
    ck, flags = pcfg["checks"], []
    if source == "picker" and img.exif_time is None:
        flags.append("no_camera_time")              # a gallery file with no camera time: its date cannot be checked
    dist = None
    if lat is None or lon is None:
        flags.append("no_gps")
    elif plot.lat is None or plot.lon is None:
        flags.append("no_plot_location")
    else:
        dist = round(distance_m(lat, lon, plot.lat, plot.lon), 1)
    if acc is not None and acc > ck["max_gps_accuracy_m"]:
        flags.append("low_gps_accuracy")
    if taken > now + timedelta(minutes=10):
        flags.append("future_time")
    if now - taken > timedelta(days=ck["max_offline_days"]):
        flags.append("old_photo")
    if img.exif_time and abs(img.exif_time - taken) > timedelta(hours=ck["max_clock_skew_hours"]):
        flags.append("time_mismatch")
    if img.exif_lat is not None and lat is not None and \
            distance_m(img.exif_lat, img.exif_lon, lat, lon) > ck["exif_gps_mismatch_m"]:
        flags.append("gps_mismatch")
    sha = hashlib.sha256(img.jpeg).hexdigest()
    flags += _match_flags(s, plot.id, stage, taken, sha, img.phash, ck["duplicate_hamming"])

    policy = latest_policy(s, plot)
    on_schedule = False
    if policy is not None:
        a, b = stage_window(pcfg, appcfg, policy, stage)
        on_schedule = a <= taken.astimezone(timezone(timedelta(hours=3))).date() <= b

    store.mkdir(parents=True, exist_ok=True)
    path = store / sha[:2] / f"{sha}.jpg"
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(img.jpeg)
    photo = Photo(ref="PH-" + secrets.token_hex(4).upper(), client_id=client_id, plot_id=plot.id, farmer_id=plot.farmer_id,
                  policy_id=policy.id if policy else None, taken_by=user.id, stage=stage, taken_at=taken, received_at=now,
                  lat=lat, lon=lon, accuracy_m=acc, distance_m=dist, sha256=sha, phash=img.phash, file_path=str(path),
                  width=img.width, height=img.height, flags=sorted(set(flags)), on_schedule=on_schedule)
    if dist is not None and dist - (acc or 0) > ck["max_distance_m"]:
        # Clearly too far, even allowing for the phone's stated GPS accuracy.
        photo.status = "rejected"
        photo.reject_reason = f"Taken {dist:,.0f} m from the registered farm (the limit is {ck['max_distance_m']} m)."
    else:
        if dist is not None and dist > ck["max_distance_m"]:
            photo.flags = sorted(set(photo.flags) | {"far_or_low_accuracy"})
        if acc is None or acc <= ck["max_gps_accuracy_m"]:
            photo.photo_point_id = (pt.id if (pt := _point(s, plot, lat, lon, ck["photo_point_radius_m"])) else None)
    s.add(photo)
    s.flush()
    audit(s, f"app:{user.id}", "photo.received", "photo", photo.ref, plot=plot.id, stage=stage, status=photo.status,
          flags=photo.flags, on_schedule=on_schedule, distance_m=dist)
    return photo


def ghost(s: Session, plot: Plot, lat: float | None, lon: float | None, radius: float) -> Photo | None:
    """The newest clean photo from the photo point nearest to where the farmer stands (else the plot's newest)."""
    photos = [p for p in s.scalars(select(Photo).where(Photo.plot_id == plot.id, Photo.status != "rejected")
                                   .order_by(Photo.taken_at.desc())) if not set(p.flags or []) & FRAUD_FLAGS]
    if lat is not None and lon is not None:
        pts = list(s.scalars(select(PhotoPoint).where(PhotoPoint.plot_id == plot.id)))
        near = min(pts, key=lambda pt: distance_m(lat, lon, pt.lat, pt.lon), default=None)
        if near and distance_m(lat, lon, near.lat, near.lon) <= radius:
            at = [p for p in photos if p.photo_point_id == near.id]
            if at:
                return at[0]
    return photos[0] if photos else None


def number(v, lo: float, hi: float) -> float | None:
    """A coordinate or accuracy from the app: None if missing, else a finite number in range."""
    if v in (None, ""):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise PhotoError("The phone sent a location we cannot read. Try again.") from None
    if not math.isfinite(f) or not lo <= f <= hi:
        raise PhotoError("The phone sent a location we cannot read. Try again.")
    return f


def _match_flags(s: Session, plot_id: str, stage: str, taken: datetime, sha: str, phash: str, wide: int) -> list[str]:
    """Same plot: "duplicate" only for a true re-send (same bytes, or a near-identical picture of the same stage
    within two days), because photos lined up with the ghost of the last one are meant to look alike.
    Another plot: "reused" for any close match. A picture refused before: "previously_rejected"."""
    out = set()
    for o in s.scalars(select(Photo)):
        d = hamming(o.phash, phash)
        same = o.sha256 == sha
        if o.status == "rejected":
            if same or d <= wide:
                out.add("previously_rejected")
        elif o.plot_id == plot_id:
            near_time = abs(_utc(o.taken_at) - taken) <= timedelta(days=2)
            if same or (d <= 2 and o.stage == stage and near_time):
                out.add("duplicate")
        elif same or d <= wide:
            out.add("reused")
    return sorted(out)


# ------------------------------------------------------------------ AI suggestion for the reviewer
SUGGEST_PROMPT = (
    "You are helping a human agronomist triage one smallholder maize field photo from Kenya. Suggest the single "
    "best tag: healthy, drought_stress, pest, disease, flood or other. Give a one-line reason (under 25 words) "
    "about what is visible. Say other if the picture is not a maize field or is too unclear. The agronomist decides; "
    "your suggestion is only a hint.")
SUGGEST_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["tag", "reason"],
                  "properties": {"tag": {"type": "string", "enum": list(TAGS)}, "reason": {"type": "string"}}}


def call_claude(jpeg: bytes, model: str, timeout: float, api_key: str) -> dict:
    """One Messages API call with the image only. Raises on any failure; the caller records it and moves on."""
    import anthropic
    client = anthropic.Anthropic(api_key=api_key, timeout=timeout, max_retries=1)
    resp = client.beta.messages.create(
        model=model, max_tokens=4096, betas=["server-side-fallback-2026-07-01"], fallbacks="default",
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": SUGGEST_SCHEMA}},
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                         "data": base64.standard_b64encode(jpeg).decode()}},
            {"type": "text", "text": SUGGEST_PROMPT}]}])
    if resp.stop_reason == "refusal":
        raise RuntimeError("the AI service declined this image")
    text = next(b.text for b in resp.content if b.type == "text")
    out = json.loads(text)
    return {"tag": out["tag"], "reason": str(out["reason"])[:300], "model": resp.model}


def suggest(s: Session, pcfg: dict, photo: Photo, caller=None, api_key: str | None = None) -> PhotoSuggestion:
    """At most one suggestion per photo. Sent only with photo_ai consent, only the stripped image, never identifiers.
    With no key, the setting off, or any error, the review queue simply shows no suggestion."""
    have = s.scalar(select(PhotoSuggestion).where(PhotoSuggestion.photo_id == photo.id))
    if have:
        return have
    ai = pcfg["ai"]
    sug = PhotoSuggestion(photo_id=photo.id, status="off")
    key = api_key if api_key is not None else os.environ.get("ANTHROPIC_API_KEY", "")
    if not ai.get("enabled"):
        sug.status = "off"
    elif photo.status == "rejected":
        sug.status = "off"
    elif not consent_granted(s, photo.farmer_id, "photo_ai"):
        sug.status = "no_consent"
    elif not key:
        sug.status = "no_key"
    else:
        img = Image.open(photo.file_path)
        img.thumbnail((ai["max_side_px"], ai["max_side_px"]), Image.LANCZOS)
        sent = pixels_only_jpeg(img)
        if has_metadata(sent):                         # belt and braces: nothing with EXIF ever leaves
            sug.status, sug.error = "error", "refused: image still had metadata"
        else:
            sug.sent_sha256 = hashlib.sha256(sent).hexdigest()
            try:
                out = (caller or call_claude)(sent, ai["model"], ai["timeout_s"], key)
                if out.get("tag") not in TAGS:
                    raise ValueError("unknown tag")
                sug.status, sug.tag, sug.reason, sug.model = "ok", out["tag"], scrub(out["reason"])[:300], out.get("model") or ai["model"]
            except Exception as e:                     # never shown to farmers; the key is never in the message
                sug.status, sug.error = "error", type(e).__name__
                log.warning("photo suggestion failed for %s: %s", photo.ref, type(e).__name__)
    s.add(sug)
    s.flush()
    audit(s, "ai", "photo.suggestion", "photo", photo.ref, status=sug.status, tag=sug.tag or "")
    return sug


# ------------------------------------------------------------------ human review
def review(s: Session, photo: Photo, reviewer: str, tag: str, extent: str, note: str = "", clear_flags: bool = False,
           ussd_code: str = "") -> PhotoReview:
    """The reviewer decides. Logged with the suggestion they were shown, then an advisory SMS (consent-gated)."""
    if photo.status == "rejected":
        raise PhotoError("A rejected photo is not reviewed.")
    if s.scalar(select(PhotoReview).where(PhotoReview.photo_id == photo.id)):
        raise PhotoError("This photo is already reviewed.")
    if tag not in TAGS or extent not in EXTENTS:
        raise PhotoError("Choose a tag and how much of the plot is affected.")
    sug = s.scalar(select(PhotoSuggestion).where(PhotoSuggestion.photo_id == photo.id, PhotoSuggestion.status == "ok"))
    r = PhotoReview(photo_id=photo.id, reviewer=reviewer, tag=tag, extent=extent, note=scrub((note or "").strip())[:500] or None,
                    suggestion_id=sug.id if sug else None, suggestion_tag=sug.tag if sug else None,
                    agreed_with_suggestion=(sug.tag == tag) if sug else None, flags_cleared=bool(clear_flags))
    s.add(r)
    photo.status = "reviewed"
    s.flush()
    audit(s, reviewer, "photo.reviewed", "photo", photo.ref, tag=tag, extent=extent, suggestion=sug.tag if sug else "",
          agreed=r.agreed_with_suggestion, flags_cleared=bool(clear_flags))
    pol = s.get(Policy, photo.policy_id) if photo.policy_id else None
    if pol is not None:
        sms.queue(s, photo.farmer, f"photo_{tag}", pol, dedupe_key=f"photo:{photo.id}", ussd_code=ussd_code)
    return r


def queue_for(s: Session, policy_ids: set[str]) -> list[Photo]:
    """Photos waiting for a reviewer, oldest first (flagged ones first)."""
    rows = [p for p in s.scalars(select(Photo).where(Photo.status == "in_review").order_by(Photo.received_at))
            if p.policy_id in policy_ids]
    return sorted(rows, key=lambda p: (not p.flags, p.received_at))


# ------------------------------------------------------------------ picture-based rider (ILLUSTRATIVE, off in quotes)
def rider_offered(pcfg: dict) -> bool:
    """The rider is never quoted until the owner switches it on in config/photo.yaml."""
    return bool(pcfg["rider"]["enabled_in_quotes"])


def rider_illustrative_premium(pcfg: dict, policy: Policy) -> float:
    return round((policy.sum_insured_per_acre or 0) * policy.acres * pcfg["rider"]["rate_of_sum_insured"], 2)


def report_damage(s: Session, pcfg: dict, user: AppUser, policy: Policy, cause: str, note: str,
                  photo_refs: list[str]) -> RiderClaim:
    if cause not in pcfg["rider"]["causes"]:
        raise PhotoError("Choose what caused the damage.")
    if policy.farmer_id != user.farmer_id and policy.plot_id not in {p.id for p in plots_for(s, user)}:
        raise PhotoError("You cannot report damage for that farm.")
    photos = [p for p in s.scalars(select(Photo).where(Photo.ref.in_(photo_refs or ["-"]), Photo.policy_id == policy.id,
                                                       Photo.status != "rejected"))]
    if not photos:
        raise PhotoError("Add at least one photo of the damage.")
    c = RiderClaim(ref="RC-" + secrets.token_hex(3).upper(), policy_id=policy.id, reported_by=user.id, cause=cause,
                   note=scrub((note or "").strip())[:500] or None)
    s.add(c)
    s.flush()
    for p in photos:
        p.rider_claim_id = c.id
    audit(s, f"app:{user.id}", "rider.reported", "policy", policy.id, claim=c.ref, cause=cause, photos=len(photos))
    return c


def assess(s: Session, pcfg: dict, claim: RiderClaim, reviewer: str, extent: str, now: datetime) -> RiderClaim:
    """ILLUSTRATIVE assessment: sum insured x the share for the damage band. Never a payout."""
    if extent not in EXTENTS:
        raise PhotoError("Choose how much of the plot is damaged.")
    pol = claim.policy
    share = pcfg["rider"]["payout_share_by_extent"][extent]
    claim.extent, claim.status, claim.assessed_by, claim.assessed_at = extent, "assessed", reviewer, now
    claim.illustrative_amount_kes = round((pol.sum_insured_per_acre or 0) * pol.acres * share, 2)
    audit(s, reviewer, "rider.assessed", "policy", pol.id, claim=claim.ref, extent=extent,
          illustrative_amount_kes=claim.illustrative_amount_kes, label="ILLUSTRATIVE")
    return claim
