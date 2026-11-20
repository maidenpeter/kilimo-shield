"""Tab 1: reinsurer and actuarial backtest simulator."""
from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from engine.parametric_engine import (
    SEASONS, SOURCE_FALLBACK, SOURCE_LIVE, WARDS, YEARS, TriggerParams, dekadal_trajectory, kpis, load_weather,
    run_backtest, zone_pricing,
)
from ui import theme

SEASON_FILTERS = {"Both seasons": ("LR", "SR"), "Long rains": ("LR",), "Short rains": ("SR",)}
PRICING_MODES = {"Target loss ratio, priced per ward": "target", "One flat rate for every ward": "flat"}
RAIN_MODES = {"Ward's own percentile": "percentile", "Fixed mm for every ward": "fixed"}


@st.cache_data(show_spinner="Loading 10 years of daily weather...")
def weather_for(ward_key: str, refresh_count: int):
    return load_weather(ward_key, refresh=refresh_count > 0)


@st.cache_data(show_spinner=False)
def backtest_for(ward_key: str, refresh_count: int, params: TriggerParams):
    weather, _, _ = weather_for(ward_key, refresh_count)
    return run_backtest(weather, params)


@st.cache_data(show_spinner="Pricing every ward...")
def zone_pricing_for(refresh_count: int, params: TriggerParams):
    return zone_pricing(params, loader=lambda key: weather_for(key, refresh_count))


def _ksh_slider(container, label, low, high, step, value, key=None, help=None):
    return container.select_slider(label, options=list(range(low, high + 1, step)), value=value,
                                   format_func=lambda v: f"KSh {v:,}", key=key, help=help)


def sidebar_controls() -> tuple[str, TriggerParams]:
    sb = st.sidebar
    sb.markdown("#### Ward and cover")
    ward_key = sb.selectbox("Pilot ward", list(WARDS), format_func=lambda k: WARDS[k].label, key="ward")
    sum_insured = _ksh_slider(sb, "Sum insured per farm per season", 20_000, 150_000, 5_000, 60_000, key="si")

    sb.markdown("#### Pricing")
    mode = PRICING_MODES[sb.radio("Premium basis", list(PRICING_MODES), key="pricing_mode")]
    target_lr, flat_rate = 60, 6.0
    if mode == "target":
        target_lr = sb.slider("Target loss ratio (%)", 50, 70, 60,
                              help="Leaves room for reinsurance, data and expenses, and the insurer's and SACCO's margin")
    else:
        flat_rate = sb.slider("Commercial premium rate (%)", 2.0, 20.0, 6.0, 0.5)
    ceiling = sb.slider("Sellable premium ceiling (%)", 6, 25, 12, key="ceiling",
                        help="Wards priced above this are not sold the standard bundle and need a custom tier")
    subsidy = sb.slider("Premium subsidy (%)", 0, 70, 0, 5,
                        help="Share paid by a county or national scheme. None is agreed: illustrative only.")

    sb.markdown("#### Triggers")
    sm_trigger = sb.slider("Soil moisture trigger (index, 50 = normal)", 15, 50, 32)
    ndvi_trigger = sb.slider("Pasture NDVI trigger (percentile)", 10, 50, 25)
    with sb.expander("More settings"):
        sm_exit = st.slider("Soil moisture for 100% crop payout", 0, max(sm_trigger - 1, 1), min(12, sm_trigger - 1))
        gate = st.slider("Fodder needs a crop payout of at least (% of its limit)", 25, 100, 50, 25)
        cap_default = min(sum_insured, round(sum_insured * 5 / 6 / 1_000) * 1_000)
        cap_ksh = _ksh_slider(st, "Seasonal cap, all layers", 10_000, sum_insured, 1_000, cap_default,
                              key=f"cap_{sum_insured}", help="KSh 50,000 on a KSh 60,000 sum insured")
        rain_mode = RAIN_MODES[st.radio("Excess-rain line", list(RAIN_MODES), key="rain_mode")]
        rain_pct, rain_mm = 90, 180
        if rain_mode == "percentile":
            rain_pct = st.slider("Percentile of the ward's wettest 10 days per season", 75, 98, 90)
        else:
            rain_mm = st.slider("Excess rain: 10-day total (mm)", 100, 300, 180, 10)
        heat_c = st.slider("Heat day: maximum above (deg C)", 26.0, 36.0, 31.0, 0.5)
        heat_days = st.slider("Heatwave: consecutive heat days", 3, 14, 7)
        capacity = st.slider("Root-zone water capacity (mm)", 60, 200, 100, 10)
        accuracy = st.slider("Assumed WhatsApp check accuracy (%)", 50, 100, 80, 5,
                             help="Used only for the with-check basis-risk figure")
        if st.button("Refresh weather from Open-Meteo", help="Download every ward's 2015-2024 record again"):
            st.session_state["refresh_count"] = st.session_state.get("refresh_count", 0) + 1
    params = TriggerParams(
        sum_insured=float(sum_insured), pricing_mode=mode, target_loss_ratio=target_lr / 100,
        premium_rate=flat_rate / 100, subsidy_share=subsidy / 100, max_sellable_rate=ceiling / 100,
        sm_trigger=float(sm_trigger), sm_exit=float(sm_exit), fodder_gate=gate / 100,
        aggregate_cap_share=cap_ksh / sum_insured, ndvi_trigger=float(ndvi_trigger), rain10_mode=rain_mode,
        rain10_percentile=float(rain_pct), rain10_trigger_mm=float(rain_mm), heat_temp_c=float(heat_c),
        heat_days=int(heat_days), capacity_mm=float(capacity), verifier_accuracy=accuracy / 100,
    )
    return ward_key, params


