"""Tab 2: SACCO M-Pesa and check-off reconciliation (ShambaRecon)."""
from __future__ import annotations

import math

import plotly.graph_objects as go
import streamlit as st

from data.seed_generator import N_MEMBERS, generate_all
from engine import recon_engine as rec
from engine.parametric_engine import WARDS
from ui import theme

MONEY = st.column_config.NumberColumn(format="localized")
METHOD_ORDER = [rec.EXACT_ID, rec.EXACT_PHONE, rec.NATIONAL_ID, rec.FUZZY_REF, rec.SPOUSE, rec.MEMBER_NAME,
                rec.CHECKOFF, rec.DUPLICATE, rec.BAD_AMOUNT, rec.AMBIGUOUS, rec.UNMATCHED]


@st.cache_data(show_spinner="Generating synthetic SACCO ledger and M-Pesa statement...")
def synthetic(payment_items: tuple):
    return generate_all(premium_by_ward=dict(payment_items))


def _masked_statement(statement):
    view = statement.copy()
    parts = view["other_party_info"].map(rec.split_other_party)
    view["other_party_info"] = [f"{rec.mask_phone(p)} - {n}" for p, n in parts]
    return view


def _masked_members(members):
    view = members[["member_id", "full_name", "ward", "phone", "national_id", "loan_balance", "overdue_interest",
                    "milk_checkoff_daily"]].copy()
    view["phone"] = view["phone"].map(lambda p: rec.mask_phone(rec.normalize_phone(p)))
    view["national_id"] = view["national_id"].map(rec.mask_id)
    view["ward"] = view["ward"].map(lambda k: WARDS[k].name)
    return view


def method_chart(mpesa) -> go.Figure:
    counts = mpesa.assign(paid_in_ksh=mpesa["paid_in_ksh"].clip(lower=0)).groupby("match_method").agg(
        rows=("match_method", "size"), value=("paid_in_ksh", "sum"))
    counts = counts.reindex([m for m in METHOD_ORDER if m in counts.index])
    colours = [theme.RED if m in rec.SUSPENSE_METHODS else theme.AMBER if m == rec.DUPLICATE else theme.GREEN
               for m in counts.index]  # Bad amount is in SUSPENSE_METHODS
    fig = go.Figure(go.Bar(x=counts["rows"], y=counts.index, orientation="h", marker_color=colours,
                           customdata=counts["value"], text=counts["rows"], textposition="outside", cliponaxis=False,
                           hovertemplate="%{y}: %{x} rows, KSh %{customdata:,.0f}<extra></extra>"))
    fig.update_yaxes(autorange="reversed")
    fig.update_xaxes(title="Statement rows", range=[0, counts["rows"].max() * 1.2])
    return theme.plot_layout(fig, height=340)


REASONS = {
    rec.EXACT_ID: "The account reference is exactly a member number, and nothing suggests a slip.",
    rec.NATIONAL_ID: "The account reference is this member's national ID number.",
    rec.FUZZY_REF: "The account reference is this member's number with a slip in it (a missing dash, a letter O for a "
                   "zero, a word around it), and neither the phone nor the name points at anyone else.",
    rec.EXACT_PHONE: "The money came from this member's registered phone, and neither the reference nor the name "
                     "points at anyone else.",
    rec.SPOUSE: "The name on the M-Pesa account is this member's spouse, three names in order, and no one else's.",
    rec.MEMBER_NAME: "The name on the M-Pesa account is this member's, three names in order, and no one else's.",
    rec.AMBIGUOUS: "The reference, the phone and the name do not settle on one member.",
    rec.UNMATCHED: "Nothing in the payment points at a member, so it waits in suspense until someone claims it.",
    rec.BAD_AMOUNT: "The amount is zero, so there is nothing to credit.",
}
UNKNOWN_PHONE = "unknown"


def _examples(members) -> dict:
    """Ready-made payments that show each rule: (reference, paid from, name on the account, amount)."""
    m = members.set_index("member_id")
    first = "MBR-1042" if "MBR-1042" in m.index else m.index[0]
    neighbour = f"MBR-{int(first[4:]) + 1}"
    own = m.loc[first]
    examples = {
        "Exact member number": (first, UNKNOWN_PHONE, "", 3_600),
        "A slip in the number": (first.replace("-", " ").replace("0", "O", 1), first, own["full_name"], 3_600),
    }
    if neighbour in m.index:
        examples["Someone else's number"] = (neighbour, first, own["full_name"], 3_600)
    married = m[m["spouse_name"].fillna("").str.split().str.len() >= 3]
    if len(married):
        examples["A spouse paying"] = ("", UNKNOWN_PHONE, married.iloc[0]["spouse_name"], 3_600)
    examples["Nothing to go on"] = ("SCHOOL FEES", UNKNOWN_PHONE, "Upendo Agrovet", 500)
    return examples


