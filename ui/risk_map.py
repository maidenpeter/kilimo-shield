"""Chapter 1 map: the five pilot wards on Kenya's 47 counties, with a season-by-season replay of 2015-2024.

The counties are drawn as plain shapes on longitude and latitude (Kenya straddles the equator, so the plain grid is
nearly true to shape). There are no map tiles: the map works offline, like the rest of the app.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from engine.parametric_engine import SEASONS, WARDS, TriggerParams, kpis
from engine.underwriting import PayTogether, WardRisk, pay_together, season_load, ward_risk
from ui import theme

GEO_PATH = Path(__file__).resolve().parent.parent / "assets" / "kenya_counties.geojson"
NAIROBI = (36.817, -1.286)  # lon, lat

# One hue, light to dark: dry earth. Lightness falls at every step, so darker always means more.
RAMP = ["#fbeadf", "#f6cdb0", "#eeaa7c", "#df824b", "#c0602a", "#94461a", "#62300f"]
COUNTY = "#eceee9"
PILOT_COUNTY = "#dbe6da"
COUNTY_EDGE = "#ffffff"
FAINT = "#98a2b3"

VIEWS = ["Burn cost", "Price", "Frequency", "Severity", "1-in-10 season", "Worst season", "Volatility",
         "Rain variability", "Accumulation", "Replay"]
# What each measure is, and why it matters when pricing: shown under the menu.
VIEW_HELP = {
    "Burn cost": "The average payout a season, as a share of the cover: the expected loss the price is built on.",
    "Price": "The premium a season: burn cost divided by the target loss ratio. A cross marks a ward above the "
             "sellable ceiling, which is not sold.",
    "Frequency": "How often the cover pays: the share of seasons with any payout. Frequent small payouts keep "
                 "farmers trusting the product.",
    "Severity": "How much it pays when it does: the average payout in the seasons that paid, as a share of the cover.",
    "1-in-10 season": "The payout exceeded in one season in ten (the 90th percentile). The tail, not the average, "
                      "sizes reinsurance and capital.",
    "Worst season": "The largest single season in 2015-2024, as a share of the cover: the worst case the record holds.",
    "Volatility": "How lumpy the payouts are: their standard deviation over their average (CV). The higher it is, "
                  "the stronger the case for a risk margin above the burn cost.",
    "Rain variability": "How much the seasonal rain changes from year to year (CV): the hazard itself, before any "
                        "product terms.",
    "Accumulation": "Expected payouts a season if every SACCO member in the ward were insured, with lines between "
                    "wards that pay in the same seasons: those losses arrive together.",
    "Replay": "Every season from 2015 to 2024 in turn: what the cover paid in each ward.",
}
TOGETHER = 0.3  # a correlation of payouts at or above this draws a line between two wards
LABEL_AT = {"njoro": "middle right", "bureti": "bottom left", "kimilili": "top center",
            "imenti_north": "middle right", "kangundo": "middle right"}
NEIGHBOURS = [("UGANDA", 34.05, 2.6), ("TANZANIA", 36.2, -4.55), ("SOMALIA", 42.05, 1.6), ("ETHIOPIA", 37.3, 5.05),
              ("SOUTH SUDAN", 34.75, 5.25)]
X_RANGE, Y_RANGE = (33.3, 42.8), (-5.0, 5.6)


@lru_cache(maxsize=1)
def counties() -> list[dict]:
    """[{"name", "x", "y"}] with every county's rings joined by gaps, ready to draw as one filled shape."""
    out = []
    for f in json.loads(GEO_PATH.read_text(encoding="utf-8"))["features"]:
        xs, ys = [], []
        for polygon in f["geometry"]["coordinates"]:
            for ring in polygon:
                xs += [p[0] for p in ring] + [None]
                ys += [p[1] for p in ring] + [None]
        out.append({"name": f["properties"]["name"], "x": xs, "y": ys})
    return out


def colour(t: float) -> str:
    """The ramp colour for t in [0, 1]."""
    t = min(max(float(t), 0.0), 1.0) * (len(RAMP) - 1)
    i = min(int(t), len(RAMP) - 2)
    a, b = RAMP[i], RAMP[i + 1]
    mix = [round(int(a[k:k + 2], 16) + (int(b[k:k + 2], 16) - int(a[k:k + 2], 16)) * (t - i)) for k in (1, 3, 5)]
    return "#" + "".join(f"{v:02x}" for v in mix)


def short(ward_key: str) -> str:
    return WARDS[ward_key].name.removesuffix(" Ward")