def payout_chart(seasons, season_keys) -> go.Figure:
    data = seasons[seasons["season"].isin(season_keys)]
    by_year = data.groupby("year")[["payout_a", "payout_b", "payout_c", "premium"]].sum().reindex(YEARS, fill_value=0)
    fig = go.Figure()
    for col, name in (("payout_a", "Payout A: crop inputs"), ("payout_b", "Payout B: fodder gap"),
                      ("payout_c", "Payout C: vet and health")):
        fig.add_bar(x=by_year.index, y=by_year[col], name=name, marker_color=theme.LAYER_COLOURS[name],
                    hovertemplate="%{x}: KSh %{y:,.0f}<extra>" + name + "</extra>")
    fig.add_scatter(x=by_year.index, y=by_year["premium"], name="Premium per farm", mode="lines+markers",
                    line={"color": theme.INK, "dash": "dash", "width": 1.5}, marker={"size": 5},
                    hovertemplate="%{x}: KSh %{y:,.0f}<extra>Premium</extra>")
    fig.update_layout(barmode="stack", bargap=0.35)
    fig.update_xaxes(dtick=1)
    fig.update_yaxes(title="KSh per farm", tickformat=",.0f")
    return theme.plot_layout(fig, height=380)


def trajectory_chart(weather, params: TriggerParams, season: str, year: int, compare: int) -> go.Figure:
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.1,
                        subplot_titles=("Soil moisture index (50 = normal)", "Pasture NDVI (proxy)"))
    for yr, colour, dash in ((year, theme.RED, "solid"), (compare, theme.GREEN, "dot")):
        traj = dekadal_trajectory(weather, yr, season, params)
        fig.add_scatter(x=traj["dekad"], y=traj["sm_index"], name=str(yr), mode="lines+markers",
                        line={"color": colour, "dash": dash, "width": 2.5}, row=1, col=1,
                        hovertemplate="Dekad %{x}: %{y:.1f}<extra>" + str(yr) + "</extra>")
        fig.add_scatter(x=traj["dekad"], y=traj["ndvi"], name=str(yr), mode="lines+markers",
                        line={"color": colour, "dash": dash, "width": 2}, showlegend=False, row=2, col=1,
                        hovertemplate="Dekad %{x}: %{y:.2f}<extra>" + str(yr) + "</extra>")
    fig.add_hline(y=50, line={"color": theme.MUTED, "dash": "dot", "width": 1}, row=1, col=1,
                  annotation_text="Normal", annotation_position="top right")
    fig.add_hline(y=params.sm_trigger, line={"color": theme.RED, "dash": "dash", "width": 1}, row=1, col=1,
                  annotation_text=f"Crop trigger {params.sm_trigger:.0f}", annotation_position="bottom right")
    for start, end, label in ((1, 3, "Germination"), (5.5, 8, "Flowering")):
        fig.add_vrect(x0=start - 0.5, x1=end + 0.5, fillcolor="#f2f4f7", opacity=0.9, line_width=0, layer="below",
                      annotation_text=label, annotation_position="top left", row=1, col=1)
    fig.update_xaxes(title="Dekad of the season (10-day blocks)", dtick=1, row=2, col=1)
    fig.update_yaxes(range=[0, 100], row=1, col=1)
    fig.update_annotations(font_size=12)
    return theme.plot_layout(fig, height=500)


