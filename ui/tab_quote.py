"""Chapter 2: a farmer's quote. Same engine and settings as the backtest; the story of one farm."""
from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from engine import quote as qt
from engine.parametric_engine import WARDS, YEARS, TriggerParams
from ui import theme
from ui.tab_parametric import weather_for


@st.cache_data(show_spinner="Pricing this farm...")
def quote_for(ward_key: str, season: str, acres: float, cows: int, practices: tuple, params: TriggerParams,
              offered: bool, refresh_count: int):
    weather, _, _ = weather_for(ward_key, refresh_count)
    return qt.quote(weather, params, ward_key=ward_key, season=season, acres=acres, cows=cows,
                    practices=dict(practices), ward_offered=offered)


def farm_words(acres: float, cows: int) -> str:
    maize = f"{acres:g} acre{'' if acres == 1 else 's'} of maize" if acres else "no maize"
    dairy = f"{cows} dairy cow{'' if cows == 1 else 's'}" if cows else "no dairy cows"
    return f"{maize} and {dairy}"


def history_chart(q: qt.Quote) -> go.Figure:
    h = q.history.set_index("year").reindex(YEARS, fill_value=0)
    fig = go.Figure()
    for col, name in (("payout_a", "Payout A: crop inputs"), ("payout_b", "Payout B: fodder gap"),
                      ("payout_c", "Payout C: vet and health")):
        fig.add_bar(x=h.index, y=h[col], name=name, marker_color=theme.LAYER_COLOURS[name],
                    hovertemplate="%{x}: KSh %{y:,.0f}<extra>" + name + "</extra>")
    fig.add_scatter(x=list(h.index), y=[q.farmer_pays] * len(h), mode="lines", name="Farmer pays a season",
                    line={"color": theme.INK, "dash": "dash", "width": 1.5},
                    hovertemplate="KSh %{y:,.0f}<extra>Farmer pays</extra>")
    fig.update_layout(barmode="stack", bargap=0.35)
    theme.year_axis(fig, YEARS)
    fig.update_yaxes(title="KSh to this farm", tickformat=",.0f")
    return theme.plot_layout(fig, height=340)


def farm_inputs(default_ward: str) -> tuple:
    wards = list(WARDS)
    ward_key = st.selectbox("Ward", wards, index=wards.index(default_ward), format_func=lambda k: WARDS[k].label,
                            key="q_ward")
    season = st.segmented_control("Season", list(qt.SEASON_WORDS), default="LR", key="q_season",
                                  format_func=lambda s: f"{qt.SEASON_WORDS[s].capitalize()} {qt.COVER_YEAR}") or "LR"
    a, c = st.columns(2)
    acres = a.number_input("Acres of maize", 0.0, qt.MAX_ACRES, 2.0, 0.5, key="q_acres")
    cows = int(c.number_input("Dairy cows", 0, qt.MAX_COWS, 2, 1, key="q_cows"))
    st.markdown("**Verified last season** (each lowers the farmer's share)")
    practices = tuple((item.id, st.checkbox(f"{item.label} (+{item.points})", key=f"q_res_{item.id}",
                                            help=f"Checked by: {item.verified_by}"))
                      for item in qt.RESILIENCE_ITEMS)
    return ward_key, season, float(acres), cows, practices


def price_panel(q: qt.Quote, params: TriggerParams) -> None:
    with theme.panel("The price"):
        theme.big(theme.ksh(q.farmer_pays), "a season, paid by the farmer")
        st.caption(f"About KSh {q.per_day_checkoff:,.0f} a day off the milk cheque for {qt.CHECKOFF_DAYS} days, "
                   "or one M-Pesa payment to the SACCO paybill with the member number as the account.")
        subsidy = (f"Government share ({params.subsidy_share:.0%}, none agreed yet)" if q.government_share
                   else "Government share (no subsidy agreed)" if q.subsidy_eligible
                   else f"Government share (not for farms outside {qt.SUBSIDY_ACRES[0]:g} to {qt.SUBSIDY_ACRES[1]:g} acres)")
        theme.ledger([
            (f"Gross premium, {q.premium_rate:.1%} of {theme.ksh(q.sum_insured)}", theme.ksh(q.gross_premium)),
            (subsidy, f"- {theme.ksh(q.government_share)}", "" if q.government_share else "muted"),
            (f"Resilience discount, {q.resilience_points} points ({q.discount_rate:.0%})", f"- {theme.ksh(q.discount)}",
             "" if q.discount else "muted"),
            ("Farmer pays", theme.ksh(q.farmer_pays), "total"),
        ])
        st.markdown("**Who pays the insurer**")
        theme.ledger([
            ("Farmer", theme.ksh(q.farmer_pays)),
            ("Government", theme.ksh(q.government_share), "" if q.government_share else "muted"),
            ("Platform, for the Resilience discount", theme.ksh(q.discount), "" if q.discount else "muted"),
            ("Partner insurer receives the full premium", theme.ksh(q.gross_premium), "total"),
        ])
        if q.discount_exceeds_fee:
            theme.note(f"The discount ({theme.ksh(q.discount)}) is larger than the platform's fee on this policy "
                       f"({theme.ksh(q.platform_fee)}): the platform would lose money on it.")