@dataclass
class WardFigures:
    key: str
    burn_pct: float
    rate_pct: float
    premium_ksh: float
    offered: bool
    paid: int
    seasons: int
    worst_pct: float
    worst_label: str
    by_season: dict  # season label -> payout as % of the sum insured
    burn_pct_all: float | None = None  # both seasons, whatever the filter: the price is set on these
    risk: WardRisk | None = None       # frequency, severity, tail, volatility and rain for the chosen seasons
    members: int = 0                   # SACCO members in the ward (the book if every one were insured)
    sum_insured: float = 0.0
    headroom_pp: float = 0.0           # sellable ceiling minus the price, in percentage points

    @property
    def expected_loss_ksh(self) -> float:
        """Expected payouts a season if every member in the ward were insured on the standard farm (and, for a ward
        that is not offered, if it were sold)."""
        return (self.risk.burn_pct if self.risk else self.burn_pct) / 100 * self.sum_insured * self.members

    @property
    def book_ksh(self) -> float:
        """Expected payouts a season that the book would actually carry: nothing in a ward that is not sold."""
        return self.expected_loss_ksh if self.offered else 0.0


def ward_figures(zones: pd.DataFrame, backtests: dict, season_keys, params: TriggerParams,
                 members: dict | None = None) -> list[WardFigures]:
    """Per-ward figures for the chosen seasons. The price is the zone price, which always uses both seasons."""
    zone = zones.set_index("ward_key")
    out = []
    for key in WARDS:
        seasons = backtests[key][backtests[key]["season"].isin(season_keys)]
        k = kpis(seasons, params)
        both = kpis(backtests[key], params).burn_cost_pct
        share = 100 * seasons["payout_total"] / params.sum_insured
        worst = seasons.loc[share.idxmax()] if len(seasons) and share.max() > 0 else None
        out.append(WardFigures(
            key=key, burn_pct=k.burn_cost_pct, rate_pct=float(zone.loc[key, "premium_rate_pct"]),
            premium_ksh=float(zone.loc[key, "premium_ksh"]), offered=zone.loc[key, "offered"] == "Yes",
            paid=k.seasons_paying, seasons=k.seasons, worst_pct=float(share.max()) if worst is not None else 0.0,
            worst_label=_season_name(worst["label"]) if worst is not None else "",
            by_season=dict(zip(seasons["label"], share)), burn_pct_all=both,
            risk=ward_risk(seasons, params.sum_insured), members=int((members or {}).get(key, 0)),
            sum_insured=params.sum_insured,
            headroom_pp=100 * params.max_sellable_rate - float(zone.loc[key, "premium_rate_pct"]),
        ))
    return out


def _season_name(label: str) -> str:
    """'2022 LR' -> 'Long rains 2022'."""
    year, season = label.split()
    return f"{SEASONS[season]['name'].split(' (')[0]} {year}"


def measure(view: str, w: WardFigures, params: TriggerParams, top: float = 0.0) -> tuple[float, str]:
    """(position on the colour ramp 0-1, the short value shown on the map). ``top`` is the largest expected loss
    across the wards, for the Accumulation view, whose scale depends on the book."""
    r = w.risk
    if view == "Burn cost":
        return w.burn_pct / 12, theme.pct(w.burn_pct, 1)
    if view == "Price":
        return w.rate_pct / (200 * params.max_sellable_rate), theme.pct(w.rate_pct, 1)
    if view == "Frequency":
        return w.paid / max(w.seasons, 1) / 0.6, f"{w.paid} of {w.seasons}"
    if view == "Severity":
        return r.severity_pct / 100, theme.pct(r.severity_pct, 0) if r.paid else "never paid"
    if view == "1-in-10 season":
        return r.p90_pct / 100, theme.pct(r.p90_pct, 0)
    if view == "Volatility":
        return ((r.volatility or 0) / 4, f"CV {r.volatility:.1f}" if r.volatility is not None else "never paid")
    if view == "Rain variability":
        return r.rain_cv / 0.6, f"CV {r.rain_cv:.2f}"
    if view == "Accumulation":
        if not w.offered:
            return 0.0, "not sold"
        return (w.book_ksh / top if top else 0.0), theme.ksh_short(w.book_ksh)
    return w.worst_pct / 100, theme.pct(w.worst_pct, 0) if w.worst_pct else "never paid"


def scale(view: str, params: TriggerParams, n_seasons: int, top: float = 0.0) -> tuple[str, list, list]:
    """Colour bar title, tick positions (0-1) and tick labels."""
    if view == "Burn cost":
        return "Burn cost, % of cover", [0, 1 / 3, 2 / 3, 1], ["0%", "4%", "8%", "12%+"]
    if view == "Price":
        c = 100 * params.max_sellable_rate
        return "Premium a season", [0, 0.5, 1], ["0%", f"{c:g}% ceiling", f"{2 * c:g}%+"]
    if view == "Frequency":
        return "Seasons with a payout", [0, 0.5, 1], ["0%", "30%", "60%+"]
    if view == "Volatility":
        return "Volatility of payouts (CV)", [0, 0.5, 1], ["0", "2", "4+"]
    if view == "Rain variability":
        return "Rain variability (CV)", [0, 0.5, 1], ["0", "0.3", "0.6+"]
    if view == "Accumulation":
        return "Expected payouts a season", [0, 1], ["0", theme.ksh_short(top)]
    return "Payout, % of cover", [0, 0.5, 1], ["0%", "50%", "100%"]