def _signed(score) -> str:
    return "n/a" if score is None else f"{score:+.0f}%"


def stat_row(k, params: TriggerParams) -> None:
    how = (f"{params.target_loss_ratio:.0%} target loss ratio" if params.pricing_mode == "target" else "flat rate")
    if not k.offered:
        premium_note, premium_tone = f"{theme.ksh(k.premium_ksh)}; above the {params.max_sellable_rate:.0%} ceiling, " \
                                     "not offered", "bad"
    elif params.subsidy_share:
        premium_note, premium_tone = (f"{theme.ksh(k.premium_ksh)}; farmer pays {theme.ksh(k.farmer_premium_ksh)} "
                                      f"after {params.subsidy_share:.0%} subsidy", "")
    else:
        premium_note, premium_tone = f"{theme.ksh(k.premium_ksh)} a season at a {how}", ""
    b = k.basis
    theme.stats([
        ("Burn cost", theme.pct(k.burn_cost_pct, 2), f"Average payout a season, of {theme.ksh(params.sum_insured)}"),
        ("Premium rate", theme.pct(k.premium_rate_pct, 1), premium_note, premium_tone),
        ("Loss ratio", theme.pct(k.loss_ratio_pct, 0), f"{k.seasons_paying} of {k.seasons} seasons paid",
         "bad" if k.loss_ratio_pct > 100 else "warn" if k.loss_ratio_pct > 70 else ""),
        ("Worst year", str(k.worst_year) if k.worst_year else "None",
         f"{theme.ksh(k.worst_year_payout)} a farm" if k.worst_year else "No season paid"),
        ("Basis-risk score", f"{_signed(b.score)} / {_signed(b.score_verified)}",
         f"Index alone / with the WhatsApp check ({params.verifier_accuracy:.0%} assumed)",
         "bad" if b.score is not None and b.score < 0 else ""),
    ])


def zone_table(zones) -> None:
    with theme.panel("Zone pricing across the pilot wards",
                     "Same terms in every ward, priced on 20 seasons (2015-2024). A ward above the sellable ceiling "
                     "is not sold the standard bundle; it is referred for a custom tier built on its own enterprise."):
        st.dataframe(zones.drop(columns=["ward_key"]), hide_index=True, width="stretch", column_config={
            "ward": "Ward", "zone": "Zone",
            "burn_cost_pct": st.column_config.NumberColumn("Burn cost %", format="%.2f"),
            "premium_rate_pct": st.column_config.NumberColumn("Premium %", format="%.1f"),
            "premium_ksh": st.column_config.NumberColumn("Premium KSh", format="localized"),
            "farmer_premium_ksh": st.column_config.NumberColumn("Farmer pays KSh", format="localized"),
            "loss_ratio_pct": st.column_config.NumberColumn("Loss ratio %", format="%.0f"),
            "seasons_paying": st.column_config.NumberColumn("Seasons paid"),
            "rain10_line_mm": st.column_config.NumberColumn("Rain line mm", format="%.0f"),
            "basis_score": st.column_config.NumberColumn("Basis, index", format="%+.0f"),
            "basis_score_verified": st.column_config.NumberColumn("Basis, with check", format="%+.0f"),
            "offered": "Offered",
        })


