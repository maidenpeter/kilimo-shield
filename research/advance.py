"""EXPERIMENTAL early advance on Layer B at Ward A: validation and pricing.

Uses the day-35 projected WRSI already computed by research/early_trigger.py
(observed CHIRPS + CHIRPS-GEFS + leave-one-out climatology, cached in
data/raw/research/early_trigger_results.json) and the final Layer B payout from
the engine. Writes data/raw/research/advance_results.json.

    .venv/Scripts/python research/advance.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from agroshield_pricing import advance as adv  # noqa: E402
from agroshield_pricing.config import load_config  # noqa: E402
from agroshield_pricing.engine import price_ward  # noqa: E402
from agroshield_pricing.pet import make_pet_source  # noqa: E402
from agroshield_pricing.rainfall import make_source  # noqa: E402

PROJECTIONS = REPO / "data" / "raw" / "research" / "early_trigger_results.json"
OUT = REPO / "data" / "raw" / "research" / "advance_results.json"


def _equivalent_range(proj: pd.Series, t: float) -> list[float]:
    """Thresholds that make exactly the same decisions as t on these seasons: (highest value below t, lowest at or above]."""
    below, above = proj[proj < t], proj[proj >= t]
    return [round(float(below.max()), 2) if len(below) else None, round(float(above.min()), 2) if len(above) else None]


def run() -> dict:
    cfg = load_config(REPO / "config")
    a = cfg.product.layer_b.advance
    proj_all = json.loads(PROJECTIONS.read_text())
    if proj_all["check_day"] != a.check_day_after_sos:
        raise SystemExit(f"projections are for day {proj_all['check_day']}, config says {a.check_day_after_sos}; "
                         "re-run research/early_trigger.py")
    rs, ps = make_source(cfg, allow_download=False), make_pet_source(cfg, allow_download=False)
    out = {"terms": a.model_dump(), "wards": {}}
    for wid in a.offered_wards:
        table = price_ward(cfg, wid, rs, ps).seasons["LR"].table
        hist = pd.DataFrame(proj_all["wards"][wid]["history"]).set_index("year")
        y0, y1 = a.validation_years
        hist = hist[(hist.index >= y0) & (hist.index <= y1)]
        final = (table["failed_onset_share"] + table["wrsi_share"]).reindex(hist.index)
        proj = hist["projected_wrsi"]
        o = adv.outcomes(proj, final, a.projected_wrsi_below, a.advance_share)
        missing = [y for y in range(y0, y1 + 1) if y not in hist.index]
        out["wards"][wid] = {
            "seasons": int(len(hist)), "years": [y0, y1], "missing_years": missing,
            "missing_note": "No CHIRPS-GEFS file for the check day (HTTP 404 on the CHC archive)." if missing else None,
            "in_sample": adv.verify(o["fired"].to_numpy(), o["event"].to_numpy()),
            "loocv": adv.leave_one_out(proj, final, a.threshold_grid, a.projected_wrsi_below, a.advance_share),
            # Same, but ties go to the LOWEST threshold (fewest advances), so the configured 95 gets no help.
            "loocv_conservative": adv.leave_one_out(proj, final, a.threshold_grid, min(a.threshold_grid),
                                                    a.advance_share),
            "equivalent_range": _equivalent_range(proj, a.projected_wrsi_below),
            "sensitivity": [{"threshold": t, **adv.verify((proj < t).to_numpy(), (final > 0).to_numpy()),
                             "expected_extra_share": float(adv.outcomes(proj, final, t, a.advance_share)["extra_share"].mean())}
                            for t in a.threshold_grid],
            "pricing": adv.price_extra(o["extra_share"], cfg),
            "history": [{"year": int(y), "sos": hist.loc[y, "sos"], "projected_wrsi": float(r["projected_wrsi"]),
                         "actual_wrsi": float(hist.loc[y, "actual_wrsi"]), "final_share": float(r["final_share"]),
                         "fired": bool(r["fired"]), "farmer_receives_share": float(r["farmer_receives_share"]),
                         "extra_share": float(r["extra_share"])} for y, r in o.iterrows()],
        }
    OUT.write_text(json.dumps(out, indent=1, default=str) + "\n", encoding="utf-8", newline="\n")
    return out


if __name__ == "__main__":
    r = run()
    for wid, w in r["wards"].items():
        print(wid, "in-sample", w["in_sample"])
        print("  LOOCV", w["loocv"]["out_of_sample"], w["loocv"]["thresholds_chosen"])
        print("  LOOCV conservative", w["loocv_conservative"]["out_of_sample"], w["loocv_conservative"]["thresholds_chosen"])
        print("  same decisions for thresholds in", w["equivalent_range"])
        print("  price", w["pricing"])