def cover_panel(q: qt.Quote) -> None:
    with theme.panel("What it covers"):
        theme.ledger([
            (f"Crop inputs: KSh {qt.CROP_PER_ACRE:,.0f} an acre, when soil moisture fails at planting or flowering",
             theme.ksh(q.cover["crop"])),
            (f"Fodder gap: KSh {qt.FODDER_PER_COW:,.0f} a cow, when the crop fails badly and pasture dries up",
             theme.ksh(q.cover["fodder"])),
            (f"Vet and health: KSh {qt.VET_PER_COW:,.0f} a cow, after a flood-level 10 days of rain or a heatwave",
             theme.ksh(q.cover["vet"])),
            ("Sum insured", theme.ksh(q.sum_insured), "total"),
            ("Most it pays in one season", theme.ksh(q.seasonal_cap), "muted"),
        ])


def render(default_ward: str, params: TriggerParams, offered_wards: set, refresh_count: int = 0) -> None:
    header = st.container()
    left, right = st.columns([2, 3], gap="large")
    with left:
        with theme.panel("The farm", "Nothing about the farmer is asked or kept: this is a price check."):
            ward_key, season, acres, cows, practices = farm_inputs(default_ward)
    ward = WARDS[ward_key]
    try:
        q = quote_for(ward_key, season, acres, cows, practices, params, ward_key in offered_wards, refresh_count)
    except qt.QuoteError as err:
        with header:
            theme.chapter(2, "A farmer's quote", ward.label, f"{ward.name} is not offered on the standard bundle.",
                          str(err))
        with right, theme.panel("Why there is no quote here"):
            st.markdown("The engine prices every ward the same way and refuses to sell a ward above the sellable "
                        "ceiling rather than hide it inside a flat rate. Bureti, a wet tea and dairy highland, needs "
                        "a cover built on milk or green-leaf records instead. Raise the ceiling in the sidebar to see "
                        "what its price would be.")
        theme.next_chapter(3, "Collecting the money", "How premiums come in and every shilling reaches the right "
                           "account.")
        return

    with header:
        theme.chapter(
            2, "A farmer's quote", f"{ward.label} · {ward.zone} zone",
            f"A {ward.name} farm with {farm_words(acres, cows)} pays {theme.ksh(q.farmer_pays)} a season.",
            f"That buys {theme.ksh(q.sum_insured)} of cover for the {qt.SEASON_WORDS[season]} {qt.COVER_YEAR}. "
            f"Enrolment closes {qt.long_date(q.enrolment_closes)}, 14 days before the season starts.")
    with right:
        price_panel(q, params)
        cover_panel(q)

    h = q.history
    paid = h[h["payout_total"] > 0]
    words = qt.SEASON_WORDS[season]
    if len(paid):
        worst = paid.loc[paid["payout_total"].idxmax()]
        story = (f"On 2015-2024 weather this cover would have paid in {len(paid)} of {len(h)} {words} seasons, "
                 f"most in {int(worst['year'])}: {theme.ksh(worst['payout_total'])}. Over the ten seasons it would "
                 f"have paid {theme.ksh(h['payout_total'].sum())} against {theme.ksh(q.gross_premium * len(h))} of "
                 "premium.")
    else:
        story = (f"On 2015-2024 weather this cover would not have paid in any {words} season. The price comes from "
                 "both seasons together, so the ward's dry years in the other season still count.")
    with theme.panel("What this cover would have paid", story):
        st.plotly_chart(history_chart(q), width="stretch")

    example = paid["payout_total"].max() if len(paid) else q.cover["crop"] * 0.25
    with theme.panel("If it pays", "No claim form and no farm visit: the index decides, then the money moves."):
        theme.steps([
            ("The season ends", "Soil moisture, pasture greenness and rainfall are read from weather data."),
            ("Within 10 days", f"The farmer gets the payout by M-Pesa. In the worst season above: "
                               f"{theme.ksh(example)}." if len(paid) else
                               f"The farmer gets the payout by M-Pesa; the smallest crop payout is {theme.ksh(example)}."),
            ("Loan first, if agreed", f"Up to 30% ({theme.ksh(example * 0.3)}) can clear the member's SACCO loan, "
                                      "never more than is owed, and only with written consent."),
            ("Borderline reading", "If the satellite reading sits in the grey zone, lead farmers' photos settle it "
                                   "(chapter 4)."),
        ])

    meta, action = st.columns([3, 1], vertical_alignment="center")
    meta.caption(f"Quote {q.quote_id}, valid until enrolment closes on {qt.long_date(q.enrolment_closes)}. "
                 "Illustrative: not a filed product and not for sale. Insurer: Partner insurer (to be named).")
    action.download_button("Quote as text", qt.quote_text(q).encode(), f"{q.quote_id}.txt", "text/plain",
                           icon=":material/download:", width="stretch")
    theme.next_chapter(3, "Collecting the money", "How this premium comes in, by M-Pesa or milk check-off, and "
                       "reaches the right account.")
