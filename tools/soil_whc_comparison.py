"""Before/after comparison of the soil water holding capacity change (Phase 7).

Usage (from the repo root):
  python tools/soil_whc_comparison.py BEFORE_RUNS_DIR AFTER_RUNS_DIR docs/pricing/soil-whc-comparison.json

Each runs dir holds one `agroshield-price run --all --offline` output (one
sub-folder per ward with results.json and manifest.json). BEFORE uses the
placeholder soil_whc_mm, AFTER the SoilGrids value. Only reads results; it never
prices anything itself.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


def _load(runs: Path) -> dict:
    out = {}
    for d in sorted(p for p in runs.iterdir() if p.is_dir()):
        res = d / "results.json"
        if not res.exists():
            continue
        r = json.loads(res.read_text(encoding="utf-8"))
        out[r["ward"]["id"]] = {"run_id": d.name, "results": r,
                                "results_sha256": hashlib.sha256(res.read_bytes()).hexdigest()}
    return out


def _season(s: dict) -> dict:
    t = s["target"]
    return {
        "soil_whc_mm": s["terms"]["soil_whc_mm"],
        "wrsi_median": s["wrsi_stats"]["median"], "wrsi_min": s["wrsi_stats"]["min"],
        "seasons": s["burn_cost"]["seasons"],
        "seasons_wrsi_below_trigger": s["wrsi_stats"]["below_trigger"],
        "main_payout_frequency": t["main"]["frequency"],
        "any_payout_frequency": t["combined"]["frequency"],
        "payout_frequency": s["burn_cost"]["payout_frequency"],
        "expected_loss": s["burn_cost"]["expected_loss"],
        "gross_rate": s["premium"]["gross_rate"],
        "event_tests": [{"year": e["year"], "wrsi": e["wrsi"], "payout": e["payout"], "passed": e["passed"]}
                        for e in s["event_tests"]],
        "wrsi_by_year": {str(h["year"]): h["wrsi"] for h in s["history"]},
        "payout_by_year": {str(h["year"]): h["payout"] for h in s["history"]},
    }


def compare(before: dict, after: dict) -> dict:
    wards = {}
    for wid in sorted(set(before) & set(after)):
        rb, ra = before[wid]["results"], after[wid]["results"]
        seasons = {}
        for sk in sorted(set(rb["seasons"]) & set(ra["seasons"])):
            b, a = _season(rb["seasons"][sk]), _season(ra["seasons"][sk])
            years = sorted(set(b["wrsi_by_year"]) | set(a["wrsi_by_year"]))
            per_year = []
            for y in years:
                wb, wa = b["wrsi_by_year"].get(y), a["wrsi_by_year"].get(y)
                pb, pa = b["payout_by_year"].get(y), a["payout_by_year"].get(y)
                per_year.append({"year": int(y), "wrsi_before": wb, "wrsi_after": wa,
                                 "wrsi_change": None if wb is None or wa is None else round(wa - wb, 2),
                                 "payout_before": pb, "payout_after": pa})
            changed_pay = [r["year"] for r in per_year if r["payout_before"] != r["payout_after"]]
            changes = [r["wrsi_change"] for r in per_year if r["wrsi_change"] is not None]
            seasons[sk] = {
                "before": {k: v for k, v in b.items() if k not in ("wrsi_by_year", "payout_by_year")},
                "after": {k: v for k, v in a.items() if k not in ("wrsi_by_year", "payout_by_year")},
                "wrsi_change_summary": {"seasons_compared": len(changes),
                                        "mean": round(sum(changes) / len(changes), 2) if changes else None,
                                        "min": min(changes) if changes else None,
                                        "max": max(changes) if changes else None,
                                        "seasons_changed": sum(1 for c in changes if c != 0)},
                "years_where_payout_changed": changed_pay,
                "per_year": per_year,
                "whc_sensitivity_after": ra["seasons"][sk]["whc_sensitivity"],
            }
        wards[wid] = {"before_run": before[wid]["run_id"], "before_results_sha256": before[wid]["results_sha256"],
                      "after_run": after[wid]["run_id"], "after_results_sha256": after[wid]["results_sha256"],
                      "soil_provenance_after": next(p for p in ra["provenance"]
                                                    if p["input"] == "Soil water holding capacity"),
                      "seasons": seasons}
    return wards


def main(argv: list[str]) -> int:
    before_dir, after_dir, out = (Path(a) for a in argv[1:4])
    data = {
        "status": "Needs owner approval: not merged into main",
        "label": ("Soil values REAL (SoilGrids 2.0 for each ward's extraction box); ward locations, triggers, "
                  "loadings and the rest of the pricing stay ILLUSTRATIVE"),
        "command": "agroshield-price run --all --offline (before: placeholder wards.yaml; after: SoilGrids wards.yaml)",
        "wards": compare(_load(before_dir), _load(after_dir)),
    }
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