def hover(w: WardFigures, which: str) -> str:
    ward = WARDS[w.key]
    price = f"Price {theme.pct(w.rate_pct, 1)} a season ({theme.ksh(w.premium_ksh)})"
    if not w.offered:
        price += ", above the ceiling: not offered"
    worst = f"Worst: {w.worst_label}, {theme.pct(w.worst_pct, 0)} of cover" if w.worst_pct else "Never paid"
    text = (f"<b>{ward.label}</b><br>{ward.zone} · {ward.enterprise}<br>{price}<br>"
            f"Burn cost {theme.pct(w.burn_pct, 2)} · paid in {w.paid} of {w.seasons} {which}<br>{worst}")
    r = w.risk
    if r:
        cv = f"{r.volatility:.1f}" if r.volatility is not None else "n/a"
        text += (f"<br>Severity {theme.pct(r.severity_pct, 0)} · 1-in-10 {theme.pct(r.p90_pct, 0)} · CV {cv}"
                 f"<br>Rain {r.rain_mean_mm:,.0f} mm a season (CV {r.rain_cv:.2f})")
    if w.members:
        text += (f"<br>{w.members} members: expected payouts {theme.ksh_short(w.expected_loss_ksh)} a season if all "
                 f"were insured{'' if w.offered else ' and the ward were sold'}")
    return text + "<extra></extra>"


def base_figure(selected: str, ring: float) -> go.Figure:
    fig = go.Figure()
    for c in counties():
        pilot = any(ward.county == c["name"] for ward in WARDS.values())
        fig.add_scatter(x=c["x"], y=c["y"], fill="toself", mode="lines", name=c["name"],
                        fillcolor=PILOT_COUNTY if pilot else COUNTY, line={"color": COUNTY_EDGE, "width": 0.8},
                        hoveron="fills", hoverinfo="name", showlegend=False)
    fig.add_scatter(x=list(X_RANGE), y=[0, 0], mode="lines", line={"color": FAINT, "width": 1, "dash": "dot"},
                    hoverinfo="skip", showlegend=False)
    fig.add_scatter(x=[X_RANGE[1] - 0.05], y=[0.18], mode="text", text=["Equator"], textposition="middle left",
                    textfont={"size": 10, "color": FAINT}, hoverinfo="skip", showlegend=False)
    fig.add_scatter(x=[n[1] for n in NEIGHBOURS], y=[n[2] for n in NEIGHBOURS], mode="text",
                    text=[n[0] for n in NEIGHBOURS], textfont={"size": 10, "color": FAINT}, hoverinfo="skip",
                    showlegend=False)
    fig.add_scatter(x=[40.9], y=[-3.9], mode="text", text=["<i>Indian Ocean</i>"], hoverinfo="skip",
                    textfont={"size": 11, "color": FAINT}, showlegend=False)
    fig.add_scatter(x=[NAIROBI[0]], y=[NAIROBI[1]], mode="markers+text", text=["Nairobi"], textposition="middle left",
                    marker={"symbol": "square", "size": 7, "color": theme.INK}, textfont={"size": 11, "color": theme.MUTED},
                    hovertemplate="Nairobi, for orientation<extra></extra>", showlegend=False)
    ward = WARDS[selected]
    fig.add_scatter(x=[ward.lon], y=[ward.lat], mode="markers", hoverinfo="skip", showlegend=False,
                    customdata=[selected], selected={"marker": {"opacity": 1}}, unselected={"marker": {"opacity": 1}},
                    marker={"size": ring, "color": "rgba(0,0,0,0)", "line": {"color": theme.INK, "width": 1.5}})
    return fig


def size(t: float) -> float:
    return 16 + 30 * min(max(float(t), 0.0), 1.0)


def ring_size(figures: list[WardFigures], ts: list[float], selected: str) -> float:
    return size(next(t for w, t in zip(figures, ts) if w.key == selected)) + 10


def ward_trace(fig: go.Figure, figures: list[WardFigures], ts: list[float], values: list[str], hovers: list[str],
               selected: str) -> None:
    fig.add_scatter(
        x=[WARDS[w.key].lon for w in figures], y=[WARDS[w.key].lat for w in figures], mode="markers+text",
        customdata=[w.key for w in figures], hovertemplate=hovers,
        text=[f"<b>{short(w.key)}</b><br>{v}" if v else f"<b>{short(w.key)}</b>" for w, v in zip(figures, values)],
        textposition=[LABEL_AT[w.key] for w in figures],
        textfont={"size": [13 if w.key == selected else 12 for w in figures], "color": theme.INK},
        marker={"size": [size(t) for t in ts], "color": [colour(t) for t in ts],
                "line": {"color": theme.SURFACE, "width": 2}},
        selected={"marker": {"opacity": 1}}, unselected={"marker": {"opacity": 1}}, showlegend=False, cliponaxis=False,
    )


