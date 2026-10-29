"""EXPERIMENTAL livestock feasibility: can a free satellite vegetation record support a pasture index in northern Kenya?

Research only. Nothing here feeds quotes, enrolment, pricing or config.

1. Probes which free NDVI sources answer (one small request each).
2. Downloads MODIS MOD13Q1 NDVI (250 m, 16-day composites, from Feb 2000) from the NASA ORNL DAAC subset web
   service for a 10 x 10 km box at two rangeland sites, with the pixel-reliability band, politely (one request at a
   time, a pause between requests). Cached in data/raw/ndvi/<site>.csv with a .meta.json and SHA-256, like CHIRPS.
3. Seasonal index per site: mean good-quality NDVI over each rainy season (long rains Mar-May, short rains Oct-Dec),
   as a z-score against all complete years 2001-2025.
4. A "one bad season in five" trigger: the 20th percentile. Because a percentile of the same record always fires
   about 20% of the time, the honest test is leave-one-out: each season is judged against a threshold set from all
   the other years. Also: do the two sites agree (spatial basis risk)?

    .venv/Scripts/python tools/research/livestock_ndvi.py           # fetch (if not cached) and analyse
    .venv/Scripts/python tools/research/livestock_ndvi.py --offline # analyse the cache only
"""
from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CACHE = REPO / "data" / "raw" / "ndvi"
OUT = REPO / "docs" / "research"
UA = "AgroShield-research/0.1 (livestock feasibility study; contact mrnwanngari@gmail.com)"
ORNL = "https://modis.ornl.gov/rst/api/v1"
PRODUCT = "MOD13Q1"
BANDS = {"ndvi": "250m_16_days_NDVI", "rel": "250m_16_days_pixel_reliability"}
KM = 5                                    # 5 km above/below and left/right of the centre: a 10 x 10 km box
PAUSE_S = 1.5
SITES = {
    "laisamis": {"label": "Around Laisamis, Marsabit County", "lat": 1.60, "lon": 37.81},
    "merti": {"label": "Around Merti, Isiolo County", "lat": 1.06, "lon": 38.67},
}
SEASONS = {"LR": (3, 5, "long rains, March to May"), "SR": (10, 12, "short rains, October to December")}
YEARS = (2001, 2025)
TRIGGER_PCTL = 0.20


def get(url: str, timeout: float = 120, tries: int = 4) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    for i in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(10 * (i + 1))


def probe() -> list[dict]:
    """Which free NDVI sources answer right now (one small request each; no bulk download)."""
    out = []
    lat, lon = SITES["laisamis"]["lat"], SITES["laisamis"]["lon"]
    try:
        d = json.loads(get(f"{ORNL}/{PRODUCT}/dates?latitude={lat}&longitude={lon}"))["dates"]
        out.append({"source": "NASA ORNL DAAC MODIS subset service, MOD13Q1 v061 NDVI (250 m, 16-day)", "reachable": True,
                    "first": d[0]["calendar_date"], "last": d[-1]["calendar_date"], "composites": len(d),
                    "url": "https://modis.ornl.gov/data/modis_webservice.html"})
    except Exception as e:
        out.append({"source": "NASA ORNL DAAC MODIS subset service", "reachable": False, "error": type(e).__name__})
    time.sleep(PAUSE_S)
    try:
        geom = {"type": "Polygon", "coordinates": [[[lon - .1, lat - .1], [lon + .1, lat - .1], [lon + .1, lat + .1],
                                                    [lon - .1, lat + .1], [lon - .1, lat - .1]]]}
        q = urllib.parse.urlencode({"datatype": 2, "begintime": "01/01/2015", "endtime": "06/30/2015", "intervaltype": 0,
                                    "operationtype": 5, "geometry": json.dumps(geom), "isZip_CurrentDataType": "false"})
        base = "https://climateserv.servirglobal.net/api"
        job = json.loads(get(f"{base}/submitDataRequest/?{q}"))[0]
        for _ in range(60):
            pr = json.loads(get(f"{base}/getDataRequestProgress/?id={job}"))[0]
            if pr == -1 or pr >= 100:
                break
            time.sleep(4)
        n = len(json.loads(get(f"{base}/getDataFromRequest/?id={job}"))["data"]) if pr >= 100 else 0
        out.append({"source": "SERVIR ClimateSERV, eMODIS NDVI East Africa (dataset 2)", "reachable": n > 0,
                    "note": f"request completed but returned {n} values for this area and period" if n == 0 else f"{n} values",
                    "url": "https://climateserv.servirglobal.net/"})
    except Exception as e:
        out.append({"source": "SERVIR ClimateSERV eMODIS NDVI", "reachable": False, "error": type(e).__name__})
    time.sleep(PAUSE_S)
    try:
        st = urllib.request.urlopen(urllib.request.Request("https://earlywarning.usgs.gov/fews/datadownloads/East%20Africa/eMODIS%20NDVI%20C6",
                                                           headers={"User-Agent": UA}), timeout=60).status
        out.append({"source": "USGS FEWS NET eMODIS NDVI C6 East Africa (bulk files)", "reachable": st == 200,
                    "note": "listing reachable; not used here because the files are whole-region rasters"})
    except Exception as e:
        out.append({"source": "USGS FEWS NET eMODIS NDVI C6 East Africa (bulk files)", "reachable": False, "error": type(e).__name__})
    return out