def try_payment(data, premium_targets: dict) -> None:
    """One payment typed by hand, matched with the same rules as the statement, with the reason in plain words."""
    members = data.members.set_index("member_id")
    examples = _examples(data.members)

    def fill():
        choice = st.session_state.get("try_example")
        if choice in examples:
            ref, phone, name, amount = examples[choice]
            st.session_state.update(try_ref=ref, try_phone=phone, try_name=name, try_amount=amount)
        st.session_state["try_example"] = None  # nothing stays selected, so one click always reloads an example

    if "try_ref" not in st.session_state:  # start on the first example
        ref, phone, name, amount = next(iter(examples.values()))
        st.session_state.update(try_ref=ref, try_phone=phone, try_name=name, try_amount=amount)
    with theme.panel("Try a payment by hand",
                     "Type a payment the way it would arrive from M-Pesa, or pick an example, and see where the money "
                     "goes and why. Nothing is saved."):
        st.pills("Examples", list(examples), key="try_example", on_change=fill, label_visibility="collapsed")
        with st.form("try_payment", border=False):
            c1, c2 = st.columns(2)
            ref = c1.text_input("Account reference", key="try_ref",
                                help="What the payer typed as the account: MBR-1042, MBR 1O42, 1042, a name...")
            phone_key = c1.selectbox(
                "Paid from", [UNKNOWN_PHONE, *members.index], key="try_phone",
                format_func=lambda k: "A phone no member registered" if k == UNKNOWN_PHONE else
                f"{k}'s registered phone ({rec.mask_phone(members.loc[k, 'phone_254'])})")
            amount = theme.number(c2, "Amount (KSh)", 0, 500_000, 3_600, 100, key="try_amount", unit="KSh",
                                  in_form=True)
            name = c2.text_input("Name on the M-Pesa account", key="try_name",
                                 help="M-Pesa shows the SIM owner's name. Leave it blank if you do not know it.")
            checked = st.form_submit_button("Check this payment", type="primary")
        inputs = (ref, phone_key, name, float(amount))
        if checked:
            phone = "" if phone_key == UNKNOWN_PHONE else members.loc[phone_key, "phone_254"]
            index = rec.MemberIndex(data.members)
            result = ((None, rec.BAD_AMOUNT, 0.0) if amount <= 0 else
                      rec.match_row(ref, phone, name, index, float(amount)))
            if result[1] == rec.AMBIGUOUS:
                why = rec.review_reason(ref, phone, name, index, float(amount))
            elif result[1] == rec.EXACT_PHONE:
                fits = rec.reference_candidates(ref, name, index, float(amount))
                why = (f"The reference fits {len(fits)} member numbers, {result[0]} among them, and the money came "
                       f"from {result[0]}'s registered phone, which settles it." if len(fits) > 1 else None)
            else:
                why = None
            st.session_state["try_result"] = (inputs, result, why)
        stored = st.session_state.get("try_result")
        if not stored or stored[0] != inputs:
            st.caption("Press Check this payment to see the result.")
            return
        (member, method, _), why = stored[1], stored[2]
        paid_from = "an unknown phone" if phone_key == UNKNOWN_PHONE else f"{phone_key}'s registered phone"
        st.caption(f"Result for: reference {ref.strip() or '(blank)'}, paid from {paid_from}, name "
                   f"{name.strip() or '(blank)'}, {theme.ksh(amount)}. Edit the payment and press Check this payment "
                   "again for a new result.")
        if member:
            row = members.loc[member]
            ward = row["ward"]
            st.markdown(f"**Credited to {member}, {row['full_name']}** ({WARDS[ward].label}). {why or REASONS[method]}")
            due = premium_targets.get(ward)
            st.markdown(f"{theme.ksh(amount)} goes first to this season's premium "
                        f"({theme.ksh(due)} owed), then overdue loan interest, then the loan, then savings."
                        if due is not None else
                        f"Their ward is not offered this season, so {theme.ksh(amount)} goes to overdue loan "
                        "interest, then the loan, then savings.")
        else:
            verdict = {rec.AMBIGUOUS: "Sent to a person to review.", rec.UNMATCHED: "Held in suspense.",
                       rec.BAD_AMOUNT: "Held: bad amount."}[method]
            tail = " A wrong credit is worse than a short wait, so a person checks it." if method == rec.AMBIGUOUS else ""
            st.markdown(f"**{verdict}** {why or REASONS[method]}{tail}")
        st.markdown(theme.status(method, "GREEN" if member else "RED" if method == rec.BAD_AMOUNT else "AMBER"),
                    unsafe_allow_html=True)


