"""Real CHIRPS v3.0 daily rainfall from the Climate Hazards Center data server.

Why this exists: the Climate Hazards Center retires CHIRPS v2 after December
2026 ("its last month of operation will be December 2026"), so any season
monitored after that date has to run on CHIRPS v3.0.

Source (no account needed, plain HTTPS):
  https://data.chc.ucsb.edu/products/CHIRPS/v3.0/daily/final/rnl/netcdf/byYear/
  chirps-v3.0.rnl.<year>.days_p05.nc   (one global 0.05 deg file per year, 3-5 GB)

Our CHIRPS v2 polygon means come from SERVIR ClimateSERV; the WIP note said
ClimateSERV did not offer CHIRPS v3 on 2026-10-30 (not re-checked). So the
polygon mean is computed here from the CHC files instead.
We never download a whole global file. Each yearly NetCDF4 file (checked on
the 1981-2026 files, 2026-11-01) is stored in deflate-compressed chunks of
31 days x 200 x 600 pixels, float32, fill -9999. We read the file's index with
HTTP range requests (about 40 small reads), then fetch only the 12 chunks that
hold the ward pixels (both wards share them): about 50 requests and 45 to 55 MB
per year. The server rate-limits (HTTP 429), so requests go one at a time with
a pause and back off when told to.

Disaggregation: CHIRPS v3 daily is a pentad total split across days. "rnl"
splits it using ERA5 reanalysis and covers 1981 to date; "sat" uses IMERG and
starts in 1998. We use "rnl" so the whole 1981 history has one consistent
method. Both sum to the same pentad totals; our index only uses multi-week
phase totals, so the choice moves little.

Polygon mean: the mean of the 0.05 deg pixels whose centres fall inside the
ward polygon, equally weighted, using the same polygon as the CHIRPS v2 request
(recorded in data/raw/chirps/<ward>.meta.json; tested). For our 0.10 deg boxes
that is 4 pixels per ward. docs/pricing/chirps3-comparison.md records how this
rule was checked against the ClimateSERV v2 series.

Cache: data/raw/chirps3/<ward>.csv (date, rain_mm polygon mean), plus
<ward>.pixels.csv (every pixel's daily value, so the mean can be audited) and
<ward>.meta.json recording the request (URLs, pixel centres, method),
retrieved_at and SHA-256 checksums of both CSVs.

The request carries only a file path and byte ranges, never personal data.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import time
import zlib
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from ..config import Ward
from ..provenance import Label, Provenance
from .base import RainfallSource, validate_series
from .chirps import ward_geometry

BASE_URL = os.environ.get("CHIRPS3_BASE_URL", "https://data.chc.ucsb.edu/products/CHIRPS/v3.0")
DISAGGREGATION = "rnl"           # ERA5-based; the only v3 daily variant that starts in 1981
DATASET = "CHIRPS v3.0 daily final (rnl, ERA5 disaggregation), 0.05 deg, polygon mean"
PIXEL_METHOD = "mean of 0.05 deg pixels whose centres fall inside the ward polygon, equal weights"
PAUSE_S = 2.0                    # pause between requests: one at a time, gently
BACKOFF_S = 30.0                 # wait after HTTP 429 / 5xx when the server gives no Retry-After
SOURCES = [
    "https://data.chc.ucsb.edu/products/CHIRPS/v3.0/README-CHIRPSv3.0.txt",
    "https://data.chc.ucsb.edu/products/CHIRPS/v3.0/daily/readme.txt",
    "https://data.chc.ucsb.edu/products/CHIRPS/v3.0/daily/final/rnl/netcdf/byYear/",
]


def year_url(year: int, base: str = BASE_URL) -> str:
    return f"{base}/daily/final/{DISAGGREGATION}/netcdf/byYear/chirps-v3.0.{DISAGGREGATION}.{year}.days_p05.nc"


# ---------------------------------------------------------------------------
# Pixel selection (pure, tested offline)
# ---------------------------------------------------------------------------
def point_in_ring(x: float, y: float, ring: list) -> bool:
    """Ray casting test; points exactly on an edge are treated as outside."""
    inside = False
    n = len(ring)
    for i in range(n - 1):
        (x1, y1), (x2, y2) = ring[i], ring[i + 1]
        if (y1 > y) != (y2 > y):
            xc = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < xc:
                inside = not inside
    return inside


def pixels_in_polygon(geometry: dict, lats: np.ndarray, lons: np.ndarray) -> list[tuple[int, int]]:
    """(row, col) of grid pixels whose centres lie inside the polygon's outer ring."""
    ring = geometry["coordinates"][0]
    xs = [p[0] for p in ring]
    ys = [p[1] for p in ring]
    rows = np.where((lats > min(ys)) & (lats < max(ys)))[0]
    cols = np.where((lons > min(xs)) & (lons < max(xs)))[0]
    out = [(int(r), int(c)) for r in rows for c in cols if point_in_ring(float(lons[c]), float(lats[r]), ring)]
    if not out:
        raise ValueError("no CHIRPS pixel centre falls inside the ward polygon")
    return out


