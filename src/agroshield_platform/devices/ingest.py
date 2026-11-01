"""Ingestion: validate and store device messages (readings and photos), and device health.

A message is {"msg_id": ..., "observed_at": ..., "readings": {metric: value}, "errors": [...], "firmware": ...}.
- Idempotent: the device's msg_id is stored once per device. The same message again is "duplicate" (harmless, so a
  device that lost the reply can resend); the same id with different content is "conflict" and is not stored.
- Validated: every metric is known for the device kind and inside its physical range, and the time has a zone, is
  not in the future (10 minutes of clock drift allowed) and not older than the store-and-forward window (90 days).
  A message that fails is "rejected" whole, with its reasons, and noted for the device.
All times are stored in UTC.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..crypto import scrub
from ..models import Device, DeviceImage, DeviceIssue, DeviceMessage, DeviceReading
from . import greenness
from .registry import DEFAULT_SETTINGS, _utc

MAX_BATCH = 200
MAX_PHOTO_BYTES = 3 * 1024 * 1024
MAX_BACKFILL = timedelta(days=90)
MAX_FUTURE = timedelta(minutes=10)
EARLIEST = datetime(2024, 1, 1, tzinfo=timezone.utc)      # an unset device clock reads 1970 or 2000
LATE_AFTER = timedelta(hours=1)                            # received this long after it was observed: sent late
MSG_ID_RE = re.compile(r"[A-Za-z0-9._:-]{1,64}")
SOIL_VWC_RE = re.compile(r"soil_vwc_(\d{1,3})cm")

RANGES = {
    "battery_v": (2.5, 15.0),          # a 1-cell lithium pack up to a 12 V lead-acid battery
    "signal_dbm": (-140.0, 0.0),
    "queue_depth": (0, 100_000),
    "soil_temp_c": (-10.0, 70.0),
    "air_temp_c": (-15.0, 60.0),
    "rain_tips": (0, 10_000),
    "interval_min": (1, 1440),
    "soil_vwc": (0.0, 100.0),          # volumetric water content, percent
}
COMMON = {"battery_v", "signal_dbm", "queue_depth"}
ALLOWED = {"camera": COMMON | {"air_temp_c"},
           "soil": COMMON | {"soil_temp_c"},
           "rain": COMMON | {"rain_tips", "interval_min", "air_temp_c"}}
INTEGER = {"queue_depth", "rain_tips", "interval_min"}


@dataclass
class Result:
    msg_id: str
    status: str                              # accepted | duplicate | conflict | rejected
    reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"msg_id": self.msg_id, "status": self.status, **({"reasons": self.reasons} if self.reasons else {})}


class BadRequest(ValueError):
    """The envelope itself is wrong (not a single message): answered with HTTP 400."""


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def parse_time(v, now: datetime) -> datetime:
    """An ISO 8601 time with a zone, or Unix seconds; checked against the clock and the backfill window."""
    if isinstance(v, bool) or v is None:
        raise ValueError("observed_at is missing")
    if isinstance(v, (int, float)):
        try:
            t = datetime.fromtimestamp(float(v), tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            raise ValueError("observed_at is not a time") from None
    elif isinstance(v, str):
        txt = v.strip()
        if re.fullmatch(r"\d{9,11}", txt):
            t = datetime.fromtimestamp(int(txt), tz=timezone.utc)
        else:
            txt = re.sub(r"(\.\d{6})\d+", r"\1", txt.replace("Z", "+00:00"))   # network servers send nanoseconds
            try:
                t = datetime.fromisoformat(txt)
            except ValueError:
                raise ValueError("observed_at is not a time") from None
            if t.tzinfo is None:
                raise ValueError("observed_at needs a time zone (UTC, ending in Z)")
            t = t.astimezone(timezone.utc)
    else:
        raise ValueError("observed_at is not a time")
    if t < EARLIEST:
        raise ValueError("observed_at is before 2024: the device clock is not set")
    if t > now + MAX_FUTURE:
        raise ValueError("observed_at is in the future: the device clock is fast")
    if t < now - MAX_BACKFILL:
        raise ValueError("observed_at is more than 90 days ago")
    return t


def _check_metric(kind: str, name, value) -> list[str]:
    if not isinstance(name, str):
        return ["a reading has no name"]
    m = SOIL_VWC_RE.fullmatch(name)
    if m and kind == "soil":
        rng = RANGES["soil_vwc"]
        if not 1 <= int(m.group(1)) <= 200:
            return [f"{name}: depth must be 1 to 200 cm"]
    elif name in ALLOWED.get(kind, ()):
        rng = RANGES[name]
    else:
        return [f"{name[:40]}: not a reading a {kind} device sends"]
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value or value in (float("inf"), float("-inf")):
        return [f"{name}: not a number"]
    if name in INTEGER and float(value) != int(value):
        return [f"{name}: must be a whole number"]
    if not rng[0] <= value <= rng[1]:
        return [f"{name}: {value} is outside {rng[0]} to {rng[1]}"]
    return []


def validate(device: Device, msg: dict, now: datetime) -> tuple[datetime, dict[str, float], list[str], str | None]:
    """Checked time, readings, device errors and firmware. Raises ValueError with every reason joined by '; '."""
    reasons: list[str] = []
    observed = None
    try:
        observed = parse_time(msg.get("observed_at"), now)
    except ValueError as e:
        reasons.append(str(e))
    readings = msg.get("readings", {})
    if not isinstance(readings, dict):
        reasons.append("readings must be an object")
        readings = {}
    for k, v in readings.items():
        reasons += _check_metric(device.kind, k, v)
    if device.kind == "rain" and ("rain_tips" in readings) != ("interval_min" in readings):
        reasons.append("rain_tips needs interval_min (and the other way round)")
    errors = msg.get("errors", [])
    if not isinstance(errors, list) or len(errors) > 10 or not all(isinstance(e, str) for e in errors):
        reasons.append("errors must be a list of up to 10 texts")
        errors = []
    firmware = msg.get("firmware")
    if firmware is not None and (not isinstance(firmware, str) or len(firmware) > 40):
        reasons.append("firmware must be a text of up to 40 characters")
    if not readings and not errors and not reasons:
        reasons.append("the message has no readings and no errors")
    if reasons:
        raise ValueError("; ".join(reasons))
    return observed, {k: float(v) for k, v in readings.items()}, [scrub(e.strip())[:200] for e in errors if e.strip()], firmware


def payload_hash(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _existing(s: Session, device: Device, msg_id: str, sha: str) -> Result | None:
    old = s.scalar(select(DeviceMessage).where(DeviceMessage.device_id == device.id, DeviceMessage.msg_id == msg_id))
    if old is None:
        return None
    if old.payload_sha256 == sha:
        return Result(msg_id, "duplicate")
    return Result(msg_id, "conflict", ["this message id was already used for different content"])


def _reject(s: Session, device: Device, msg_id: str | None, reasons: str, now: datetime) -> Result:
    s.add(DeviceIssue(device_id=device.id, kind="rejected", msg_id=msg_id, detail=scrub(reasons)[:300], at=now))
    device.last_error, device.last_error_at = f"Message refused: {scrub(reasons)}"[:200], now
    return Result(msg_id or "", "rejected", reasons.split("; "))


def _touch(device: Device, observed: datetime, now: datetime, readings: dict, firmware: str | None) -> None:
    """Health: last heard from now; battery and signal from the newest reading (a late batch never overwrites them)."""
    device.last_seen_at = now
    if device.last_observed_at is None or observed >= _utc(device.last_observed_at):
        device.last_observed_at = observed
        if "battery_v" in readings:
            device.last_battery_v = readings["battery_v"]
        if "signal_dbm" in readings:
            device.last_signal_dbm = readings["signal_dbm"]
        if firmware:
            device.firmware = firmware


def store_message(s: Session, device: Device, msg, transport: str, now: datetime | None = None,
                  identity: str | None = None) -> Result:
    """Store one message. `identity` (a hash) replaces the content hash where a resend legitimately differs in
    detail, such as a LoRaWAN reading resent later with a different age and signal strength."""
    now = now or now_utc()
    if not isinstance(msg, dict):
        return _reject(s, device, None, "a message must be an object", now)
    msg_id = msg.get("msg_id")
    if not isinstance(msg_id, str) or not MSG_ID_RE.fullmatch(msg_id):
        return _reject(s, device, None, "msg_id: 1 to 64 letters, digits or . _ : -", now)
    sha = identity or payload_hash(msg)
    if (seen := _existing(s, device, msg_id, sha)) is not None:
        device.last_seen_at = now
        return seen
    try:
        observed, readings, errors, firmware = validate(device, msg, now)
    except ValueError as e:
        return _reject(s, device, msg_id, str(e), now)
    if "rain_tips" in readings:
        mm_per_tip = float(device.settings.get("mm_per_tip", DEFAULT_SETTINGS["rain"]["mm_per_tip"]))
        readings["rain_mm"] = tips_to_mm(readings["rain_tips"], mm_per_tip)
    try:
        with s.begin_nested():
            m = DeviceMessage(device_id=device.id, msg_id=msg_id, transport=transport, observed_at=observed,
                              received_at=now, payload_sha256=sha)
            s.add(m)
            s.flush()
            s.add_all([DeviceReading(message_id=m.id, device_id=device.id, metric=k, value=v, observed_at=observed)
                       for k, v in readings.items()])
            for e in errors:
                s.add(DeviceIssue(device_id=device.id, kind="device_error", msg_id=msg_id, detail=e, at=now))
            s.flush()
    except IntegrityError:                    # the same message arrived twice at once
        return _existing(s, device, msg_id, sha) or Result(msg_id, "duplicate")
    if errors:
        device.last_error, device.last_error_at = errors[-1], now
    _touch(device, observed, now, readings, firmware)
    return Result(msg_id, "accepted")


def tips_to_mm(tips: float, mm_per_tip: float) -> float:
    """Tipping bucket: each tip is a fixed depth of rain (0.2 mm is common; calibrate each gauge)."""
    return round(float(tips) * float(mm_per_tip), 3)


def ingest_batch(s: Session, device: Device, body, transport: str, now: datetime | None = None) -> list[Result]:
    """A device's batch: {"messages": [...]} (store-and-forward catch-up sends many at once, oldest first)."""
    now = now or now_utc()
    if not isinstance(body, dict) or not isinstance(body.get("messages"), list):
        raise BadRequest('send {"messages": [ ... ]}')
    msgs = body["messages"]
    if not 1 <= len(msgs) <= MAX_BATCH:
        raise BadRequest(f"send 1 to {MAX_BATCH} messages at a time")
    return [store_message(s, device, m, transport, now) for m in msgs]


