"""Tab 2: SACCO M-Pesa and check-off reconciliation engine."""
from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from data.seed_generator import N_MEMBERS, generate_all
from engine import recon_engine as rec
from engine.parametric_engine import WARDS
from ui import theme

MONEY = st.column_config.NumberColumn(format="localized")
METHOD_ORDER = [rec.EXACT_ID, rec.EXACT_PHONE, rec.NATIONAL_ID, rec.FUZZY_REF, rec.SPOUSE, rec.MEMBER_NAME,
                rec.CHECKOFF, rec.DUPLICATE, rec.AMBIGUOUS, rec.UNMATCHED]


@st.cache_data(show_spinner="Generating synthetic SACCO ledger and M-Pesa statement...")
def synthetic():
    return generate_all()


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
    counts = mpesa.groupby("match_method").agg(rows=("receipt_no", "size"), value=("paid_in_ksh", "sum"))
    counts = counts.reindex([m for m in METHOD_ORDER if m in counts.index])
    colours = [theme.RED if m in rec.SUSPENSE_METHODS else theme.AMBER if m == rec.DUPLICATE else theme.GREEN
               for m in counts.index]
    fig = go.Figure(go.Bar(x=counts["rows"], y=counts.index, orientation="h", marker_color=colours,
                           customdata=counts["value"],
                           hovertemplate="%{y}: %{x} rows, KSh %{customdata:,.0f}<extra></extra>"))
    fig.update_yaxes(autorange="reversed")
    fig.update_xaxes(title="Statement rows")
    return theme.plot_layout(fig, "How each M-Pesa row was placed", height=380)


