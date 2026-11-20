"""Tab 3: WhatsApp amber-zone verification and pilot unit economics."""
from __future__ import annotations

import html
import math

import plotly.graph_objects as go
import streamlit as st

from engine import whatsapp_simulator as wa
from engine.parametric_engine import WARDS
from engine.unit_economics import PilotInputs, pilot_economics
from ui import theme

STATE_TONE = {wa.State.GREEN: "GREEN", wa.State.RELEASED: "GREEN", wa.State.AMBER_HOLD: "AMBER",
              wa.State.VERIFYING: "AMBER", wa.State.RED_UNLOCKED: "RED", wa.State.RED_AUTOMATIC: "RED"}


def whatsapp_card(ward_key: str, vci: float) -> str:
    message = html.escape(wa.bounty_message(ward_key, vci))
    return (f'<div class="ss-wa"><div class="bar">ShambaShield 360 Field Checks'
            f'<small>Business account, simulated: no message is sent</small></div>'
            f'<div class="bubble">{message}<div class="meta">09:00, sent to {wa.NETWORK_SIZE} verifiers</div></div></div>')


def gps_chart(ward_key: str, subs) -> go.Figure:
    ward = WARDS[ward_key]
    km_lat = 111.0
    km_lon = 111.0 * max(math.cos(math.radians(ward.lat)), 0.2)
    x = (subs["gps_lon"] - ward.lon) * km_lon
    y = (subs["gps_lat"] - ward.lat) * km_lat
    colours = [theme.RED if c else theme.GREEN for c in subs["confirms_stress"]]
    symbols = ["circle" if inside else "x" for inside in subs["inside_ward"]]
    fig = go.Figure()
    angles = [i * 2 * math.pi / 72 for i in range(73)]
    fig.add_scatter(x=[wa.GEOFENCE_KM * math.cos(a) for a in angles], y=[wa.GEOFENCE_KM * math.sin(a) for a in angles],
                    mode="lines", line={"color": theme.MUTED, "dash": "dot"}, name=f"Ward area ({wa.GEOFENCE_KM:.0f} km)",
                    hoverinfo="skip")
    fig.add_scatter(x=[0], y=[0], mode="markers", marker={"symbol": "star", "size": 16, "color": theme.AMBER},
                    name="Ward centre")
    fig.add_scatter(x=x, y=y, mode="markers", marker={"color": colours, "symbol": symbols, "size": 12,
                                                      "line": {"width": 1, "color": "#fff"}},
                    text=subs["verifier"] + "<br>" + subs["stress_tag"], hovertemplate="%{text}<extra></extra>",
                    name="Photos (red: stress, green: normal, x: outside ward)")
    fig.update_xaxes(title="km east of ward centre", range=[-13, 13], zeroline=False)
    fig.update_yaxes(title="km north", range=[-13, 13], scaleanchor="x", zeroline=False)
    return theme.plot_layout(fig, "Where the photos were taken", height=430)


def verification_section(default_ward: str) -> None:
    st.subheader("WhatsApp trust loop: verify the amber zone on the ground")
    left, right = st.columns([3, 2])
    with left:
        ward_key = st.selectbox("Ward", list(WARDS), index=list(WARDS).index(default_ward),
                                format_func=lambda k: WARDS[k].label, key="wa_ward")
        vci = st.slider("Current Vegetation Condition Index, VCI (%)", 0.0, 100.0, 36.5, 0.5, key="wa_vci")
        z = wa.zone(vci)
        st.markdown(f"Zone: {theme.badge(z, z)} &nbsp; Amber band {wa.AMBER_LOW:.0f}% to {wa.AMBER_HIGH:.0f}%, "
                    f"unlock at {wa.CONSENSUS_THRESHOLD:.0%} agreement", unsafe_allow_html=True)
        theme.note("The VCI slider stands in for a satellite reading. Verifiers, photos and tags are simulated; no "
                   "WhatsApp message or airtime is sent.")
        with st.expander(f"Registered verifiers in {WARDS[ward_key].name} ({wa.NETWORK_SIZE})"):
            st.dataframe(wa.verifier_network(ward_key), hide_index=True, width="stretch")
    with right:
        if z == "AMBER":
            st.markdown(whatsapp_card(ward_key, vci), unsafe_allow_html=True)
        elif z == "RED":
            theme.note("VCI is below the amber band: the index alone is clear and the payout goes ahead, "
                       "so no photos are requested.")
        else:
            theme.note("VCI is above the amber band: no action, keep monitoring.")

    key = (ward_key, round(vci, 1))
    if st.button(f"Simulate {wa.SUBMISSIONS} farmer geotagged submissions", type="primary", disabled=z != "AMBER",
                 key="wa_run"):
        machine = wa.AmberZoneMachine(ward_key, vci)
        machine.run()
        st.session_state["wa_case"] = (key, machine)
    stored = st.session_state.get("wa_case")
    machine = stored[1] if stored and stored[0] == key else wa.AmberZoneMachine(ward_key, vci)

    tone = STATE_TONE[machine.state]
    st.markdown(f"Ward status: {theme.badge(machine.state.value, tone)}", unsafe_allow_html=True)
    if machine.submissions is not None:
        subs = machine.submissions
        valid = subs[subs["inside_ward"]]
        share = wa.consensus(subs)
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            theme.kpi("Verification consensus", f"{share:.0%}",
                      f"{int(valid['confirms_stress'].sum())} of {len(valid)} valid photos confirm stress",
                      "red" if share >= wa.CONSENSUS_THRESHOLD else "")
        with c2:
            theme.kpi("Threshold", f"{wa.CONSENSUS_THRESHOLD:.0%}", "Agreement needed to unlock")
        with c3:
            theme.kpi("Photos excluded", str(int((~subs["inside_ward"]).sum())), "Taken outside the ward area", "amber")
        with c4:
            theme.kpi("Airtime paid", theme.ksh(machine.airtime_cost), f"KSh {wa.BOUNTY_KSH} per valid photo")
        table_col, map_col = st.columns([3, 2])
        table_col.dataframe(subs, hide_index=True, width="stretch", height=430, column_config={
            "verifier": "Verifier", "role": "Role", "submitted_at": "Sent", "gps_lat": "Latitude",
            "gps_lon": "Longitude", "distance_km": "Km from centre", "inside_ward": "Inside ward",
            "stress_tag": "Tag (chosen by the sender)", "confirms_stress": "Confirms stress",
            "airtime_ksh": st.column_config.NumberColumn("Airtime (KSh)")})
        map_col.plotly_chart(gps_chart(ward_key, subs), width="stretch")
    with st.expander("Decision log", expanded=machine.submissions is not None):
        for line in machine.log:
            st.markdown(f"- {line}")


