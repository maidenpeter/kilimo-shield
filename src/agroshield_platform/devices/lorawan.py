"""LoRaWAN payloads for the soil moisture node and the rain gauge, and the network server webhook.

Byte layout (all multi-byte fields big-endian; full description in docs/hardware/SOIL_NODE.md). Version 1.

Soil moisture node, FPort 1, 11 + 3n bytes (n = 1 to 3 depths; 20 bytes for three):
    0     u8   version (1)
    1-2   u16  sequence number (wraps at 65535)
    3-4   u16  age in minutes (0 = measured now; > 0 = a stored reading sent late)
    5     u8   flags: bit0-2 sensor at depth 1-3 not responding, bit3 temperature sensor fault, bit4 battery low,
               bit5 restarted since last uplink, bit6 more stored readings waiting
    6-7   u16  battery in millivolts
    8     u8   n, the number of depths
    9..   n x  [u8 depth in cm, u16 volumetric water content in 0.1 % (0xFFFF = no reading)]
    last  i16  soil temperature in 0.01 C (0x7FFF = no reading)

Rain gauge (tipping bucket), FPort 2, 14 bytes:
    0     u8   version (1)
    1-2   u16  sequence number
    3-4   u16  age in minutes
    5     u8   flags: bit0 reed switch fault, bit3 temperature sensor fault, bit4 battery low, bit5 restarted,
               bit6 more stored readings waiting
    6-7   u16  battery in millivolts
    8-9   u16  bucket tips counted in the interval
    10-11 u16  interval length in minutes
    12-13 i16  air temperature in 0.01 C (0x7FFF = no reading)

The same layout is decoded on The Things Stack by firmware/soil-node/ttn_decoder.js (a test keeps the two equal).
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import struct
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Device, DeviceMessage
from .ingest import Result, _reject, now_utc, parse_time, store_message

VERSION = 1
RESEND_SLACK = timedelta(minutes=10)     # how far a resent reading's computed time may drift from the first copy's
SOIL_PORT, RAIN_PORT = 1, 2
NO_VWC, NO_TEMP = 0xFFFF, 0x7FFF
SOIL_FLAGS = {0: "soil sensor at depth 1 not responding", 1: "soil sensor at depth 2 not responding",
              2: "soil sensor at depth 3 not responding", 3: "temperature sensor fault", 5: "device restarted"}
RAIN_FLAGS = {0: "rain gauge switch fault: tip count may be wrong", 3: "temperature sensor fault", 5: "device restarted"}
FLAG_LOW_BATTERY, FLAG_BACKLOG = 4, 6


class PayloadError(ValueError):
    pass


def encode_soil(seq: int, age_min: int, battery_mv: int, depths: list[tuple[int, float | None]],
                soil_temp_c: float | None, flags: int = 0) -> bytes:
    if not 1 <= len(depths) <= 3:
        raise PayloadError("1 to 3 depths")
    out = struct.pack(">BHHBHB", VERSION, seq & 0xFFFF, age_min, flags, battery_mv, len(depths))
    for cm, vwc in depths:
        out += struct.pack(">BH", cm, NO_VWC if vwc is None else round(vwc * 10))
    return out + struct.pack(">h", NO_TEMP if soil_temp_c is None else round(soil_temp_c * 100))


def encode_rain(seq: int, age_min: int, battery_mv: int, tips: int, interval_min: int,
                air_temp_c: float | None = None, flags: int = 0) -> bytes:
    return struct.pack(">BHHBHHHh", VERSION, seq & 0xFFFF, age_min, flags, battery_mv, tips, interval_min,
                       NO_TEMP if air_temp_c is None else round(air_temp_c * 100))


def decode(port: int, payload: bytes) -> dict:
    """{version, seq, age_min, flags, battery_v, readings, errors, backlog} or PayloadError."""
    if not payload or payload[0] != VERSION:
        raise PayloadError(f"unknown payload version {payload[0] if payload else 'none'}")
    if port == SOIL_PORT:
        if len(payload) < 12:
            raise PayloadError("soil payload too short")
        _, seq, age, flags, mv, n = struct.unpack_from(">BHHBHB", payload, 0)
        if not 1 <= n <= 3 or len(payload) != 11 + 3 * n:
            raise PayloadError("soil payload length does not match its number of depths")
        readings = {}
        for i in range(n):
            cm, raw = struct.unpack_from(">BH", payload, 9 + 3 * i)
            if raw != NO_VWC:
                readings[f"soil_vwc_{cm}cm"] = raw / 10
        (temp,) = struct.unpack_from(">h", payload, 9 + 3 * n)
        if temp != NO_TEMP:
            readings["soil_temp_c"] = temp / 100
        names = SOIL_FLAGS
    elif port == RAIN_PORT:
        if len(payload) != 14:
            raise PayloadError("rain payload must be 14 bytes")
        _, seq, age, flags, mv, tips, interval, temp = struct.unpack(">BHHBHHHh", payload)
        readings = {"rain_tips": tips, "interval_min": interval}
        if temp != NO_TEMP:
            readings["air_temp_c"] = temp / 100
        names = RAIN_FLAGS
    else:
        raise PayloadError(f"unknown FPort {port}")
    if mv:
        readings["battery_v"] = mv / 1000
    errors = [text for bit, text in names.items() if flags & (1 << bit)]
    return {"version": VERSION, "seq": seq, "age_min": age, "flags": flags, "readings": readings, "errors": errors,
            "battery_low": bool(flags & (1 << FLAG_LOW_BATTERY)), "backlog": bool(flags & (1 << FLAG_BACKLOG))}


def parse_uplink(body: dict) -> dict:
    """dev_eui, port, payload, received_at and best RSSI from a The Things Stack (v3) or ChirpStack (v4) uplink."""
    if not isinstance(body, dict):
        raise PayloadError("not an uplink")
    if "uplink_message" in body:                                       # The Things Stack
        up = body.get("uplink_message") or {}
        eui = (body.get("end_device_ids") or {}).get("dev_eui")
        port, data, received = up.get("f_port"), up.get("frm_payload"), body.get("received_at") or up.get("received_at")
        rx = up.get("rx_metadata") or []
    elif "deviceInfo" in body:                                         # ChirpStack
        eui = (body.get("deviceInfo") or {}).get("devEui")
        port, data, received, rx = body.get("fPort"), body.get("data"), body.get("time"), body.get("rxInfo") or []
    else:
        raise PayloadError("not an uplink message")
    if not isinstance(eui, str) or not isinstance(port, int) or not isinstance(data, str):
        raise PayloadError("uplink without device EUI, FPort or payload")
    try:
        payload = base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError):
        raise PayloadError("payload is not base64") from None
    rssi = [m.get("rssi") for m in rx if isinstance(m, dict) and isinstance(m.get("rssi"), (int, float))]
    return {"dev_eui": eui.upper(), "port": port, "payload": payload, "received_at": received,
            "rssi": max(rssi) if rssi else None}


def handle_uplink(s: Session, body: dict, now: datetime | None = None) -> tuple[int, dict]:
    """HTTP status and answer for one network server uplink."""
    now = now or now_utc()
    try:
        up = parse_uplink(body)
    except PayloadError as e:
        return 400, {"error": str(e)}
    device = s.scalar(select(Device).where(Device.dev_eui == up["dev_eui"]))
    if device is None or device.status != "active":
        return 404, {"error": "unknown or retired device"}
    try:
        d = decode(up["port"], up["payload"])
        want = {SOIL_PORT: "soil", RAIN_PORT: "rain"}[up["port"]]
        if device.kind != want:
            raise PayloadError(f"FPort {up['port']} is for a {want} device; this is a {device.kind} device")
    except PayloadError as e:
        r = _reject(s, device, None, str(e), now)
        return 422, r.as_dict()
    try:
        received = parse_time(up["received_at"], now) if up["received_at"] else now
    except ValueError:
        received = now
    observed = received - timedelta(minutes=d["age_min"])
    readings = dict(d["readings"])
    if up["rssi"] is not None and -140 <= up["rssi"] <= 0:
        readings["signal_dbm"] = float(up["rssi"])
    # The message id is the node's sequence number and the day it measured; the identity leaves out the age and
    # flags bytes (and the signal), so a reading the node sends again later is recognised as the same reading.
    msg = {"msg_id": f"lw{up['port']}-{d['seq']}-{observed:%Y%m%d}",
           "observed_at": observed.isoformat(), "readings": readings, "errors": d["errors"]}
    p = up["payload"]
    identity = hashlib.sha256(bytes([up["port"]]) + p[:3] + b"\0\0\0" + p[6:]).hexdigest()
    # The age is in whole minutes, so a reading measured just before midnight UTC can come back on a resend with a
    # time just after it, under the next day's id. The same reading under a neighbouring day's id is a duplicate.
    for edge in (observed - RESEND_SLACK, observed + RESEND_SLACK):
        other = f"lw{up['port']}-{d['seq']}-{edge:%Y%m%d}"
        if other != msg["msg_id"]:
            old = s.scalar(select(DeviceMessage).where(DeviceMessage.device_id == device.id,
                                                       DeviceMessage.msg_id == other))
            if old is not None and old.payload_sha256 == identity:
                device.last_seen_at = now
                return 200, Result(other, "duplicate").as_dict()
    r: Result = store_message(s, device, msg, "lorawan", now, identity=identity)
    return {"accepted": 200, "duplicate": 200, "conflict": 409}.get(r.status, 422), r.as_dict()
