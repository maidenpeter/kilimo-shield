"""Hardware layer routes (milestone 9): device ingestion API and the underwriter's device pages.

Device API (no session; each device signs in with its own key in a header, never in the URL)
  POST /api/devices/v1/readings         JSON {"messages": [...]}       headers X-Device-Id, X-Device-Key
  POST /api/devices/v1/images           a JPEG body                    headers X-Device-Id, X-Device-Key, X-Msg-Id,
                                                                       X-Observed-At, X-Battery-mV (optional)
  POST /api/devices/v1/lorawan/uplink   a network server uplink        header X-Integration-Key
Underwriter pages (role underwriter)
  /uw/devices, /uw/devices/{uid}, /uw/devices/{uid}/photos/{id}.jpg

Underwriters see every device in the pilot wards (shared platform equipment, no personal data and nothing about
another insurer's book); wards where their insurer has cover are listed first. Device data never decides a payout.
"""
from __future__ import annotations

import json
import os
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from starlette.concurrency import run_in_threadpool

from .. import underwriting as uw
from ..db import transaction
from ..devices import ingest, lorawan, rain, registry
from ..devices.registry import _utc
from ..models import Device, DeviceImage, DeviceIssue, DeviceMessage, DeviceReading
from ..settings import REPO

MAX_JSON = 512 * 1024
NAIROBI = rain.NAIROBI
UID_RE = registry.UID_RE
WINDOW_DAYS = 30


def image_store(settings) -> Path:
    """Where camera photos are kept: AGROSHIELD_DEVICE_STORE, else next to a SQLite database, else var/."""
    if os.environ.get("AGROSHIELD_DEVICE_STORE"):
        return Path(os.environ["AGROSHIELD_DEVICE_STORE"])
    url = make_url(settings.database_url)
    if url.get_backend_name() == "sqlite" and url.database and url.database != ":memory:":
        return Path(url.database).parent / "device_images"
    return REPO / "var" / "device_images"


async def _read(request: Request, limit: int) -> bytes:
    cl = request.headers.get("content-length", "")
    if cl.isdigit() and int(cl) > limit:
        raise HTTPException(413, "Too large.")
    buf = bytearray()
    async for chunk in request.stream():
        buf += chunk
        if len(buf) > limit:
            raise HTTPException(413, "Too large.")
    return bytes(buf)


def _json(raw: bytes):
    try:
        return json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(400, "The body is not JSON.") from None


UNAUTHORISED = {"error": "unknown device or wrong key"}


