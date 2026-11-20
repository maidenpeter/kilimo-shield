"""Tab 1: reinsurer and actuarial backtest simulator."""
from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from engine.parametric_engine import (
    SEASONS, SOURCE_FALLBACK, SOURCE_LIVE, WARDS, YEARS, TriggerParams, dekadal_trajectory, kpis, load_weather,
    run_backtest,
)
from ui import theme

SEASON_FILTERS = {"Both seasons": ("LR", "SR"), "Long rains (MAM)": ("LR",), "Short rains (OND)": ("SR",)}


@st.cache_data(show_spinner="Loading 10 years of daily weather...")
def weather_for(ward_key: str, refresh_count: int):
    return load_weather(ward_key, refresh=refresh_count > 0)


@st.cache_data(show_spinner=False)
def backtest_for(ward_key: str, refresh_count: int, params: TriggerParams):
    weather, _, _ = weather_for(ward_key, refresh_count)
    return run_backtest(weather, params)


def sidebar_controls() -> tuple[str, TriggerParams]:
    sb = st.sidebar
    sb.markdown("### Reinsurer backtest")
    ward_key = sb.selectbox("Pilot ward", list(WARDS), format_func=lambda k: WARDS[k].label, key="ward")
    sum_insured = sb.slider("Sum insured per farm per season (KSh)", 20_000, 150_000, 60_000, 5_000)
    rate = sb.slider("Commercial premium rate (%)", 2.0, 15.0, 6.0, 0.5)
    sm_trigger = sb.slider("Soil moisture trigger (index, 50 = normal)", 15, 50, 32)
    ndvi_trigger = sb.slider("Pasture NDVI trigger (percentile)", 10, 50, 30)
    with sb.expander("More trigger settings"):
        sm_exit = st.slider("Soil moisture for 100% crop payout", 0, max(sm_trigger - 1, 1), min(12, sm_trigger - 1))
        rain10 = st.slider("Excess rain: 10-day total (mm)", 100, 300, 180, 10)
        heat_c = st.slider("Heat day: maximum above (deg C)", 26.0, 36.0, 31.0, 0.5)
        heat_days = st.slider("Heatwave: consecutive heat days", 3, 14, 7)
        capacity = st.slider("Root-zone water capacity (mm)", 60, 200, 100, 10)
    if sb.button("Refresh weather from Open-Meteo", help="Download the ward's 2015-2024 record again"):
        st.session_state["refresh_count"] = st.session_state.get("refresh_count", 0) + 1
    params = TriggerParams(
        sum_insured=float(sum_insured), premium_rate=rate / 100, sm_trigger=float(sm_trigger), sm_exit=float(sm_exit),
        ndvi_trigger=float(ndvi_trigger), rain10_trigger_mm=float(rain10), heat_temp_c=float(heat_c),
        heat_days=int(heat_days), capacity_mm=float(capacity),
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
                    line={"color": theme.INK, "dash": "dash", "width": 2},
                    hovertemplate="%{x}: KSh %{y:,.0f}<extra>Premium</extra>")
    fig.update_layout(barmode="stack")
    fig.update_xaxes(dtick=1)
    fig.update_yaxes(title="KSh per farm", tickformat=",.0f", tickprefix="KSh ")
    return theme.plot_layout(fig, "Payouts per farm, 2015-2024")