def render(premium_targets: dict, payment_levels: dict, sum_insured: float = 60_000.0,
           gross_premiums: dict | None = None, seasonal_cap: float = 50_000.0) -> None:
    """``premium_targets``: what a member owes this season in each ward that is offered the product (KSh, after
    any subsidy). ``payment_levels``: what members in every ward aim to pay, which shapes the synthetic statement."""
    payment_items = tuple(sorted((k, round(v, 2)) for k, v in payment_levels.items()))
    # A run is only valid for the premiums it charged AND the statement it read; either changing makes it stale.
    premium_items = (tuple(sorted((k, round(v, 2)) for k, v in premium_targets.items())), payment_items)
    data = synthetic(payment_items)

    header = st.container()
    head, action = st.columns([3, 1], vertical_alignment="center")
    head.caption(f"{N_MEMBERS} fictional SACCO members and a {len(data.statement)}-row M-Pesa paybill statement "
                 "with the usual errors: mistyped member IDs, spouse phones, micro-payments, duplicate exports. Each "
                 "member owes their ward's premium from chapter 1, less any subsidy; a ward that is not offered "
                 "owes none. Phone "
                 "numbers and national IDs are masked.")
    if action.button("Run reconciliation", type="primary", key="run_recon", width="stretch"):
        with st.spinner(f"Matching {len(data.statement)} rows..."):
            st.session_state["recon"] = (premium_items, rec.reconcile(data.statement, data.members, premium_targets))
        st.session_state.pop("claim_split", None)
        st.toast("Reconciliation finished")
    exact_lookup_misses = float((~rec.naive_exact_match(data.statement, data.members)).mean())

    with st.expander("Inputs: member ledger and paybill statement"):
        left, right = st.columns(2)
        left.markdown("**SACCO member ledger**")
        left.dataframe(_masked_members(data.members), hide_index=True, height=260, width="stretch",
                       column_config={"loan_balance": MONEY, "overdue_interest": MONEY})
        right.markdown("**M-Pesa paybill statement**")
        right.dataframe(_masked_statement(data.statement), hide_index=True, height=260, width="stretch",
                        column_config={"paid_in_ksh": MONEY})
    try_payment(data, premium_targets)

    stored = st.session_state.get("recon")
    if stored is None or stored[0] != premium_items:
        with header:
            theme.chapter(3, "Collecting the money", "ShambaRecon",
                          f"Premiums arrive as messy M-Pesa payments. A clerk's exact lookup would leave "
                          f"{theme.pct(100 * exact_lookup_misses, 0)} of these unallocated.",
                          "Press Run reconciliation to match this statement to members and allocate every shilling.")
        with theme.panel("No reconciliation yet" if stored is None else "Premiums have changed"):
            st.markdown("Press **Run reconciliation** to match the statement to members and allocate the money."
                        if stored is None else
                        "The ward premiums on the backtest tab changed since the last run. Run it again.")
        return
    result: rec.ReconResult = stored[1]

    mpesa = result.mpesa
    acc = rec.accuracy(result, data.truth)
    with header:
        theme.chapter(
            3, "Collecting the money", "ShambaRecon",
            f"A clerk's exact lookup leaves {theme.pct(100 * result.before_suspense_rows, 0)} of payments "
            f"unallocated. ShambaRecon leaves {theme.pct(100 * result.after_suspense_rows, 1)}.",
            f"{acc['wrong_member']} payments credited to the wrong member, {result.duplicates_caught} duplicates held, "
            f"and {theme.ksh(result.members.loc[result.members['policy_status'] == rec.ACTIVE, 'to_premium'].sum())} "
            "of premium ready to remit to the partner insurer.")
    left_for_review = mpesa.loc[mpesa["match_method"].isin(rec.SUSPENSE_METHODS), "paid_in_ksh"].clip(lower=0).sum()
    st.caption(f"Reconciled {len(mpesa)} M-Pesa rows and {len(result.ledger) - len(mpesa)} milk check-offs "
               f"in {result.seconds:.2f} seconds.")
    theme.stats([
        ("Unallocated, by rows",
         f"{theme.pct(100 * result.before_suspense_rows)} → {theme.pct(100 * result.after_suspense_rows)}",
         "A clerk's exact lookup, then ShambaRecon", "good"),
        ("Unallocated, by value",
         f"{theme.pct(100 * result.before_suspense_value)} → {theme.pct(100 * result.after_suspense_value)}",
         f"{theme.ksh(left_for_review)} left for a person to review"),
        ("Duplicates held", str(result.duplicates_caught),
         f"{theme.ksh(result.duplicate_value_exact_ref)} of them an exact lookup would credit twice", "warn"),
        # rounded down, so one wrong credit in a thousand never shows as 100.0%
        ("Matched to the right member", f"{math.floor(acc['precision'] * 1000 + 1e-9) / 10:.1f}%",
         f"{acc['correct']} of {acc['credited']} credited rows (synthetic ground truth)"),
    ])
    status = result.members["policy_status"].value_counts()
    remit = result.members.loc[result.members["policy_status"] == rec.ACTIVE, "to_premium"].sum()
    theme.stats([
        ("Active", f"{status.get(rec.ACTIVE, 0)}", "Ward premium paid in full", "good"),
        ("Grace period", f"{status.get(rec.GRACE, 0)}", "At least half paid", "warn"),
        ("Pending", f"{status.get(rec.PENDING, 0)}", "Less than half paid, or nothing", "bad"),
        ("Not offered", f"{status.get(rec.NOT_OFFERED, 0)}", "Ward above the sellable ceiling"),
        ("Premium to remit", theme.ksh_short(remit), "To the partner insurer, active policies"),
    ])

    with theme.panel("Where the money went",
                     "How each M-Pesa row was placed, and the waterfall: each member's money fills the premium "
                     "first, then overdue interest, then principal and savings, in the order it arrived."):
        chart_col, split_col = st.columns([3, 2])
        chart_col.plotly_chart(method_chart(mpesa), width="stretch")
        totals = result.ledger[["to_premium", "to_interest", "to_principal", "to_savings"]].sum()
        split_col.dataframe(
            {"Priority": ["1. Seasonal premium", "2. Overdue loan interest", "3a. Loan principal", "3b. Member savings"],
             "KSh": [round(v) for v in totals]},
            hide_index=True, width="stretch", column_config={"KSh": MONEY})
        split_col.caption(f"Total allocated: {theme.ksh(totals.sum())} from M-Pesa and milk check-off.")

    with theme.panel("Reconciliation ledger", "Every row, the member it went to, how it was matched and the split."):
        f1, f2, f3 = st.columns([2, 1, 1], vertical_alignment="bottom")
        methods = f1.multiselect("Match method", [m for m in METHOD_ORDER if m in set(result.ledger["match_method"])],
                                 key="ledger_methods")
        query = f2.text_input("Search reference, receipt or member", key="ledger_query")
        only_mpesa = f3.toggle("M-Pesa rows only", value=True, key="ledger_mpesa")
        view = mpesa if only_mpesa else result.ledger
        if methods:
            view = view[view["match_method"].isin(methods)]
        if query:
            q = query.strip().upper()
            view = view[view["account_reference"].fillna("").str.upper().str.contains(q, regex=False)
                        | view["receipt_no"].str.upper().str.contains(q, regex=False)
                        | view["member_id"].fillna("").str.upper().str.contains(q, regex=False)]
        names = dict(zip(result.members["member_id"], result.members["full_name"]))
        table = view.assign(
            payer=[f"{rec.mask_phone(p)} {n}".strip() if p else n
                   for p, n in zip(view["payer_phone"], view["payer_name"])],
            member_name=view["member_id"].map(names),
        )[["receipt_no", "completion_time", "paid_in_ksh", "account_reference", "payer", "member_id", "member_name",
           "match_method", "confidence", "to_premium", "to_interest", "to_principal", "to_savings"]]
        st.dataframe(table, hide_index=True, width="stretch", height=380, column_config={
            "receipt_no": "Receipt", "completion_time": "Time",
            "paid_in_ksh": st.column_config.NumberColumn("Paid in KSh", format="localized"),
            "account_reference": "Account reference", "payer": "Payer", "member_id": "Member",
            "member_name": "Member name", "match_method": "Match method",
            "confidence": st.column_config.ProgressColumn("Confidence", min_value=0, max_value=100, format="%.0f"),
            "to_premium": st.column_config.NumberColumn("Premium", format="localized"),
            "to_interest": st.column_config.NumberColumn("Interest", format="localized"),
            "to_principal": st.column_config.NumberColumn("Principal", format="localized"),
            "to_savings": st.column_config.NumberColumn("Savings", format="localized"),
        })
        bordereau = rec.bordereau(result.members, WARDS, sum_insured=sum_insured, gross_premium=gross_premiums)
        d1, d2, d3 = st.columns([1, 1, 2], vertical_alignment="center")
        d1.download_button(f"Bordereau ({len(bordereau)} policies)", bordereau.to_csv(index=False).encode(),
                           "underwriter_bordereaux.csv", "text/csv", icon=":material/download:")
        d2.download_button(f"Ledger ({len(table)} rows)", table.to_csv(index=False).encode(),
                           "reconciliation_ledger.csv", "text/csv", icon=":material/download:")
        d3.caption("Bordereau layout is a draft to agree with the partner insurer; identifiers are masked.")

    with theme.panel("Claim-split settlement",
                     "When a trigger fires, part of each payout can clear the member's SACCO loan. Illustrative: it "
                     "needs each member's written consent to assign claim proceeds, and the insurer's agreement. "
                     "Only active policies are paid."):
        k1, k2, k3, k4 = st.columns([2, 1, 1, 1], vertical_alignment="bottom")
        wards = k1.multiselect("Wards where the drought trigger fired", list(WARDS), default=["kangundo"],
                               format_func=lambda k: WARDS[k].label, key="split_wards")
        cap = int(seasonal_cap)
        payout = k2.number_input("Payout per member (KSh)", 1_000, cap, min(25_000, cap), 1_000,
                                 key=f"split_payout_{cap}", help="At most the seasonal cap of the cover")
        # The share outlives this panel (it is hidden while the reconciliation is stale), and chapter 2 reads it.
        if "split_share" not in st.session_state and "split_share_kept" in st.session_state:
            st.session_state["split_share"] = st.session_state["split_share_kept"]
        farmer_pct = theme.number(k3, "Farmer share by M-Pesa (%)", 50, 100, 70, 5, key="split_share", unit="%")
        st.session_state["split_share_kept"] = farmer_pct
        farmer_share = farmer_pct / 100
        split_key = (tuple(wards), float(payout), farmer_share, premium_items)
        if k4.button("Simulate payout", key="run_split", width="stretch"):
            st.session_state["claim_split"] = (split_key, rec.claim_split(result.members, wards, float(payout),
                                                                          farmer_share))
        stored_split = st.session_state.get("claim_split")
        split = stored_split[1] if stored_split and stored_split[0] == split_key else None
        if split is None:
            st.caption("Choose the wards and press Simulate payout." if not stored_split else
                       "The wards, payout or share changed. Press Simulate payout again.")
    if split is not None:
        with theme.panel("Settlement", "Who gets what from the simulated payout."):
            cleared = int(((split["loan_owed_before_ksh"] > 0) & (split["loan_owed_after_ksh"] <= 0.5)).sum())
            theme.stats([
                ("Members paid", f"{len(split)}", "Active policies in the selected wards"),
                ("To farmers by M-Pesa", theme.ksh_short(split["to_farmer_b2c_ksh"].sum()), "Hay, seed and inputs"),
                ("To SACCO loans", theme.ksh_short(split["to_sacco_loan_ksh"].sum()), "Capped at what each member owes"),
                ("Loans cleared", str(cleared), "Owed nothing after the payout"),
            ])
            view = split.assign(ward=split["ward"].map(lambda k: WARDS[k].name))
            money = lambda label: st.column_config.NumberColumn(label, format="localized")
            st.dataframe(view, hide_index=True, width="stretch", height=300, column_config={
                "member_id": "Member", "full_name": "Name", "ward": "Ward", "phone_masked": "Phone",
                "payout_ksh": money("Payout KSh"), "to_farmer_b2c_ksh": money("To farmer KSh"),
                "to_sacco_loan_ksh": money("To SACCO loan KSh"), "loan_owed_before_ksh": money("Owed before KSh"),
                "loan_owed_after_ksh": money("Owed after KSh")})
            st.download_button("Settlement file", split.to_csv(index=False).encode(), "sacco_claim_split_settlement.csv",
                               "text/csv", icon=":material/download:")
    theme.next_chapter(4, "Trust and the numbers", "What happens when the satellite is unsure, and what the pilot "
                       "earns.")