def render() -> dict:
    ward_key, params = sidebar_controls()
    ward = WARDS[ward_key]
    refresh_count = st.session_state.get("refresh_count", 0)
    weather, source, meta = weather_for(ward_key, refresh_count)
    seasons = backtest_for(ward_key, refresh_count, params)
    zones = zone_pricing_for(refresh_count, params)

    head, pick = st.columns([5, 3], vertical_alignment="bottom")
    with head:
        st.markdown(f"## {ward.label}")
        where = ""
        if source != SOURCE_FALLBACK and meta.get("grid_lat") is not None:
            where = (f" Weather: Open-Meteo grid cell {meta['grid_lat']:.3f}, {meta['grid_lon']:.3f} at "
                     f"{meta.get('elevation_m', 0):,.0f} m, retrieved {str(meta.get('retrieved_at', ''))[:10]}.")
        st.caption(f"{ward.enterprise}. {ward.zone} zone.{where}")
    filter_label = pick.segmented_control("Seasons", list(SEASON_FILTERS), default="Both seasons",
                                          key="season_filter", label_visibility="collapsed") or "Both seasons"
    if source == SOURCE_FALLBACK:
        theme.note("No network and no cached copy: these figures use synthetic weather so the demo still runs. "
                   "They are not this ward's history.")
    elif source == SOURCE_LIVE:
        st.caption("Fresh download from Open-Meteo; the cached copy has been updated.")

    season_keys = SEASON_FILTERS[filter_label]
    k = kpis(seasons[seasons["season"].isin(season_keys)], params)
    stat_row(k, params)

    with theme.panel("Payouts per farm, 2015-2024",
                     "Each bar is what one insured farm would have received that year, by layer. The dashed line is "
                     "the premium it would have paid."):
        st.plotly_chart(payout_chart(seasons, season_keys), width="stretch")

    zone_table(zones)

    with theme.panel("Season trajectory",
                     "Soil moisture index (a SAR-style proxy, 50 is normal for the date) and pasture greenness, "
                     "dekad by dekad. Shaded: germination and flowering windows."):
        t1, t2, t3 = st.columns(3)
        season = t1.selectbox("Season", list(SEASONS), format_func=lambda s: SEASONS[s]["name"], key="traj_season")
        year = t2.selectbox("Year", YEARS, index=YEARS.index(2022), key="traj_year")
        compare = t3.selectbox("Compare with", YEARS, index=YEARS.index(2020), key="traj_compare")
        st.plotly_chart(trajectory_chart(weather, params, season, year, compare), width="stretch")

    with st.expander("Season-by-season results"):
        table = seasons[["label", "rain_mm", "sm_weighted", "ndvi_pct", "max_rain10_mm", "hot_run_days", "wrsi",
                         "payout_a", "payout_b", "payout_c", "payout_uncapped", "payout_total"]]
        st.dataframe(table, hide_index=True, width="stretch", column_config={
            "label": "Season", "rain_mm": st.column_config.NumberColumn("Rain mm", format="%.0f"),
            "sm_weighted": st.column_config.NumberColumn("Weighted soil moisture", format="%.1f"),
            "ndvi_pct": st.column_config.NumberColumn("Pasture NDVI pct", format="%.0f"),
            "max_rain10_mm": st.column_config.NumberColumn("Wettest 10 days mm", format="%.0f"),
            "hot_run_days": st.column_config.NumberColumn("Heat run days"),
            "wrsi": st.column_config.NumberColumn("WRSI", format="%.0f"),
            "payout_a": st.column_config.NumberColumn("A KSh", format="localized"),
            "payout_b": st.column_config.NumberColumn("B KSh", format="localized"),
            "payout_c": st.column_config.NumberColumn("C KSh", format="localized"),
            "payout_uncapped": st.column_config.NumberColumn("Before cap KSh", format="localized"),
            "payout_total": st.column_config.NumberColumn("Paid KSh", format="localized"),
        })
        st.caption(f"Excess-rain line for this ward: {k.rain10_line_mm:.0f} mm in 10 days.")
        st.download_button("Download season results (CSV)", seasons.to_csv(index=False).encode(),
                           f"backtest_{ward_key}.csv", "text/csv")

    with st.expander("How the three layers pay, and how the price is set"):
        rain_rule = (f"more than this ward's {params.rain10_percentile:.0f}th percentile of its wettest 10 days per "
                     f"season ({k.rain10_line_mm:.0f} mm here)" if params.rain10_mode == "percentile"
                     else f"more than {params.rain10_trigger_mm:.0f} mm")
        price_rule = (f"Each ward's premium is its burn cost divided by the {params.target_loss_ratio:.0%} target loss "
                      "ratio, rounded up to 0.1%." if params.pricing_mode == "target"
                      else "One flat rate for every ward.")
        st.markdown(f"""
**Sum insured {theme.ksh(params.sum_insured)} per farm per season**, with sub-limits of {theme.ksh(params.crop_allocation)}
for crop inputs, {theme.ksh(params.fodder_allocation)} for livestock fodder and {theme.ksh(params.health_payout)} for vet
and health, and a seasonal cap of {theme.ksh(params.aggregate_cap)} across all three. When the layers together would
pay more than the cap, each is scaled down by the same share.

- **Payout A, crop inputs.** Soil moisture is averaged over germination (days 1 to 30, weight 35%) and flowering
  (days 45 to 75, weight 65%). Below {params.sm_trigger:.0f} it pays 25% of the crop sub-limit, rising in a straight
  line to 100% at {params.sm_exit:.0f}. Paid within 10 days of the season's end.
- **Payout B, fodder gap.** Only after a severe crop loss (Payout A at {params.fodder_gate:.0%} of its sub-limit or
  more) **and** when pasture greenness from day {params.fodder_ndvi_days[0]} to the season's end is below the
  {params.ndvi_trigger:.0f}th percentile of this ward's record. Pays 50% to 100% of the sub-limit; a
  hotter-than-usual season raises the share.
- **Payout C, vet and health.** A flat {theme.ksh(params.health_payout)} when any 10 days bring {rain_rule}
  (disease and flood risk), or the daily maximum stays above {params.heat_temp_c:.0f} deg C for {params.heat_days}
  days or more (dairy heat stress).

**Price.** {price_rule} A ward above the {params.max_sellable_rate:.0%} sellable ceiling is not offered. The subsidy
slider only shows what a farmer would pay if a scheme covered part of the premium; no subsidy is agreed.

**Data.** Daily rainfall, reference evapotranspiration (FAO-56) and maximum temperature: Open-Meteo Historical Weather
API (ERA5-based reanalysis, CC BY 4.0). A root-zone water balance ({params.capacity_mm:.0f} mm capacity) turns the
weather into soil water. The **soil moisture index** compares each day's soil water with the same time of year in
this ward's 2015-2024 record: 50 is normal, and each standard deviation drier takes 25 points off. The pasture NDVI
follows soil water with a lag. Both are **synthetic proxies** for Sentinel-1 SAR soil moisture and Sentinel-2 NDVI.

**Basis-risk score.** Each season is checked against the maize Water Requirement Satisfaction Index (WRSI, FAO crop
curve, same water balance); below 60 counts as a poor or failed season (FEWS NET scale). A mismatch is a payout
without a poor season, or a poor season without a payout. The score is how many fewer mismatches the crop index has
than a rainfall-only trigger (season rain below 75% of average); negative means rainfall-only did better. The second
figure sends seasons within {params.amber_band:.0f} points of the trigger to the WhatsApp photo check and **assumes**
the photos settle {params.verifier_accuracy:.0%} of them correctly; the network has not run in the field. Both are
model checks: they need yields or loan-default records from the SACCO.
""")
    offered = zones[zones["offered"] == "Yes"]
    return {"ward_key": ward_key, "params": params, "kpis": k,
            "zone_premiums": dict(zip(zones["ward_key"], zones["premium_ksh"])),
            "zone_farmer_premiums": dict(zip(zones["ward_key"], zones["farmer_premium_ksh"])),
            "offered_premiums": dict(zip(offered["ward_key"], offered["farmer_premium_ksh"]))}
