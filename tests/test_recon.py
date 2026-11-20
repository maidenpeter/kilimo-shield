import pandas as pd
import pytest

from data import seed_generator as sg
from engine import recon_engine as rec
from engine.parametric_engine import WARDS


@pytest.fixture(scope="module")
def data():
    return sg.generate_all()


@pytest.fixture(scope="module")
def result(data):
    return rec.reconcile(data.statement, data.members)


def test_generator_sizes_and_mix(data):
    assert len(data.members) == 500
    assert data.members["member_id"].iloc[0] == "MBR-1001" and data.members["member_id"].iloc[-1] == "MBR-1500"
    assert data.members["national_id"].is_unique
    assert len(data.statement) == 520
    shares = data.truth["scenario"].value_counts(normalize=True)
    assert shares["mistyped_id"] == pytest.approx(0.18, abs=0.01)
    assert shares["spouse_phone"] == pytest.approx(0.14, abs=0.01)
    assert shares["partial"] == pytest.approx(0.10, abs=0.01)
    assert shares["duplicate_export"] + shares["not_a_member"] == pytest.approx(0.05, abs=0.01)
    assert data.members["loan_balance"].between(0, 85_000).all()


def test_generator_is_deterministic(data):
    again = sg.generate_all()
    pd.testing.assert_frame_equal(data.statement, again.statement)
    pd.testing.assert_frame_equal(data.members, again.members)


@pytest.mark.parametrize("raw,expected", [
    ("0712345678", "254712345678"), ("0712 345 678", "254712345678"), ("+254 712 345678", "254712345678"),
    ("254712345678", "254712345678"), ("712345678", "254712345678"), ("12345", ""), (None, ""),
])
def test_normalize_phone(raw, expected):
    assert rec.normalize_phone(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("MBR-1042", "MBR1042"), ("mbr 1042", "MBR1042"), ("MRB-1042", "MBR1042"), ("MBR-1O42", "MBR1042"),
    ("MBR-1042-MILK", "MBR1042MILK"), ("ACC MBR-1042", "MBR1042"), ("KAMAU MILK", "KAMAUMILK"),
])
def test_canonical_ref(raw, expected):
    assert rec.canonical_ref(raw) == expected


def test_masking_hides_the_middle():
    assert rec.mask_phone("254712345678") == "254712***678"
    assert rec.mask_id("23456789") == "****789"


def test_matching_methods(data):
    index = rec.MemberIndex(data.members)
    m = data.members.iloc[41]  # MBR-1042
    assert rec.match_row("MBR-1042", "", "", index)[:2] == ("MBR-1042", rec.EXACT_ID)
    assert rec.match_row("", m["phone_254"], "", index)[:2] == ("MBR-1042", rec.EXACT_PHONE)
    assert rec.match_row(m["national_id"], "254700000001", "SOMEONE", index)[:2] == ("MBR-1042", rec.NATIONAL_ID)
    for typo in ("MBR1042", "MBR-1042-MILK", "MRB-1042", "MBR-1O42", "mbr 1042"):
        member, method, score = rec.match_row(typo, "254700000001", "", index)
        assert (member, method) == ("MBR-1042", rec.FUZZY_REF) and score >= rec.FUZZY_THRESHOLD
    assert rec.match_row("SCHOOL FEES", "254700000001", "MAMA MBOGA STORES", index)[1] == rec.UNMATCHED


def test_spouse_payment_matches_through_the_spouse_name(data):
    index = rec.MemberIndex(data.members)
    married = data.members[data.members["spouse_name"] != ""].iloc[0]
    member, method, _ = rec.match_row("", "254700000002", married["spouse_name"].upper(), index)
    assert (member, method) == (married["member_id"], rec.SPOUSE)


def test_truncated_reference_is_not_guessed(data):
    index = rec.MemberIndex(data.members)
    member, method, _ = rec.match_row("MBR-104", "254700000003", "NOBODY KNOWN", index)
    assert member is None and method == rec.AMBIGUOUS


def test_reconciliation_beats_exact_lookup(result):
    assert result.before_suspense_rows > 0.3
    assert result.after_suspense_rows < 0.05
    assert result.after_suspense_value < result.before_suspense_value
    assert result.duplicates_caught == 12


def test_accuracy_against_ground_truth(result, data):
    acc = rec.accuracy(result, data.truth)
    assert acc["precision"] >= 0.99
    assert acc["recall"] >= 0.97
    assert acc["wrong_member"] == 0


def test_duplicates_are_never_credited(result):
    dupes = result.ledger[result.ledger["match_method"] == rec.DUPLICATE]
    assert len(dupes) == 12
    assert dupes[["to_premium", "to_interest", "to_principal", "to_savings"]].sum().sum() == 0