def not_offered_trace(fig: go.Figure, figures: list[WardFigures]) -> None:
    """A cross over a ward that is not sold the standard bundle, so the status never rests on colour alone."""
    blocked = [w for w in figures if not w.offered]
    if blocked:
        # It sits on top of the circle, so it carries the ward too: a tap on the cross opens that ward.
        fig.add_scatter(x=[WARDS[w.key].lon for w in blocked], y=[WARDS[w.key].lat for w in blocked], mode="markers",
                        marker={"symbol": "x-thin", "size": 14, "line": {"color": theme.SURFACE, "width": 2.5}},
                        customdata=[w.key for w in blocked], hoverinfo="skip", showlegend=False,
                        selected={"marker": {"opacity": 1}}, unselected={"marker": {"opacity": 1}})


def colour_bar(fig: go.Figure, title: str, ticks: list, labels: list) -> None:
    fig.add_scatter(x=[None], y=[None], mode="markers", hoverinfo="skip", showlegend=False, marker={
        "colorscale": [[i / (len(RAMP) - 1), c] for i, c in enumerate(RAMP)], "cmin": 0, "cmax": 1, "color": [0],
        "showscale": True, "colorbar": {
            "orientation": "h", "x": 0.96, "xanchor": "right", "y": 1.0, "yanchor": "top", "len": 0.45,
            "thickness": 9, "outlinewidth": 0, "tickvals": ticks, "ticktext": labels, "ticks": "",
            "ticklabeloverflow": "allow",
            "title": {"text": title, "side": "top", "font": {"size": 11, "color": theme.MUTED}},
            "tickfont": {"size": 10, "color": theme.MUTED}}})


def finish(fig: go.Figure, height: int = 520, bottom: int = 8) -> go.Figure:
    fig.update_layout(
        height=height, paper_bgcolor=theme.SURFACE, plot_bgcolor=theme.SURFACE, dragmode=False, hovermode="closest",
        font={"color": theme.BODY, "family": "IBM Plex Sans, sans-serif"},
        margin={"l": 0, "r": 0, "t": 8, "b": bottom},
        hoverlabel={"bgcolor": theme.SURFACE, "font": {"family": "IBM Plex Sans, sans-serif"}}, showlegend=False,
    )
    fig.update_xaxes(range=list(X_RANGE), visible=False, fixedrange=True, constrain="domain")
    fig.update_yaxes(range=list(Y_RANGE), visible=False, fixedrange=True, scaleanchor="x", scaleratio=1,
                     constrain="domain")
    return fig


def together_lines(fig: go.Figure, together: list[PayTogether], which: str) -> None:
    """A line between two wards whose payouts rise and fall together, thicker the closer they move."""
    for pair in together:
        if pair.correlation is None or pair.correlation < TOGETHER:
            continue
        a, b = WARDS[pair.a], WARDS[pair.b]
        tip = (f"{short(pair.a)} and {short(pair.b)} paid together in {pair.both_paid} {which} "
               f"(correlation {pair.correlation:.2f})")
        fig.add_scatter(x=[a.lon, (a.lon + b.lon) / 2, b.lon], y=[a.lat, (a.lat + b.lat) / 2, b.lat],
                        mode="lines", line={"color": theme.INK, "width": 1 + 6 * pair.correlation, "dash": "dot"},
                        opacity=0.45, hovertemplate=tip + "<extra></extra>", showlegend=False)


def static_map(view: str, figures: list[WardFigures], params: TriggerParams, selected: str, which: str,
               together: list[PayTogether] | None = None) -> go.Figure:
    top = max((w.book_ksh for w in figures), default=0.0)
    pairs = [measure(view, w, params, top) for w in figures]
    fig = base_figure(selected, ring_size(figures, [p[0] for p in pairs], selected))
    if view == "Accumulation" and together:
        together_lines(fig, together, which)
    ward_trace(fig, figures, [p[0] for p in pairs], [p[1] for p in pairs], [hover(w, which) for w in figures], selected)
    not_offered_trace(fig, figures)
    colour_bar(fig, *scale(view, params, figures[0].seasons, top))
    return finish(fig)