def render(premium_target: float = rec.PREMIUM_TARGET, sum_insured: float = 60_000.0) -> None:
    data = synthetic()
    st.subheader("ShambaRecon: every shilling matched and allocated")
    theme.note(f"Synthetic data: {N_MEMBERS} fictional SACCO members and a {len(data.statement)}-row M-Pesa paybill "
               "statement with typical errors (mistyped member IDs, spouse phones, micro-payments, duplicate "
               "exports). Phone numbers and national IDs are masked on screen.")

    with st.expander("Inputs: member ledger and paybill statement"):
        left, right = st.columns(2)
        left.markdown("**SACCO member ledger**")
        left.dataframe(_masked_members(data.members), hide_index=True, height=260, width="stretch",
                       column_config={"loan_balance": MONEY, "overdue_interest": MONEY})
        right.markdown("**M-Pesa paybill statement**")
        right.dataframe(_masked_statement(data.statement), hide_index=True, height=260, width="stretch",
                        column_config={"paid_in_ksh": MONEY})

    if st.button("Run automated reconciliation", type="primary", key="run_recon"):
        st.session_state["recon"] = (premium_target, rec.reconcile(data.statement, data.members, premium_target))
        st.session_state.pop("claim_split", None)
    stored = st.session_state.get("recon")
    if stored is not None and stored[0] != premium_target:
        st.info(f"The premium is now {theme.ksh(premium_target)} (sidebar). Run the reconciliation again.")
        return
    if stored is None:
        st.info("Press the button to match the statement and allocate the money.")
        return
    result: rec.ReconResult = stored[1]

    mpesa = result.mpesa
    acc = rec.accuracy(result, data.truth)
    st.success(f"Reconciled {len(mpesa)} M-Pesa rows and {len(result.ledger) - len(mpesa)} milk check-offs "
               f"in {result.seconds:.2f} seconds.")

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        theme.kpi("Unallocated suspense rate", f"{result.before_suspense_rows:.1%} to {result.after_suspense_rows:.1%}",
                  "Share of rows: a clerk's exact lookup, then ShambaRecon", "amber")
    with c2:
        theme.kpi("Suspense by value", f"{result.before_suspense_value:.1%} to {result.after_suspense_value:.1%}",
                  f"Left for review: {theme.ksh(mpesa.loc[mpesa['match_method'].isin(rec.SUSPENSE_METHODS), 'paid_in_ksh'].sum())}")
    with c3:
        theme.kpi("Duplicates caught", str(result.duplicates_caught),
                  f"{theme.ksh(result.duplicate_value)} that an exact lookup would credit twice", "red")
    with c4:
        theme.kpi("Match accuracy", f"{acc['precision']:.1%}",
                  f"{acc['correct']} of {acc['credited']} credited rows on the right member (synthetic ground truth)")

    status = result.members["policy_status"].value_counts()
    remit = result.members.loc[result.members["policy_status"] == rec.ACTIVE, "to_premium"].sum()
    s1, s2, s3, s4 = st.columns(4)
    with s1:
        theme.kpi("Policies ACTIVE", f"{status.get(rec.ACTIVE, 0)}", f"Full {theme.ksh(premium_target)} received")
    with s2:
        theme.kpi("GRACE_PERIOD", f"{status.get(rec.GRACE, 0)}", "At least half the premium paid", "amber")
    with s3:
        theme.kpi("PENDING", f"{status.get(rec.PENDING, 0)}", "Less than half paid, or nothing yet", "red")
    with s4:
        theme.kpi("Premium to remit", theme.ksh(remit), "To the partner insurer for ACTIVE policies")

    chart_col, split_col = st.columns([3, 2])
    chart_col.plotly_chart(method_chart(mpesa), width="stretch")
    totals = result.ledger[["to_premium", "to_interest", "to_principal", "to_savings"]].sum()
    with split_col:
        st.markdown("**Waterfall totals (M-Pesa and check-off)**")
        st.dataframe(
            {"Priority": ["1. Seasonal premium", "2. Overdue loan interest", "3a. Loan principal", "3b. Member savings"],
             "KSh": [round(v) for v in totals]},
            hide_index=True, width="stretch", column_config={"KSh": MONEY})
        st.caption("Each member's money fills priority 1 first, then 2, then 3, in the order it arrived.")

    st.markdown("#### Reconciliation ledger")
    f1, f2, f3 = st.columns([2, 1, 1])
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
        payer=[f"{rec.mask_phone(p)} {n}".strip() if p else n for p, n in zip(view["payer_phone"], view["payer_name"])],
        member_name=view["member_id"].map(names),
    )[["receipt_no", "completion_time", "paid_in_ksh", "account_reference", "payer", "member_id", "member_name",
       "match_method", "confidence", "to_premium", "to_interest", "to_principal", "to_savings"]]
    st.dataframe(table, hide_index=True, width="stretch", height=380, column_config={
        "receipt_no": "Receipt", "completion_time": "Time",
        "paid_in_ksh": st.column_config.NumberColumn("Paid in (KSh)", format="localized"),
        "account_reference": "Account reference", "payer": "Payer", "member_id": "Member",
        "member_name": "Member name", "match_method": "Match method",
        "confidence": st.column_config.ProgressColumn("Confidence", min_value=0, max_value=100, format="%.0f"),
        "to_premium": st.column_config.NumberColumn("To premium", format="localized"),
        "to_interest": st.column_config.NumberColumn("To interest", format="localized"),
        "to_principal": st.column_config.NumberColumn("To principal", format="localized"),
        "to_savings": st.column_config.NumberColumn("To savings", format="localized"),
    })
    st.caption(f"{len(table)} rows shown.")

    bordereau = rec.bordereau(result.members, WARDS, sum_insured=sum_insured, premium_target=premium_target)
    d1, d2 = st.columns(2)
    d1.download_button(f"Download underwriter bordereau ({len(bordereau)} policies, CSV)",
                       bordereau.to_csv(index=False).encode(), "underwriter_bordereaux.csv", "text/csv")
    d2.download_button("Download full reconciliation ledger (CSV)",
                       table.to_csv(index=False).encode(), "reconciliation_ledger.csv", "text/csv")
    st.caption("Bordereau layout is a draft to agree with the partner insurer; identifiers are masked.")

    st.markdown("#### Smart claim-split settlement")
    theme.note("Illustrative. Sending part of a claim to a SACCO loan needs each member's written consent to assign "
               "claim proceeds, and the insurer's agreement. Only ACTIVE policies are paid.")
    k1, k2, k3 = st.columns([2, 1, 1])
    wards = k1.multiselect("Wards where the drought trigger fired", list(WARDS), default=["kangundo"],
                           format_func=lambda k: WARDS[k].label, key="split_wards")
    payout = k2.number_input("Payout per member (KSh)", 1_000, 60_000, 25_000, 1_000, key="split_payout")
    farmer_share = k3.slider("Farmer share by M-Pesa B2C (%)", 50, 100, 70, 5, key="split_share") / 100
    if st.button("Simulate drought payout", key="run_split"):
        st.session_state["claim_split"] = rec.claim_split(result.members, wards, float(payout), farmer_share)
    split = st.session_state.get("claim_split")
    if split is not None:
        m1, m2, m3, m4 = st.columns(4)
        with m1:
            theme.kpi("Members paid", f"{len(split)}", "ACTIVE policies in the selected wards")
        with m2:
            theme.kpi("To farmers (M-Pesa B2C)", theme.ksh_short(split["to_farmer_b2c_ksh"].sum()),
                      "Emergency hay, seed and inputs")
        with m3:
            theme.kpi("To SACCO loan accounts", theme.ksh_short(split["to_sacco_loan_ksh"].sum()),
                      "Capped at what each member owes", "amber")
        with m4:
            cleared = int(((split["loan_owed_before_ksh"] > 0) & (split["loan_owed_after_ksh"] <= 0.5)).sum())
            theme.kpi("Loans fully cleared", str(cleared), "Reduces non-performing loans")
        view = split.assign(ward=split["ward"].map(lambda k: WARDS[k].name))
        money = lambda label: st.column_config.NumberColumn(label, format="localized")
        st.dataframe(view, hide_index=True, width="stretch", height=300, column_config={
            "member_id": "Member", "full_name": "Name", "ward": "Ward", "phone_masked": "Phone",
            "payout_ksh": money("Payout (KSh)"), "to_farmer_b2c_ksh": money("To farmer, B2C (KSh)"),
            "to_sacco_loan_ksh": money("To SACCO loan (KSh)"), "loan_owed_before_ksh": money("Owed before (KSh)"),
            "loan_owed_after_ksh": money("Owed after (KSh)")})
        st.download_button("Download claim-split settlement (CSV)", split.to_csv(index=False).encode(),
                           "sacco_claim_split_settlement.csv", "text/csv")