def fetch_site(key: str, site: dict, log=print) -> Path:
    csv, meta = CACHE / f"{key}.csv", CACHE / f"{key}.meta.json"
    if csv.exists() and meta.exists() and hashlib.sha256(csv.read_bytes()).hexdigest() == json.loads(meta.read_text())["sha256"]:
        return csv
    dates = json.loads(get(f"{ORNL}/{PRODUCT}/dates?latitude={site['lat']}&longitude={site['lon']}"))["dates"]
    rows = {}
    for i in range(0, len(dates), 10):                       # the service returns at most 10 composites per request
        chunk = dates[i:i + 10]
        for band, name in BANDS.items():
            q = urllib.parse.urlencode({"latitude": site["lat"], "longitude": site["lon"], "band": name,
                                        "startDate": chunk[0]["modis_date"], "endDate": chunk[-1]["modis_date"],
                                        "kmAboveBelow": KM, "kmLeftRight": KM})
            sub = json.loads(get(f"{ORNL}/{PRODUCT}/subset?{q}"))
            for s in sub["subset"]:
                rows.setdefault(s["calendar_date"], {})[band] = s["data"]
            time.sleep(PAUSE_S)
        log(f"  {key}: {min(i + 10, len(dates))}/{len(dates)} composites")
    CACHE.mkdir(parents=True, exist_ok=True)
    lines = ["date,ndvi_mean_good,good_pixels,total_pixels"]
    for d in sorted(rows):
        nd, rel = rows[d].get("ndvi", []), rows[d].get("rel", [])
        good = [v * 0.0001 for v, r in zip(nd, rel) if r in (0, 1) and v > -2000]   # good or marginal quality
        lines.append(f"{d},{statistics.fmean(good):.4f},{len(good)},{len(nd)}" if good else f"{d},,0,{len(nd)}")
    csv.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    meta.write_text(json.dumps({
        "site": key, **site, "product": f"{PRODUCT} (MODIS Terra vegetation indices, 16-day, 250 m)",
        "provider": "NASA ORNL DAAC MODIS/VIIRS subset web service", "service": ORNL,
        "box_km": 2 * KM, "quality": "pixels with reliability 0 (good) or 1 (marginal); fill values dropped",
        "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sha256": hashlib.sha256(csv.read_bytes()).hexdigest()}, indent=2) + "\n", newline="\n")
    return csv


def load(csv: Path) -> list[tuple[date, float, float]]:
    out = []
    for line in csv.read_text(encoding="utf-8").splitlines()[1:]:
        d, v, good, tot = line.split(",")
        if v:
            out.append((date.fromisoformat(d), float(v), int(good) / max(1, int(tot))))
    return out


def seasonal(series) -> dict:
    """(season, year) -> mean NDVI of composites starting inside the season months, with the share of good pixels."""
    out = {}
    for se, (m0, m1, _) in SEASONS.items():
        for y in range(YEARS[0], YEARS[1] + 1):
            vals = [(v, q) for d, v, q in series if d.year == y and m0 <= d.month <= m1]
            if len(vals) >= 4:
                out[(se, y)] = {"ndvi": statistics.fmean(v for v, _ in vals), "composites": len(vals),
                                "good_share": statistics.fmean(q for _, q in vals)}
    for se in SEASONS:
        xs = [v["ndvi"] for (s, _), v in out.items() if s == se]
        mu, sd = statistics.fmean(xs), statistics.pstdev(xs)
        for (s, y), v in out.items():
            if s == se:
                v["z"] = (v["ndvi"] - mu) / sd if sd else 0.0
    return out