def register(app: FastAPI, *, factory, render, require, cfg, settings) -> None:
    store = image_store(settings)
    chirps = rain.ChirpsFiles(Path(cfg.root).parent / "data" / "raw" / "chirps")
    app.state.device_clock = None          # the simulator (tools/devices/simulate.py) sets its simulated time here

    def clock() -> datetime:
        return app.state.device_clock() if app.state.device_clock else ingest.now_utc()

    # ------------------------------------------------------------------ device API
    @app.post("/api/devices/v1/readings")
    async def api_readings(request: Request):
        body = _json(await _read(request, MAX_JSON))
        uid, key = request.headers.get("x-device-id"), request.headers.get("x-device-key")

        def work():
            now = clock()
            with transaction(factory) as s:
                dev = registry.authenticate(s, uid, key, now)
                if dev is None:
                    return JSONResponse(UNAUTHORISED, status_code=401)
                try:
                    results = ingest.ingest_batch(s, dev, body, "https", now)
                except ingest.BadRequest as e:
                    return JSONResponse({"error": str(e)}, status_code=400)
                return JSONResponse({"results": [r.as_dict() for r in results]})
        return await run_in_threadpool(work)

    @app.post("/api/devices/v1/images")
    async def api_images(request: Request):
        data = await _read(request, ingest.MAX_PHOTO_BYTES)
        h = request.headers

        def work():
            now = clock()
            with transaction(factory) as s:
                dev = registry.authenticate(s, h.get("x-device-id"), h.get("x-device-key"), now)
                if dev is None:
                    return JSONResponse(UNAUTHORISED, status_code=401)
                r, img = ingest.store_photo(s, dev, data, h.get("x-msg-id"), h.get("x-observed-at"), store,
                                            battery_mv=h.get("x-battery-mv"), signal_dbm=h.get("x-signal-dbm"), now=now)
                out = r.as_dict()
                if img is not None:
                    out["greenness_gcc"] = img.gcc
                return JSONResponse(out, status_code={"accepted": 200, "duplicate": 200, "conflict": 409}.get(r.status, 422))
        return await run_in_threadpool(work)

    @app.post("/api/devices/v1/lorawan/uplink")
    async def api_lorawan(request: Request):
        body = _json(await _read(request, MAX_JSON))
        key = request.headers.get("x-integration-key")

        def work():
            with transaction(factory) as s:
                if registry.authenticate_integration(s, key) is None:
                    return JSONResponse({"error": "unknown integration key"}, status_code=401)
                status, out = lorawan.handle_uplink(s, body, clock())
                return JSONResponse(out, status_code=status)
        return await run_in_threadpool(work)

    # ------------------------------------------------------------------ underwriter pages
    def visible(s, off) -> tuple[list[Device], set[str]]:
        covered = {p.ward_id for p in uw.policies(s, off.insurer_id)}
        devs = list(s.scalars(select(Device).where(Device.ward_id.in_(list(cfg.pilot.wards)))
                              .order_by(Device.ward_id, Device.kind, Device.uid)))
        return devs, covered

    def device_or_404(s, off, uid: str) -> Device:
        if not UID_RE.fullmatch(uid):
            raise HTTPException(404)
        devs, _ = visible(s, off)
        d = next((x for x in devs if x.uid == uid), None)
        if d is None:
            raise HTTPException(404)
        return d

    def latest(s, d: Device, prefix: str) -> dict[str, tuple[float, datetime]]:
        rows = s.execute(select(DeviceReading.metric, DeviceReading.value, DeviceReading.observed_at)
                         .where(DeviceReading.device_id == d.id, DeviceReading.metric.like(f"{prefix}%"))
                         .order_by(DeviceReading.observed_at.desc()).limit(12))
        out: dict[str, tuple[float, datetime]] = {}
        for m, v, at in rows:
            out.setdefault(m, (v, _utc(at)))
        return out

    def rain_since(s, d: Device, since: datetime) -> float:
        return round(s.scalar(select(func.coalesce(func.sum(DeviceReading.value), 0.0)).where(
            DeviceReading.device_id == d.id, DeviceReading.metric == "rain_mm", DeviceReading.observed_at >= since)) or 0.0, 1)

    def summary(s, d: Device, now: datetime) -> dict:
        if d.kind == "soil":
            vals = latest(s, d, "soil_vwc_")
            depths = sorted(vals, key=lambda m: int(re.sub(r"\D", "", m)))
            return {"soil": [(int(re.sub(r"\D", "", m)), vals[m][0]) for m in depths],
                    "at": max((v[1] for v in vals.values()), default=None)}
        if d.kind == "rain":
            return {"rain_24h": rain_since(s, d, now - timedelta(hours=24)), "rain_7d": rain_since(s, d, now - timedelta(days=7))}
        img = s.scalar(select(DeviceImage).where(DeviceImage.device_id == d.id).order_by(DeviceImage.observed_at.desc()).limit(1))
        n7 = s.scalar(select(func.count()).select_from(DeviceImage).where(DeviceImage.device_id == d.id,
                                                                            DeviceImage.observed_at >= now - timedelta(days=7)))
        return {"gcc": img.gcc if img else None, "at": _utc(img.observed_at) if img else None, "photos_7d": n7}

    @app.get("/uw/devices", response_class=HTMLResponse)
    def uw_devices(request: Request):
        with transaction(factory) as s:
            off = require(request, s, role="underwriter")
            now = ingest.now_utc()
            devs, covered = visible(s, off)
            issues = ingest.issues_since(s, [d.id for d in devs], now - timedelta(days=7))
            rows = [{"d": d, "h": ingest.health(d, now), "sum": summary(s, d, now), "issues_7d": issues.get(d.id, 0)}
                    for d in devs]
            wards = sorted({d.ward_id for d in devs} | set(cfg.pilot.wards), key=lambda w: (w not in covered, w))
            groups = [{"ward_id": w, "covered": w in covered, "rows": [r for r in rows if r["d"].ward_id == w]} for w in wards]
            totals = {"all": len(rows), "ok": sum(r["h"]["state"] == "ok" for r in rows),
                      "attention": sum(r["h"]["state"] in ("late", "offline", "never") for r in rows),
                      "low_battery": sum(r["h"]["battery_low"] for r in rows)}
            return render(request, "uw_devices.html", off, groups=groups, totals=totals, kinds=registry.KINDS,
                          sites=registry.SITE_TYPES, now=now)

    @app.get("/uw/devices/{uid}", response_class=HTMLResponse)
    def uw_device(request: Request, uid: str):
        with transaction(factory) as s:
            off = require(request, s, role="underwriter")
            d = device_or_404(s, off, uid)
            now = ingest.now_utc()
            today = now.astimezone(NAIROBI).date()
            start = today - timedelta(days=WINDOW_DAYS - 1)
            days = [today - timedelta(days=i) for i in range(WINDOW_DAYS)]
            view = {"d": d, "h": ingest.health(d, now), "kinds": registry.KINDS, "sites": registry.SITE_TYPES,
                    "days": days, "now": now}
            if d.kind == "rain":
                gauge = rain.daily_totals(s, d, start, today)
                reported = rain.reporting_days(s, d, start, today)
                view.update(gauge=gauge, reported=reported, sat=chirps.daily(d.ward_id, start, today),
                            chirps_last=chirps.last_day(d.ward_id), chirps_ok=chirps.available(d.ward_id),
                            flags=rain.check_against_chirps(d.ward_id, gauge, reported, chirps, start, today),
                            chart=bars([(x, gauge.get(x)) for x in reversed(days)]))
            else:
                series = daily_means(s, d, start, today)
                view["series"] = series
                if d.kind == "soil":
                    view["depths"] = sorted({int(re.sub(r"\D", "", m)) for m in series if m.startswith("soil_vwc_")})
                    cols = [series.get(f"soil_vwc_{dp}cm", {}) for dp in view["depths"]]
                    view["soil_rows"] = [(x, [c.get(x) for c in cols], series.get("soil_temp_c", {}).get(x))
                                         for x in days if any(x in c for c in cols)]
                    top = f"soil_vwc_{view['depths'][0]}cm" if view["depths"] else None
                    view["chart"] = line([(x, series.get(top, {}).get(x)) for x in reversed(days)]) if top else None
                else:
                    view["chart"] = line([(x, series.get("greenness_gcc", {}).get(x)) for x in reversed(days)])
                    view["photos"] = list(s.scalars(select(DeviceImage).where(DeviceImage.device_id == d.id)
                                                    .order_by(DeviceImage.observed_at.desc()).limit(6)))
            view["issues"] = list(s.scalars(select(DeviceIssue).where(DeviceIssue.device_id == d.id)
                                            .order_by(DeviceIssue.at.desc()).limit(15)))
            msgs = list(s.scalars(select(DeviceMessage).where(DeviceMessage.device_id == d.id)
                                  .order_by(DeviceMessage.received_at.desc(), DeviceMessage.id.desc()).limit(15)))
            view["messages"] = [{"m": m, "late": _utc(m.received_at) - _utc(m.observed_at) > ingest.LATE_AFTER} for m in msgs]
            view["late_7d"] = ingest.late_messages(s, d, now - timedelta(days=7))
            return render(request, "uw_device.html", off, **view)

    @app.get("/uw/devices/{uid}/photos/{image_id}.jpg")
    def uw_device_photo(request: Request, uid: str, image_id: int):
        with transaction(factory) as s:
            off = require(request, s, role="underwriter")
            d = device_or_404(s, off, uid)
            img = s.get(DeviceImage, image_id)
            if img is None or img.device_id != d.id:
                raise HTTPException(404)
            f = (store / img.path).resolve()
        if not f.is_relative_to(store.resolve()) or not f.exists():
            raise HTTPException(404)
        return FileResponse(f, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})