def test_every_matched_shilling_is_allocated_once(result):
    credited = result.ledger[~result.ledger["match_method"].isin(rec.SUSPENSE_METHODS + (rec.DUPLICATE,))]
    split = credited[["to_premium", "to_interest", "to_principal", "to_savings"]].sum(axis=1)
    assert split.sum() == pytest.approx(credited["paid_in_ksh"].sum())
    assert (split - credited["paid_in_ksh"]).abs().max() < 1e-6


def test_waterfall_order_and_status():
    members = pd.DataFrame([
        {"member_id": "MBR-1", "full_name": "A B", "surname": "B", "phone": "0712000001", "national_id": "1",
         "ward": "njoro", "spouse_name": "", "loan_balance": 10_000.0, "overdue_interest": 500.0,
         "savings_balance": 0.0},
        {"member_id": "MBR-2", "full_name": "C D", "surname": "D", "phone": "0712000002", "national_id": "2",
         "ward": "njoro", "spouse_name": "", "loan_balance": 0.0, "overdue_interest": 0.0, "savings_balance": 0.0},
    ])
    ledger = pd.DataFrame([
        {"receipt_no": "R1", "completion_time": "2026-10-01 09:00:00", "paid_in_ksh": 2_000.0, "member_id": "MBR-1",
         "match_method": rec.EXACT_ID},
        {"receipt_no": "R2", "completion_time": "2026-10-02 09:00:00", "paid_in_ksh": 3_000.0, "member_id": "MBR-1",
         "match_method": rec.FUZZY_REF},
        {"receipt_no": "R3", "completion_time": "2026-10-02 10:00:00", "paid_in_ksh": 1_900.0, "member_id": "MBR-2",
         "match_method": rec.EXACT_ID},
    ])
    out, summary = rec.allocate_waterfall(ledger, members, premium_target=3_600)
    r2 = out[out["receipt_no"] == "R2"].iloc[0]
    assert (r2["to_premium"], r2["to_interest"], r2["to_principal"]) == (1_600, 500, 900)
    s = summary.set_index("member_id")
    assert s.loc["MBR-1", "policy_status"] == rec.ACTIVE and s.loc["MBR-1", "loan_after"] == 9_100
    assert s.loc["MBR-2", "policy_status"] == rec.GRACE  # 1,900 of 3,600 is more than half


def test_zone_premiums_follow_each_members_ward():
    premiums = {"njoro": 5_100.0, "imenti_north": 6_780.0, "kangundo": 5_880.0, "kimilili": 5_940.0,
                "bureti": 10_740.0}
    data = sg.generate_all(premium_by_ward=premiums)
    result = rec.reconcile(data.statement, data.members, premiums)
    m = result.members
    assert (m["premium_due"] == m["ward"].map(premiums)).all()
    active = m[m["policy_status"] == rec.ACTIVE]
    assert len(active) > 150
    assert (active["to_premium"] == active["premium_due"]).all()
    grace = m[m["policy_status"] == rec.GRACE]
    assert (grace["to_premium"] >= 0.5 * grace["premium_due"]).all()
    assert rec.accuracy(result, data.truth)["wrong_member"] == 0
    b = rec.bordereau(m, WARDS)
    assert (b["premium_due_ksh"] == b["ward"].map({w.name: premiums[k] for k, w in WARDS.items()})).all()


def test_bordereau_lists_only_active_policies(result):
    b = rec.bordereau(result.members, WARDS)
    assert len(b) == (result.members["policy_status"] == rec.ACTIVE).sum()
    assert (b["premium_received_ksh"] == 3_600).all()
    assert (b["premium_due_ksh"] == 3_600).all()
    assert b["national_id_masked"].str.startswith("****").all()
    assert (b["insurer"] == "Partner insurer (to be named)").all()


def test_claim_split_caps_the_sacco_share(result):
    split = rec.claim_split(result.members, list(WARDS), 25_000, 0.70)
    assert len(split) == (result.members["policy_status"] == rec.ACTIVE).sum()
    assert (split["to_sacco_loan_ksh"] <= 7_500 + 1e-6).all()
    assert (split["to_sacco_loan_ksh"] <= split["loan_owed_before_ksh"] + 1e-6).all()
    assert (split["to_farmer_b2c_ksh"] + split["to_sacco_loan_ksh"] == 25_000).all()
    no_loan = split[split["loan_owed_before_ksh"] == 0]
    assert (no_loan["to_farmer_b2c_ksh"] == 25_000).all()


def test_include_checkoff_changes_status(data):
    with_checkoff = rec.reconcile(data.statement, data.members)
    without = rec.reconcile(data.statement, data.members, include_checkoff=False)
    active = lambda r: (r.members["policy_status"] == rec.ACTIVE).sum()
    assert active(with_checkoff) >= active(without)
