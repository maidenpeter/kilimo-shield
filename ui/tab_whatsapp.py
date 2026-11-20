"""Tab 3: WhatsApp amber-zone verification and pilot unit economics."""
from __future__ import annotations

import html
import math

import plotly.graph_objects as go
import streamlit as st

from engine import whatsapp_simulator as wa
from engine.parametric_engine import WARDS
from engine.unit_economics import PilotInputs, pilot_economics
from ui import brand, theme

STATE_TONE = {wa.State.GREEN: "GREEN", wa.State.RELEASED: "GREEN", wa.State.AMBER_HOLD: "AMBER",
              wa.State.VERIFYING: "AMBER", wa.State.RED_UNLOCKED: "RED", wa.State.RED_AUTOMATIC: "RED"}


def whatsapp_card(ward_key: str, vci: float) -> str:
    message = html.escape(wa.bounty_message(ward_key, vci))
    return (f'<div class="ss-wa"><div class="bar">{brand.APP_NAME} field checks'
            f'<small>WhatsApp Business preview. Simulated: nothing is sent.</small></div>'
            f'<div class="bubble">{message}<div class="meta">09:00, to {wa.NETWORK_SIZE} verifiers</div></div></div>')


def gps_chart(ward_key: str, subs) -> go.Figure:
    ward = WARDS[ward_key]
    km_lon = 111.0 * max(math.cos(math.radians(ward.lat)), 0.2)
    x = (subs["gps_lon"] - ward.lon) * km_lon
    y = (subs["gps_lat"] - ward.lat) * 111.0
    fig = go.Figure()
    angles = [i * 2 * math.pi / 72 for i in range(73)]
    fig.add_scatter(x=[wa.GEOFENCE_KM * math.cos(a) for a in angles], y=[wa.GEOFENCE_KM * math.sin(a) for a in angles],
                    mode="lines", line={"color": theme.MUTED, "dash": "dot", "width": 1},
                    name=f"Ward area, {wa.GEOFENCE_KM:.0f} km", hoverinfo="skip")
    fig.add_scatter(x=[0], y=[0], mode="markers", marker={"symbol": "cross-thin", "size": 12,
                                                          "line": {"width": 2, "color": theme.INK}},
                    name="Ward centre", hoverinfo="skip")
    for confirms, colour, label in ((True, theme.RED, "Confirms stress"), (False, theme.GREEN, "Looks normal")):
        sel = subs["confirms_stress"] == confirms
        fig.add_scatter(x=x[sel], y=y[sel], mode="markers", name=label,
                        marker={"color": colour, "size": 10, "line": {"width": 1, "color": "#fff"},
                                "symbol": ["circle" if inside else "x" for inside in subs.loc[sel, "inside_ward"]]},
                        text=subs.loc[sel, "verifier"] + "<br>" + subs.loc[sel, "stress_tag"],
                        hovertemplate="%{text}<extra></extra>")
    fig.update_xaxes(title="km east of centre", range=[-13, 13])
    fig.update_yaxes(title="km north", range=[-13, 13], scaleanchor="x")
    return theme.plot_layout(fig, height=400)