def polygon_mean(pixels: pd.DataFrame) -> pd.Series:
    """Equal-weight mean across pixel columns."""
    return pixels.mean(axis=1)


# ---------------------------------------------------------------------------
# HTTP range reading of a remote NetCDF4 / HDF5 file
# ---------------------------------------------------------------------------
class HttpRangeFile(io.RawIOBase):
    """Read-only file over HTTP range requests with a small block cache.

    Used only to read the HDF5 index (dimension variables and chunk B-tree);
    the data chunks themselves are fetched in one request each.
    """

    def __init__(self, url: str, session, block: int = 256 * 1024, log=print):
        self.url, self.block, self.pos, self.session, self.log = url, block, 0, session, log
        self.cache: dict[int, bytes] = {}
        self.requests = 0
        self.bytes = 0
        r = self._polite(lambda: session.head(url, timeout=60, allow_redirects=True), (200,))
        self.size = int(r.headers["Content-Length"])
        self.last_modified = r.headers.get("Last-Modified")

    def _polite(self, call, ok: tuple[int, ...]):
        """One request after a pause; on 429 or 5xx wait (Retry-After if given) and retry.

        The CHC server rate-limits (HTTP 429). We back off rather than retry fast.
        """
        attempts = 6
        for attempt in range(attempts):
            time.sleep(PAUSE_S)
            try:
                r = call()
            except Exception:
                if attempt == attempts - 1:
                    raise
                time.sleep(BACKOFF_S * (attempt + 1))
                continue
            if r.status_code in ok:
                return r
            if r.status_code == 404:
                raise FileNotFoundError(f"not published (HTTP 404): {self.url}")
            if r.status_code == 429 or r.status_code >= 500:
                if attempt == attempts - 1:
                    break
                try:
                    wait = float(r.headers.get("Retry-After", ""))
                except ValueError:
                    wait = BACKOFF_S * (attempt + 1)
                self.log(f"  server answered HTTP {r.status_code}; waiting {wait:.0f} s")
                time.sleep(wait)
                continue
            raise IOError(f"unexpected HTTP {r.status_code} for {self.url}")
        raise IOError(f"gave up after {attempts} attempts (last HTTP {r.status_code}) for {self.url}")

    def get_range(self, start: int, length: int) -> bytes:
        for attempt in range(3):
            r = self._polite(lambda: self.session.get(
                self.url, headers={"Range": f"bytes={start}-{start + length - 1}"}, timeout=300), (206,))
            if len(r.content) == length:
                self.requests += 1
                self.bytes += length
                return r.content
            self.log(f"  short read {len(r.content)} of {length} bytes; retrying")
        raise IOError(f"short reads from {self.url} at byte {start}")

    def seekable(self):
        return True

    def readable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, off, whence=0):
        self.pos = off if whence == 0 else (self.pos + off if whence == 1 else self.size + off)
        return self.pos

    def _blk(self, i: int) -> bytes:
        if i not in self.cache:
            a = i * self.block
            self.cache[i] = self.get_range(a, min(self.block, self.size - a))
        return self.cache[i]

    def readinto(self, buf):
        n = min(len(buf), self.size - self.pos)
        if n <= 0:
            return 0
        out = bytearray()
        p = self.pos
        while len(out) < n:
            i = p // self.block
            d = self._blk(i)
            take = d[p - i * self.block: p - i * self.block + n - len(out)]
            out += take
            p += len(take)
        buf[:n] = out
        self.pos += n
        return n


