"""Real CHIRPS v2.0 daily rainfall via SERVIR ClimateSERV.

ClimateSERV averages CHIRPS (0.05 deg, daily) over a polygon server-side and
returns a small JSON time series, so a whole ward history is a few hundred KB
rather than the gigabytes of the raw global files.

Downloads are cached in data/raw/chirps/<ward>.csv with a .meta.json beside it
recording the exact request (geometry, dataset id, dates), retrieval time and a
SHA-256 of the CSV. The cache is committed, so any trigger calculation can be
re-run from identical raw inputs. If the ward geometry in config changes, the
cache no longer matches and is refused until it is re-fetched.

The request carries only a geometry and dates, never personal data.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from ..config import Ward
from ..provenance import Label, Provenance
from .base import RainfallSource, validate_series

BASE_URL = os.environ.get("CLIMATESERV_BASE_URL", "https://climateserv.servirglobal.net/api")
DATATYPE_CHIRPS = 0          # ClimateSERV dataset id for UCSB CHIRPS daily
OPERATION_AVERAGE = 5        # spatial mean over the polygon
INTERVAL_DAILY = 0
CHUNK_YEARS = 5              # years per request; keeps each server job short


def ward_geometry(ward: Ward) -> dict:
    """Square box of side extraction_box_deg centred on the ward centroid."""
    h = ward.extraction_box_deg / 2
    lat, lon = ward.centroid.lat, ward.centroid.lon
    ring = [[lon - h, lat - h], [lon + h, lat - h], [lon + h, lat + h], [lon - h, lat + h], [lon - h, lat - h]]
    return {"type": "Polygon", "coordinates": [[[round(x, 6), round(y, 6)] for x, y in ring]]}


def _get_json(url: str, params: dict, timeout: float = 120, retries: int = 4):
    full = url + "?" + urllib.parse.urlencode(params)
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(full, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(5 * (attempt + 1))


def fetch_chunk(geometry: dict, start: str, end: str, log=print) -> pd.Series:
    """Fetch one date range (MM/DD/YYYY strings) from ClimateSERV."""
    req = _get_json(f"{BASE_URL}/submitDataRequest/", {
        "datatype": DATATYPE_CHIRPS, "begintime": start, "endtime": end,
        "intervaltype": INTERVAL_DAILY, "operationtype": OPERATION_AVERAGE,
        "geometry": json.dumps(geometry), "isZip_CurrentDataType": "false",
    })
    job = req[0]
    deadline = time.time() + 900
    while True:
        progress = _get_json(f"{BASE_URL}/getDataRequestProgress/", {"id": job})[0]
        if progress == -1:
            raise RuntimeError(f"ClimateSERV job {job} failed ({start} to {end})")
        if progress >= 100:
            break
        if time.time() > deadline:
            raise TimeoutError(f"ClimateSERV job {job} did not finish ({start} to {end})")
        time.sleep(4)
    data = _get_json(f"{BASE_URL}/getDataFromRequest/", {"id": job})["data"]
    s = pd.Series(
        {pd.Timestamp(year=d["year"], month=d["month"], day=d["day"]): d["value"]["avg"] for d in data},
        dtype=float,
    )
    log(f"  {start} to {end}: {len(s)} days")
    return s


class ChirpsClimateServSource(RainfallSource):
    def __init__(self, cache_dir: str | Path, allow_download: bool = True, log=print):
        self.cache_dir = Path(cache_dir)
        self.allow_download = allow_download
        self.log = log

    def _paths(self, ward: Ward) -> tuple[Path, Path]:
        return self.cache_dir / f"{ward.id}.csv", self.cache_dir / f"{ward.id}.meta.json"

    def is_cached(self, ward: Ward, start_year: int, end_year: int) -> bool:
        csv, meta = self._paths(ward)
        if not (csv.exists() and meta.exists()):
            return False
        m = json.loads(meta.read_text())
        if m["request"]["geometry"] != ward_geometry(ward):
            raise ValueError(
                f"cached CHIRPS for {ward.id} was fetched for a different geometry; "
                f"re-fetch with `agroshield-price fetch-rainfall --ward {ward.id} --refresh`")
        if hashlib.sha256(csv.read_bytes()).hexdigest() != m["sha256"]:
            raise ValueError(f"{csv} does not match its recorded SHA-256; the raw input was modified")
        return m["start_year"] <= start_year and m["end_year"] >= end_year

    def fetch(self, ward: Ward, start_year: int, end_year: int) -> Path:
        """Download and cache the full range for a ward. Returns the CSV path."""
        geometry = ward_geometry(ward)
        self.log(f"Fetching CHIRPS daily for {ward.id} {start_year}-{end_year} from ClimateSERV")
        parts = []
        for y0 in range(start_year, end_year + 1, CHUNK_YEARS):
            y1 = min(y0 + CHUNK_YEARS - 1, end_year)
            parts.append(fetch_chunk(geometry, f"01/01/{y0}", f"12/31/{y1}", self.log))
        s = validate_series(pd.concat(parts), start_year, end_year, f"CHIRPS {ward.id}")
        csv, meta = self._paths(ward)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        out = pd.DataFrame({"date": s.index.strftime("%Y-%m-%d"), "rain_mm": s.round(4).values})
        out.to_csv(csv, index=False, lineterminator="\n")
        meta.write_text(json.dumps({
            "ward_id": ward.id,
            "dataset": "UCSB CHIRPS v2.0 daily, 0.05 deg, polygon mean",
            "provider": "SERVIR ClimateSERV",
            "request": {"base_url": BASE_URL, "datatype": DATATYPE_CHIRPS,
                        "operationtype": OPERATION_AVERAGE, "intervaltype": INTERVAL_DAILY,
                        "geometry": geometry},
            "start_year": start_year, "end_year": end_year,
            "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "sha256": hashlib.sha256(csv.read_bytes()).hexdigest(),
        }, indent=2) + "\n", newline="\n")
        return csv

    def daily(self, ward: Ward, start_year: int, end_year: int) -> pd.Series:
        if not self.is_cached(ward, start_year, end_year):
            if not self.allow_download:
                raise FileNotFoundError(
                    f"no cached CHIRPS for {ward.id} {start_year}-{end_year}; run "
                    f"`agroshield-price fetch-rainfall --ward {ward.id}`")
            self.fetch(ward, start_year, end_year)
        csv, _ = self._paths(ward)
        df = pd.read_csv(csv, parse_dates=["date"]).set_index("date")["rain_mm"]
        return validate_series(df, start_year, end_year, f"CHIRPS {ward.id}")

    def provenance(self, ward: Ward) -> Provenance:
        _, meta = self._paths(ward)
        m = json.loads(meta.read_text()) if meta.exists() else {}
        return Provenance(Label.REAL, "CHIRPS v2.0 daily via SERVIR ClimateSERV", {
            "cache_file": f"data/raw/chirps/{ward.id}.csv",
            "sha256": m.get("sha256"),
            "retrieved_at": m.get("retrieved_at"),
            "geometry": "box of %.2f deg around the ward centroid" % ward.extraction_box_deg,
            "caveat": ("CHIRPS daily values are disaggregated from pentad totals and are "
                       "unreliable day by day; the index only uses multi-week phase totals."),
        })