def verification_section(default_ward: str) -> None:
    head, action = st.columns([3, 1], vertical_alignment="bottom")
    with head:
        st.markdown("## Settle a grey-zone reading on the ground")
        st.caption(f"When a ward's vegetation index sits between {wa.AMBER_LOW:.0f}% and {wa.AMBER_HIGH:.0f}%, the "
                   f"payout waits for geotagged photos from the ward's lead farmers and agro-vets (KSh "
                   f"{wa.BOUNTY_KSH} airtime each). {wa.CONSENSUS_THRESHOLD:.0%} agreement unlocks it. Simulated: "
                   "no message or airtime is sent.")
    ward_key = st.session_state.get("wa_ward", default_ward)
    vci = st.session_state.get("wa_vci", 36.5)
    z = wa.zone(vci)
    run = action.button(f"Simulate {wa.SUBMISSIONS} photo replies", type="primary", disabled=z != "AMBER",
                        key="wa_run", width="stretch")

    with theme.panel("Ward reading"):
        controls, preview = st.columns([3, 2], gap="large")
        with controls:
            st.selectbox("Ward", list(WARDS), index=list(WARDS).index(default_ward),
                         format_func=lambda k: WARDS[k].label, key="wa_ward")
            st.slider("Vegetation Condition Index, VCI (%)", 0.0, 100.0, 36.5, 0.5, key="wa_vci",
                      help="Stands in for the satellite reading")
            zone_text = {"RED": "below the amber band: the index alone pays",
                         "AMBER": "in the amber band: payout on hold until the photos agree",
                         "GREEN": "above the amber band: no action"}[z]
            st.markdown(f"{theme.status(z, z)} &nbsp;{zone_text}", unsafe_allow_html=True)
            with st.expander(f"Registered verifiers in {WARDS[ward_key].name} ({wa.NETWORK_SIZE})"):
                st.dataframe(wa.verifier_network(ward_key), hide_index=True, width="stretch")
        with preview:
            if z == "AMBER":
                st.markdown(whatsapp_card(ward_key, vci), unsafe_allow_html=True)
            else:
                st.caption("The photo request only goes out for an amber reading.")

    key = (ward_key, round(vci, 1))
    if run:
        machine = wa.AmberZoneMachine(ward_key, vci)
        machine.run()
        st.session_state["wa_case"] = (key, machine)
        st.toast(f"{WARDS[ward_key].name}: {machine.state.value}")
    stored = st.session_state.get("wa_case")
    machine = stored[1] if stored and stored[0] == key else wa.AmberZoneMachine(ward_key, vci)

    with theme.panel("Verification result"):
        st.markdown(f"Ward status: {theme.status(machine.state.value, STATE_TONE[machine.state])}",
                    unsafe_allow_html=True)
        if machine.submissions is None:
            st.caption("No photos yet." if z == "AMBER" else "Nothing to verify at this reading.")
        else:
            subs = machine.submissions
            valid = subs[subs["inside_ward"]]
            share = wa.consensus(subs)
            theme.stats([
                ("Agreement", f"{share:.0%}", f"{int(valid['confirms_stress'].sum())} of {len(valid)} valid photos "
                 "confirm stress"),
                ("Needed to unlock", f"{wa.CONSENSUS_THRESHOLD:.0%}", "Of photos taken inside the ward"),
                ("Excluded", str(int((~subs["inside_ward"]).sum())), "Taken outside the ward area"),
                ("Airtime paid", theme.ksh(machine.airtime_cost), f"KSh {wa.BOUNTY_KSH} per valid photo"),
            ])
            table_col, map_col = st.columns([3, 2])
            table_col.dataframe(subs, hide_index=True, width="stretch", height=400, column_config={
                "verifier": "Verifier", "role": "Role", "submitted_at": "Sent", "gps_lat": "Latitude",
                "gps_lon": "Longitude", "distance_km": "Km from centre", "inside_ward": "Inside ward",
                "stress_tag": "Sender's tag", "confirms_stress": "Confirms stress",
                "airtime_ksh": st.column_config.NumberColumn("Airtime KSh")})
            map_col.plotly_chart(gps_chart(ward_key, subs), width="stretch")
        with st.expander("Decision log", expanded=machine.submissions is not None):
            for line in machine.log:
                st.markdown(f"- {line}")