def pctl(xs: list[float], p: float) -> float:
    xs = sorted(xs)
    k = (len(xs) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def analyse(by_site: dict) -> dict:
    res = {}
    for key, ss in by_site.items():
        site = {"seasons": {}}
        for se in SEASONS:
            yrs = sorted(y for (s, y) in ss if s == se)
            zs = {y: ss[(se, y)]["z"] for y in yrs}
            thr_in = pctl(list(zs.values()), TRIGGER_PCTL)
            loo = {y: zs[y] <= pctl([zs[o] for o in yrs if o != y], TRIGGER_PCTL) for y in yrs}
            fired = [y for y in yrs if loo[y]]
            runs = sum(1 for y in fired if y - 1 in fired)
            site["seasons"][se] = {
                "years": yrs, "z": {str(y): round(zs[y], 3) for y in yrs},
                "ndvi": {str(y): round(ss[(se, y)]["ndvi"], 4) for y in yrs},
                "good_share": {str(y): round(ss[(se, y)]["good_share"], 3) for y in yrs},
                "in_sample_threshold_z": round(thr_in, 3),
                "fired_leave_one_out": fired, "fire_rate_leave_one_out": round(len(fired) / len(yrs), 3),
                "back_to_back_years": runs}
        res[key] = site
    # spatial agreement: same season and year, both sites
    a, b = list(by_site)
    agree = {}
    for se in SEASONS:
        fa, fb = set(res[a]["seasons"][se]["fired_leave_one_out"]), set(res[b]["seasons"][se]["fired_leave_one_out"])
        za, zb = res[a]["seasons"][se]["z"], res[b]["seasons"][se]["z"]
        common = sorted(set(za) & set(zb))
        r = statistics.correlation([za[y] for y in common], [zb[y] for y in common]) if len(common) > 2 else None
        agree[se] = {"both": sorted(fa & fb), "only_" + a: sorted(fa - fb), "only_" + b: sorted(fb - fa),
                     "z_correlation": round(r, 3) if r is not None else None}
    return {"sites": res, "agreement": agree}


SVG_W, SVG_H = 760, 220


def chart(site: dict, se: str) -> str:
    s = site["seasons"][se]
    yrs = s["years"]
    zs = [s["z"][str(y)] for y in yrs]
    lo, hi = min(-2.5, min(zs)), max(2.5, max(zs))
    step = (SVG_W - 60) / len(yrs)
    y0 = lambda z: 20 + (hi - z) / (hi - lo) * (SVG_H - 50)                         # noqa: E731
    bars = []
    for i, (yr, z) in enumerate(zip(yrs, zs)):
        x = 40 + i * step
        top, bot = sorted((y0(0), y0(z)))
        cls = "hit" if yr in s["fired_leave_one_out"] else "bar"
        bars.append(f'<rect class="{cls}" x="{x + step * .15:.1f}" y="{top:.1f}" width="{step * .7:.1f}" height="{max(1, bot - top):.1f}">'
                    f'<title>{yr}: z = {z:+.2f}{" (trigger)" if cls == "hit" else ""}</title></rect>')
        if i % 4 == 0:
            bars.append(f'<text x="{x + step / 2:.1f}" y="{SVG_H - 8}" text-anchor="middle">{yr}</text>')
    thr = s["in_sample_threshold_z"]
    return (f'<svg viewBox="0 0 {SVG_W} {SVG_H}" role="img" aria-label="Seasonal NDVI z-score by year, {SEASONS[se][2]}">'
            f'<line class="axis" x1="36" x2="{SVG_W}" y1="{y0(0):.1f}" y2="{y0(0):.1f}"/>'
            f'<line class="thr" x1="36" x2="{SVG_W}" y1="{y0(thr):.1f}" y2="{y0(thr):.1f}"/>'
            f'<text x="40" y="{y0(thr) + 14:.1f}">1 in 5 line (z {thr:+.2f})</text>' + "".join(bars) + "</svg>")


def html(report: dict) -> str:
    a = report["analysis"]
    rows = "".join(f"<tr><td>{p['source']}</td><td>{'yes' if p.get('reachable') else 'no'}</td>"
                   f"<td>{(p['first'] + ' to ' + p['last']) if p.get('first') else ''}</td><td>{p.get('note') or p.get('error') or ''}</td></tr>"
                   for p in report["probes"])
    parts = []
    for key, site in a["sites"].items():
        parts.append(f"<h2>{SITES[key]['label']}</h2><p class='muted'>Box of 10 by 10 km centred on {SITES[key]['lat']} N, "
                     f"{SITES[key]['lon']} E (approximate rangeland location, chosen for this test only).</p>")
        for se, s in site["seasons"].items():
            parts.append(f"<h3>{SEASONS[se][2][:1].upper() + SEASONS[se][2][1:]}</h3>{chart(site, se)}"
                         f"<p>Seasons judged below the line, each against a threshold set from the other years: "
                         f"<b>{', '.join(map(str, s['fired_leave_one_out'])) or 'none'}</b> "
                         f"({s['fire_rate_leave_one_out'] * 100:.0f}% of {len(s['years'])} seasons; "
                         f"{s['back_to_back_years']} back-to-back).</p>")
    ag = "".join(f"<li>{SEASONS[se][2][:1].upper() + SEASONS[se][2][1:]}: both sites below the line in {', '.join(map(str, v['both'])) or 'no year'}; "
                 f"correlation of the two sites' scores {v['z_correlation']}.</li>" for se, v in a["agreement"].items())
    findings = "".join(f"<li>{f}</li>" for f in report["findings"])
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Livestock feasibility (experimental)</title>
<style>
:root {{ --bg:#F6F3EC; --ink:#1C1F26; --ink2:#4A4F5C; --accent:#00695C; --warn:#8A5600; --hit:#B3261E; --line:#D9D3C7; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#0F1117; --ink:#ECEDEF; --ink2:#B6BAC4; --accent:#2DD4BF; --warn:#F5B547; --hit:#FF8A80; --line:#2A2D36; }} }}
body {{ margin:0; background:var(--bg); color:var(--ink); font:16px/1.55 system-ui, sans-serif; }}
main {{ max-width: 900px; margin: 0 auto; padding: 24px 16px 64px; }} h1, h2, h3 {{ line-height:1.2; }}
.badge {{ display:inline-block; background:var(--warn); color:var(--bg); font-weight:700; padding:4px 10px; border-radius:999px; font-size:13px; }}
.muted {{ color:var(--ink2); font-size:14px; }} table {{ border-collapse:collapse; width:100%; font-size:14px; }}
td, th {{ border-bottom:1px solid var(--line); padding:6px 8px; text-align:left; vertical-align:top; }}
svg {{ width:100%; height:auto; }} svg text {{ fill:var(--ink2); font-size:12px; }} .axis {{ stroke:var(--line); }}
.thr {{ stroke:var(--warn); stroke-dasharray:5 4; stroke-width:2; }} .bar {{ fill:var(--accent); }} .hit {{ fill:var(--hit); }}
.box {{ border:1px dashed var(--warn); padding:12px 16px; border-radius:8px; }}
</style></head><body><main>
<p><span class="badge">EXPERIMENTAL: research only</span></p>
<h1>Livestock cover: is the satellite data good enough?</h1>
<p class="box">This is a feasibility test, not a product. Nothing here is used in quotes, enrolment, pricing or config, and
livestock cover is not available. Generated {report['generated_at']} by <code>tools/research/livestock_ndvi.py</code>.</p>
<h2>Which free NDVI data could we reach?</h2>
<table><thead><tr><th>Source</th><th>Reachable</th><th>Record</th><th>Note</th></tr></thead><tbody>{rows}</tbody></table>
<h2>Method</h2>
<ul><li>MODIS MOD13Q1 NDVI, 250 m, 16-day composites, good or marginal pixels only, averaged over a 10 by 10 km box.</li>
<li>Seasonal index: the mean NDVI over each rainy season (long rains March to May, short rains October to December),
expressed as a z-score against {YEARS[0]} to {YEARS[1]}.</li>
<li>Trigger: the 20th percentile, roughly one bad season in five. Each season is judged against a threshold built from the
other years only (leave one out), so the result is not forced to 20%.</li>
<li>Real schemes in Kenya (IBLI, KLIP) use their own NDVI products and area units; this test does not reproduce them.</li></ul>
<h2>Findings</h2><ul>{findings}</ul>
{''.join(parts)}
<h2>Do the two sites agree?</h2><ul>{ag}</ul>
<h2>What would still be needed</h2>
<ul><li>Real insurance units (for example sub-locations) and their boundaries instead of 10 km boxes.</li>
<li>Livestock loss or body-condition data to measure basis risk; without it, the trigger can only be checked against
other indices.</li>
<li>A forage-season definition agreed with pastoral experts for each area, and a check against known drought years.</li>
<li>A licensed partner insurer (to be named) and regulator approval before anything is offered.</li></ul>
<h2>Sources</h2><ol>
<li><a href="https://modis.ornl.gov/data/modis_webservice.html">MODIS/VIIRS web service</a>, NASA ORNL DAAC.</li>
<li><a href="https://lpdaac.usgs.gov/products/mod13q1v061/">MOD13Q1 v061 product page</a>, NASA LP DAAC.</li>
<li><a href="https://documents1.worldbank.org/curated/en/888931613729186587/pdf/Building-Financial-Resilience-in-Pastoral-Communities-in-Africa-Lessons-Learned-from-Implementing-the-Kenya-Livestock-Insurance-Program-KLIP.pdf">Lessons learned from implementing KLIP</a>, World Bank Group with ILRI.</li>
<li><a href="https://cgspace.cgiar.org/bitstreams/71636f2a-da64-4005-9740-2c43826eb5ec/download">Coping with Drought: IBLI in Kenya</a>, BASIS / UC Davis, 2012.</li>
</ol></main></body></html>
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    args = ap.parse_args()
    probes = [] if args.offline else probe()
    by_site = {}
    for key, site in SITES.items():
        csv = CACHE / f"{key}.csv"
        if not args.offline:
            print("fetching", key)
            csv = fetch_site(key, site)
        if not csv.exists():
            print(f"no cached NDVI for {key}; run without --offline", file=sys.stderr)
            return 1
        by_site[key] = seasonal(load(csv))
    analysis = analyse(by_site)
    findings = []
    for key, site in analysis["sites"].items():
        for se, s in site["seasons"].items():
            findings.append(f"{SITES[key]['label']}, {SEASONS[se][2]}: {len(s['years'])} seasons of data; a one-in-five line "
                            f"would have been crossed in {len(s['fired_leave_one_out'])} of them "
                            f"({', '.join(map(str, s['fired_leave_one_out'])) or 'none'}).")
    a_key, b_key = list(SITES)
    for se, v in analysis["agreement"].items():
        either = len(v["both"]) + len(v["only_" + a_key]) + len(v["only_" + b_key])
        findings.append(f"Two sites about 110 km apart, {SEASONS[se][2]}: the seasonal scores move together (correlation "
                        f"{v['z_correlation']}), but of the {either} seasons below the line at either site, only "
                        f"{len(v['both'])} were below it at both. Which seasons trigger depends on where the index is "
                        "measured, so one index for a wide area would carry real basis risk: units need to be small.")
    # The one external check we have a source for: KLIP paid out in both seasons of 2016-17 across its six counties
    # (World Bank KLIP paper, Table 1). Different counties and area units, so this is an indicator, not a test of KLIP.
    klip = []
    for key, site in analysis["sites"].items():
        sr16, lr17 = site["seasons"]["SR"]["z"].get("2016"), site["seasons"]["LR"]["z"].get("2017")
        fired = [s for s, y in (("SR", 2016), ("LR", 2017)) if y in site["seasons"][s]["fired_leave_one_out"]]
        klip.append(f"{SITES[key]['label']}: short rains 2016 z {sr16:+.2f}, long rains 2017 z {lr17:+.2f}; "
                    f"below the line in {len(fired)} of the 2 seasons in which KLIP paid out (in other counties).")
    findings += klip
    report = {"label": "EXPERIMENTAL", "purpose": "livestock feasibility only; not used in quotes, enrolment, pricing or config",
              "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "probes": probes,
              "sites": SITES, "seasons": {k: v[2] for k, v in SEASONS.items()}, "years": YEARS,
              "trigger_percentile": TRIGGER_PCTL, "analysis": analysis, "findings": findings}
    if args.offline and (OUT / "livestock-feasibility.json").exists():
        report["probes"] = json.loads((OUT / "livestock-feasibility.json").read_text(encoding="utf-8")).get("probes", [])
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "livestock-feasibility.json").write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8", newline="\n")
    (OUT / "livestock-feasibility.html").write_text(html(report), encoding="utf-8", newline="\n")
    print("\n".join(findings))
    return 0


if __name__ == "__main__":
    sys.exit(main())
