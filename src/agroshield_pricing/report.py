"""Render a ward's pricing results as JSON and a self-contained HTML report."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import jinja2
import numpy as np

from . import svgcharts as sc
from .engine import WardResult
from .wrsi import DEKADS_PER_YEAR, to_dekads, window_dekads

V1_COLOR, V0_COLOR = "var(--series-1)", "var(--series-2)"
MONTH_TICKS = [m * 3 for m in range(12)]          # dekad-of-year index of each month's first dekad
MONTHS = [date(2001, m + 1, 1).strftime("%b") for m in range(12)]


def season_charts(result: WardResult, sr) -> dict:
    s = sr.summary
    years = s["years"]
    t = s["terms"]
    v1, v0 = sr.table, sr.v0
    top = max(0.1, float(v1["payout_share"].max()), float(v0["payout_frac"].max())) * 1.1

    def tip1(i):
        y = years[i]
        r = v1.loc[y]
        what = "failed onset" if r["failed_onset"] else f"WRSI {r['wrsi']:.0f}"
        if r["germination_failed"]:
            what += ", germination dry spell (replanting paid)"
        return f"{y}: {what}, payout {r['payout_share']:.0%} of sum insured"

    def accent(i):
        r = v1.loc[years[i]]
        return "var(--series-4)" if (r["failed_onset"] or r["germination_failed"]) else None

    charts = {
        "wrsi": sc.wrsi_dots(years, [None if r["failed_onset"] else float(r["wrsi"]) for _, r in v1.iterrows()],
                             t["trigger_wrsi"], t["exit_wrsi"], "End-of-season WRSI by year"),
        "payouts_v1": sc.bars(years, [float(v1.loc[y, "payout_share"]) for y in years], V1_COLOR,
                              "v1 payouts by year", tip1, y_max=top, accent=accent),
        "payouts_v0": sc.bars(years, [float(v0["payout_frac"].get(y, 0.0)) for y in years], V0_COLOR,
                              "v0 per-phase payouts by year",
                              lambda i: f"{years[i]}: v0 payout {float(v0['payout_frac'].get(years[i], 0.0)):.0%}",
                              y_max=top),
        "exceedance": sc.lines(
            {"v1": [(pt["exceedance"], pt["loss"]) for pt in s["exceedance"]],
             "v0": [(pt["exceedance"], pt["loss"]) for pt in _exceedance(v0["payout_frac"])]},
            {"v1": V1_COLOR, "v0": V0_COLOR}, "Loss exceedance, v1 and v0", lambda v: f"{v:.0%}",
            lambda v: f"{v:.0%}", "Chance of a season paying at least this much", "Payout",
            x_range=(0, 1), tooltip=lambda n, x, y: f"{n}: {x:.0%} chance of a payout of {y:.0%} or more"),
        "traces": {},
    }
    for year, tr in sorted(sr.traces.items()):
        cum_wr, cum_aet = tr["wr"].cumsum().to_numpy(), tr["aet"].cumsum().to_numpy()
        labels = list(tr["dekad"])
        charts["traces"][year] = sc.lines(
            {"Water requirement": [(i + 1, float(v)) for i, v in enumerate(cum_wr)],
             "Water used (AET)": [(i + 1, float(v)) for i, v in enumerate(cum_aet)]},
            {"Water requirement": "var(--series-1)", "Water used (AET)": "var(--series-2)"},
            f"Cumulative water balance {year}", lambda v: labels[int(v) - 1].rsplit(" ", 1)[0] if 1 <= v <= len(labels) else "",
            lambda v: f"{v:g}", "", "Cumulative mm", x_range=(1, len(labels)),
            xticks=list(range(1, len(labels) + 1, 3)),
            tooltip=lambda n, x, y: f"{labels[int(x) - 1]}: {n.lower()} {y:.0f} mm to date")
    la = s["layer_a"]
    if la.get("available"):
        h = la["history"]
        charts["layer_a_probs"] = sc.prob_dots(
            [x["year"] for x in h], [x["prob_below"] for x in h], la["terms"]["trigger_prob_below_normal"],
            [x["layer_b_pays"] for x in h], "Synthetic forecast probability of below-normal rain",
            [f"{x['year']}: P(below) {x['prob_below']:.0%}{', voucher' if x['voucher'] else ''}; "
             f"Mar-May rain {x['forecast_season_rain_mm']:.0f} mm{' (below normal)' if x['below_normal'] else ''}; "
             f"Layer B {'paid ' + format(x['layer_b_payout'], '.0%') if x['layer_b_pays'] else 'did not pay'}" for x in h])
        sw = la["skill_sweep"]
        charts["layer_a_skill"] = sc.lines(
            {"Hit rate: Layer B payout seasons": [(r["skill"], r["hit_rate_layer_b"]["median"] or 0) for r in sw],
             "Hit rate: below-normal rain": [(r["skill"], r["hit_rate_below_normal"]["median"] or 0) for r in sw],
             "Seasons with a voucher": [(r["skill"], r["trigger_frequency"]) for r in sw]},
            {"Hit rate: Layer B payout seasons": "var(--series-1)", "Hit rate: below-normal rain": "var(--series-2)",
             "Seasons with a voucher": "var(--series-3)"},
            "Layer A scores by forecast skill", lambda v: f"{v:.1f}", lambda v: f"{v:.0%}",
            "Forecast skill (correlation with observed Mar-May rain)", "Share", x_range=(0, max(r["skill"] for r in sw)),
            y_range=(0, 1), xticks=[r["skill"] for r in sw],
            tooltip=lambda n, x, y: f"skill {x:.1f}: {n.lower()} {y:.0%} (median of draws)")
    fv = s["fewsnet_validation"]
    if fv.get("available"):
        charts["fewsnet"] = sc.scatter_xy(
            [{"x": p["ours"], "y": p["fewsnet"], "tip": f"{p['year']}: ours {p['ours']:.0f}, FEWS NET {p['fewsnet']:.0f}"}
             for p in fv["pairs"]], "Our WRSI vs FEWS NET WRSI", "Our end-of-season WRSI", "FEWS NET WRSI")
    return charts


def _exceedance(pay) -> list[dict]:
    x = np.sort(pay.to_numpy(dtype=float))[::-1]
    return [{"loss": float(v), "exceedance": (i + 1) / (len(x) + 1)} for i, v in enumerate(x)]


def ward_charts(result: WardResult) -> dict:
    """Dekadal climatology of rain and PET, with each season's planting window shaded."""
    def by_dekad(daily):
        dk = to_dekads(daily)
        return dk.groupby(dk.index % DEKADS_PER_YEAR).mean()

    rain, pet = by_dekad(result.rain_daily), by_dekad(result.pet_daily)
    bands = []
    for sr in result.seasons.values():
        w = sr.summary["calendar"]["planting_window"]
        a, b = window_dekads(_MD(w), 2001)
        bands.append({"start": a % DEKADS_PER_YEAR, "end": b % DEKADS_PER_YEAR + 1,
                      "label": f"{sr.summary['season_label']} planting window",
                      "title": f"Start of season searched {w['start']} to {w['end']}"})
    return {"climatology": sc.lines(
        {"Rain": [(i, float(v)) for i, v in rain.items()], "PET": [(i, float(v)) for i, v in pet.items()]},
        {"Rain": "var(--series-1)", "PET": "var(--series-2)"}, "Mean dekadal rain and PET",
        lambda v: MONTHS[int(v) // 3] if 0 <= v < 36 else "", lambda v: f"{v:g}", "", "mm per dekad",
        x_range=(0, 35), xticks=MONTH_TICKS, bands=bands,
        tooltip=lambda n, x, y: f"{MONTHS[int(x) // 3]} dekad {int(x) % 3 + 1}: mean {n.lower()} {y:.0f} mm")}


class _MD:
    """Adapter so window_dekads can read a dumped planting window dict."""
    def __init__(self, d):
        self.start, self.end = d["start"], d["end"]


def render_html(result: WardResult, manifest: dict) -> str:
    env = jinja2.Environment(
        loader=jinja2.PackageLoader("agroshield_pricing", "templates"),
        autoescape=jinja2.select_autoescape(["html"]),
        undefined=jinja2.StrictUndefined,
    )
    env.filters["pct"] = lambda v, d=1: "n/a" if v is None or v != v else f"{v * 100:.{d}f}%"
    env.filters["kes"] = lambda v: f"KES {v:,.0f}"
    env.filters["mm"] = lambda v: f"{v:,.0f} mm"
    env.filters["num"] = lambda v, d=0: "n/a" if v is None or v != v else f"{v:,.{d}f}"
    seasons = [{"s": sr.summary, "charts": season_charts(result, sr)} for sr in result.seasons.values()]
    return env.get_template("report.html").render(r=result.summary, seasons=seasons,
                                                   ward_charts=ward_charts(result), m=manifest)


def write_json(path: Path, obj) -> None:
    # newline="\n": the file is hashed into the manifest, so it must not depend on the OS.
    # allow_nan=False: failed-onset seasons have no WRSI; they are written as null, not NaN.
    text = json.dumps(_clean(obj), indent=2, default=_jsonable, allow_nan=False)
    path.write_text(text + "\n", encoding="utf-8", newline="\n")


def _clean(o):
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (float, np.floating)) and o != o:
        return None
    if isinstance(o, np.floating):
        return float(o)
    if isinstance(o, np.bool_):
        return bool(o)
    return o


def _jsonable(o):
    if isinstance(o, (np.floating, np.integer)):
        return o.item()
    if isinstance(o, np.bool_):
        return bool(o)
    return str(o)