def economics_section(burn_cost_pct: float, premium_rate: float) -> None:
    with theme.panel("Pilot unit economics",
                     "Illustrative. The platform carries no insurance risk: it earns a calculating-agent fee on "
                     "premium and a reconciliation fee from the SACCO. Burn cost and starting premium come from the "
                     "ward selected on the backtest tab."):
        c1, c2, c3 = st.columns(3, gap="large")
        farms = c1.select_slider("Pilot farms", options=list(range(1_000, 50_001, 500)), value=15_000,
                                 format_func=lambda v: f"{v:,}", key="ue_farms")
        avg_si = c1.select_slider("Average sum insured", options=list(range(20_000, 150_001, 5_000)), value=60_000,
                                  format_func=lambda v: f"KSh {v:,}", key="ue_si")
        fee = c2.slider("Calculating-agent fee (% of premium)", 2, 20, 10, key="ue_fee")
        saas = c2.slider("SACCO reconciliation fee (KSh per member a month)", 0, 50, 10, key="ue_saas")
        start_rate = min(max(round(premium_rate * 100, 1), 2.0), 30.0)
        rate = c3.slider("Premium rate per season (%)", 2.0, 30.0, start_rate, 0.1, key=f"ue_rate_{start_rate}",
                         help="Starts at the selected ward's premium")
        ceded = c3.slider("Ceded to the treaty reinsurer (%)", 0, 90, 70, 5, key="ue_ceded")
        econ = pilot_economics(PilotInputs(farms=farms, avg_sum_insured=float(avg_si), premium_rate=rate / 100,
                                           agent_fee_rate=fee / 100, saas_fee_member_month=float(saas),
                                           burn_cost_rate=burn_cost_pct / 100, reinsurer_share=ceded / 100))
        theme.stats([
            ("Platform revenue a season", theme.ksh_short(econ.platform_revenue_season), "Agent fee plus SACCO fee"),
            ("Contribution a year", theme.ksh_short(econ.platform_contribution_year),
             "Two seasons of revenue, less airtime bounties"),
            ("Gross premium a season", theme.ksh_short(econ.gross_premium_season),
             f"{farms:,} farms at {rate:.1f}% of {theme.ksh(avg_si)}"),
            ("Expected loss ratio", f"{econ.loss_ratio:.0%}", f"Burn cost {burn_cost_pct:.2f}% from the backtest",
             "bad" if econ.loss_ratio > 1 else "warn" if econ.loss_ratio > 0.7 else ""),
        ])
        fig = go.Figure(go.Bar(
            x=["Platform fee", "Insurer keeps", "Reinsurer receives"],
            y=[econ.platform_fee_season, econ.insurer_retained_premium_season, econ.reinsurer_ceded_premium_season],
            marker_color=[theme.AMBER, theme.GREEN, "#64748b"], hovertemplate="%{x}: KSh %{y:,.0f}<extra></extra>"))
        fig.update_yaxes(title="KSh a season", tickformat=",.0f")
        left, right = st.columns([3, 2])
        left.markdown("**Where one season's premium goes**")
        left.plotly_chart(theme.plot_layout(fig, height=320), width="stretch")
        right.markdown("**A season, line by line**")
        right.dataframe({
            "Line": ["Gross premium", "Expected claims", "Platform fee", "SACCO fee", "Airtime bounties",
                     "Insurer net premium", "Insurer expected claims", "Reinsurer net premium",
                     "Reinsurer expected claims"],
            "KSh": [round(v) for v in (econ.gross_premium_season, econ.expected_claims_season, econ.platform_fee_season,
                                        econ.saas_revenue_season, econ.verification_cost_season,
                                        econ.insurer_retained_premium_season, econ.insurer_expected_claims_season,
                                        econ.reinsurer_ceded_premium_season, econ.reinsurer_expected_claims_season)],
        }, hide_index=True, width="stretch", column_config={"KSh": st.column_config.NumberColumn(format="localized")})
        right.caption("Insurer and reinsurer bear the platform fee in proportion to their shares, so fee plus both "
                      "net premiums equals gross premium. Airtime assumes 3 ward checks a season.")


def render(default_ward: str, burn_cost_pct: float, premium_rate: float) -> None:
    verification_section(default_ward)
    economics_section(burn_cost_pct, premium_rate)
