"""Render a ward's pricing and backtest results as JSON and a self-contained HTML report."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import jinja2

from . import svgcharts as sc
from .engine import WardResult

PHASE_COLORS = {  # fixed categorical order, validated light + dark (see template vars)
    "germination": "var(--series-1)",
    "vegetative": "var(--series-2)",
    "flowering": "var(--series-3)",
    "grain_fill": "var(--series-4)",
}
SEASON_COLORS = {"LR": "var(--series-1)", "SR": "var(--series-2)"}


def pretty(phase: str) -> str:
    return phase.replace("_", " ").capitalize()


MONTH_STARTS = [date(2001, m, 1).timetuple().tm_yday for m in range(1, 13)]
SHORT = {"germination": "G", "vegetative": "V", "flowering": "F", "grain_fill": "GF", "maturity": "M"}


def _doy_label(doy: float) -> str:
    return date.fromordinal(date(2001, 1, 1).toordinal() + int(doy) - 1).strftime("%b")


def season_charts(sr, meaningful: float) -> dict:
    s = sr.summary
    years = s["years"]
    terms = s["terms"]
    pay = sr.payouts
    stacks = {p: [terms[p]["weight"] * float(pay.loc[y, f"f_{p}"]) for y in years] for p in terms}

    def bar_tip(i):
        y = years[i]
        parts = [f"{pretty(p)} {stacks[p][i]:.1%}" for p in terms if stacks[p][i] > 0]
        return f"{y}: payout {pay.loc[y, 'payout_frac']:.1%} of sum insured" + (
            " (" + ", ".join(parts) + ")" if parts else " (no trigger)")

    charts = {
        "payouts": sc.stacked_bars(years, stacks, {p: PHASE_COLORS.get(p, "var(--series-1)") for p in terms},
                                   f"Historical Layer B payouts, {s['season_label']}", bar_tip),
        "phases": {},
    }
    for p, t in terms.items():
        vals = [float(sr.phase_rain.loc[y, p]) for y in years]
        charts["phases"][p] = sc.dots_with_levels(
            years, vals, [("trigger", t["trigger_mm"]), ("exit", t["exit_mm"])],
            f"{pretty(p)} rainfall by season", highlight=lambda v, t=t: v < t["trigger_mm"])

    bt = s["backtest"]
    if bt.get("available"):
        cutoff = bt["bad_season_cutoff_t_per_ha"]
        classes = {
            "ok": ("var(--series-1)", "Index and yield agree"),
            "basis": ("var(--series-2)", "Basis risk: bad yield, no payout"),
            "false": ("var(--series-3)", "False payout: paid, yield fine"),
        }
        pts = []
        for d in bt["season_detail"]:
            cls = "basis" if d["bad"] and not d["paid"] else "false" if d["paid"] and not d["bad"] else "ok"
            pts.append({"x": d["payout_frac"], "y": d["yield_t_per_ha"], "cls": cls,
                        "tip": f"{d['year']}: payout {d['payout_frac']:.1%}, yield {d['yield_t_per_ha']:.2f} t/ha "
                               f"(SYNTHETIC) - {classes[cls][1]}"})
        charts["scatter"] = sc.scatter(pts, classes, meaningful, cutoff, "Index payout vs synthetic yield")
        charts["scatter_legend"] = [{"color": c, "label": lbl} for c, lbl in classes.values()]
    return charts


def ward_charts(result: WardResult) -> dict:
    first = next(iter(result.seasons.values()))
    clim = first.climatology.rolling(15, center=True, min_periods=1).mean()
    clim = clim[clim.index <= 365]
    bands = []
    for sr in result.seasons.values():
        label = sr.summary["season_label"]
        for w in sr.windows_example:
            a, b = min(w.start.dayofyear, 365), min(w.end.dayofyear, 365)
            base = {"group": label, "short": SHORT.get(w.phase, w.phase[:2].upper()),
                    "name": f"{label}: {pretty(w.phase)} ({w.start:%d %b} to {w.end:%d %b})",
                    "insured": w.phase in sr.summary["terms"]}
            if b < a:  # crosses New Year: split; the January tail is its own label group
                bands += [{**base, "start": a, "end": 365},
                          {**base, "start": 1, "end": b, "group": label + " (cont.)"}]
            else:
                bands.append({**base, "start": a, "end": b})
    exceed = {s: [(pt["exceedance"], pt["loss"]) for pt in sr.summary["exceedance"]]
              for s, sr in result.seasons.items()}
    return {
        "climatology": sc.band_line(list(clim.index), list(clim.values), bands,
                                    "Mean daily rainfall with crop phases", MONTH_STARTS, _doy_label,
                                    "", "Mean daily rain (mm, 15-day smoothed)"),
        "exceedance": sc.lines(
            exceed, SEASON_COLORS, "Loss exceedance", lambda v: f"{v:.0%}", lambda v: f"{v:.0%}",
            "Chance of a season paying at least this much", "Payout, share of sum insured",
            x_range=(0, 1), tooltip=lambda name, x, y: f"{name}: {x:.0%} chance of a payout of {y:.1%} or more"),
        "exceedance_legend": [{"color": SEASON_COLORS[s], "label": sr.summary["season_label"]}
                              for s, sr in result.seasons.items()],
    }


def render_html(result: WardResult, manifest: dict) -> str:
    env = jinja2.Environment(
        loader=jinja2.PackageLoader("agroshield_pricing", "templates"),
        autoescape=jinja2.select_autoescape(["html"]),
        undefined=jinja2.StrictUndefined,
    )
    env.filters["pct"] = lambda v, d=1: "n/a" if v is None else f"{v * 100:.{d}f}%"
    env.filters["kes"] = lambda v: f"KES {v:,.0f}"
    env.filters["mm"] = lambda v: f"{v:,.0f} mm"
    env.filters["pretty"] = pretty
    meaningful = manifest["backtest_settings"]["meaningful_payout"]
    seasons = [{"s": sr.summary, "charts": season_charts(sr, meaningful)} for sr in result.seasons.values()]
    tpl = env.get_template("report.html")
    return tpl.render(r=result.summary, seasons=seasons, ward_charts=ward_charts(result),
                      m=manifest, phase_colors=PHASE_COLORS)


def write_json(path: Path, obj) -> None:
    # newline="\n": the file is hashed into the manifest, so it must not depend on the OS.
    path.write_text(json.dumps(obj, indent=2, default=str) + "\n", encoding="utf-8", newline="\n")