def store_photo(s: Session, device: Device, data: bytes, msg_id: str | None, observed_raw, store: Path,
                battery_mv: str | None = None, signal_dbm: str | None = None, transport: str = "https",
                now: datetime | None = None) -> tuple[Result, DeviceImage | None]:
    """A sentinel camera photo: checked, stored as a file, greenness measured and kept in the time series."""
    now = now or now_utc()
    if device.kind != "camera":
        return _reject(s, device, msg_id if msg_id and MSG_ID_RE.fullmatch(msg_id) else None,
                       "only a field camera sends photos", now), None
    if not isinstance(msg_id, str) or not MSG_ID_RE.fullmatch(msg_id):
        return _reject(s, device, None, "msg_id: 1 to 64 letters, digits or . _ : -", now), None
    if not data:
        return _reject(s, device, msg_id, "the photo is empty", now), None
    if len(data) > MAX_PHOTO_BYTES:
        return _reject(s, device, msg_id, "the photo is larger than 3 MB", now), None
    sha = hashlib.sha256(data).hexdigest()
    if (seen := _existing(s, device, msg_id, sha)) is not None:
        device.last_seen_at = now
        return seen, None
    reasons = []
    try:
        observed = parse_time(observed_raw, now)
    except ValueError as e:
        reasons.append(str(e))
    readings: dict[str, float] = {}
    for header, metric, scale in ((battery_mv, "battery_v", 1000.0), (signal_dbm, "signal_dbm", 1.0)):
        if header in (None, "", "0"):
            continue                                                   # 0 means "not measured" on the camera
        try:
            readings[metric] = float(header) / scale
        except ValueError:
            reasons.append(f"{metric}: not a number")
            continue
        reasons += _check_metric("camera", metric, readings[metric])
    try:
        g = greenness.analyse(data)
    except greenness.PhotoError as e:
        reasons.append(str(e))
    if reasons:
        return _reject(s, device, msg_id, "; ".join(reasons), now), None
    rel = Path(device.uid) / f"{observed:%Y-%m}" / f"{sha}.jpg"
    (store / rel).parent.mkdir(parents=True, exist_ok=True)
    if not (store / rel).exists():
        (store / rel).write_bytes(data)
    readings.update({"greenness_gcc": g["gcc"], "greenness_exg": g["exg"], "green_fraction": g["green_fraction"]})
    try:
        with s.begin_nested():
            m = DeviceMessage(device_id=device.id, msg_id=msg_id, transport=transport, observed_at=observed,
                              received_at=now, payload_sha256=sha)
            s.add(m)
            s.flush()
            img = DeviceImage(device_id=device.id, message_id=m.id, sha256=sha, path=rel.as_posix(), size_bytes=len(data),
                              width=g["width"], height=g["height"], gcc=g["gcc"], exg=g["exg"],
                              green_fraction=g["green_fraction"], observed_at=observed)
            s.add(img)
            s.add_all([DeviceReading(message_id=m.id, device_id=device.id, metric=k, value=v, observed_at=observed)
                       for k, v in readings.items()])
            s.flush()
    except IntegrityError:
        return _existing(s, device, msg_id, sha) or Result(msg_id, "duplicate"), None
    _touch(device, observed, now, readings, None)
    return Result(msg_id, "accepted"), img


