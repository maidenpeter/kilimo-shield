"""Build the research 3b report: docs/research/3b-forecast-skill.html (+ results JSON).

Run after research/fetch_data.py and research/early_trigger.py:
    .venv/Scripts/python research/report_3b.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from html import escape
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(Path(__file__).parent))

import jinja2  # noqa: E402

from agroshield_pricing import svgcharts as sc  # noqa: E402
from agroshield_pricing.config import load_config  # noqa: E402
from agroshield_pricing.engine import price_ward  # noqa: E402
from agroshield_pricing.layer_a import run_layer_a, verify  # noqa: E402
from agroshield_pricing.pet import make_pet_source  # noqa: E402
from agroshield_pricing.rainfall import make_source  # noqa: E402

import skill  # noqa: E402

RAW = REPO / "data" / "raw" / "research"
OUT = REPO / "docs" / "research"
PREVIOUS_PLACEHOLDER_SKILL = 0.45   # milestone 3 placeholder, replaced by the measured value
BLUE_RAMP = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]  # sequential, light -> dark


def c3s_cells() -> dict[str, Path]:
    return {p.stem.replace("c3s_seas51_hindcast_", ""): p for p in sorted(RAW.glob("c3s_seas51_hindcast_*.csv"))}


def c3s_skill_for_file(path: Path, ward_id: str, season: str) -> dict:
    df = pd.read_csv(path)
    ens = df[df["season"] == season].pivot(index="year", columns="member", values="mean_mm_per_day")
    obs = skill.observed_season_totals(ward_id, season).reindex(ens.index)
    prob = pd.Series({y: float((ens.loc[y] < np.percentile(ens.drop(y).to_numpy().ravel(), 100 / 3)).mean())
                      for y in ens.index})
    below = skill.loo_lower_tercile(obs)
    return {"correlation": skill.corr_ci(ens.mean(axis=1).to_numpy(), obs.to_numpy()),
            "tercile": skill.scores(prob, below), "prob": prob, "below": below, "obs": obs, "ens_mean": ens.mean(axis=1)}


def heatmap(cells: list[dict], key: str, label: str, vmin: float, vmax: float, fmt, towns: dict) -> str:
    lats = sorted({c["lat"] for c in cells})
    lons = sorted({c["lon"] for c in cells})
    W, H, PADL, PADT = 560, 640, 50, 10
    cw, ch = (W - PADL - 10) / len(lons), (H - PADT - 40) / len(lats)
    xi = {v: i for i, v in enumerate(lons)}
    yi = {v: i for i, v in enumerate(sorted(lats, reverse=True))}
    parts = []
    for c in cells:
        v = (c[key] - vmin) / (vmax - vmin)
        col = BLUE_RAMP[int(np.clip(v, 0, 0.999) * len(BLUE_RAMP))]
        x, y = PADL + xi[c["lon"]] * cw, PADT + yi[c["lat"]] * ch
        stroke = ' stroke="var(--ink-1)" stroke-width="0.6"' if c.get("candidate") else ""
        parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{cw + 0.3:.1f}" height="{ch + 0.3:.1f}" fill="{col}"{stroke}>'
                     f'<title>{c["lat"]:.2f}, {c["lon"]:.2f}: {escape(label)} {fmt(c[key])}; OND {c["ond_mm"]:.0f} mm, '
                     f'MAM {c["mam_mm"]:.0f} mm{"; candidate" if c.get("candidate") else ""}</title></rect>')
    for name, (la, lo) in towns.items():
        if lons[0] <= lo <= lons[-1] and lats[0] <= la <= lats[-1]:
            x = PADL + (lo - lons[0]) / (lons[-1] - lons[0]) * (len(lons) - 1) * cw + cw / 2
            y = PADT + (lats[-1] - la) / (lats[-1] - lats[0]) * (len(lats) - 1) * ch + ch / 2
            parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="var(--surface-1)" stroke="var(--ink-1)" stroke-width="1.5"/>'
                         f'<text class="ref-label" x="{x + 5:.1f}" y="{y + 4:.1f}">{escape(name)}</text>')
    for t in np.arange(np.ceil(lons[0] * 2) / 2, lons[-1] + 0.01, 0.5):
        parts.append(f'<text class="tick" x="{PADL + (t - lons[0]) / 0.05 * cw:.1f}" y="{H - 22}" text-anchor="middle">{t:.1f}E</text>')
    for t in np.arange(np.ceil(lats[0] * 2) / 2, lats[-1] + 0.01, 0.5):
        parts.append(f'<text class="tick" x="{PADL - 6}" y="{PADT + (lats[-1] - t) / 0.05 * ch + 4:.1f}" text-anchor="end">{abs(t):.1f}S</text>')
    return f'<svg class="chart" viewBox="0 0 {W} {H}" role="img" aria-label="{escape(label)}">{"".join(parts)}</svg>'


def main() -> None:
    cfg = load_config(REPO / "config")
    rs, ps = make_source(cfg, allow_download=False), make_pet_source(cfg, allow_download=False)
    wards = {w: price_ward(cfg, w, rs, ps) for w in cfg.pilot.wards}
    out: dict = {"built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "wards": {}}
    charts: dict = {}

    # (b) C3S at the ward cell, then the neighbour cells as a robustness check.
    files = c3s_cells()
    ward_cell = files.pop("36E_0N")
    for wid in cfg.pilot.wards:
        w = out["wards"][wid] = {"name": wards[wid].summary["ward"]["name"]}
        for season in ("MAM", "OND"):
            r = c3s_skill_for_file(ward_cell, wid, season)
            w[f"c3s_{season}"] = {"correlation": r["correlation"], "tercile": r["tercile"],
                                  "viability": skill.meaningful({"correlation": r["correlation"], "tercile": r["tercile"]})}
            w[f"c3s_{season}_neighbours"] = [
                {"cell": tag, "r": (n := c3s_skill_for_file(p, wid, season))["correlation"]["r"],
                 "ci95": n["correlation"]["ci95"], "roc_auc": n["tercile"]["roc_auc"]} for tag, p in files.items()]
            if wid == cfg.pilot.default_ward:
                yrs = [int(y) for y in r["obs"].index]
                z = lambda s: ((s - s.mean()) / s.std()).tolist()  # noqa: E731
                charts[f"c3s_{season}_series"] = sc.lines(
                    {"Observed (CHIRPS, ward)": list(zip(yrs, z(r["obs"]))), "C3S ensemble mean": list(zip(yrs, z(r["ens_mean"])))},
                    {"Observed (CHIRPS, ward)": "var(--series-1)", "C3S ensemble mean": "var(--series-2)"},
                    f"{season} rainfall: observed vs C3S hindcast", lambda v: f"{int(v)}", lambda v: f"{v:+.0f}",
                    "", "Standardised anomaly", x_range=(min(yrs), max(yrs)), y_range=(-3, 3),
                    xticks=list(range(1985, 2016, 5)),
                    tooltip=lambda n, x, y: f"{int(x)}: {n} {y:+.1f} sd")
                charts[f"c3s_{season}_probs"] = sc.prob_dots(
                    yrs, r["prob"].tolist(), 0.45, r["below"].tolist(), f"C3S P(below normal), {season}",
                    [f"{y}: P(below) {p:.0%}; observed {o:.0f} mm{' (below normal)' if b else ''}"
                     for y, p, o, b in zip(yrs, r["prob"], r["obs"], r["below"])])
            # GHACOF
            try:
                w[f"ghacof_{season}"] = skill.ghacof_skill(wid, season)
            except FileNotFoundError:
                w[f"ghacof_{season}"] = {"available": False, "reason": "GHACOF outlooks not downloaded"}

    # (c) Layer A re-priced with the measured MAM skill (Ward A only: not offered at Ward B).
    wa = cfg.pilot.default_ward
    measured = max(0.0, out["wards"][wa]["c3s_MAM"]["correlation"]["r"])
    cfg_m = cfg.model_copy(deep=True)
    cfg_m.product.synthetic_forecast.skill_correlation["LR"] = round(measured, 2)
    lb_share = wards[wa].seasons["LR"].table["payout_share"]
    la_measured = run_layer_a(cfg_m, wa, "LR", wards[wa].rain_daily, lb_share)
    cfg_p = cfg.model_copy(deep=True)
    cfg_p.product.synthetic_forecast.skill_correlation["LR"] = PREVIOUS_PLACEHOLDER_SKILL
    la_placeholder = run_layer_a(cfg_p, wa, "LR", wards[wa].rain_daily, lb_share)
    # Direct: the real C3S trigger on the hindcast years, scored against Layer B payouts.
    r = c3s_skill_for_file(ward_cell, wa, "MAM")
    yrs = [y for y in r["prob"].index if y in lb_share.index]
    trig = (r["prob"].loc[yrs] >= cfg.product.layer_a.trigger_prob_below_normal).to_numpy()
    vb = verify(trig, (lb_share.loc[yrs] > 0).to_numpy())
    vv = cfg.product.layer_a.voucher_kes_per_acre
    out["layer_a_repriced"] = {
        "measured_skill_used": round(measured, 2), "placeholder_skill": PREVIOUS_PLACEHOLDER_SKILL,
        "synthetic_at_placeholder_skill": {k: la_placeholder[k] for k in ("trigger_frequency_mean", "expected_cost_kes", "gross_kes",
                                                                           "cost_per_acre_range_kes", "scores")},
        "synthetic_at_measured_skill": {k: la_measured[k] for k in ("trigger_frequency_mean", "expected_cost_kes", "gross_kes",
                                                                     "cost_per_acre_range_kes", "scores")},
        "direct_c3s_hindcast": {"years": [int(min(yrs)), int(max(yrs))], "triggers": int(trig.sum()),
                                "trigger_frequency": float(trig.mean()),
                                "hit_rate_layer_b": float(vb["hit_rate"][0]),
                                "false_alarm_ratio_layer_b": None if np.isnan(vb["false_alarm_ratio"][0]) else float(vb["false_alarm_ratio"][0]),
                                "expected_cost_kes": round(float(trig.mean()) * vv, 2),
                                "trigger_years": [int(y) for y, t in zip(yrs, trig) if t],
                                "layer_b_payout_years": [int(y) for y in yrs if lb_share.loc[y] > 0]},
        "viability": out["wards"][wa]["c3s_MAM"]["viability"]}

    # (d) Early-season trigger.
    et = RAW / "early_trigger_results.json"
    out["early_trigger"] = json.loads(et.read_text()) if et.exists() else {"available": False}
    # As specified (projection below the WRSI trigger) the prototype may never fire: the
    # unobserved two-thirds of the season is filled with climatology, which pulls the
    # projection towards normal. Show how a higher projection threshold would score.
    for wid, e in out["early_trigger"].get("wards", {}).items():
        if not e.get("available"):
            continue
        h = pd.DataFrame(e["history"])
        act = h["actual_wrsi"] < out["early_trigger"]["trigger_wrsi"]
        e["lowest_projection"] = float(h["projected_wrsi"].min())
        e["threshold_sensitivity"] = []
        for th in (80, 85, 90, 95):
            t = h["projected_wrsi"] < th
            e["threshold_sensitivity"].append({
                "projection_below": th, "fires": int(t.sum()), "frequency": float(t.mean()),
                "hit_rate": float((t & act).sum() / act.sum()) if act.sum() else None,
                "false_alarm_ratio": float((t & ~act).sum() / t.sum()) if t.sum() else None})

    # (e) Eastern Kenya scan.
    try:
        import eastern_kenya
        scan = eastern_kenya.scan()
        out["eastern_kenya"] = {k: v for k, v in scan.items() if k != "cells"}
        charts["eastern_reliability"] = heatmap(scan["cells"], "ond_reliable", "OND reaches 250 mm", 0, 1,
                                                lambda v: f"{v:.0%} of years", eastern_kenya.TOWNS)
        charts["eastern_share"] = heatmap(scan["cells"], "ond_share", "OND share of MAM+OND rain", 0.35, 0.75,
                                          lambda v: f"{v:.0%}", eastern_kenya.TOWNS)
    except FileNotFoundError:
        out["eastern_kenya"] = {"available": False, "reason": "eastern Kenya CHIRPS grid not downloaded"}

    # Data sources.
    out["sources"] = {p.name.replace(".meta.json", ""): json.loads(p.read_text()) for p in sorted(RAW.glob("*.meta.json"))}

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "3b-results.json").write_text(json.dumps(out, indent=1, default=str) + "\n", encoding="utf-8", newline="\n")
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(str(Path(__file__).parent / "templates")),
                             autoescape=True, undefined=jinja2.StrictUndefined)
    env.filters["pct"] = lambda v, d=0: "n/a" if v is None or v != v else f"{v * 100:.{d}f}%"
    env.filters["num"] = lambda v, d=0: "n/a" if v is None or v != v else f"{v:,.{d}f}"
    env.filters["kes"] = lambda v: "n/a" if v is None else f"KES {v:,.0f}"
    html = env.get_template("3b.html").render(o=out, charts=charts, cfg=cfg)
    (OUT / "3b-forecast-skill.html").write_text(html, encoding="utf-8", newline="\n")
    print("wrote", OUT / "3b-forecast-skill.html")


if __name__ == "__main__":
    main()