def read_year_window(url: str, row_lo: int, row_hi: int, col_lo: int, col_hi: int,
                     session, log=print) -> tuple[pd.DatetimeIndex, np.ndarray, dict]:
    """Daily values for rows [row_lo, row_hi] x cols [col_lo, col_hi] of one yearly file.

    Returns (dates, array[t, rows, cols], info). Fill values (-9999) become NaN.
    """
    import h5py  # fetch-time dependency only; reading the cache needs no h5py

    f = HttpRangeFile(url, session, log=log)
    with h5py.File(io.BufferedReader(f, buffer_size=1 << 16), "r") as h:
        p = h["precip"]
        t_units = h["time"].attrs["units"]
        t_units = t_units.decode() if isinstance(t_units, bytes) else str(t_units)
        base = pd.Timestamp(t_units.split("since")[1].strip().split(" ")[0])
        days = h["time"][:].astype("float64")
        dates = pd.DatetimeIndex([base + pd.Timedelta(days=float(d)) for d in days]).normalize()
        fill = float(np.atleast_1d(p.attrs.get("_FillValue", [-9999.0]))[0])
        ct, cr, cc = p.chunks
        filters = p.id.get_create_plist()
        nfilt = filters.get_nfilters()
        names = [filters.get_filter(i)[0] for i in range(nfilt)]
        direct = names == [h5py.h5z.FILTER_DEFLATE]
        dtype = p.dtype
        nt = p.shape[0]
        out = np.full((nt, row_hi - row_lo + 1, col_hi - col_lo + 1), np.nan, dtype="float64")
        chunks_read = []
        for t0 in range(0, nt, ct):
            for r0 in range((row_lo // cr) * cr, row_hi + 1, cr):
                for c0 in range((col_lo // cc) * cc, col_hi + 1, cc):
                    if direct:
                        info = p.id.get_chunk_info_by_coord((t0, r0, c0))
                        if info.byte_offset is None:
                            continue  # chunk never written: all fill
                        raw = f.get_range(info.byte_offset, info.size)
                        block = np.frombuffer(zlib.decompress(raw), dtype=dtype).reshape(ct, cr, cc)
                        chunks_read.append([t0, r0, c0, int(info.byte_offset), int(info.size)])
                    else:  # unexpected filter pipeline: let h5py read (slower, still ranged)
                        block = np.full((ct, cr, cc), fill, dtype=dtype)
                        sub = p[t0:t0 + ct, r0:r0 + cr, c0:c0 + cc]
                        block[:sub.shape[0], :sub.shape[1], :sub.shape[2]] = sub
                    rs, re_ = max(row_lo, r0), min(row_hi, r0 + cr - 1)
                    cs, ce = max(col_lo, c0), min(col_hi, c0 + cc - 1)
                    te = min(t0 + ct, nt)
                    out[t0:te, rs - row_lo:re_ - row_lo + 1, cs - col_lo:ce - col_lo + 1] = \
                        block[:te - t0, rs - r0:re_ - r0 + 1, cs - c0:ce - c0 + 1]
    out[(out == fill) | (out < -1)] = np.nan
    info = {"url": url, "file_size": f.size, "last_modified": f.last_modified,
            "requests": f.requests, "bytes": f.bytes, "chunks": chunks_read,
            "direct_chunk_read": direct}
    return dates, out, info


def read_grid(url: str, session) -> tuple[np.ndarray, np.ndarray]:
    """Latitude and longitude pixel centres of a yearly file."""
    import h5py

    f = HttpRangeFile(url, session)
    with h5py.File(io.BufferedReader(f, buffer_size=1 << 16), "r") as h:
        return h["latitude"][:].astype("float64"), h["longitude"][:].astype("float64")


# ---------------------------------------------------------------------------
# Rainfall source
# ---------------------------------------------------------------------------
class Chirps3Source(RainfallSource):
    """CHIRPS v3.0 daily (rnl) polygon means, cached under data/raw/chirps3/."""

    def __init__(self, cache_dir: str | Path, allow_download: bool = True, log=print):
        self.cache_dir = Path(cache_dir)
        self.allow_download = allow_download
        self.log = log

    def _paths(self, ward: Ward) -> tuple[Path, Path, Path]:
        d = self.cache_dir
        return d / f"{ward.id}.csv", d / f"{ward.id}.meta.json", d / f"{ward.id}.pixels.csv"

    def meta(self, ward: Ward) -> dict:
        _, meta, _ = self._paths(ward)
        return json.loads(meta.read_text()) if meta.exists() else {}

    def is_cached(self, ward: Ward, start_year: int, end_year: int) -> bool:
        csv, meta, pix = self._paths(ward)
        if not (csv.exists() and meta.exists()):
            return False
        m = json.loads(meta.read_text())
        if m["request"]["geometry"] != ward_geometry(ward):
            raise ValueError(
                f"cached CHIRPS3 for {ward.id} was fetched for a different geometry; "
                f"re-fetch with `agroshield-price fetch-rainfall --dataset chirps3 --ward {ward.id} --refresh`")
        if hashlib.sha256(csv.read_bytes()).hexdigest() != m["sha256"]:
            raise ValueError(f"{csv} does not match its recorded SHA-256; the raw input was modified")
        if pix.exists() and hashlib.sha256(pix.read_bytes()).hexdigest() != m.get("pixels_sha256"):
            raise ValueError(f"{pix} does not match its recorded SHA-256; the raw input was modified")
        return m["start_year"] <= start_year and m["end_year"] >= end_year

    def _read_years(self, wards: list[Ward], years: list[int], partial_dir: Path | None = None,
                    missing_ok: bool = False):
        """Pixel values for each ward, one remote yearly file at a time.

        With `partial_dir`, each year's window is kept there as it arrives so an
        interrupted fetch resumes where it stopped (the folder is not committed).
        With `missing_ok`, a last year whose file is not yet published is skipped.
        """
        import requests

        session = requests.Session()
        session.headers["User-Agent"] = "AgroShield (CHIRPS v3 ward polygon means; research use)"
        lats, lons = read_grid(year_url(years[0]), session)
        geoms = {w.id: ward_geometry(w) for w in wards}
        pix = {wid: pixels_in_polygon(g, lats, lons) for wid, g in geoms.items()}
        allr = [r for v in pix.values() for r, _ in v]
        allc = [c for v in pix.values() for _, c in v]
        # One pixel of margin: the same chunks, and the window then also allows
        # other pixel-selection rules to be checked without fetching again.
        r_lo, r_hi, c_lo, c_hi = min(allr) - 1, max(allr) + 1, min(allc) - 1, max(allc) + 1
        self.log(f"CHIRPS3: wards {', '.join(geoms)}; rows {r_lo}-{r_hi}, cols {c_lo}-{c_hi}")
        per_ward: dict[str, list[pd.DataFrame]] = {wid: [] for wid in geoms}
        files = []
        for year in years:
            t = time.time()
            part = partial_dir / f"{year}_{r_lo}_{r_hi}_{c_lo}_{c_hi}.npz" if partial_dir else None
            if part is not None and part.exists():
                z = np.load(part, allow_pickle=False)
                dates, arr = pd.DatetimeIndex(z["dates"].astype("datetime64[ns]")), z["arr"]
                info = json.loads(str(z["info"]))
            else:
                try:
                    dates, arr, info = read_year_window(year_url(year), r_lo, r_hi, c_lo, c_hi, session, self.log)
                except FileNotFoundError:
                    if not (missing_ok and year == years[-1]):
                        raise
                    self.log(f"  {year}: not published yet")   # e.g. January, before the first month is out
                    continue
                if part is not None and not np.isnan(arr).any():   # only complete years are kept
                    part.parent.mkdir(parents=True, exist_ok=True)
                    np.savez(part, dates=dates.values.astype("datetime64[D]"), arr=arr,
                             info=json.dumps({k: v for k, v in info.items() if k != "chunks"}))
                self.log(f"  {year}: {len(dates)} days, {info['requests']} requests, "
                         f"{info['bytes'] / 1e6:.1f} MB, {time.time() - t:.0f} s")
            files.append({k: info[k] for k in ("url", "file_size", "last_modified", "requests", "bytes")})
            for wid, plist in pix.items():
                cols = {f"p{r}_{c}": arr[:, r - r_lo, c - c_lo] for r, c in plist}
                per_ward[wid].append(pd.DataFrame(cols, index=dates))
        return lats, lons, geoms, pix, per_ward, files

    def fetch_range(self, ward: Ward, start: str, end: str) -> pd.Series:
        """Polygon-mean daily rain from `start` to `end` (YYYY-MM-DD) as far as published.

        For monitoring: nothing is written here; the caller caches what it keeps.
        """
        years = list(range(int(start[:4]), int(end[:4]) + 1))
        _, _, _, _, per_ward, _ = self._read_years([ward], years, missing_ok=True)
        df = pd.concat(per_ward[ward.id]).sort_index().loc[start:end]
        df = df[df.notna().all(axis=1)]
        s = polygon_mean(df)
        s.name = "rain_mm"
        return s

    def fetch_many(self, wards: list[Ward], start_year: int, end_year: int,
                   through: str | None = None) -> list[Path]:
        """Fetch several wards at once (they share chunks). `through` (YYYY-MM-DD)
        keeps days after end_year up to that date, e.g. the part of 2026 published so far."""
        last_year = int(through[:4]) if through else end_year
        partial = self.cache_dir / "_partial"
        lats, lons, geoms, pix, per_ward, files = self._read_years(
            wards, list(range(start_year, last_year + 1)), partial)
        out_paths = []
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        for w in wards:
            df = pd.concat(per_ward[w.id]).sort_index()
            df = df[~df.index.duplicated()]
            end = pd.Timestamp(through) if through else pd.Timestamp(f"{end_year}-12-31")
            df = df.loc[f"{start_year}-01-01":end]
            hist = df.loc[:f"{end_year}-12-31"]
            if hist.isna().any().any():
                raise ValueError(f"CHIRPS3 {w.id}: missing values in the {start_year}-{end_year} history")
            tail = df.loc[f"{end_year + 1}-01-01":]
            if len(tail):  # keep only the published part of the current year
                ok = tail.notna().all(axis=1)
                last_ok = ok[ok].index.max() if ok.any() else None
                df = df.loc[:last_ok] if last_ok is not None else hist
            mean = polygon_mean(df)
            validate_series(mean.loc[:f"{end_year}-12-31"], start_year, end_year, f"CHIRPS3 {w.id}")
            csv, meta, pixp = self._paths(w)
            pd.DataFrame({"date": mean.index.strftime("%Y-%m-%d"), "rain_mm": mean.round(4).values}) \
                .to_csv(csv, index=False, lineterminator="\n")
            pdf = df.round(4)
            pdf.insert(0, "date", df.index.strftime("%Y-%m-%d"))
            pdf.to_csv(pixp, index=False, lineterminator="\n")
            meta.write_text(json.dumps({
                "ward_id": w.id,
                "dataset": DATASET,
                "provider": "UCSB Climate Hazards Center data server (data.chc.ucsb.edu)",
                "request": {
                    "base_url": BASE_URL, "disaggregation": DISAGGREGATION,
                    "file_pattern": f"{BASE_URL}/daily/final/{DISAGGREGATION}/netcdf/byYear/"
                                    f"chirps-v3.0.{DISAGGREGATION}.{{year}}.days_p05.nc",
                    "access": "HTTP range requests on yearly NetCDF4 files: file index plus the "
                              "compressed chunks covering the ward pixels",
                    "geometry": geoms[w.id],
                    "geometry_note": "same polygon as the CHIRPS v2 request in data/raw/chirps/"
                                     f"{w.id}.meta.json",
                    "pixel_method": PIXEL_METHOD,
                    "pixels": [{"row": r, "col": c, "lat": round(float(lats[r]), 4),
                                "lon": round(float(lons[c]), 4)} for r, c in pix[w.id]],
                },
                "start_year": start_year, "end_year": end_year,
                "last_date": mean.index.max().strftime("%Y-%m-%d"),
                "files": files,
                "sources": SOURCES,
                "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "sha256": hashlib.sha256(csv.read_bytes()).hexdigest(),
                "pixels_sha256": hashlib.sha256(pixp.read_bytes()).hexdigest(),
            }, indent=2) + "\n", newline="\n")
            out_paths.append(csv)
        return out_paths

    def fetch(self, ward: Ward, start_year: int, end_year: int) -> Path:
        return self.fetch_many([ward], start_year, end_year)[0]

    def _load(self, ward: Ward) -> pd.Series:
        csv, _, _ = self._paths(ward)
        return pd.read_csv(csv, parse_dates=["date"]).set_index("date")["rain_mm"]

    def daily(self, ward: Ward, start_year: int, end_year: int) -> pd.Series:
        if not self.is_cached(ward, start_year, end_year):
            if not self.allow_download:
                raise FileNotFoundError(
                    f"no cached CHIRPS3 for {ward.id} {start_year}-{end_year}; run "
                    f"`agroshield-price fetch-rainfall --dataset chirps3 --ward {ward.id}`")
            self.fetch(ward, start_year, end_year)
        return validate_series(self._load(ward), start_year, end_year, f"CHIRPS3 {ward.id}")

    def latest(self, ward: Ward) -> pd.Series:
        """Everything cached, including any days after the history window."""
        s = self._load(ward).sort_index()
        s.name = "rain_mm"
        return s

    def provenance(self, ward: Ward) -> Provenance:
        m = self.meta(ward)
        return Provenance(Label.REAL, "CHIRPS v3.0 daily (rnl) from the UCSB Climate Hazards Center", {
            "cache_file": f"data/raw/chirps3/{ward.id}.csv",
            "sha256": m.get("sha256"),
            "retrieved_at": m.get("retrieved_at"),
            "geometry": "box of %.2f deg around the ward centroid" % ward.extraction_box_deg,
            "pixel_method": PIXEL_METHOD,
            "caveat": ("CHIRPS v3 daily values split pentad totals across days using ERA5 (rnl) and "
                       "are unreliable day by day; the index only uses multi-week phase totals."),
        })