def replay_map(figures: list[WardFigures], params: TriggerParams, selected: str, which: str) -> go.Figure:
    """Every season in turn: each ward's circle shows what the cover paid that season."""
    labels = list(figures[0].by_season)
    fig = base_figure(selected, 40)

    def frame_values(label):
        shares = [w.by_season.get(label, 0.0) for w in figures]
        return [s / 100 for s in shares], [theme.pct(s, 0) if s > 0 else "" for s in shares]

    def caption(label):
        paid = sorted(((w.by_season.get(label, 0.0), short(w.key)) for w in figures), reverse=True)
        names = " · ".join(f"{n} {theme.pct(s, 0)}" for s, n in paid if s > 0) or "No ward paid"
        return f"<b>{_season_name(label)}</b><br>{names}"

    ts, values = frame_values(labels[0])
    hovers = [hover(w, which) for w in figures]
    ward_trace(fig, figures, ts, values, hovers, selected)
    ward_index = len(fig.data) - 1
    not_offered_trace(fig, figures)
    fig.add_scatter(x=[X_RANGE[0] + 0.1], y=[-3.2], mode="text", text=[caption(labels[0])], textposition="middle right",
                    textfont={"size": 13, "color": theme.INK}, hoverinfo="skip", showlegend=False)
    caption_index = len(fig.data) - 1
    colour_bar(fig, *scale("Replay", params, len(labels)))

    frames = []
    for label in labels:
        ts, values = frame_values(label)
        frames.append(go.Frame(name=label, traces=[ward_index, caption_index], data=[
            go.Scatter(marker={"size": [size(t) for t in ts], "color": [colour(t) for t in ts],
                               "line": {"color": theme.SURFACE, "width": 2}},
                       text=[f"<b>{short(w.key)}</b><br>{v}" if v else f"<b>{short(w.key)}</b>"
                             for w, v in zip(figures, values)]),
            go.Scatter(text=[caption(label)]),
        ]))
    fig.frames = frames
    step = {"frame": {"duration": 0, "redraw": False}, "mode": "immediate", "transition": {"duration": 250}}
    fig.update_layout(
        updatemenus=[{"type": "buttons", "direction": "left", "x": 0, "y": -0.01, "xanchor": "left", "yanchor": "top",
                      "pad": {"r": 8, "t": 0}, "showactive": False, "bgcolor": theme.SURFACE, "bordercolor": theme.LINE,
                      "font": {"size": 12, "color": theme.INK}, "buttons": [
                          {"label": "Play", "method": "animate", "args": [None, {
                              "frame": {"duration": 1100, "redraw": False}, "fromcurrent": True,
                              "transition": {"duration": 450, "easing": "cubic-in-out"}}]},
                          {"label": "Pause", "method": "animate", "args": [[None], {
                              "frame": {"duration": 0, "redraw": False}, "mode": "immediate"}]}]}],
        sliders=[{"active": 0, "x": 0.2, "len": 0.8, "y": -0.01, "yanchor": "top", "pad": {"t": 4, "b": 0},
                  "currentvalue": {"visible": False}, "bgcolor": theme.LINE, "bordercolor": theme.LINE,
                  "activebgcolor": theme.GREEN, "tickcolor": theme.LINE, "font": {"size": 10, "color": theme.MUTED},
                  # A year under each long rains, a dot for the short rains that follow it
                  "steps": [{"label": lab.split()[0] if lab.endswith("LR") else "·", "value": lab,
                             "method": "animate", "args": [[lab], step]} for lab in labels]}],
    )
    return finish(fig, height=600, bottom=78)


def _names(group: list[WardFigures]) -> str:
    names = [short(w.key) for w in group]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def _tied(figures: list[WardFigures], shown) -> tuple[list, list]:
    """The wards at the top and at the bottom, judged by the value as shown, so equal figures always tie."""
    hi = max(figures, key=lambda w: shown(w)[0])
    lo = min(figures, key=lambda w: shown(w)[0])
    return ([w for w in figures if shown(w)[1] == shown(hi)[1]], [w for w in figures if shown(w)[1] == shown(lo)[1]])