def trajectory_chart(weather, params: TriggerParams, season: str, year: int, compare: int) -> go.Figure:
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.08,
                        subplot_titles=("Soil moisture index (50 = normal)", "Pasture NDVI (proxy)"))
    for yr, colour, dash in ((year, theme.AMBER, "solid"), (compare, theme.GREEN, "dot")):
        traj = dekadal_trajectory(weather, yr, season, params)
        fig.add_scatter(x=traj["dekad"], y=traj["sm_index"], name=f"{yr} soil moisture", mode="lines+markers",
                        line={"color": colour, "dash": dash, "width": 3}, row=1, col=1,
                        hovertemplate="Dekad %{x}: %{y:.1f}<extra>" + str(yr) + "</extra>")
        fig.add_scatter(x=traj["dekad"], y=traj["ndvi"], name=f"{yr} NDVI", mode="lines+markers",
                        line={"color": colour, "dash": dash, "width": 2}, showlegend=False, row=2, col=1,
                        hovertemplate="Dekad %{x}: %{y:.2f}<extra>" + str(yr) + "</extra>")
    fig.add_hline(y=50, line={"color": theme.MUTED, "dash": "dot", "width": 1}, row=1, col=1,
                  annotation_text="Normal", annotation_position="top right")
    fig.add_hline(y=params.sm_trigger, line={"color": theme.RED, "dash": "dash"}, row=1, col=1,
                  annotation_text=f"Crop trigger {params.sm_trigger:.0f}", annotation_position="bottom right")
    for start, end, label in ((1, 3, "Germination"), (5.5, 8, "Flowering")):
        fig.add_vrect(x0=start - 0.5, x1=end + 0.5, fillcolor=theme.AMBER_SOFT, opacity=0.35, line_width=0,
                      annotation_text=label, annotation_position="top left", row=1, col=1)
    fig.update_xaxes(title="Dekad of the season (10-day blocks)", dtick=1, row=2, col=1)
    fig.update_yaxes(range=[0, 100], row=1, col=1)
    name = SEASONS[season]["name"]
    return theme.plot_layout(fig, f"{name}: {year} against {compare}", height=520)


