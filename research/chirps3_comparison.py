"""CHIRPS v2.0 against CHIRPS v3.0: the same pricing engine on both rainfall datasets.

Prices every pilot ward twice from the committed caches (no downloads):
  * data/raw/chirps/   CHIRPS v2.0 daily, polygon mean from SERVIR ClimateSERV
  * data/raw/chirps3/  CHIRPS v3.0 daily (rnl), polygon mean of the same 4 pixels
with the same PET, the same config and the same product terms, and writes
docs/pricing/chirps3-comparison.json. The Markdown note beside it is written
by hand from this JSON.

    .venv/Scripts/python research/chirps3_comparison.py

Nothing here changes pricing: config/pilot.yaml keeps rainfall.source: chirps.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from agroshield_pricing.config import load_config  # noqa: E402
from agroshield_pricing.engine import price_ward  # noqa: E402
from agroshield_pricing.pet import make_pet_source  # noqa: E402
from agroshield_pricing.rainfall import make_source  # noqa: E402
from agroshield_pricing.wrsi import to_dekads  # noqa: E402

OUT = REPO / "docs" / "pricing" / "chirps3-comparison.json"
RESEARCH = REPO / "data" / "raw" / "research"
NAMES = {"chirps": "CHIRPS v2.0", "chirps3": "CHIRPS v3.0"}
YEARS_OF_NOTE = (1984, 2008)
LARGE_WRSI_GAP = 10.0          # points; seasons at or above this are listed and explained


def _r(x, n=2):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else round(float(x), n)


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def season_rows(summary: dict) -> pd.DataFrame:
    h = pd.DataFrame(summary["history"]).set_index("year")
    return h


def price(cfg, ds: str) -> dict:
    rs = make_source(cfg, ds, allow_download=False)
    ps = make_pet_source(cfg, allow_download=False)
    return {wid: price_ward(cfg, wid, rs, ps) for wid in cfg.pilot.wards}


def rainfall_agreement(r2: pd.Series, r3: pd.Series, y0: int, y1: int) -> dict:
    """How closely the two daily series agree, at the time steps the index uses."""
    a, b = r2.loc[f"{y0}-01-01":f"{y1}-12-31"], r3.loc[f"{y0}-01-01":f"{y1}-12-31"]
    da, db = to_dekads(a), to_dekads(b)
    ann_a, ann_b = a.groupby(a.index.year).sum(), b.groupby(b.index.year).sum()
    mam_a = a[a.index.month.isin([3, 4, 5])].groupby(a[a.index.month.isin([3, 4, 5])].index.year).sum()
    mam_b = b[b.index.month.isin([3, 4, 5])].groupby(b[b.index.month.isin([3, 4, 5])].index.year).sum()
    return {
        "annual_mean_mm": {"v2": _r(ann_a.mean(), 1), "v3": _r(ann_b.mean(), 1),
                           "v3_minus_v2_pct": _r(100 * (ann_b.mean() / ann_a.mean() - 1), 1)},
        "march_to_may_mean_mm": {"v2": _r(mam_a.mean(), 1), "v3": _r(mam_b.mean(), 1),
                                 "v3_minus_v2_pct": _r(100 * (mam_b.mean() / mam_a.mean() - 1), 1)},
        "correlation_daily": _r(np.corrcoef(a, b)[0, 1], 3),
        "correlation_dekadal": _r(np.corrcoef(da, db)[0, 1], 3),
        "correlation_annual": _r(np.corrcoef(ann_a, ann_b)[0, 1], 3),
        "correlation_march_to_may": _r(np.corrcoef(mam_a, mam_b)[0, 1], 3),
        "decade_mean_annual_mm": [{"years": f"{d}-{min(d + 9, y1)}", "v2": _r(ann_a.loc[d:d + 9].mean(), 0),
                                   "v3": _r(ann_b.loc[d:d + 9].mean(), 0)} for d in range(y0, y1 + 1, 10)],
        "annual_totals_mm": [{"year": int(y), "v2": _r(ann_a[y], 1), "v3": _r(ann_b[y], 1)} for y in ann_a.index],
    }


def ward_block(cfg, wid: str, w2, w3) -> dict:
    s2, s3 = w2.summary["seasons"]["LR"], w3.summary["seasons"]["LR"]
    h2, h3 = season_rows(s2), season_rows(s3)
    trig = s2["terms"]["trigger_wrsi"]
    seasons = []
    for y in h2.index:
        a, b = h2.loc[y], h3.loc[y]
        seasons.append({
            "year": int(y),
            "sos": {"v2": a["sos"], "v3": b["sos"]},
            "season_rain_mm": {"v2": _r(a["season_rain_mm"], 1), "v3": _r(b["season_rain_mm"], 1)},
            "wrsi": {"v2": _r(a["wrsi"]), "v3": _r(b["wrsi"])},
            "wrsi_gap": _r(b["wrsi"] - a["wrsi"]) if a["wrsi"] is not None and b["wrsi"] is not None else None,
            "failed_onset": {"v2": bool(a["failed_onset"]), "v3": bool(b["failed_onset"])},
            "germination_failed": {"v2": bool(a["germination_failed"]), "v3": bool(b["germination_failed"])},
            "payout_share": {"v2": _r(a["payout"], 4), "v3": _r(b["payout"], 4)},
            "payout_kes_per_acre": {"v2": _r(a["payout_kes"], 0), "v3": _r(b["payout_kes"], 0)},
        })

    def paid(h):
        return [int(y) for y in h.index if h.loc[y, "payout"] > 0]

    def key(s):
        b, p = s["burn_cost"], s["premium"]
        return {"payout_seasons": b["payout_seasons"], "payout_frequency": _r(b["payout_frequency"], 4),
                "expected_loss": _r(b["expected_loss"], 4), "loss_1_in_10": _r(b["loss_1_in_10"], 4),
                "loss_1_in_20": _r(b["loss_1_in_20"], 4), "max_loss": _r(b["max_loss"], 4),
                "gross_rate": _r(p["gross_rate"], 4),
                "gross_kes_per_acre_at_10000": _r(s["combined_gross_per_acre"]["total_gross_kes"], 0),
                "wrsi_median": s["wrsi_stats"]["median"], "wrsi_min": s["wrsi_stats"]["min"],
                "seasons_below_trigger": s["wrsi_stats"]["below_trigger"],
                "germination_vouchers": s["onset_stats"]["germination_failures"],
                "failed_onsets": s["onset_stats"]["failed_onsets"],
                "event_tests": [{k: e[k] for k in ("year", "wrsi", "payout", "required", "passed")}
                                for e in s["event_tests"]]}

    p2, p3 = paid(h2), paid(h3)
    gaps = [s for s in seasons if s["wrsi_gap"] is not None and abs(s["wrsi_gap"]) >= LARGE_WRSI_GAP]
    flips = [s["year"] for s in seasons if (s["payout_share"]["v2"] > 0) != (s["payout_share"]["v3"] > 0)]
    return {
        "ward": {"id": wid, "name": w2.summary["ward"]["name"]},
        "trigger_wrsi": trig,
        "rainfall": rainfall_agreement(w2.rain_daily, w3.rain_daily, cfg.rainfall.history.start_year,
                                       cfg.rainfall.history.end_year),
        "summary": {"v2": key(s2), "v3": key(s3)},
        "payout_years": {"v2": p2, "v3": p3, "both": sorted(set(p2) & set(p3)),
                         "only_v2": sorted(set(p2) - set(p3)), "only_v3": sorted(set(p3) - set(p2))},
        "payout_status_changes": flips,
        "large_wrsi_gaps": [{"year": s["year"], "v2": s["wrsi"]["v2"], "v3": s["wrsi"]["v3"],
                             "season_rain_v2": s["season_rain_mm"]["v2"], "season_rain_v3": s["season_rain_mm"]["v3"],
                             "sos_v2": s["sos"]["v2"], "sos_v3": s["sos"]["v3"]} for s in gaps],
        # Over the seasons that have a WRSI on both datasets (a failed onset has none).
        "wrsi_correlation": _r(pd.concat([h2["wrsi"], h3["wrsi"]], axis=1).astype(float).dropna().corr().iloc[0, 1], 3),
        "wrsi_mean_abs_gap": _r(np.nanmean([abs(s["wrsi_gap"]) for s in seasons if s["wrsi_gap"] is not None]), 2),
        "years_of_note": {str(y): next(s for s in seasons if s["year"] == y) for y in YEARS_OF_NOTE},
        "seasons": seasons,
    }


def research_summary() -> dict:
    """The early trigger and the advance on both datasets, from the research result files."""
    out = {}
    for ds, sfx in (("chirps", ""), ("chirps3", ".chirps3")):
        et, ad = RESEARCH / f"early_trigger_results{sfx}.json", RESEARCH / f"advance_results{sfx}.json"
        block = {}
        if et.exists():
            e = json.loads(et.read_text())
            block["early_trigger"] = {w: {k: r.get(k) for k in ("seasons", "actual_below_trigger_seasons",
                                                               "corr_projected_vs_actual", "with_gefs",
                                                               "gross_kes_per_acre")}
                                      for w, r in e["wards"].items()}
        if ad.exists():
            a = json.loads(ad.read_text())
            if et.exists():
                # The committed v2 file covers only the offered ward; check every ward the same
                # way (in memory, the committed file is not rewritten).
                import advance
                a = advance.run(None if ds == "chirps" else ds, load_config(REPO / "config").pilot.wards,
                                write=False)
            block["advance"] = {w: {"offered": r.get("offered", True), "seasons": r["seasons"],
                                    "missing_years": r["missing_years"], "in_sample": r["in_sample"],
                                    "loocv_out_of_sample": r["loocv"]["out_of_sample"],
                                    "pricing": r["pricing"]}
                                for w, r in a["wards"].items()}
        out[ds] = block
    return out


def run() -> dict:
    cfg = load_config(REPO / "config")
    v2, v3 = price(cfg, "chirps"), price(cfg, "chirps3")
    m3 = {w: json.loads((REPO / "data" / "raw" / "chirps3" / f"{w}.meta.json").read_text()) for w in cfg.pilot.wards}
    return {
        "status": "Needs owner approval: not merged into main. Pricing on main stays on CHIRPS v2.0.",
        "generated_by": "research/chirps3_comparison.py",
        "index_version": cfg.product.layer_b.version,
        "history": cfg.rainfall.history.model_dump(),
        "config_sha256": cfg.file_hashes,
        "inputs": {w: {"chirps_v2": {"file": f"data/raw/chirps/{w}.csv",
                                      "sha256": _sha(REPO / "data" / "raw" / "chirps" / f"{w}.csv")},
                       "chirps_v3": {"file": f"data/raw/chirps3/{w}.csv", "sha256": m3[w]["sha256"],
                                     "last_date": m3[w]["last_date"],
                                     "pixels": m3[w]["request"]["pixels"]}}
                   for w in cfg.pilot.wards},
        "pixel_rule_check": json.loads((REPO / "data" / "raw" / "chirps3" / "checks" /
                                        "v2_pixel_rule_2008.json").read_text())["result"],
        "wards": {w: ward_block(cfg, w, v2[w], v3[w]) for w in cfg.pilot.wards},
        "research": research_summary(),
    }


if __name__ == "__main__":
    out = run()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1, default=str) + "\n", encoding="utf-8", newline="\n")
    for w, b in out["wards"].items():
        print(w, json.dumps(b["summary"], default=str))
        print("  payout years", b["payout_years"])
        print("  rainfall", {k: v for k, v in b["rainfall"].items() if k != "annual_totals_mm"})
        print("  large gaps", b["large_wrsi_gaps"])
        print("  of note", json.dumps(b["years_of_note"], default=str))
    print(f"wrote {OUT}")