def story(view: str, figures: list[WardFigures], params: TriggerParams, which: str,
          together: list[PayTogether] | None = None, load: pd.Series | None = None) -> str:
    """One or two sentences that say what the map shows, true for every setting."""
    nobody = f"With these triggers no ward would have been paid in any of the {which}."
    paying = [w for w in figures if w.risk and w.risk.paid]
    if view in ("Severity", "1-in-10 season", "Volatility") and not paying:
        return nobody
    if view == "Severity":
        hi, lo = _tied(paying, lambda w: (w.risk.severity_pct, theme.pct(w.risk.severity_pct, 0)))
        return (f"When it pays, {_names(hi)} {'pays' if len(hi) == 1 else 'pay'} the most: "
                f"{theme.pct(hi[0].risk.severity_pct, 0)} of the cover on average. {_names(lo)} the least, "
                f"{theme.pct(lo[0].risk.severity_pct, 0)}. High severity with low frequency means rare, heavy losses.")
    if view == "1-in-10 season":
        hi, lo = _tied(figures, lambda w: (w.risk.p90_pct, theme.pct(w.risk.p90_pct, 0)))
        return (f"In a 1-in-10 season {_names(hi)} would pay {theme.pct(hi[0].risk.p90_pct, 0)} of the cover to every "
                f"farm, {_names(lo)} {theme.pct(lo[0].risk.p90_pct, 0)}. The tail, not the average, sizes "
                "reinsurance and capital.")
    if view == "Volatility":
        hi, lo = _tied(paying, lambda w: (w.risk.volatility or 0, f"{w.risk.volatility or 0:.1f}"))
        return (f"{_names(hi)} {'has' if len(hi) == 1 else 'have'} the lumpiest payouts (CV "
                f"{hi[0].risk.volatility:.1f}): rare, large losses. {_names(lo)} {'is' if len(lo) == 1 else 'are'} "
                f"the steadiest (CV {lo[0].risk.volatility:.1f}). The price uses only the average, so volatility is "
                "the case for a risk margin on top.")
    if view == "Rain variability":
        hi, lo = _tied(figures, lambda w: (w.risk.rain_cv, f"{w.risk.rain_cv:.2f}"))
        return (f"{_names(hi)}'s seasonal rain varies most from year to year (CV {hi[0].risk.rain_cv:.2f}, around "
                f"{hi[0].risk.rain_mean_mm:,.0f} mm a season); {_names(lo)}'s the least ({lo[0].risk.rain_cv:.2f}). "
                "This is the hazard itself, before any product terms.")
    if view == "Accumulation":
        if not any(w.members for w in figures):
            return "No SACCO register is loaded, so there is no book to add up."
        total = sum(w.book_ksh for w in figures)
        unsold = [w for w in figures if not w.offered]
        text = (f"With every SACCO member in the offered wards insured on the standard farm, the book would expect "
                f"{theme.ksh_short(total)} of payouts a season")
        text += (f" ({_names(unsold)} {'is' if len(unsold) == 1 else 'are'} not sold, so left out)." if unsold else ".")
        if load is not None and len(load) and load.max() > 0:
            text += (f" Its worst season, {_season_name(load.idxmax())}, would have cost "
                     f"{theme.ksh_short(load.max())}.")
        sold = {w.key for w in figures if w.offered}
        close = sorted((p for p in (together or []) if p.correlation is not None and p.correlation >= TOGETHER),
                       key=lambda p: -p.correlation)
        in_book = [p for p in close if p.a in sold and p.b in sold]
        if in_book:
            top = in_book[0]
            text += (f" The lines join sold wards that pay in the same seasons; {short(top.a)} and {short(top.b)} "
                     f"move most together (correlation {top.correlation:.2f}).")
        else:
            text += (" No two sold wards pay together closely (every correlation is below "
                     f"{TOGETHER:g}): the book is well spread.")
        outside = [p for p in close if p not in in_book]
        if outside:
            p = outside[0]
            new = p.a if p.a not in sold else p.b
            text += (f" Selling {short(new)} would add accumulation: it pays together with "
                     f"{short(p.b if new == p.a else p.a)} (correlation {p.correlation:.2f}).")
        return text
    if view == "Burn cost":
        hi, lo = _tied(figures, lambda w: (w.burn_pct, theme.pct(w.burn_pct, 1)))
        if hi[0].burn_pct == 0:
            return nobody
        if len(hi) == len(figures):
            return f"Every ward has the same burn cost, {theme.pct(hi[0].burn_pct, 1)} of the sum insured a season."
        one = len(hi) == 1
        text = (f"{_names(hi)} {'carries' if one else 'carry'} the most risk: {'its' if one else 'their'} cover would "
                f"have paid {theme.pct(hi[0].burn_pct, 1)} of the sum insured a season on average. ")
        if lo[0].burn_pct == 0:
            return text + f"{_names(lo)} would never have been paid."
        return text + f"{_names(lo)} {'carries' if len(lo) == 1 else 'carry'} the least, {theme.pct(lo[0].burn_pct, 1)}."
    if view == "Price":
        blocked = [w for w in figures if not w.offered]
        ceiling = f"{params.max_sellable_rate:.0%}"
        if params.pricing_mode == "flat":
            rate = theme.pct(figures[0].rate_pct, 1)
            if len(blocked) == len(figures):
                return (f"One flat rate of {rate} is above the {ceiling} ceiling, so the standard bundle is not "
                        "offered in any ward (the crosses).")
            burn = {w.key: w.burn_pct if w.burn_pct_all is None else w.burn_pct_all for w in figures}  # both seasons
            losing = [w for w in figures if burn[w.key] > w.rate_pct + 1e-9]
            text = f"On one flat rate every ward pays {rate}, although their burn costs run from " \
                   f"{theme.pct(min(burn.values()), 1)} to {theme.pct(max(burn.values()), 1)}."
            if len(losing) == len(figures):
                return text + " That is less than every ward's burn cost: the cover would pay out more than it collects."
            if losing:
                return text + (f" {_names(losing)} would pay out more than {'it collects' if len(losing) == 1 else 'they collect'}; "
                               "the other wards make up the difference.")
            return text + " Every ward's burn cost is below it, so the low-risk wards pay furthest over their risk."
        if len(blocked) == len(figures):
            rates = [w.rate_pct for w in figures]
            return (f"Every ward prices above the {ceiling} ceiling, from {theme.pct(min(rates), 1)} to "
                    f"{theme.pct(max(rates), 1)}, so the standard bundle is not offered anywhere (the crosses).")
        text = f"{len(figures) - len(blocked)} of {len(figures)} wards price at or under the {ceiling} ceiling."
        if blocked:
            costs = [f"{short(w.key)} ({theme.pct(w.rate_pct, 1)})" for w in blocked]
            listed = costs[0] if len(costs) == 1 else ", ".join(costs[:-1]) + " and " + costs[-1]
            one = len(blocked) == 1
            text += (f" {listed} {'prices' if one else 'price'} above it, so the standard bundle is not offered "
                     f"{'there' if one else 'in those wards'} (the {'cross' if one else 'crosses'}).")
        return text
    if view == "Frequency":
        most, least = max(w.paid for w in figures), min(w.paid for w in figures)
        n = figures[0].seasons
        if most == 0:
            return nobody
        if most == least:
            return f"Every ward would have been paid in {most} of {n} {which}."
        top = [w for w in figures if w.paid == most]
        bottom = [w for w in figures if w.paid == least]
        if least == 0:
            return (f"{_names(top)} would have been paid in {most} of {n} {which}; {_names(bottom)} "
                    f"{'was' if len(bottom) == 1 else 'were'} never paid.")
        return (f"{_names(top)} would have been paid in {most} of {n} {which}; {_names(bottom)} in {least}. "
                "Frequent small payouts and rare large ones can cost the same.")
    if view == "Worst season":
        worst = max(w.worst_pct for w in figures)
        if not worst:
            return nobody
        top = [w for w in figures if theme.pct(w.worst_pct, 0) == theme.pct(worst, 0)]
        if len(top) == 1:
            return (f"The worst single season was {top[0].worst_label} in {short(top[0].key)}: the cover would have "
                    f"paid {theme.pct(worst, 0)} of the sum insured to every farm.")
        where = "; ".join(f"{short(w.key)} in {w.worst_label}" for w in top)
        return f"The worst single seasons paid {theme.pct(worst, 0)} of the sum insured to every farm: {where}."
    labels = list(figures[0].by_season)
    counts = {lab: sum(w.by_season.get(lab, 0) > 0 for w in figures) for lab in labels}
    busiest = max(labels, key=lambda lab: (counts[lab], sum(w.by_season.get(lab, 0) for w in figures)))
    if not counts[busiest]:
        return nobody + " Press Play to check each one."
    play = "Press Play to run 2015 to 2024 season by season, or drag the slider."
    if counts[busiest] == 1:
        return f"{play} No season paid more than one ward at once, so these triggers never saw a widespread drought."
    return (f"{play} A widespread drought shows as several circles at once: {_season_name(busiest)} paid in "
            f"{counts[busiest]} of {len(figures)} wards.")