def economics_section(burn_cost_pct: float, premium_rate: float) -> None:
    st.subheader("Pilot unit economics (illustrative)")
    c1, c2, c3 = st.columns(3)
    farms = c1.slider("Pilot farms", 1_000, 50_000, 15_000, 500, key="ue_farms")
    avg_si = c1.slider("Average sum insured (KSh)", 20_000, 150_000, 60_000, 5_000, key="ue_si")
    fee = c2.slider("Platform calculating-agent fee (% of premium)", 2, 20, 10, key="ue_fee")
    saas = c2.slider("SACCO reconciliation fee (KSh per member per month)", 0, 50, 10, key="ue_saas")
    start_rate = min(max(round(premium_rate * 100, 1), 2.0), 30.0)
    rate = c3.slider("Premium rate per season (%)", 2.0, 30.0, start_rate, 0.1, key=f"ue_rate_{start_rate}",
                     help="Starts at the selected ward's premium from the backtest tab")
    ceded = c3.slider("Ceded to the treaty reinsurer (%)", 0, 90, 70, 5, key="ue_ceded")
    econ = pilot_economics(PilotInputs(farms=farms, avg_sum_insured=float(avg_si), premium_rate=rate / 100,
                                       agent_fee_rate=fee / 100, saas_fee_member_month=float(saas),
                                       burn_cost_rate=burn_cost_pct / 100, reinsurer_share=ceded / 100))
    k1, k2, k3, k4 = st.columns(4)
    with k1:
        theme.kpi("Founder revenue per season", theme.ksh_short(econ.founder_revenue_season),
                  "Agent fee plus SaaS, less airtime bounties")
    with k2:
        theme.kpi("Founder revenue per year", theme.ksh_short(econ.founder_revenue_year), "Long and short rains")
    with k3:
        theme.kpi("Gross premium per season", theme.ksh_short(econ.gross_premium_season),
                  f"{farms:,} farms at {rate:.1f}% of {theme.ksh(avg_si)}", "amber")
    with k4:
        theme.kpi("Expected loss ratio", f"{econ.loss_ratio:.0%}",
                  f"Burn cost {burn_cost_pct:.2f}% from the backtest tab", "red" if econ.loss_ratio > 0.7 else "")

    fig = go.Figure(go.Bar(
        x=["Platform fee", "Insurer keeps", "Reinsurer receives"],
        y=[econ.platform_fee_season, econ.insurer_retained_premium_season - econ.platform_fee_season * (1 - ceded / 100),
           econ.reinsurer_ceded_premium_season - econ.platform_fee_season * ceded / 100],
        marker_color=[theme.AMBER, theme.GREEN, "#64748b"], hovertemplate="%{x}: KSh %{y:,.0f}<extra></extra>"))
    fig.update_yaxes(title="KSh per season", tickformat=",.0f")
    left, right = st.columns([3, 2])
    left.plotly_chart(theme.plot_layout(fig, "Where one season's premium goes", height=360), width="stretch")
    with right:
        st.markdown("**Per season**")
        st.dataframe({
            "Line": ["Gross premium", "Expected claims", "Platform fee", "SACCO SaaS revenue", "Airtime bounties",
                     "Insurer retained premium", "Insurer expected claims", "Reinsurer ceded premium",
                     "Reinsurer expected claims"],
            "KSh": [round(v) for v in (econ.gross_premium_season, econ.expected_claims_season, econ.platform_fee_season,
                                        econ.saas_revenue_season, econ.verification_cost_season,
                                        econ.insurer_retained_premium_season, econ.insurer_expected_claims_season,
                                        econ.reinsurer_ceded_premium_season, econ.reinsurer_expected_claims_season)],
        }, hide_index=True, width="stretch", column_config={"KSh": st.column_config.NumberColumn(format="localized")})
        st.caption("The platform carries no insurance risk. The fee is shared pro rata between insurer and reinsurer.")


def render(default_ward: str, burn_cost_pct: float, premium_rate: float) -> None:
    verification_section(default_ward)
    st.divider()
    economics_section(burn_cost_pct, premium_rate)
