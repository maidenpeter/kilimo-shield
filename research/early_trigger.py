"""Research 3b(d): EXPERIMENTAL early-season trigger for the long rains.

About CHECK_DAY days after the start of season, project the end-of-season WRSI
from:
  * observed CHIRPS rain from the start of season up to the check day,
  * the CHIRPS-GEFS 15-day forecast issued on the check day (spread evenly), and
  * leave-one-out daily climatology for the rest of the growing period,
then run the same water balance as Layer B. If the projection is below the WRSI
trigger, a smaller early payout is made (priced separately, not in the product).
A "no forecast" variant (climatology from the check day) shows what GEFS adds.

CHIRPS-GEFS: 15-day mean forecast, Africa 0.05 deg, uncompressed float32 GeoTIFF
(1500 x 1600, origin 20W 40N, one row per strip). Only the 3 x 3 pixels around a
ward are read, with an HTTP range request, and cached in data/raw/research/.
"""
from __future__ import annotations

import json
import struct
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from agroshield_pricing.config import load_config  # noqa: E402
from agroshield_pricing.engine import price_ward  # noqa: E402
from agroshield_pricing.pet import make_pet_source  # noqa: E402
from agroshield_pricing.rainfall import make_source  # noqa: E402
from agroshield_pricing.wrsi import (dekad_number, kc_by_dekad, to_dekads, water_balance,  # noqa: E402
                                     wrsi_from)

GEFS_URL = "https://data.chc.ucsb.edu/products/EWX/data/forecasts/CHIRPS-GEFS_precip_v12/15day/Africa/precip_mean/data.{y}.{doy:03d}.tif"
UA = "AgroShield-research/0.1 (contact: mrnwanngari@gmail.com)"
CHECK_DAY = 35            # days after the start of season
EARLY_PAYOUT = 0.20       # share of sum insured, EXPERIMENTAL placeholder
WIDTH, ORIGIN_LON, ORIGIN_LAT, RES = 1500, -20.0, 40.0, 0.05
CACHE = REPO / "data" / "raw" / "research" / "chirps_gefs_15day.json"


def paths(dataset: str | None) -> tuple[Path, Path]:
    """(GEFS cache, results file) for a rainfall dataset. CHIRPS v2 keeps the original
    names; any other dataset gets its own files, because its start-of-season dates
    (and so the forecast issue dates) differ."""
    out = REPO / "data" / "raw" / "research"
    if dataset in (None, "chirps"):
        return CACHE, out / "early_trigger_results.json"
    return out / f"chirps_gefs_15day.{dataset}.json", out / f"early_trigger_results.{dataset}.json"


def _range(url: str, start: int, end: int) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Range": f"bytes={start}-{end}"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404 or attempt == 3:
                raise                       # not published: no point asking again
            # The CHC server rate-limits (HTTP 429): back off for longer than for other errors.
            time.sleep((30 if e.code == 429 else 5) * (attempt + 1))
            continue
        except Exception:
            if attempt == 3:
                raise
            time.sleep(5 * (attempt + 1))


def _packbits(data: bytes) -> bytes:
    """TIFF PackBits (compression 32773) decoder."""
    out, i = bytearray(), 0
    while i < len(data):
        n = data[i] if data[i] < 128 else data[i] - 256
        i += 1
        if n >= 0:
            out += data[i:i + n + 1]
            i += n + 1
        elif n != -128:
            out += bytes([data[i]]) * (1 - n)
            i += 1
    return bytes(out)


def _tiff_rows(url: str, rows: list[int]) -> dict[int, np.ndarray]:
    """Read whole rows of a strip-per-row float32 GeoTIFF with range requests.

    The layout changed over the archive (uncompressed up to 2022, PackBits from
    2023), so each file's own directory and strip table are read every time.
    """
    off = struct.unpack("<I", _range(url, 0, 7)[4:8])[0]
    ifd = _range(url, off, off + 2 + 12 * 40)
    tags = {}
    for i in range(struct.unpack("<H", ifd[:2])[0]):
        tag, typ, cnt = struct.unpack("<HHI", ifd[2 + 12 * i:10 + 12 * i])
        raw = ifd[10 + 12 * i:14 + 12 * i]
        tags[tag] = (typ, cnt, struct.unpack("<H", raw[:2])[0] if typ == 3 and cnt == 1 else struct.unpack("<I", raw)[0])
    width, comp = tags[256][2], tags[259][2]
    if tags[278][2] != 1 or tags[258][2] != 32 or tags[339][2] != 3 or comp not in (1, 32773):
        raise ValueError(f"unsupported TIFF layout in {url}: {tags}")
    so, sc = tags[273][2], tags[279][2]
    out = {}
    for r in rows:
        o = struct.unpack("<I", _range(url, so + 4 * r, so + 4 * r + 3))[0]
        c = struct.unpack("<I", _range(url, sc + 4 * r, sc + 4 * r + 3))[0]
        data = _range(url, o, o + c - 1)
        if comp == 32773:
            data = _packbits(data)
        out[r] = np.frombuffer(data[:width * 4], dtype="<f4")
    return out