def ranking(view: str, figures: list[WardFigures], params: TriggerParams, selected: str) -> list[tuple]:
    top = max((w.book_ksh for w in figures), default=0.0)

    def label(w):
        return short(w.key) + (" (shown below)" if w.key == selected else "")

    if view == "Replay":  # the ward that paid most often first
        rows = sorted(figures, key=lambda w: (-w.paid, -w.burn_pct))
        return [(label(w), f"{w.paid} of {w.seasons} paid", "" if w.key == selected else "muted") for w in rows]
    keyed = sorted(figures, key=lambda w: -measure(view, w, params, top)[0])
    return [(label(w), measure(view, w, params, top)[1], "" if w.key == selected else "muted") for w in keyed]


def profile_card(w: WardFigures, params: TriggerParams, which: str) -> None:
    """Everything an underwriter weighs for the selected ward, in one strip."""
    r = w.risk
    headroom = w.headroom_pp
    theme.stats([
        ("Frequency", theme.pct(r.frequency_pct, 0), f"{r.paid} of {r.seasons} {which} paid"),
        ("Severity", theme.pct(r.severity_pct, 0) if r.paid else "n/a", "Average payout when it pays, of cover"),
        ("1-in-10 season", theme.pct(r.p90_pct, 0), "Payout exceeded in one season in ten"),
        ("Volatility", f"CV {r.volatility:.1f}" if r.volatility is not None else "n/a",
         "Payouts' standard deviation over their average", "warn" if (r.volatility or 0) > 2.5 else ""),
        ("Rain", f"{r.rain_mean_mm:,.0f} mm", f"A season; varies by CV {r.rain_cv:.2f}"),
        ("Headroom to ceiling", f"{'+' if headroom >= 0 else '-'}{abs(headroom):.1f} pts",
         f"{params.max_sellable_rate:.0%} ceiling minus the {theme.pct(w.rate_pct, 1)} price",
         "bad" if headroom < 0 else "warn" if headroom < 1 else ""),
        ("Book in this ward",
         "n/a" if not w.members else theme.ksh_short(w.members * w.sum_insured) if w.offered else "Not sold",
         "No SACCO register loaded" if not w.members else
         f"{w.members} members insured; expected payouts {theme.ksh_short(w.expected_loss_ksh)} a season"
         if w.offered else
         f"Would be {theme.ksh_short(w.members * w.sum_insured)} for {w.members} members, expecting "
         f"{theme.ksh_short(w.expected_loss_ksh)} a season, if it were sold"),
    ])


