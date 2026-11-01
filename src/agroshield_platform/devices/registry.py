"""Device registry: register, re-key and retire devices; LoRaWAN network server integrations; authentication.

A device key is 256 random bits shown once. Only its SHA-256 hash is stored: with that much entropy a plain hash
is as strong as a slow password hash and stays cheap on every upload. Keys travel only over TLS (HTTPS or MQTT over
TLS), in a header or the MQTT payload, never in a URL.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..crypto import scrub
from ..db import audit
from ..models import Device, DeviceIntegration, DeviceIssue

KINDS = {"camera": "Field camera", "soil": "Soil moisture", "rain": "Rain gauge"}
SITE_TYPES = {"school": "School", "sacco_office": "SACCO office", "demo_plot": "Demonstration plot", "other": "Other"}
DEFAULT_SETTINGS = {
    "camera": {"report_every_min": 720, "photos_per_day": 2, "battery_low_v": 3.45},
    "soil": {"report_every_min": 60, "depths_cm": [10, 30, 60], "battery_low_v": 3.3},
    "rain": {"report_every_min": 60, "mm_per_tip": 0.2, "battery_low_v": 3.3},
}
UID_RE = re.compile(r"[A-Z0-9][A-Z0-9-]{2,31}")
EUI_RE = re.compile(r"[0-9A-F]{16}")
AUTH_ISSUE_EVERY = timedelta(minutes=10)      # at most one "wrong key" note per device in this time


class DeviceError(ValueError):
    pass


def hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def new_secret() -> str:
    return secrets.token_urlsafe(32)


def settings_for(kind: str, overrides: dict | None = None) -> dict:
    return {**DEFAULT_SETTINGS[kind], **(overrides or {})}


def register(s: Session, *, uid: str, kind: str, ward_id: str, site_type: str, site_label: str, actor: str,
             wards=None, name: str | None = None, lat: float | None = None, lon: float | None = None,
             dev_eui: str | None = None, settings: dict | None = None) -> tuple[Device, str]:
    """Add a device. Returns it and its key (shown once; only the hash is kept)."""
    uid = (uid or "").strip().upper()
    if not UID_RE.fullmatch(uid):
        raise DeviceError("Device id: 3 to 32 capital letters, digits or dashes (as printed on its label).")
    if kind not in KINDS:
        raise DeviceError(f"Kind must be one of {', '.join(KINDS)}.")
    if wards is not None and ward_id not in wards:
        raise DeviceError(f"Unknown ward {ward_id!r}.")
    if site_type not in SITE_TYPES:
        raise DeviceError(f"Site type must be one of {', '.join(SITE_TYPES)}.")
    site_label = (site_label or "").strip()
    if not site_label or len(site_label) > 120:
        raise DeviceError("Site label: 1 to 120 characters, e.g. \"Primary school (fictional)\".")
    if scrub(site_label) != site_label or (name and scrub(name) != name):
        raise DeviceError("Labels must not hold an ID or phone number. Name the site, never a person.")
    if dev_eui is not None:
        dev_eui = dev_eui.strip().upper().replace(":", "").replace("-", "")
        if not EUI_RE.fullmatch(dev_eui):
            raise DeviceError("DevEUI must be 16 hexadecimal digits.")
    for v, lo, hi, what in ((lat, -5.0, 5.5, "Latitude"), (lon, 33.5, 42.0, "Longitude")):
        if v is not None and not lo <= v <= hi:
            raise DeviceError(f"{what} is outside Kenya.")
    if s.scalar(select(Device).where(Device.uid == uid)):
        raise DeviceError(f"Device {uid} is already registered.")
    if dev_eui and s.scalar(select(Device).where(Device.dev_eui == dev_eui)):
        raise DeviceError("That DevEUI is already registered to another device.")
    secret = new_secret()
    d = Device(uid=uid, kind=kind, name=(name or f"{KINDS[kind]} {uid}")[:80], ward_id=ward_id, site_type=site_type,
               site_label=site_label, lat=lat, lon=lon, secret_hash=hash_secret(secret), dev_eui=dev_eui,
               settings=settings_for(kind, settings), status="active", created_by=actor)
    s.add(d)
    s.flush()
    audit(s, actor, "device.registered", "device", uid, kind=kind, ward=ward_id, site_type=site_type)
    return d, secret


def get(s: Session, uid: str) -> Device | None:
    return s.scalar(select(Device).where(Device.uid == (uid or "").strip().upper()))


def rotate_secret(s: Session, device: Device, actor: str) -> str:
    secret = new_secret()
    device.secret_hash = hash_secret(secret)
    audit(s, actor, "device.key_rotated", "device", device.uid)
    return secret


def retire(s: Session, device: Device, actor: str, reason: str = "") -> None:
    device.status = "retired"
    audit(s, actor, "device.retired", "device", device.uid, reason=reason[:200])


def add_integration(s: Session, name: str, actor: str, kind: str = "lorawan_webhook") -> tuple[DeviceIntegration, str]:
    name = (name or "").strip()
    if not 1 <= len(name) <= 60:
        raise DeviceError("Integration name: 1 to 60 characters.")
    if s.scalar(select(DeviceIntegration).where(DeviceIntegration.name == name)):
        raise DeviceError(f"Integration {name!r} already exists.")
    secret = new_secret()
    i = DeviceIntegration(name=name, kind=kind, secret_hash=hash_secret(secret), active=True)
    s.add(i)
    s.flush()
    audit(s, actor, "device.integration_added", "device_integration", name, kind=kind)
    return i, secret


def authenticate(s: Session, uid: str | None, key: str | None, now: datetime | None = None) -> Device | None:
    """The active device with this id and key, or None. A wrong key for a known device is noted (rate-limited)."""
    if not uid or not key:
        return None
    d = get(s, uid)
    if d is None:
        hmac.compare_digest(hash_secret(key), hash_secret("x"))     # same work either way
        return None
    if not hmac.compare_digest(d.secret_hash, hash_secret(key)):
        now = now or datetime.now(timezone.utc)
        last = s.scalar(select(DeviceIssue.at).where(DeviceIssue.device_id == d.id, DeviceIssue.kind == "auth_failed")
                        .order_by(DeviceIssue.at.desc()).limit(1))
        if last is None or now - _utc(last) > AUTH_ISSUE_EVERY:
            s.add(DeviceIssue(device_id=d.id, kind="auth_failed", detail="A message came with a wrong device key.", at=now))
        return None
    return d if d.status == "active" else None


def authenticate_integration(s: Session, key: str | None) -> DeviceIntegration | None:
    if not key:
        return None
    h = hash_secret(key)
    for i in s.scalars(select(DeviceIntegration).where(DeviceIntegration.active.is_(True))):
        if hmac.compare_digest(i.secret_hash, h):
            return i
    return None


def _utc(dt: datetime) -> datetime:
    """SQLite gives timestamps back without a zone; every device time is stored in UTC."""
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
