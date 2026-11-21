"""Chapter 2: a farmer's quote. Same engine and settings as the backtest; the story of one farm."""
from __future__ import annotations

import html

import plotly.graph_objects as go
import streamlit as st

from engine import quote as qt
from engine.parametric_engine import WARDS, YEARS, TriggerParams, minimum_applies
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


def who_else_pays(q: qt.Quote) -> str:
    """One sentence on who else pays, as AgroShield's quick price put it; the build-up sits behind Details."""
    insurer = f"The insurer still receives the full {theme.ksh(q.gross_premium)}."
    caveat = "(an illustrative subsidy: none is agreed)"
    if q.government_share and q.discount:
        return (f"The government pays {theme.ksh(q.government_share)} {caveat}, and the Resilience discount takes "
                f"{theme.ksh(q.discount)} off the farmer's share, paid by the platform. {insurer}")
    if q.government_share:
        return f"The government pays the other {theme.ksh(q.government_share)} {caveat}. {insurer}"
    if q.discount:
        return (f"The Resilience discount takes {theme.ksh(q.discount)} off, paid by the platform. {insurer}")
    if q.subsidy_share and not q.subsidy_eligible:
        return (f"No government help for this farm: the illustrative subsidy is only for farms of "
                f"{qt.SUBSIDY_ACRES[0]:g} to {qt.SUBSIDY_ACRES[1]:g} acres. The farmer pays the full premium.")
    if q.subsidy_share:
        return (f"The illustrative {q.subsidy_share:.0%} subsidy comes to less than half a shilling on this small "
                "premium, so the farmer pays the full premium.")
    return "No subsidy and no discount: the farmer pays the full premium."


def _snapshot(ward_key, season, acres, cows, practices, params) -> dict:
    return {"ward": ward_key, "season": season, "acres": acres, "cows": cows,
            "practices": tuple(sorted(i for i, on in practices if on)), "params": params}


def _what_changed(old: dict, new: dict) -> str:
    """The inputs that differ between two snapshots, in plain words."""
    parts = []
    if old["ward"] != new["ward"]:
        parts.append(f"ward {WARDS[old['ward']].name} to {WARDS[new['ward']].name}")
    if old["season"] != new["season"]:
        parts.append(f"season {qt.SEASON_WORDS[old['season']]} to {qt.SEASON_WORDS[new['season']]}")
    if old["acres"] != new["acres"]:
        parts.append(f"acres {old['acres']:g} to {new['acres']:g}")
    if old["cows"] != new["cows"]:
        parts.append(f"cows {old['cows']} to {new['cows']}")
    ticked = [qt.ITEMS[i].label.lower() for i in new["practices"] if i not in old["practices"]]
    unticked = [qt.ITEMS[i].label.lower() for i in old["practices"] if i not in new["practices"]]
    if ticked:
        parts.append("ticked " + " and ".join(ticked))
    if unticked:
        parts.append("unticked " + " and ".join(unticked))
    if old["params"] != new["params"]:
        parts.append("a sidebar setting")
    return ", ".join(parts)


def track_change(snapshot: dict, farmer_pays: int | None) -> None:
    """Remember the last change and what it did to the price; it stays on screen until the next change."""
    previous = st.session_state.get("q_prev")
    if previous and previous[0] != snapshot:
        st.session_state["q_change"] = (_what_changed(previous[0], snapshot), previous[1], farmer_pays)
    st.session_state["q_prev"] = (snapshot, farmer_pays)


def show_change() -> None:
    change = st.session_state.get("q_change")
    if not change:
        st.caption("Change anything on the left or in the sidebar: the price, and the effect of every setting, "
                   "update at once.")
        return
    what, old, new = change
    lead = f"Last change: {what}."
    if new is None:
        theme.change_line(lead, "This farm can no longer be quoted.", "up")
    elif old is None:
        theme.change_line(lead, f"Now quoted at {theme.ksh(new)} (it could not be quoted before).", "same")
    elif new == old:
        theme.change_line(lead, f"The price did not move: still {theme.ksh(new)}.", "same")
    else:
        diff = new - old
        theme.change_line(lead, f"Farmer pays {theme.ksh(old)} → {theme.ksh(new)} "
                                f"({'+' if diff > 0 else '−'}{theme.ksh(abs(diff))}).", "up" if diff > 0 else "down")