def render() -> dict:
    ward_key, params = sidebar_controls()
    ward = WARDS[ward_key]
    refresh_count = st.session_state.get("refresh_count", 0)
    weather, source, meta = weather_for(ward_key, refresh_count)
    seasons = backtest_for(ward_key, refresh_count, params)

    st.subheader(f"{ward.label}: {ward.enterprise}")
    tone = "AMBER" if source == SOURCE_FALLBACK else "GREEN"
    detail = ""
    if source != SOURCE_FALLBACK and meta.get("grid_lat") is not None:
        detail = (f"Grid cell {meta['grid_lat']:.3f}, {meta['grid_lon']:.3f} at {meta.get('elevation_m', 0):,.0f} m; "
                  f"retrieved {str(meta.get('retrieved_at', ''))[:10]}")
    st.markdown(theme.badge(source, tone) + f" <small>{detail}</small>", unsafe_allow_html=True)
    if source == SOURCE_FALLBACK:
        theme.note("No network and no cached copy: these charts use synthetic weather so the demo still runs. "
                   "Numbers are not this ward's history.")
    elif source == SOURCE_LIVE:
        st.caption("Fresh download from Open-Meteo; the cached copy has been updated.")

    filter_label = st.radio("Seasons", list(SEASON_FILTERS), horizontal=True, key="season_filter")
    season_keys = SEASON_FILTERS[filter_label]
    selected = seasons[seasons["season"].isin(season_keys)]
    k = kpis(selected, params)

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        theme.kpi("10-year average burn cost", theme.pct(k.burn_cost_pct, 2),
                  f"Average payout per season as a share of sum insured; premium rate {params.premium_rate:.1%}")
    with c2:
        tone = "red" if k.loss_ratio_pct > 100 else "amber" if k.loss_ratio_pct > 70 else ""
        theme.kpi("Historical loss ratio", theme.pct(k.loss_ratio_pct, 0),
                  f"Payouts over premiums; {k.seasons_paying} of {k.seasons} seasons paid", tone)
    with c3:
        theme.kpi("Max probable loss year", str(k.worst_year) if k.worst_year else "None",
                  f"{theme.ksh(k.worst_year_payout)} per farm ({k.worst_year_pct:.0f}% of the year's sum insured)"
                  if k.worst_year else "No season paid", "amber")
    with c4:
        score = "n/a" if k.basis_risk_score is None else f"{k.basis_risk_score:+.0f}%"
        worse = k.basis_risk_score is not None and k.basis_risk_score < 0
        theme.kpi("Basis-risk reduction score", score,
                  f"Mismatched seasons: {k.mismatches_multi} with this index, {k.mismatches_rain_only} with "
                  f"rainfall only{' (rainfall only does better here)' if worse else ''}", "red" if worse else "")

    st.plotly_chart(payout_chart(seasons, season_keys), width="stretch")

    st.markdown("#### Season trajectory")
    st.caption("Soil moisture index: a SAR-style proxy, 50 is normal for the date. Shaded: germination and flowering.")
    t1, t2, t3 = st.columns(3)
    season = t1.selectbox("Season", list(SEASONS), format_func=lambda s: SEASONS[s]["name"], key="traj_season")
    year = t2.selectbox("Year", YEARS, index=YEARS.index(2022), key="traj_year")
    compare = t3.selectbox("Compare with", YEARS, index=YEARS.index(2020), key="traj_compare")
    st.plotly_chart(trajectory_chart(weather, params, season, year, compare), width="stretch")

    with st.expander("Season-by-season results"):
        table = seasons[["label", "rain_mm", "sm_weighted", "ndvi_pct", "max_rain10_mm", "hot_run_days", "wrsi",
                         "payout_a", "payout_b", "payout_c", "payout_total"]]
        st.dataframe(table, hide_index=True, width="stretch", column_config={
            "label": "Season", "rain_mm": st.column_config.NumberColumn("Rain (mm)", format="%.0f"),
            "sm_weighted": st.column_config.NumberColumn("Weighted soil moisture", format="%.1f"),
            "ndvi_pct": st.column_config.NumberColumn("Pasture NDVI percentile", format="%.0f"),
            "max_rain10_mm": st.column_config.NumberColumn("Wettest 10 days (mm)", format="%.0f"),
            "hot_run_days": st.column_config.NumberColumn("Longest heat run (days)"),
            "wrsi": st.column_config.NumberColumn("WRSI", format="%.0f"),
            "payout_a": st.column_config.NumberColumn("Payout A (KSh)", format="%,.0f"),
            "payout_b": st.column_config.NumberColumn("Payout B (KSh)", format="%,.0f"),
            "payout_c": st.column_config.NumberColumn("Payout C (KSh)", format="%,.0f"),
            "payout_total": st.column_config.NumberColumn("Total (KSh)", format="%,.0f"),
        })
        st.download_button("Download season results (CSV)", seasons.to_csv(index=False).encode(),
                           f"backtest_{ward_key}.csv", "text/csv")

    with st.expander("How the three layers pay"):
        st.markdown(f"""
**Sum insured {theme.ksh(params.sum_insured)} per farm per season**, split into crop inputs
{theme.ksh(params.crop_allocation)}, livestock fodder {theme.ksh(params.fodder_allocation)} and vet and health
{theme.ksh(params.health_payout)}.

- **Payout A, crop inputs.** Soil moisture is averaged over germination (days 1 to 30, weight 35%) and flowering
  (days 45 to 75, weight 65%). Below {params.sm_trigger:.0f} it pays 25% of the crop allocation, rising in a straight
  line to 100% at {params.sm_exit:.0f}. Paid within 10 days of the season's end.
- **Payout B, fodder gap.** Only when Payout A pays **and** late-season pasture greenness is below the
  {params.ndvi_trigger:.0f}th percentile of this ward's 2015-2024 record (no maize stover will follow a failed crop).
  Pays 50% to 100% of the fodder allocation; a hotter-than-usual season raises the share.
- **Payout C, vet and health.** A flat {theme.ksh(params.health_payout)} when any 10 days bring more than
  {params.rain10_trigger_mm:.0f} mm (disease and flood risk) or the daily maximum stays above {params.heat_temp_c:.0f} deg C
  for {params.heat_days} days or more (dairy heat stress).

**Data.** Daily rainfall, reference evapotranspiration (FAO-56) and maximum temperature: Open-Meteo Historical Weather
API (ERA5-based reanalysis, CC BY 4.0). A root-zone water balance ({params.capacity_mm:.0f} mm capacity) turns the
weather into soil water. The **soil moisture index** compares each day's soil water with the same time of year in
this ward's 2015-2024 record: 50 is normal, and each standard deviation drier takes 25 points off, so one trigger
level means the same thing in a wet ward and a dry one. The pasture NDVI follows soil water with a lag. Both are
**synthetic proxies** for Sentinel-1 SAR soil moisture and Sentinel-2 NDVI; no satellite data is used yet.

**Basis-risk score.** Each season is checked against the maize Water Requirement Satisfaction Index (WRSI, FAO crop
curve, same water balance); below 60 counts as a poor or failed season (FEWS NET scale). A mismatch is a payout
without a poor season, or a poor season without a payout. The score is how many fewer mismatches this index has than
a rainfall-only trigger (season rain below 75% of average); negative means rainfall-only did better. It is a model
check, not a measurement: it needs yields or loan-default records from the SACCO.
""")
    return {"ward_key": ward_key, "params": params, "kpis": k}
