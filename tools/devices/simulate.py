"""Device simulator: realistic readings through the real ingestion API, so the pipeline is tested without hardware.

Per ward it runs a sentinel camera (photos at 10:00 and 13:00, heartbeats, battery drain), a soil moisture node
(three depths and temperature, hourly) and a rain gauge (bucket tips, hourly), over a stretch of days ending now.
Rain falls on a seeded random pattern; soil water rises with rain and dries out between storms; the crop greens up.
It also plays out what goes wrong in the field:
  - an outage: the ward-a camera and soil node lose signal for two days, keep their messages (SD card, node memory)
    and send them all when the signal returns (store and forward), oldest first
  - a lost reply: the first caught-up message is sent again, and the server must store it once (duplicate)
  - a faulty sensor: one reading of 150% soil water, which the server must refuse

Soil nodes and rain gauges alternate between LoRaWAN (through the network server webhook) and HTTPS JSON, so both
paths are exercised. All devices and sites are fictional.

    python tools/devices/simulate.py --in-process --days 10
        a temporary database and the app in this process (FastAPI TestClient); prints a summary
    python tools/devices/simulate.py --base-url http://127.0.0.1:8000 --keys keys.json [--integration-key K]
        a running portal. keys.json lists {"uid", "kind", "key", "dev_eui"?} for each device, from
        python -m agroshield_platform.devices register --json. Every message then arrives "now", so the portal shows
        them as sent late; --in-process sets the server clock to the simulated time instead.
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import math
import random
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
from PIL import Image

NAIROBI = timezone(timedelta(hours=3))
PHOTO_HOURS = (10, 13)
MM_PER_TIP = 0.2
DEPTHS = (10, 30, 60)


@dataclass
class SimDevice:
    uid: str
    kind: str
    key: str
    ward: str
    dev_eui: str | None = None
    battery_v: float = 3.9
    drain_per_day: float = 0.01
    seq: int = 0
    queue: list = field(default_factory=list)        # stored while offline: ("json"|"photo"|"lorawan", payload, at)
    vwc: list = field(default_factory=lambda: [24.0, 27.0, 30.0])


def fleet_specs(wards=("ward-a", "ward-b")) -> list[dict]:
    """The fictional fleet: per ward a camera, a soil node and a rain gauge. LoRaWAN for the ward-a soil node and
    the ward-b rain gauge; HTTPS for the others."""
    out = []
    for i, w in enumerate(wards):
        tag = w.split("-")[-1].upper()
        out += [
            {"uid": f"CAM-{tag}-01", "kind": "camera", "ward_id": w, "site_type": "school",
             "site_label": f"Primary school demonstration plot, {tag} (fictional)"},
            {"uid": f"SOIL-{tag}-01", "kind": "soil", "ward_id": w, "site_type": "school",
             "site_label": f"Primary school demonstration plot, {tag} (fictional)",
             "dev_eui": f"70B3D57ED00000{i * 2 + 1:02X}" if i % 2 == 0 else None},
            {"uid": f"RAIN-{tag}-01", "kind": "rain", "ward_id": w, "site_type": "sacco_office",
             "site_label": f"SACCO office compound, {tag} (fictional)",
             "dev_eui": f"70B3D57ED00000{i * 2 + 2:02X}" if i % 2 == 1 else None},
        ]
    return out


def register_fleet(factory, wards) -> tuple[list[SimDevice], str]:
    """Register the fleet and a LoRaWAN integration directly in the database (in-process mode)."""
    from agroshield_platform.db import transaction
    from agroshield_platform.devices import registry
    devices = []
    with transaction(factory) as s:
        for spec in fleet_specs(tuple(w for w in ("ward-a", "ward-b") if w in wards)):
            d, key = registry.register(s, **spec, actor="simulator", wards=wards)
            devices.append(_sim(spec["uid"], spec["kind"], key, spec["ward_id"], spec.get("dev_eui")))
        _, ikey = registry.add_integration(s, "simulated network server", "simulator")
    return devices, ikey


def _sim(uid, kind, key, ward, dev_eui=None) -> SimDevice:
    start = {"camera": 3.65 if ward == "ward-b" else 4.05, "soil": 3.6, "rain": 3.6}[kind]
    drain = {"camera": 0.04, "soil": 0.004, "rain": 0.003}[kind]
    return SimDevice(uid, kind, key, ward, dev_eui, battery_v=start, drain_per_day=drain)


# ---------------------------------------------------------------------------------------------------- the weather
def rain_by_hour(rng: random.Random, hours: list[datetime]) -> dict[datetime, float]:
    """Afternoon storms on about a third of days, 5 to 40 mm, spread over two to four hours."""
    out = {h: 0.0 for h in hours}
    for day in sorted({h.astimezone(NAIROBI).date() for h in hours}):
        if rng.random() < 0.35:
            total = min(40.0, rng.gammavariate(2.0, 6.0) + 3.0)
            start = rng.randint(14, 18)
            n = rng.randint(2, 4)
            for k in range(n):
                at = datetime(day.year, day.month, day.day, min(start + k, 23), tzinfo=NAIROBI).astimezone(timezone.utc)
                if at in out:
                    out[at] += total / n
    return out


def step_soil(vwc: list[float], rain_mm: float, hour_local: int) -> list[float]:
    top, mid, deep = vwc
    top = min(42.0, top + rain_mm * 0.45)
    if 9 <= hour_local <= 17:
        top -= 0.12                                   # daytime drying
    top -= 0.02
    mid += (top - mid) * 0.02
    deep += (mid - deep) * 0.006
    return [max(9.0, top), max(10.0, mid), max(12.0, deep)]


def field_photo(rng: np.random.Generator, canopy: float, w: int = 320, h: int = 240) -> bytes:
    """A synthetic crop photo: brown soil, green plants covering `canopy` of the ground, a strip of sky."""
    img = np.empty((h, w, 3), dtype=np.float64)
    img[:] = (122, 92, 64)
    img += rng.normal(0, 10, img.shape)
    blobs = rng.random((h // 12 + 1, w // 12 + 1))
    mask = np.kron(blobs, np.ones((12, 12)))[:h, :w] > (1 - canopy)
    leaf = np.array((58, 138, 52)) + rng.normal(0, 12, (h, w, 3))
    img[mask] = leaf[mask]
    img[: h // 6] = (172, 200, 228)
    buf = io.BytesIO()
    Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)).save(buf, "JPEG", quality=85)
    return buf.getvalue()


# ---------------------------------------------------------------------------------------------------- sending
class Sender:
    def __init__(self, client, integration_key: str | None, clock=None):
        self.client, self.integration_key, self.clock = client, integration_key, clock
        self.results: Counter = Counter()
        self.per_device: dict[str, Counter] = {}
        self.requests = 0

    def _count(self, uid: str, status: str):
        self.results[status] += 1
        self.per_device.setdefault(uid, Counter())[status] += 1

    def json(self, d: SimDevice, messages: list[dict]) -> list[dict]:
        r = self.client.post("/api/devices/v1/readings", json={"messages": messages},
                             headers={"X-Device-Id": d.uid, "X-Device-Key": d.key})
        self.requests += 1
        if r.status_code != 200:
            raise RuntimeError(f"{d.uid}: readings refused ({r.status_code}): {r.text[:200]}")
        out = r.json()["results"]
        for x in out:
            self._count(d.uid, x["status"])
        return out

    def photo(self, d: SimDevice, data: bytes, msg_id: str, at: datetime, battery_mv: int) -> dict:
        r = self.client.post("/api/devices/v1/images", content=data, headers={
            "X-Device-Id": d.uid, "X-Device-Key": d.key, "X-Msg-Id": msg_id, "Content-Type": "image/jpeg",
            "X-Observed-At": str(int(at.timestamp())), "X-Battery-mV": str(battery_mv)})
        self.requests += 1
        out = r.json()
        self._count(d.uid, out.get("status", f"http {r.status_code}"))
        return out

    def lorawan(self, d: SimDevice, port: int, payload: bytes, sent_at: datetime, fcnt: int) -> dict:
        body = {"end_device_ids": {"device_id": d.uid.lower(), "dev_eui": d.dev_eui},
                "received_at": sent_at.isoformat().replace("+00:00", "Z"),
                "uplink_message": {"f_port": port, "f_cnt": fcnt, "frm_payload": base64.b64encode(payload).decode(),
                                   "rx_metadata": [{"gateway_ids": {"gateway_id": "sim-gateway"}, "rssi": -97, "snr": 6.5}]}}
        r = self.client.post("/api/devices/v1/lorawan/uplink", json=body,
                             headers={"X-Integration-Key": self.integration_key or ""})
        self.requests += 1
        out = r.json()
        self._count(d.uid, out.get("status", f"http {r.status_code}"))
        return out


def run(client, devices: list[SimDevice], *, days: int = 10, end: datetime | None = None, seed: int = 7,
        integration_key: str | None = None, set_clock=None, outage_days: tuple[int, int] = (4, 2)) -> dict:
    """Play `days` of field life ending at `end` (default: now) through `client` (TestClient or httpx.Client).
    set_clock(datetime | None), when given, sets the server's device clock to the simulated time."""
    from agroshield_platform.devices import lorawan as lw
    if days > 60:
        raise ValueError("at most 60 days (the server accepts readings up to 90 days old)")
    end = (end or datetime.now(timezone.utc)).replace(minute=0, second=0, microsecond=0)
    hours = [end - timedelta(hours=k) for k in range(days * 24, 0, -1)]
    nrng = np.random.default_rng(seed)
    wards = sorted({d.ward for d in devices})
    rain_in = {w: rain_by_hour(random.Random(f"{seed}-{w}"), hours) for w in wards}   # each ward its own storms
    off_from = end - timedelta(days=outage_days[0])
    off_to = off_from + timedelta(days=outage_days[1])
    offline = {d.uid for d in devices if d.ward == "ward-a" and d.kind in ("camera", "soil")}
    send = Sender(client, integration_key)
    caught_up: dict[str, int] = {}
    fault_sent = False
    fcnt = Counter()

    def deliver(d: SimDevice, item, now: datetime):
        kind, payload, at = item
        if kind == "json":
            return send.json(d, [payload])[0]
        if kind == "photo":
            data, msg_id, mv = payload
            return send.photo(d, data, msg_id, at, mv)
        port, raw = payload
        fcnt[d.uid] += 1
        age = int((now - at).total_seconds() // 60)
        raw = raw[:3] + age.to_bytes(2, "big") + raw[5:]       # the node sets the age when it sends
        return send.lorawan(d, port, raw, now, fcnt[d.uid])

    for h in hours:
        local = h.astimezone(NAIROBI)
        now = h + timedelta(minutes=2)                        # sent two minutes after the hour
        if set_clock:
            set_clock(now)
        day_frac = (h - hours[0]).total_seconds() / (days * 86400)
        for d in devices:
            d.battery_v = max(3.0, d.battery_v - d.drain_per_day / 24)
            if d.kind == "camera" and d.ward == "ward-a" and local.hour == 12:
                d.battery_v = min(4.15, d.battery_v + 0.03)   # the ward-a camera has a small solar panel
            items = []
            mv = int(d.battery_v * 1000)
            if d.kind == "soil":
                d.vwc = step_soil(d.vwc, rain_in[d.ward][h], local.hour)
                temp = 18 + 5 * math.sin((local.hour - 9) / 24 * 2 * math.pi)
                d.seq += 1
                vals = [round(v, 1) for v in d.vwc]
                if d.ward == "ward-b" and not fault_sent and h >= hours[len(hours) // 2]:
                    vals[0], fault_sent = 150.0, True         # a faulty sensor: must be refused
                if d.dev_eui and integration_key:
                    items.append(("lorawan", (lw.SOIL_PORT, lw.encode_soil(d.seq, 0, mv, list(zip(DEPTHS, vals)),
                                                                             round(temp, 2))), h))
                else:
                    readings = {f"soil_vwc_{dp}cm": v for dp, v in zip(DEPTHS, vals)}
                    items.append(("json", {"msg_id": f"{d.uid}-{int(h.timestamp())}", "observed_at": h.isoformat(),
                                           "readings": {**readings, "soil_temp_c": round(temp, 2),
                                                        "battery_v": round(d.battery_v, 3)}}, h))
            elif d.kind == "rain":
                tips = int(round(rain_in[d.ward][h] / MM_PER_TIP))
                d.seq += 1
                if d.dev_eui and integration_key:
                    items.append(("lorawan", (lw.RAIN_PORT, lw.encode_rain(d.seq, 0, mv, tips, 60, 21.5)), h))
                else:
                    items.append(("json", {"msg_id": f"{d.uid}-{int(h.timestamp())}", "observed_at": h.isoformat(),
                                           "readings": {"rain_tips": tips, "interval_min": 60,
                                                        "battery_v": round(d.battery_v, 3)}}, h))
            elif local.hour in PHOTO_HOURS:
                canopy = 0.15 + 0.45 * day_frac
                msg_id = f"{d.uid}-{int(h.timestamp())}-{d.seq}"
                d.seq += 1
                items.append(("photo", (field_photo(nrng, canopy), msg_id, mv), h))
            in_outage = d.uid in offline and off_from <= h < off_to
            if in_outage:
                d.queue.extend(items)
                continue
            if d.queue:                                       # signal is back: send what was stored, oldest first
                backlog, d.queue = d.queue, []
                caught_up[d.uid] = len(backlog)
                first = backlog[0]
                for item in backlog:
                    deliver(d, item, now)
                deliver(d, first, now)                        # the reply to the first one was "lost": sent again
                if d.kind == "camera":                        # the heartbeat after an outage reports it
                    send.json(d, [{"msg_id": f"{d.uid}-hb-{int(h.timestamp())}-catchup", "observed_at": h.isoformat(),
                                   "readings": {"battery_v": round(d.battery_v, 3), "queue_depth": 0},
                                   "errors": [f"{len(backlog)} photos sent late after an outage"]}])
            for item in items:
                deliver(d, item, now)
            if d.kind == "camera" and items:                   # heartbeat at each photo wake
                send.json(d, [{"msg_id": f"{d.uid}-hb-{int(h.timestamp())}", "observed_at": h.isoformat(),
                               "firmware": "cam-0.1.0", "readings": {"battery_v": round(d.battery_v, 3),
                                                                     "signal_dbm": -85, "queue_depth": 0}}])
    if set_clock:
        set_clock(None)
    return {"days": days, "end": end.isoformat(), "requests": send.requests, "results": dict(send.results),
            "per_device": {k: dict(v) for k, v in send.per_device.items()}, "caught_up": caught_up,
            "outage": {"devices": sorted(offline), "from": off_from.isoformat(), "to": off_to.isoformat()},
            "rain_mm_total": {w: round(sum(r.values()), 1) for w, r in rain_in.items()}}


# ---------------------------------------------------------------------------------------------------- command line
def fast_scratch_db(factory) -> None:
    """A throwaway SQLite file needs no crash safety: keep the journal in memory and skip fsync. Each of the
    simulator's thousand requests is its own transaction, and on Windows the journal file costs most of the time.
    Only for the simulator's (and tests') scratch database, never the portal's."""
    from sqlalchemy import event
    engine = factory.kw["bind"]

    @event.listens_for(engine, "connect")
    def _fast(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA journal_mode=MEMORY")
        dbapi_conn.execute("PRAGMA synchronous=OFF")
    engine.dispose()


def in_process(days: int, seed: int) -> dict:
    import base64 as b64
    import secrets
    import tempfile

    from fastapi.testclient import TestClient

    from agroshield_platform.settings import REPO, Settings
    from agroshield_platform.web.app import create_app
    from agroshield_pricing.config import load_config

    tmp = Path(tempfile.mkdtemp(prefix="agroshield-sim-"))
    settings = Settings(database_url=f"sqlite:///{(tmp / 'sim.db').as_posix()}", encryption_key=secrets.token_bytes(32),
                        lookup_key=secrets.token_bytes(32), session_secret=b64.b64encode(secrets.token_bytes(32)).decode(),
                        config_dir=REPO / "config", dev_keys=True)
    app = create_app(settings)
    fast_scratch_db(app.state.factory)
    cfg = load_config(settings.config_dir)
    devices, ikey = register_fleet(app.state.factory, cfg.wards)
    with TestClient(app) as client:          # one event loop for every request (much faster than one each)
        report = run(client, devices, days=days, seed=seed, integration_key=ikey,
                     set_clock=lambda t: setattr(app.state, "device_clock", (lambda: t) if t else None))
    report["database"] = str(tmp / "sim.db")
    return report


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--in-process", action="store_true")
    p.add_argument("--base-url")
    p.add_argument("--keys", help="JSON list of {uid, kind, key, ward, dev_eui?}")
    p.add_argument("--integration-key")
    p.add_argument("--days", type=int, default=10)
    p.add_argument("--seed", type=int, default=7)
    a = p.parse_args(argv)
    if a.in_process:
        report = in_process(a.days, a.seed)
    elif a.base_url and a.keys:
        import httpx
        keys = json.loads(Path(a.keys).read_text(encoding="utf-8"))
        devices = [_sim(k["uid"], k["kind"], k["key"], k.get("ward", "ward-a"), k.get("dev_eui")) for k in keys]
        with httpx.Client(base_url=a.base_url, timeout=30) as client:
            report = run(client, devices, days=a.days, seed=a.seed, integration_key=a.integration_key)
    else:
        p.error("give --in-process, or --base-url with --keys")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