# ---------------------------------------------------------------------------------------------------- health
HEALTH = {"ok": ("Reporting", "ok"), "late": ("Late", "warn"), "offline": ("Not heard from", "crit"),
          "never": ("Never reported", "warn"), "retired": ("Retired", "")}


def health(device: Device, now: datetime | None = None) -> dict:
    """Plain-language state from the last message received, the battery and the report interval."""
    now = now or now_utc()
    every = timedelta(minutes=int(device.settings.get("report_every_min",
                                                      DEFAULT_SETTINGS[device.kind]["report_every_min"])))
    seen = _utc(device.last_seen_at) if device.last_seen_at else None
    if device.status == "retired":
        state = "retired"
    elif seen is None:
        state = "never"
    elif now - seen > max(6 * every, timedelta(hours=24)):
        state = "offline"
    elif now - seen > 2 * every:
        state = "late"
    else:
        state = "ok"
    low_v = float(device.settings.get("battery_low_v", DEFAULT_SETTINGS[device.kind]["battery_low_v"]))
    label, tone = HEALTH[state]
    return {"state": state, "label": label, "tone": tone, "since": (now - seen) if seen else None,
            "seen_text": ago(now - seen) if seen else "never",
            "battery_low": device.last_battery_v is not None and device.last_battery_v < low_v, "battery_low_v": low_v}


def ago(dt: timedelta) -> str:
    mins = int(dt.total_seconds() // 60)
    if mins < 2:
        return "just now"
    if mins < 120:
        return f"{mins} minutes ago"
    if mins < 48 * 60:
        return f"{mins // 60} hours ago"
    return f"{mins // 1440} days ago"


def issues_since(s: Session, device_ids: list[int], since: datetime) -> dict[int, int]:
    if not device_ids:
        return {}
    rows = s.execute(select(DeviceIssue.device_id, func.count()).where(DeviceIssue.device_id.in_(device_ids),
                                                                         DeviceIssue.at >= since)
                     .group_by(DeviceIssue.device_id))
    return {d: n for d, n in rows}


def late_messages(s: Session, device: Device, since: datetime) -> int:
    """Messages received more than an hour after they were observed (stored on the device and sent later)."""
    msgs = s.execute(select(DeviceMessage.observed_at, DeviceMessage.received_at)
                     .where(DeviceMessage.device_id == device.id, DeviceMessage.received_at >= since))
    return sum(1 for o, r in msgs if _utc(r) - _utc(o) > LATE_AFTER)