def gefs_15day_mm(lat: float, lon: float, issue: pd.Timestamp) -> tuple[float | None, str]:
    """Mean 15-day forecast total (mm) over the 3x3 pixels around a point."""
    url = GEFS_URL.format(y=issue.year, doy=issue.dayofyear)
    row = int((ORIGIN_LAT - lat) / RES)
    col = int((lon - ORIGIN_LON) / RES)
    try:
        rows = _tiff_rows(url, [row - 1, row, row + 1])
    except Exception as e:
        return None, f"{url} [{type(e).__name__}: {e}]"[:300]
    vals = [float(v) for r in rows.values() for v in r[col - 1:col + 2] if 0 <= v < 2000]   # nodata -9999
    return (float(np.mean(vals)) if len(vals) >= 5 else None), url


def fetch_gefs(cfg, tables: dict, cache_path: Path = CACHE) -> dict:
    if cache_path.exists():
        cache = json.loads(cache_path.read_text())
    else:   # start from the CHIRPS v2 cache: entries whose issue date matches are reused
        cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    for wid, table in tables.items():
        c = cfg.ward(wid).centroid
        for y, r in table.iterrows():
            if r["sos_date"] is None or y < 2000:
                continue
            issue = pd.Timestamp(r["sos_date"]) + pd.Timedelta(days=CHECK_DAY)
            key = f"{wid}:{y}"
            if key in cache and cache[key]["issue"] == str(issue.date()) and not _retry(cache[key]):
                continue
            mm, url = gefs_15day_mm(c.lat, c.lon, issue)
            cache[key] = {"ward_id": wid, "year": int(y), "issue": str(issue.date()), "gefs_15day_mm": mm, "url": url}
            print(f"  {wid} {y}: issued {issue.date()} -> {mm}")
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(cache, indent=1) + "\n", encoding="utf-8", newline="\n")
            time.sleep(2.0)                 # one request at a time, with pauses
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(cache, indent=1) + "\n", encoding="utf-8", newline="\n")
    if cache_path != CACHE:
        _write_meta(cache_path)
    return cache


def _retry(entry: dict) -> bool:
    """A cached failure is asked for again unless the file was simply not published (HTTP 404)."""
    return entry.get("gefs_15day_mm") is None and "404" not in str(entry.get("url"))


def _write_meta(cache_path: Path) -> None:
    """<cache>.meta.json beside a per-dataset GEFS cache: request, retrieved_at and SHA-256."""
    import hashlib

    meta = cache_path.with_name(cache_path.name + ".meta.json")
    sha = hashlib.sha256(cache_path.read_bytes()).hexdigest()
    if meta.exists() and json.loads(meta.read_text()).get("sha256") == sha:
        return
    meta.write_text(json.dumps({
        "url_pattern": GEFS_URL,
        "request": "HTTP range requests for the 3 x 3 pixels around each ward centroid, one file per check day",
        "seeded_from": CACHE.relative_to(REPO).as_posix(),
        "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sha256": sha,
        "bytes": cache_path.stat().st_size,
    }, indent=2) + "\n", encoding="utf-8", newline="\n")


def projected_wrsi(cfg, ward, cal, rain: pd.Series, pet_dk: pd.Series, sos_date: str, gefs_mm: float | None) -> float:
    lb = cfg.product.layer_b
    sos = pd.Timestamp(sos_date)
    n = cal.lgp_dekads
    check = sos + pd.Timedelta(days=CHECK_DAY)
    end = sos + pd.Timedelta(days=n * 10 + 40)
    days = pd.date_range(sos - pd.Timedelta(days=lb.spinup_dekads * 10 + 10), end)
    other = rain[rain.index.year != sos.year]
    clim = other.groupby(other.index.dayofyear).mean()
    proj = pd.Series([rain.get(d, 0.0) if d < check else clim.get(d.dayofyear, 0.0) for d in days], index=days)
    if gefs_mm is not None:
        fc = pd.date_range(check, check + pd.Timedelta(days=14))
        proj.loc[fc] = gefs_mm / 15
    dk = to_dekads(proj)
    t = dekad_number(sos)
    crop, spin = list(range(t, t + n)), list(range(t - lb.spinup_dekads, t))
    kc = kc_by_dekad(n, lb.kc.points_pct, lb.kc.values)
    tr = water_balance(dk.reindex(crop).fillna(0).to_numpy(), pet_dk.reindex(crop).to_numpy(), kc, ward.soil_whc_mm,
                       lb.depletion_fraction, dk.reindex(spin).fillna(0).to_numpy(), pet_dk.reindex(spin).to_numpy())
    return wrsi_from(tr)