GLOSSARY = [
    ("Burn cost", "Average payout a season as a share of the cover. The price is the burn cost divided by the target "
                  "loss ratio, rounded up to 0.1%, never under 1%."),
    ("Loss ratio", "Payouts as a share of premium. The target (60% by default) leaves room for reinsurance, data, "
                   "expenses and margins."),
    ("Frequency and severity", "How often the cover pays, and how much when it does. Burn cost is roughly the two "
                               "multiplied."),
    ("1-in-10 season", "The payout exceeded in one season out of ten (the 90th percentile of 2015-2024)."),
    ("Volatility (CV)", "Standard deviation of seasonal payouts over their average. Above about 2.5 the payouts are "
                        "rare and large."),
    ("Rain variability (CV)", "Standard deviation of seasonal rainfall over its average: the hazard, before any terms."),
    ("Headroom to ceiling", "Sellable ceiling minus the price, in percentage points. Below zero the ward is not sold."),
    ("Accumulation", "Wards whose payouts rise and fall together (correlation of seasonal payouts). Their losses "
                     "arrive in the same season, so they add up for the insurer and the reinsurer."),
    ("Basis risk", "Seasons where the index and the crop disagree, compared with a rainfall-only trigger (chapter 1 "
                   "stat strip)."),
]


def render(selected: str, zones: pd.DataFrame, backtests: dict, season_keys, params: TriggerParams,
           which: str, members: dict | None = None) -> None:
    """The map panel. Tapping a ward opens its story: the sidebar ward changes on the next run."""
    figures = ward_figures(zones, backtests, season_keys, params, members)
    together = pay_together(backtests, season_keys)
    sold = {w.key for w in figures if w.offered}
    load = season_load(backtests, season_keys, {k: n for k, n in (members or {}).items() if k in sold})
    counted = "both seasons" if which == "seasons" else f"the {which} only (the price always uses both)"
    with theme.panel("Where the risk sits",
                     f"The five pilot wards on Kenya's 47 counties, on the same terms, counting {counted}. Circles "
                     "grow and darken with the measure. Tap a ward to open its story."):
        pick, why = st.columns([1, 2], vertical_alignment="bottom")
        view = pick.selectbox("Colour the wards by", VIEWS, key="map_measure",
                              help="Each measure is worked out from the same 2015-2024 backtest as the price.")
        why.markdown(f'<p class="ss-panel-desc" style="margin:0 0 0.9rem">{VIEW_HELP[view]}</p>',
                     unsafe_allow_html=True)
        left, right = st.columns([5, 2], gap="medium")
        fig = replay_map(figures, params, selected, which) if view == "Replay" else \
            static_map(view, figures, params, selected, which,
                       [p for p in together if p.a in sold and p.b in sold])  # the lines show the book only
        picks = st.session_state.get("map_picks", 0)
        event = left.plotly_chart(fig, width="stretch", key=f"risk_map_{picks}", on_select="rerun",
                                  selection_mode="points", config={"displayModeBar": False, "scrollZoom": False})
        with right:
            st.markdown(f'<p class="ss-map-story">{story(view, figures, params, which, together, load)}</p>',
                        unsafe_allow_html=True)
            theme.ledger(ranking(view, figures, params, selected))
            if any(not w.offered for w in figures):
                st.caption(f"× marks a ward priced above the {params.max_sellable_rate:.0%} ceiling: the standard "
                           "bundle is not offered there.")
            st.caption("County outlines: geoBoundaries (RCMRD), public domain. A ward is priced on its own "
                       "weather, not its county's.")
        chosen = next(w for w in figures if w.key == selected)
        st.markdown(f"**Underwriting profile: {WARDS[selected].label}** ({which} counted; the price always uses "
                    "both)" if which != "seasons" else f"**Underwriting profile: {WARDS[selected].label}**")
        profile_card(chosen, params, which)
        with st.expander("What these measures mean"):
            for term, meaning in GLOSSARY:
                st.markdown(f"**{term}.** {meaning}")
    points = (event or {}).get("selection", {}).get("points", []) if event else []
    picked = next((p.get("customdata") for p in points if p.get("customdata") in WARDS), None)
    if picked:
        # Rerun at once on a fresh chart, so the tap is not replayed and the next tap is never lost.
        st.session_state["map_picks"] = picks + 1
        if picked != selected:
            st.session_state["_map_pick"] = picked
        st.rerun()
