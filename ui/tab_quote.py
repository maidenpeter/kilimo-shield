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


def article(word: str) -> str:
    return "An" if word[:1].upper() in "AEIOU" else "A"


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
                            key=f"q_ward_{default_ward}")  # follows the sidebar ward until changed here
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


def subsidy_label(q: qt.Quote) -> str:
    if not q.subsidy_share:
        return "Government share (no subsidy agreed)"
    if not q.subsidy_eligible:
        return (f"Government share (an illustrative {q.subsidy_share:.0%} subsidy, only for farms of "
                f"{qt.SUBSIDY_ACRES[0]:g} to {qt.SUBSIDY_ACRES[1]:g} acres)")
    return f"Government share ({q.subsidy_share:.0%}, illustrative: none agreed)"


def price_panel(q: qt.Quote) -> None:
    with theme.panel("The price"):
        theme.big(theme.ksh(q.farmer_pays), "a season, paid by the farmer")
        if q.per_day_checkoff is not None:
            st.caption(f"About {theme.ksh(q.per_day_checkoff)} a day off the milk cheque for {qt.CHECKOFF_DAYS} days, "
                       "or one M-Pesa payment to the SACCO paybill with the member number as the account.")
        else:
            st.caption("One M-Pesa payment to the SACCO paybill, with the member number as the account.")
        theme.ledger([
            (f"Gross premium, {q.premium_rate:.1%} of {theme.ksh(q.sum_insured)}", theme.ksh(q.gross_premium)),
            (subsidy_label(q), f"- {theme.ksh(q.government_share)}", "" if q.government_share else "muted"),
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
    unit = q.unit_cover
    with theme.panel("What it covers"):
        theme.ledger([
            (f"Crop inputs: {theme.ksh(unit['crop'])} an acre, when soil moisture fails at planting or flowering",
             theme.ksh(q.cover["crop"])),
            (f"Fodder gap: {theme.ksh(unit['fodder'])} a cow, when the crop fails badly and pasture dries up",
             theme.ksh(q.cover["fodder"])),
            (f"Vet and health: {theme.ksh(unit['vet'])} a cow, after a flood-level 10 days of rain or a heatwave",
             theme.ksh(q.cover["vet"])),
            ("Sum insured", theme.ksh(q.sum_insured), "total"),
            ("Most it pays in one season", theme.ksh(q.seasonal_cap), "muted"),
        ])


def no_quote(header, right, ward, err: qt.QuoteError, params: TriggerParams, zone_rate: float | None) -> None:
    if isinstance(err, qt.WardNotOffered):
        lede = f"{ward.name} is not offered on the standard bundle."
        sub = (f"Its standard farm prices at {zone_rate:.1f}% a season, above the {params.max_sellable_rate:.0%} "
               "sellable ceiling." if zone_rate is not None else str(err))
        why = ("The engine prices every ward the same way and refuses to sell one above the sellable ceiling"
               + (" rather than hide it inside a flat rate. " if params.pricing_mode == "target" else
                  ". At a flat rate above the ceiling, no ward is offered. "))
        why += ("Bureti, a wet tea and dairy highland, needs a cover built on milk or green-leaf records instead. "
                if ward.zone == "Wet highland" else "")
        why += "Raise the ceiling in the sidebar to see what its quote would be."
    elif isinstance(err, qt.FarmAboveCeiling):
        lede = "This farm prices above the sellable ceiling."
        sub = str(err)
        why = ("The ward is offered, but this mix of maize and cows costs more than farmers will pay. A different mix "
               "usually prices lower; or raise the ceiling in the sidebar.")
    else:
        lede = "This farm cannot be quoted."
        sub = str(err)
        why = "Change the acres or cows on the left."
    with header:
        theme.chapter(2, "A farmer's quote", ward.label, lede, sub)
    with right, theme.panel("Why there is no quote"):
        st.markdown(why)


def render(default_ward: str, params: TriggerParams, offered_wards: set, refresh_count: int = 0,
           zone_rates: dict | None = None) -> None:
    header = st.container()
    left, right = st.columns([2, 3], gap="large")
    with left:
        with theme.panel("The farm", "Nothing about the farmer is asked or kept: this is a price check."):
            ward_key, season, acres, cows, practices = farm_inputs(default_ward)
    ward = WARDS[ward_key]
    try:
        q = quote_for(ward_key, season, acres, cows, practices, params, ward_key in offered_wards, refresh_count)
    except qt.QuoteError as err:
        no_quote(header, right, ward, err, params, (zone_rates or {}).get(ward_key))
        theme.next_chapter(3, "Collecting the money", "How premiums come in and every shilling reaches the right "
                           "account.")
        return

    with header:
        theme.chapter(
            2, "A farmer's quote", f"{ward.label} · {ward.zone} zone",
            f"{article(ward.name)} {ward.name} farm with {qt.farm_words(acres, cows)} pays "
            f"{theme.ksh(q.farmer_pays)} a season.",
            f"That buys {theme.ksh(q.sum_insured)} of cover for the {qt.SEASON_WORDS[season]} {qt.COVER_YEAR}. "
            f"Enrolment closes {qt.long_date(q.enrolment_closes)}, 14 days before the season starts.")
    with right:
        price_panel(q)
        cover_panel(q)

    h = q.history
    paid = h[h["payout_total"] > 0]
    words = qt.SEASON_WORDS[season]
    if len(paid):
        worst = paid.loc[paid["payout_total"].idxmax()]
        story = (f"On 2015-2024 weather this cover would have paid in {len(paid)} of {len(h)} {words} seasons, "
                 f"most in {int(worst['year'])}: {theme.ksh(worst['payout_total'])}. Over the {len(h)} seasons it "
                 f"would have paid {theme.ksh(h['payout_total'].sum())} to this farm, against "
                 f"{theme.ksh(q.farmer_pays * len(h))} paid by the farmer")
        story += (f" (the full premium was {theme.ksh(q.gross_premium * len(h))})." if q.farmer_pays != q.gross_premium
                  else ".")
    else:
        story = f"On 2015-2024 weather this cover would not have paid in any {words} season."
        story += (" The price comes from both seasons together, so the ward's dry years in the other season still "
                  "count." if q.pricing_mode == "target" else " The flat rate does not depend on this history.")
    with theme.panel("What this cover would have paid", story):
        st.plotly_chart(history_chart(q), width="stretch")

    with theme.panel("If it pays", "No claim form and no farm visit: the index decides, then the money moves."):
        if len(paid):
            example = float(paid["payout_total"].max())
            within = f"The farmer gets the payout by M-Pesa. In the worst season above: {theme.ksh(example)}."
            loan = (f"Up to 30% ({theme.ksh(example * 0.3)}) can clear the member's SACCO loan, never more than is "
                    "owed, and only with written consent.")
        else:
            within = "The farmer gets the payout by M-Pesa."
            loan = ("Up to 30% of it can clear the member's SACCO loan, never more than is owed, and only with "
                    "written consent.")
        theme.steps([
            ("The season ends", "Soil moisture, pasture greenness and rainfall are read from weather data."),
            ("Within 10 days", within),
            ("Loan first, if agreed", loan),
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