def daily_means(s, d: Device, start: date, end: date) -> dict[str, dict[date, float]]:
    """Mean of each metric per Nairobi day (soil moisture by depth, greenness)."""
    lo = datetime.combine(start, datetime.min.time(), NAIROBI).astimezone(timezone.utc)
    hi = datetime.combine(end + timedelta(days=1), datetime.min.time(), NAIROBI).astimezone(timezone.utc)
    acc: dict[str, dict[date, list[float]]] = {}
    for m, v, at in s.execute(select(DeviceReading.metric, DeviceReading.value, DeviceReading.observed_at).where(
            DeviceReading.device_id == d.id, DeviceReading.observed_at >= lo, DeviceReading.observed_at < hi)):
        acc.setdefault(m, {}).setdefault(_utc(at).astimezone(NAIROBI).date(), []).append(v)
    return {m: {k: round(sum(v) / len(v), 3) for k, v in days.items()} for m, days in acc.items()}


def bars(points: list[tuple[date, float | None]], width: int = 600, height: int = 120) -> dict:
    top = max([v for _, v in points if v] or [1.0])
    w = width / max(len(points), 1)
    return {"width": width, "height": height, "kind": "bars", "max": top,
            "cols": [{"x": round(i * w + 1, 1), "w": round(w - 2, 1), "h": round((v or 0) / top * (height - 20), 1),
                      "y": round(height - 16 - (v or 0) / top * (height - 20), 1), "day": dd, "v": v}
                     for i, (dd, v) in enumerate(points)]}


def line(points: list[tuple[date, float | None]], width: int = 600, height: int = 120) -> dict | None:
    vals = [v for _, v in points if v is not None]
    if not vals:
        return None
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1.0
    step = width / max(len(points) - 1, 1)
    pts = [(round(i * step, 1), round(height - 16 - (v - lo) / span * (height - 26), 1), dd, v)
           for i, (dd, v) in enumerate(points) if v is not None]
    return {"width": width, "height": height, "kind": "line", "min": lo, "max": hi,
            "path": " ".join(f"{x},{y}" for x, y, _, _ in pts), "dots": pts}