def price_panel(q: qt.Quote) -> None:
    with theme.panel("The price"):
        theme.big(theme.ksh(q.farmer_pays), "a season, paid by the farmer")
        show_change()
        if q.per_day_checkoff is not None:
            st.caption(f"About {theme.ksh(q.per_day_checkoff)} a day off the milk cheque for {qt.CHECKOFF_DAYS} days, "
                       "or one M-Pesa payment to the SACCO paybill with the member number as the account.")
        else:
            st.caption("One M-Pesa payment to the SACCO paybill, with the member number as the account.")
        st.markdown(who_else_pays(q))
        theme.split_bar([("Farmer", q.farmer_pays, theme.GREEN), ("Government", q.government_share, "#64748b"),
                         ("Platform discount", q.discount, "#ca8a04")],
                        f"Who pays the {theme.ksh(q.gross_premium)} premium")
        with st.expander("Details: how the price is built"):
            theme.ledger([
                (f"Gross premium, {qt.rate_text(q.premium_rate)} of {theme.ksh(q.sum_insured)}",
                 theme.ksh(q.gross_premium)),
                (subsidy_label(q), f"- {theme.ksh(q.government_share)}", "" if q.government_share else "muted"),
                (f"Resilience discount, {q.resilience_points} points ({q.discount_rate:.0%})",
                 f"- {theme.ksh(q.discount)}", "" if q.discount else "muted"),
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
            theme.warn(f"The discount ({theme.ksh(q.discount)}) is larger than the platform's fee on this policy "
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


def _signed(diff: int) -> str:
    return "no change" if diff == 0 else f"{'+' if diff > 0 else '−'}{theme.ksh(abs(diff))} a season"


def _tone(diff: int) -> str:
    return "up" if diff > 0 else "down" if diff < 0 else ""


def what_moves(q: qt.Quote, ward_key: str, season: str, acres: float, cows: int, practices: tuple,
               params: TriggerParams, offered: bool, refresh_count: int) -> None:
    """Every setting next to its effect on what the farmer pays, priced by the same engine as the quote."""
    def nudge(label: str, new_acres: float, new_cows: int) -> tuple[str, str]:
        try:
            other = quote_for(ward_key, season, new_acres, new_cows, practices, params, offered, refresh_count)
        except qt.FarmAboveCeiling:
            return f"{label} prices this farm above the ceiling.", "up"
        except qt.QuoteError:
            return f"{label} cannot be quoted.", ""
        diff = other.farmer_pays - q.farmer_pays
        return f"{label}: {_signed(diff)}.", _tone(diff)

    rows: list[tuple] = [("group", "This farm")]
    if acres + 1 <= qt.MAX_ACRES:
        rows.append(("Acres of maize", f"{acres:g}", *nudge("One more acre", acres + 1, cows)))
    if cows + 1 <= qt.MAX_COWS:
        rows.append(("Dairy cows", f"{cows}", *nudge("One more cow", acres, cows + 1)))
    chosen = dict(practices)
    for item in qt.RESILIENCE_ITEMS:
        flipped = {**chosen, item.id: not chosen.get(item.id, False)}
        points, _ = qt.resilience(flipped)
        diff = (q.farmer_share - qt.discount_for(q.farmer_share, points)) - q.farmer_pays
        on = chosen.get(item.id, False)
        if diff == 0:
            why = ("the discount is already at its 15% cap" if q.discount_rate >= qt.DISCOUNT_CAP else
                   "the higher irrigation item counts instead" if item.group else "no premium to discount")
            effect, tone = f"No change: {why}.", ""
        elif on:
            effect, tone = f"Saves {theme.ksh(diff)} a season now.", "down"
        else:
            effect, tone = f"Verifying it: {_signed(diff)}.", _tone(diff)
        rows.append((f"{item.label} (+{item.points})", "verified" if on else "no", effect, tone))
    rows.append(("Season", qt.SEASON_WORDS[season], "No effect on the price: it is set on both seasons together. It "
                 "changes only the history below.", ""))
    rows.append(("group", "Ward and sidebar settings"))
    rows.append(("Ward", WARDS[ward_key].name, f"Sets the rate: this farm's mix prices at {qt.rate_text(q.premium_rate)} "
                 f"of its {theme.ksh(q.sum_insured)} cover here.", ""))
    rows.append(("Sum insured", theme.ksh(params.sum_insured), f"Sets the cover: {theme.ksh(q.unit_cover['crop'])} an "
                 f"acre and {theme.ksh(q.unit_cover['fodder'] + q.unit_cover['vet'])} a cow.", ""))
    if params.pricing_mode == "target":
        rows.append(("Target loss ratio", f"{params.target_loss_ratio:.0%}", "The rate is this farm's burn cost divided "
                     "by it, rounded up to 0.1% and at least 1%: a higher ratio, a lower price.", ""))
    else:
        rows.append(("Flat rate", qt.rate_text(params.premium_rate), "Every farm pays this rate, whatever its risk.", ""))
    if q.government_share:
        subsidy = (f"The government pays −{theme.ksh(q.government_share)} a season (illustrative: none agreed).",
                   "down")
    elif q.subsidy_share and not q.subsidy_eligible:
        subsidy = (f"None for this farm: only farms of {qt.SUBSIDY_ACRES[0]:g} to {qt.SUBSIDY_ACRES[1]:g} acres "
                   "qualify.", "")
    else:
        subsidy = ("None.", "")
    rows.append(("Subsidy", f"{params.subsidy_share:.0%}", *subsidy))
    rows.append(("Platform fee", f"{params.platform_fee_rate:.0%}", f"No effect on this price: it is the platform's "
                 f"share of it, {theme.ksh(q.platform_fee)}.", ""))
    with theme.panel("What changes the price",
                     "Live: every setting next to what it does to this farmer's price, worked out by the same "
                     "engine as the quote. Red raises the price, green lowers it."):
        theme.drivers([row if row[0] == "group" else (row[0], row[1], html.escape(row[2]), row[3]) for row in rows])


def no_quote(header, right, ward, err: qt.QuoteError, params: TriggerParams, zone_rate: float | None) -> None:
    if isinstance(err, qt.WardNotOffered):
        lede = f"{ward.name} is not offered on the standard bundle."
        sub = (f"Its standard farm prices at {theme.pct(zone_rate, 1)} a season, above the {params.max_sellable_rate:.0%} "
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
        show_change()
        theme.warn(why)


def render(default_ward: str, params: TriggerParams, offered_wards: set, refresh_count: int = 0,
           zone_rates: dict | None = None) -> None:
    header = st.container()
    left, right = st.columns([2, 3], gap="large")
    with left:
        with theme.panel("The farm", "Type the farm's acres and cows and tick what was verified last season. "
                                     "Nothing about the farmer is asked or kept: this is a price check."):
            ward_key, season, acres, cows, practices = farm_inputs(default_ward)
    ward = WARDS[ward_key]
    snapshot = _snapshot(ward_key, season, acres, cows, practices, params)
    try:
        q = quote_for(ward_key, season, acres, cows, practices, params, ward_key in offered_wards, refresh_count)
    except qt.QuoteError as err:
        track_change(snapshot, None)
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
    track_change(snapshot, q.farmer_pays)
    with right:  # the price, then right under it what moves it
        price_panel(q)
        what_moves(q, ward_key, season, acres, cows, practices, params, ward_key in offered_wards, refresh_count)
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
        if q.pricing_mode == "flat":
            story += " The flat rate does not depend on this history."
        elif q.burn_cost_rate == 0:
            story += (f" It would not have paid in the other season either, so the price is the product's "
                      f"{params.min_premium_rate:.0%} minimum.")
        elif minimum_applies(q.burn_cost_rate, params):
            story += (f" The other season's payouts price below the {params.min_premium_rate:.0%} minimum, so the "
                      "minimum applies.")
        else:
            story += " The price comes from both seasons together, so the ward's dry years in the other season count."
    with theme.panel("What this cover would have paid", story):
        st.plotly_chart(history_chart(q), width="stretch")

    with theme.panel("If it pays", "No claim form and no farm visit: the index decides, then the money moves."):
        # The loan share is the claim split set in chapter 3 (70/30 unless it was changed there).
        # the live box first (chapter 3 renders after this one), then the share kept while that box is hidden
        live = st.session_state.get("split_share", st.session_state.get("split_share_kept", 70))
        loan_share = 1 - min(max(float(live), 50.0), 100.0) / 100
        if len(paid):
            example = float(paid["payout_total"].max())
            within = f"The farmer gets the payout by M-Pesa. In the worst season above: {theme.ksh(example)}."
            loan = (f"Up to {loan_share:.0%} ({theme.ksh(example * loan_share)}) can clear the member's SACCO loan, "
                    "never more than is owed, and only with written consent." if loan_share > 0 else
                    "With the split set in chapter 3, all of it goes to the farmer and none clears a loan.")
        else:
            within = "The farmer gets the payout by M-Pesa."
            loan = (f"Up to {loan_share:.0%} of it can clear the member's SACCO loan, never more than is owed, and "
                    "only with written consent." if loan_share > 0 else
                    "With the split set in chapter 3, all of it goes to the farmer and none clears a loan.")
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