def run(dataset: str | None = None) -> dict:
    cfg = load_config(REPO / "config")
    rs, ps = make_source(cfg, dataset, allow_download=False), make_pet_source(cfg, allow_download=False)
    results, tables, data = {}, {}, {}
    for wid in cfg.pilot.wards:
        r = price_ward(cfg, wid, rs, ps)
        tables[wid] = r.seasons["LR"].table
        data[wid] = (r.rain_daily, to_dekads(r.pet_daily))
    cache = fetch_gefs(cfg, tables, paths(dataset)[0])
    trig = cfg.product.layer_b.trigger_wrsi
    for wid, table in tables.items():
        ward, cal = cfg.ward(wid), cfg.calendar(wid, "LR")
        rain, pet_dk = data[wid]
        rows = []
        for y, r in table.iterrows():
            if r["sos_date"] is None or y < 2000:
                continue
            g = cache.get(f"{wid}:{y}", {}).get("gefs_15day_mm")
            if g is None:
                continue
            with_fc = projected_wrsi(cfg, ward, cal, rain, pet_dk, r["sos_date"], g)
            no_fc = projected_wrsi(cfg, ward, cal, rain, pet_dk, r["sos_date"], None)
            rows.append({"year": int(y), "sos": r["sos"], "gefs_15day_mm": round(g, 1),
                         "projected_wrsi": with_fc, "projected_wrsi_no_forecast": no_fc, "actual_wrsi": float(r["wrsi"]),
                         "early_trigger": with_fc < trig, "early_trigger_no_forecast": no_fc < trig,
                         "actual_below_trigger": float(r["wrsi"]) < trig})
        df = pd.DataFrame(rows)
        if df.empty:
            results[wid] = {"available": False, "reason": "no CHIRPS-GEFS values retrieved"}
            continue

        def verify(col):
            t, a = df[col].to_numpy(), df["actual_below_trigger"].to_numpy()
            return {"triggers": int(t.sum()), "frequency": float(t.mean()),
                    "hit_rate": float((t & a).sum() / a.sum()) if a.sum() else None,
                    "false_alarm_ratio": float((t & ~a).sum() / t.sum()) if t.sum() else None}

        si = cfg.product.sum_insured.default_kes_per_acre
        freq = float(df["early_trigger"].mean())
        prem = cfg.product.premium
        rm = prem.risk_margin.factor * np.sqrt(freq * (1 - freq)) if prem.risk_margin.method == "std_dev" else 0.0
        gross = (freq + rm) / (1 - sum(prem.loadings.values())) * EARLY_PAYOUT
        results[wid] = {
            "available": True, "seasons": int(len(df)), "years": [int(df["year"].min()), int(df["year"].max())],
            "actual_below_trigger_seasons": int(df["actual_below_trigger"].sum()),
            "corr_projected_vs_actual": float(np.corrcoef(df["projected_wrsi"], df["actual_wrsi"])[0, 1]),
            "corr_no_forecast_vs_actual": float(np.corrcoef(df["projected_wrsi_no_forecast"], df["actual_wrsi"])[0, 1]),
            "with_gefs": verify("early_trigger"), "no_forecast": verify("early_trigger_no_forecast"),
            "early_payout_share": EARLY_PAYOUT,
            "expected_cost_kes_per_acre": round(freq * EARLY_PAYOUT * si, 2),
            "gross_kes_per_acre": round(gross * si, 2),
            "history": df.to_dict(orient="records"),
        }
    out = {"check_day": CHECK_DAY, "trigger_wrsi": trig, "wards": results}
    if dataset not in (None, "chirps"):
        out["rainfall_dataset"] = dataset
    return out


if __name__ == "__main__":
    # Optional argument: rainfall dataset (chirps = v2.0, the default; chirps3 = v3.0).
    ds = sys.argv[1] if len(sys.argv) > 1 else None
    out = run(ds)
    p = paths(ds)[1]
    p.write_text(json.dumps(out, indent=1, default=str) + "\n", encoding="utf-8", newline="\n")
    for wid, r in out["wards"].items():
        print(wid, {k: v for k, v in r.items() if k != "history"})
