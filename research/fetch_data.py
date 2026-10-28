"""Download the inputs for research task 3b (forecast skill and site scan).

Run from the repo root:  .venv/Scripts/python research/fetch_data.py [c3s] [ghacof] [eastern]

Everything is cached in data/raw/research/ with a .meta.json (URL, retrieval
time, SHA-256), like the pricing inputs. Requests identify the client and are
made one at a time.

  c3s      C3S ECMWF SEAS5.1 seasonal hindcast precipitation (1981-2016 starts,
           25 members, 6 leads) for the 1-degree cell holding both pilot wards,
           from the IRI Data Library mirror (downloads need no login).
  ghacof   GHACOF consensus outlook tercile probabilities at each pilot ward, for
           every March-May and Sep/Oct-December outlook on the ICPAC geoportal
           (GeoServer WFS, one point query per outlook and ward).
  eastern  CHIRPS v2.0 monthly rainfall 1981-2025 over semi-arid eastern Kenya
           (Machakos, Makueni, Kitui), 0.05 degree, from the IRI Data Library.
           ~6 MB; not committed (see .gitignore), re-fetch with this script.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "data" / "raw" / "research"
UA = "AgroShield-research/0.1 (contact: mrnwanngari@gmail.com)"

IRI = "https://iridl.ldeo.columbia.edu"
C3S_PATH = "SOURCES/.EU/.Copernicus/.CDS/.C3S/.ECMWF/.SEAS51/.hindcast/.prcp"
C3S_CELL = (36, 0)        # lon, lat of the 1-degree cell containing both pilot wards
WFS = "https://geoportal.icpac.net/geoserver/ows"
ICPAC_SEARCH = "https://geoportal.icpac.net/api/v2/resources/"
CHIRPS_MONTHLY = "SOURCES/.UCSB/.CHIRPS/.v2p0/.monthly/.global/.precipitation"
EASTERN_BOX = {"lon": (37.0, 39.5), "lat": (-3.5, -0.5)}


def get(url: str, timeout: float = 300, retries: int = 4) -> bytes:
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:
            if attempt == retries - 1:
                raise
            print(f"  retry {attempt + 1} after {e}")
            time.sleep(10 * (attempt + 1))


def save(name: str, data: bytes, url: str, extra: dict | None = None) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    path.write_bytes(data)
    meta = {"url": url, "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data), **(extra or {})}
    (OUT / (name + ".meta.json")).write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"saved {path.relative_to(REPO)} ({len(data):,} B)")
    return path


# Season -> (start month of the forecast, leads averaged). A 1 Feb start with
# leads 1.5-3.5 months covers March-May; a 1 Sep start covers October-December.
C3S_SEASONS = {"MAM": ("Feb", (1.5, 3.5)), "OND": ("Sep", (1.5, 3.5))}


NEIGHBOUR_CELLS = [(35, 0), (37, 0), (36, -1), (36, 1)]   # robustness check around the ward cell


def fetch_c3s_neighbours() -> None:
    for cell in NEIGHBOUR_CELLS:
        print(f"-- cell {cell}")
        fetch_c3s(cell)


def fetch_c3s(cell: tuple[int, int] = C3S_CELL) -> None:
    """One small request per start date: the 25-member mean rate over the season's leads.

    Asking IRI for the whole point series at once times out (it must read every
    start, lead and member), so each year and season is requested separately and
    averaged over leads on the server.
    """
    lon, lat = cell
    tag = f"{abs(lon)}{'E' if lon >= 0 else 'W'}_{abs(lat)}{'N' if lat >= 0 else 'S'}"
    rows = ["season,year,member,mean_rate_m_s,mean_mm_per_day"]
    urls = []
    for season, (month, (l0, l1)) in C3S_SEASONS.items():
        for year in range(1981, 2017):
            url = (f"{IRI}/{C3S_PATH}/X/{lon}/VALUE/Y/{lat}/VALUE/S/(1%20{month}%20{year})/VALUE/"
                   f"L/{l0}/{l1}/RANGE/%5BL%5Daverage/data.tsv")
            vals = [float(v) for v in get(url, 300).decode().split()]
            if len(vals) != 25:
                raise ValueError(f"{season} {year}: expected 25 members, got {len(vals)}")
            rows += [f"{season},{year},{m + 1},{v:.6e},{v * 86400 * 1000:.4f}" for m, v in enumerate(vals)]
            urls.append(url)
            print(f"  {season} {year}: ensemble mean {sum(vals) / 25 * 86400 * 1000:.2f} mm/day")
            time.sleep(0.5)
    save(f"c3s_seas51_hindcast_{tag}.csv", ("\n".join(rows) + "\n").encode(), urls[0].split("/X/")[0],
         {"dataset": "C3S ECMWF SEAS5.1 hindcast, total precipitation, 25 members, via IRI Data Library",
          "cell": {"lon": lon, "lat": lat}, "seasons": {k: {"start": v[0], "leads_months": v[1]} for k, v in C3S_SEASONS.items()},
          "example_url": urls[0], "requests": len(urls)})


def _ghacof_layers() -> list[dict]:
    url = ICPAC_SEARCH + "?" + urllib.parse.urlencode({"filter{title.icontains}": "GHACOF", "page_size": 200})
    data = json.loads(get(url))
    save("ghacof_layers.json", json.dumps(data, indent=1).encode(), url)
    layers = []
    for r in data["resources"]:
        t = r["title"]
        if r.get("resource_type") != "layer" or "Temperature" in t:
            continue
        season = ("MAM" if re.search(r"March.{0,6}May", t) else
                  "OND" if re.search(r"(October|September).{0,8}December", t) else None)
        year = re.search(r"(19|20)\d\d", t)
        if season and year:
            layers.append({"pk": r["pk"], "title": t, "alternate": r["alternate"], "season": season,
                           "year": int(year.group(0))})
    return sorted(layers, key=lambda x: (x["season"], x["year"], x["pk"]))


def fetch_ghacof() -> None:
    sys.path.insert(0, str(REPO / "src"))
    from agroshield_pricing.config import load_config
    cfg = load_config(REPO / "config")
    layers = _ghacof_layers()
    print(f"{len(layers)} GHACOF rainfall outlook layers (MAM / OND)")
    results = []
    for lay in layers:
        for wid in cfg.pilot.wards:
            c = cfg.ward(wid).centroid
            params = {"service": "WFS", "version": "1.0.0", "request": "GetFeature", "typeName": lay["alternate"],
                      "outputFormat": "application/json", "CQL_FILTER": f"INTERSECTS(the_geom, POINT({c.lon} {c.lat}))"}
            url = WFS + "?" + urllib.parse.urlencode(params)
            try:
                feats = json.loads(get(url, 180)).get("features", [])
                props = [f["properties"] for f in feats]
            except Exception as e:  # keep going; record the failure
                props, url = None, f"{url}  [FAILED: {e}]"
            results.append({**lay, "ward_id": wid, "point": {"lon": c.lon, "lat": c.lat}, "properties": props, "url": url})
            print(f"  {lay['season']} {lay['year']} {wid}: {props}")
            time.sleep(1)
    body = json.dumps(results, indent=1).encode()
    save("ghacof_ward_probabilities.json", body, WFS, {"layers": len(layers), "query": "WFS point INTERSECTS per ward"})


CHC_BIL = "https://data.chc.ucsb.edu/products/CHIRPS-2.0/africa_monthly/bils/sub/v2p0chirps{y}{m:02d}.bil"
BIL_COLS, BIL_UL_LON, BIL_UL_LAT, BIL_RES = 1500, -19.975, 39.975, 0.05   # from the .hdr files (pixel centres)


def fetch_eastern_bil() -> None:
    """CHIRPS monthly 1981-2016 for the eastern box from CHC's uncompressed Africa BIL files.

    Each file is int16 mm/month, 1500 x 1600, rows of 3000 bytes. One multi-range
    request per file fetches just the 60 row segments covering the box (~6 KB),
    instead of the 4.8 MB file. Used because the IRI CHIRPS service timed out.
    """
    import numpy as np
    (x0, x1), (y0, y1) = EASTERN_BOX["lon"], EASTERN_BOX["lat"]
    c0 = int(round((x0 + BIL_RES / 2 - BIL_UL_LON) / BIL_RES))
    c1 = int(round((x1 - BIL_RES / 2 - BIL_UL_LON) / BIL_RES))
    r0 = int(round((BIL_UL_LAT - (y1 - BIL_RES / 2)) / BIL_RES))
    r1 = int(round((BIL_UL_LAT - (y0 + BIL_RES / 2)) / BIL_RES))
    rows, cols = list(range(r0, r1 + 1)), list(range(c0, c1 + 1))
    ranges = ",".join(f"{(r * BIL_COLS + c0) * 2}-{(r * BIL_COLS + c1) * 2 + 1}" for r in rows)
    months, years = [3, 4, 5, 10, 11, 12], list(range(1981, 2017))
    data = np.full((len(years), len(months), len(rows), len(cols)), -32768, dtype=np.int16)
    for yi, y in enumerate(years):
        for mi, m in enumerate(months):
            url = CHC_BIL.format(y=y, m=m)
            for attempt in range(4):
                try:
                    req = urllib.request.Request(url, headers={"User-Agent": UA, "Range": f"bytes={ranges}"})
                    with urllib.request.urlopen(req, timeout=180) as resp:
                        ctype, body = resp.headers.get("Content-Type", ""), resp.read()
                    break
                except Exception as e:
                    if attempt == 3:
                        raise
                    print(f"  retry after {e}")
                    time.sleep(10 * (attempt + 1))
            boundary = ctype.split("boundary=")[1].encode()
            for part in body.split(b"--" + boundary)[1:-1]:
                head, _, payload = part.partition(b"\r\n\r\n")
                start = int(re.search(rb"Content-Range: bytes (\d+)-", head).group(1))
                r = start // 2 // BIL_COLS
                data[yi, mi, rows.index(r)] = np.frombuffer(payload[:len(cols) * 2], dtype="<i2")
        print(f"  {y}: done")
    lats = [BIL_UL_LAT - r * BIL_RES for r in rows]
    lons = [BIL_UL_LON + c * BIL_RES for c in cols]
    path = OUT / "chirps_monthly_eastern_kenya.npz"
    OUT.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, precip=data, years=years, months=months, lat=lats, lon=lons)
    save_meta = {"dataset": "CHIRPS v2.0 monthly (mm/month), CHC Africa BIL files, multi-range reads",
                 "url_pattern": CHC_BIL, "box": EASTERN_BOX, "years": [years[0], years[-1]], "months": months}
    raw = path.read_bytes()
    (OUT / (path.name + ".meta.json")).write_text(json.dumps(
        {"url": CHC_BIL, "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
         "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw), **save_meta}, indent=2) + "\n",
        encoding="utf-8", newline="\n")
    print(f"saved {path.relative_to(REPO)} ({len(raw):,} B)")


def fetch_eastern() -> None:
    (x0, x1), (y0, y1) = EASTERN_BOX["lon"], EASTERN_BOX["lat"]
    url = (f"{IRI}/{CHIRPS_MONTHLY}/X/{x0}/{x1}/RANGEEDGES/Y/{y0}/{y1}/RANGEEDGES/"
           f"T/(Jan%201981)/(Dec%202025)/RANGE/data.nc")
    save("chirps_monthly_eastern_kenya.nc", get(url, 1800), url,
         {"dataset": "CHIRPS v2.0 monthly precipitation (mm/month), via IRI Data Library", "box": EASTERN_BOX})


if __name__ == "__main__":
    jobs = sys.argv[1:] or ["c3s", "ghacof", "eastern"]
    for job in jobs:
        print(f"== {job}")
        {"c3s": fetch_c3s, "c3s-neighbours": fetch_c3s_neighbours, "ghacof": fetch_ghacof, "eastern-bil": fetch_eastern_bil,
         "eastern": fetch_eastern}[job]()
