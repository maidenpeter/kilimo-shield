"""Hargreaves PET from NASA POWER daily temperature (fallback PET source).

NASA POWER serves MERRA-2 based daily Tmax/Tmin for a point (~0.5 deg grid)
with no key. Raw temperatures are cached in data/raw/nasapower/<ward>.csv with
a .meta.json recording the request, the POWER grid-cell elevation, retrieval
time and SHA-256, exactly like the CHIRPS cache.

The grid cell's mean elevation can differ from the ward's by hundreds of
metres in the Rift Valley, so temperatures are shifted by a standard lapse rate
(config: pet.lapse_rate_c_per_km) from the grid elevation to the ward elevation
before computing PET. The request carries only coordinates and dates.
"""
from __future__ import annotations

import hashlib
import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from ..config import Ward
from ..provenance import Label, Provenance
from ..rainfall.base import validate_series
from . import PetSource
from .hargreaves import hargreaves_et0

BASE_URL = "https://power.larc.nasa.gov/api/temporal/daily/point"
PARAMS = ("T2M_MAX", "T2M_MIN")
CHUNK_YEARS = 10


def _get_json(params: dict, timeout: float = 180, retries: int = 4):
    url = BASE_URL + "?" + urllib.parse.urlencode(params)
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(5 * (attempt + 1))


class HargreavesNasaPowerSource(PetSource):
    def __init__(self, cache_dir: str | Path, lapse_rate_c_per_km: float = 6.5,
                 allow_download: bool = True, log=print):
        self.cache_dir = Path(cache_dir)
        self.lapse = lapse_rate_c_per_km
        self.allow_download = allow_download
        self.log = log

    def _paths(self, ward: Ward) -> tuple[Path, Path]:
        return self.cache_dir / f"{ward.id}.csv", self.cache_dir / f"{ward.id}.meta.json"

    def is_cached(self, ward: Ward, start_year: int, end_year: int) -> bool:
        csv, meta = self._paths(ward)
        if not (csv.exists() and meta.exists()):
            return False
        m = json.loads(meta.read_text())
        point = {"lat": ward.centroid.lat, "lon": ward.centroid.lon}
        if m["request"]["point"] != point:
            raise ValueError(f"cached NASA POWER data for {ward.id} is for a different point; "
                             f"re-fetch with `agroshield-price fetch-climate --ward {ward.id} --refresh`")
        if hashlib.sha256(csv.read_bytes()).hexdigest() != m["sha256"]:
            raise ValueError(f"{csv} does not match its recorded SHA-256; the raw input was modified")
        return m["start_year"] <= start_year and m["end_year"] >= end_year

    def fetch(self, ward: Ward, start_year: int, end_year: int) -> Path:
        self.log(f"Fetching NASA POWER Tmax/Tmin for {ward.id} {start_year}-{end_year}")
        frames, elevation = [], None
        for y0 in range(start_year, end_year + 1, CHUNK_YEARS):
            y1 = min(y0 + CHUNK_YEARS - 1, end_year)
            data = _get_json({"parameters": ",".join(PARAMS), "community": "AG",
                              "latitude": ward.centroid.lat, "longitude": ward.centroid.lon,
                              "start": f"{y0}0101", "end": f"{y1}1231", "format": "JSON"})
            elevation = data["geometry"]["coordinates"][2]
            p = data["properties"]["parameter"]
            df = pd.DataFrame({"tmax_c": p["T2M_MAX"], "tmin_c": p["T2M_MIN"]})
            df.index = pd.to_datetime(df.index, format="%Y%m%d")
            frames.append(df)
            self.log(f"  {y0}-{y1}: {len(df)} days")
        df = pd.concat(frames).sort_index()
        fill = (df <= -998).any(axis=1)
        if fill.any():
            raise ValueError(f"NASA POWER returned {int(fill.sum())} missing days for {ward.id}")
        expected = pd.date_range(f"{start_year}-01-01", f"{end_year}-12-31", freq="D")
        if not df.index.equals(expected):
            raise ValueError(f"NASA POWER series for {ward.id} is incomplete: "
                             f"{len(expected.difference(df.index))} missing days")
        if ((df["tmax_c"] - df["tmin_c"]) < 0).any() or (df.abs() > 60).any().any():
            raise ValueError(f"NASA POWER temperatures for {ward.id} are implausible")
        csv, meta = self._paths(ward)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        out = pd.DataFrame({"date": df.index.strftime("%Y-%m-%d"),
                            "tmax_c": df["tmax_c"].round(2).values, "tmin_c": df["tmin_c"].round(2).values})
        out.to_csv(csv, index=False, lineterminator="\n")
        meta.write_text(json.dumps({
            "ward_id": ward.id,
            "dataset": "NASA POWER daily T2M_MAX / T2M_MIN (MERRA-2), community AG",
            "provider": "NASA Langley POWER",
            "request": {"base_url": BASE_URL, "parameters": list(PARAMS),
                        "point": {"lat": ward.centroid.lat, "lon": ward.centroid.lon}},
            "grid_elevation_m": elevation,
            "start_year": start_year, "end_year": end_year,
            "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "sha256": hashlib.sha256(csv.read_bytes()).hexdigest(),
        }, indent=2) + "\n", newline="\n")
        return csv

    def temperatures(self, ward: Ward, start_year: int, end_year: int) -> tuple[pd.DataFrame, dict]:
        if not self.is_cached(ward, start_year, end_year):
            if not self.allow_download:
                raise FileNotFoundError(f"no cached NASA POWER data for {ward.id}; run "
                                        f"`agroshield-price fetch-climate --ward {ward.id}`")
            self.fetch(ward, start_year, end_year)
        csv, meta = self._paths(ward)
        df = pd.read_csv(csv, parse_dates=["date"]).set_index("date")
        df = df.loc[f"{start_year}-01-01":f"{end_year}-12-31"]
        return df, json.loads(meta.read_text())

    def lapse_shift_c(self, ward: Ward, meta: dict) -> float:
        if ward.elevation_m is None or meta.get("grid_elevation_m") is None:
            return 0.0
        return self.lapse * (meta["grid_elevation_m"] - ward.elevation_m) / 1000.0

    def daily(self, ward: Ward, start_year: int, end_year: int) -> pd.Series:
        df, meta = self.temperatures(ward, start_year, end_year)
        shift = self.lapse_shift_c(ward, meta)
        pet = hargreaves_et0(df["tmax_c"] + shift, df["tmin_c"] + shift, ward.centroid.lat,
                             df.index.dayofyear.to_numpy())
        s = pd.Series(pet, index=df.index, name="pet_mm")
        return validate_series(s, start_year, end_year, f"Hargreaves PET {ward.id}")

    def provenance(self, ward: Ward) -> Provenance:
        _, meta_path = self._paths(ward)
        m = json.loads(meta_path.read_text()) if meta_path.exists() else {}
        return Provenance(Label.REAL, "Hargreaves PET from NASA POWER temperature (FALLBACK)", {
            "cache_file": f"data/raw/nasapower/{ward.id}.csv",
            "sha256": m.get("sha256"),
            "retrieved_at": m.get("retrieved_at"),
            "lapse_shift_c": round(self.lapse_shift_c(ward, m), 2) if m else None,
            "note": ("FALLBACK: FEWS NET Penman-Monteith PET was unreachable (USGS server 503) and only "
                     "covers 2001 onward. Hargreaves can overstate PET in humid conditions."),
        })
