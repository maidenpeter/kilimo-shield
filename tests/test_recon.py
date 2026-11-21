import numpy as np
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
    ("MBR-1042-MILK", "MBR1042"), ("ACC MBR-1042", "MBR1042"), ("KAMAU MILK", "KAMAUMILK"),
    ("MBR-104 OTIENO", "MBR104"), ("MBR-104OTIENO", "MBR104"), ("MBR-104O", "MBR1040"), ("MBR LOAN", "MBRLOAN"),
    ("MBR LOAN MBR-1042", "MBR1042"),
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


def test_conflicting_evidence_goes_to_review(data):
    index = rec.MemberIndex(data.members)
    m = data.members.set_index("member_id")
    other_phone = m.loc["MBR-1008", "phone_254"]
    # a reference naming one member, paid from another member's registered phone
    assert rec.match_row("MBR 1001", other_phone, "", index)[1] == rec.AMBIGUOUS
    # but an exact member ID is the payer's instruction and stands on its own, unless it is one keying slip from the
    # member who paid (MBR-1001 from MBR-1008's phone)
    far_phone = m.loc[m.index[-1], "phone_254"]
    assert rec.match_row("MBR-1001", far_phone, "", index)[:2] == ("MBR-1001", rec.EXACT_ID)
    assert rec.match_row("MBR-1001", other_phone, "", index)[1] == rec.AMBIGUOUS
    # a mistyped ID paid under exactly another member's full name
    two_word = data.members[data.members["full_name"].str.split().str.len() == 2].iloc[0]
    got = rec.match_row("MBR 1100", "254700000004", two_word["full_name"], index)[0]
    assert got != two_word["member_id"] and (got is None or two_word["member_id"] == "MBR-1100")


def test_names_compare_without_case_or_punctuation(data):
    index = rec.MemberIndex(data.members)
    married = data.members[data.members["spouse_name"] != ""].iloc[3]
    messy = married["spouse_name"].lower() + "."
    assert rec.match_row("", "254700000005", messy, index)[:2] == (married["member_id"], rec.SPOUSE)


def test_national_id_must_stand_alone(data):
    index = rec.MemberIndex(data.members)
    nid = data.members["national_id"].iloc[10]
    assert rec.match_row(nid, "254700000006", "", index)[1] == rec.NATIONAL_ID
    assert rec.match_row("2547" + nid, "254700000006", "", index)[1] != rec.NATIONAL_ID


def test_bad_rows_never_corrupt_the_waterfall(data):
    statement = data.statement.head(40).copy()
    statement.loc[0, "paid_in_ksh"] = float("nan")
    statement.loc[1, "paid_in_ksh"] = -500
    statement.loc[2, "receipt_no"] = None
    members = data.members.copy()
    members.loc[members.index[:50], "overdue_interest"] = float("nan")
    r = rec.reconcile(statement, members)
    bad = r.ledger[r.ledger["match_method"] == rec.BAD_AMOUNT]
    assert len(bad) == 2 and bad[["to_premium", "to_interest", "to_principal", "to_savings"]].to_numpy().sum() == 0
    credited = r.ledger[~r.ledger["match_method"].isin(rec.SUSPENSE_METHODS + (rec.DUPLICATE,))]
    alloc = credited[["to_premium", "to_interest", "to_principal", "to_savings"]].sum(axis=1)
    assert (alloc - credited["paid_in_ksh"]).abs().max() < 1e-6
    assert r.members[["interest_after", "loan_after"]].notna().all().all()


def test_empty_statement(data):
    r = rec.reconcile(data.statement.iloc[0:0], data.members)
    assert r.after_suspense_rows == 0 and r.duplicates_caught == 0


def test_a_ward_priced_at_zero_is_still_offered(data):
    premiums = {"njoro": 0.0, "kangundo": 5_880.0}
    r = rec.reconcile(data.statement, data.members, premiums)
    status = r.members.set_index("ward")["policy_status"]
    assert (status.loc["njoro"] == rec.ACTIVE).all()
    assert (status.loc["bureti"] == rec.NOT_OFFERED).all()


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
    # with a 50% subsidy the SACCO collects half and the bordereau shows the other half as subsidy due
    half = {k: v / 2 for k, v in premiums.items()}
    sub = rec.reconcile(data.statement, data.members, half)
    bs = rec.bordereau(sub.members, WARDS, gross_premium=premiums)
    assert (bs["gross_premium_ksh"] == bs["premium_due_ksh"] + bs["subsidy_due_ksh"]).all()
    assert (bs["subsidy_due_ksh"] == bs["premium_due_ksh"]).all()


def test_name_only_payments_need_an_unmistakable_name(data):
    index = rec.MemberIndex(data.members)
    m = data.members.set_index("member_id")
    full = m.loc["MBR-1100", "full_name"].upper()   # Esther Nekesa Wanyama
    assert rec.match_row("SHAMBA", "254700000011", full, index)[:2] == ("MBR-1100", rec.MEMBER_NAME)
    # two of her names are exactly another member's full name: a person decides
    assert rec.match_row("SHAMBA", "254700000011", "NEKESA WANYAMA", index)[1] == rec.AMBIGUOUS
    # one letter off is never credited on a name alone
    assert rec.match_row("SHAMBA", "254700000011", full.replace("NEKESA", "WEKESA"), index)[0] is None


def test_blank_cells_from_a_csv_export(tmp_path):
    paths = sg.write_csvs(out_dir=tmp_path)
    members = pd.read_csv(paths[0], dtype={"national_id": str})
    statement = pd.read_csv(paths[1])
    assert members["spouse_name"].isna().any()  # blank cells come back as NaN
    result = rec.reconcile(statement, members)
    assert rec.accuracy(result, pd.read_csv(paths[2]))["wrong_member"] == 0


def test_ward_not_offered_owes_no_premium():
    premiums = {"njoro": 5_100.0, "imenti_north": 6_780.0, "kangundo": 5_880.0, "kimilili": 5_940.0}  # no bureti
    data = sg.generate_all(premium_by_ward={**premiums, "bureti": 10_740.0})
    result = rec.reconcile(data.statement, data.members, premiums)
    m = result.members
    bureti = m[m["ward"] == "bureti"]
    assert len(bureti) > 0
    assert (bureti["policy_status"] == rec.NOT_OFFERED).all()
    assert bureti["to_premium"].sum() == 0
    assert (m.loc[m["ward"] != "bureti", "policy_status"] != rec.NOT_OFFERED).all()
    assert "Bureti" not in set(rec.bordereau(m, WARDS)["ward"])
    assert "bureti" not in set(rec.claim_split(m, list(WARDS))["ward"])


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


def test_round_two_reference_cases(data):
    index = rec.MemberIndex(data.members)
    m = data.members.set_index("member_id")
    unknown = "254700000001"
    for two in ("MBR1001 MBR1002", "MBR-1001 & MBR-1002", "MBR-1001/1002"):
        assert rec.match_row(two, unknown, "", index)[1] == rec.AMBIGUOUS, two
    # a bare number that is the amount is never a member number
    assert rec.match_row("1200", unknown, "UPENDO AGROVET", index, 1200)[0] is None
    # a bare number from an unknown payer with no other support goes to review
    assert rec.match_row("1042", unknown, "SOMEONE ELSE", index, 3600)[0] is None
    # the first MBR word that carries a number counts
    assert rec.match_row("MBR LOAN MBR-1042", unknown, m.loc["MBR-1042", "full_name"], index)[0] == "MBR-1042"
    # a member ID next to another member's national ID
    assert rec.match_row(f"MBR 1251 {m.loc['MBR-1001', 'national_id']}", unknown, "", index)[1] == rec.AMBIGUOUS
    assert rec.normalize_name("Ndung'u  Kamau.") == "NDUNGU KAMAU"


def test_reference_naming_someone_else_overrides_the_phone(data):
    index = rec.MemberIndex(data.members)
    member = data.members.iloc[0]
    other_surname = next(s for s in data.members["surname"].str.upper().str.replace("'", "")
                         if s not in index.words_of(member["member_id"]))
    assert rec.match_row(f"FOR {other_surname}", member["phone_254"], "", index)[1] == rec.AMBIGUOUS
    assert rec.match_row("SHAMBA", member["phone_254"], "", index)[:2] == (member["member_id"], rec.EXACT_PHONE)


def test_shared_phone_or_national_id_never_decides(data):
    members = data.members.copy()
    members.loc[1, "phone"] = members.loc[0, "phone"]
    members.loc[3, "national_id"] = members.loc[2, "national_id"]
    index = rec.MemberIndex(members)
    assert rec.match_row("", rec.normalize_phone(members.loc[0, "phone"]), "", index)[1] == rec.AMBIGUOUS
    assert rec.match_row(members.loc[2, "national_id"], "254700000001", "", index)[1] == rec.AMBIGUOUS


def test_receipt_duplicates_ignore_case_and_spaces(data):
    head = data.statement.head(20)
    tripled = pd.concat([head, head.assign(receipt_no=head["receipt_no"] + " "),
                         head.assign(receipt_no=head["receipt_no"].str.lower())], ignore_index=True)
    r = rec.reconcile(tripled, data.members)
    assert r.duplicates_caught == len(tripled) - head["receipt_no"].nunique()


def test_text_amounts_are_numbers(data):
    statement = data.statement.head(10).astype({"paid_in_ksh": str})
    statement.loc[0, "paid_in_ksh"] = "N/A"
    r = rec.reconcile(statement, data.members)
    assert r.members["paid_in_ksh"].dtype.kind == "f"
    assert (r.ledger["match_method"] == rec.BAD_AMOUNT).sum() == 1


def test_round_three_reference_cases(data):
    index = rec.MemberIndex(data.members)
    m = data.members.set_index("member_id")
    unknown = "254700000001"
    own_name = m.loc["MBR-1042", "full_name"].upper()
    for sep in (":", "#", "\u2013", "="):
        assert rec.match_row(f"MBR{sep}1042", unknown, own_name, index)[0] == "MBR-1042", sep
    assert rec.match_row("MBR-1001/02", unknown, "", index)[1] == rec.AMBIGUOUS
    # a number equal to the amount is the amount: the member's own phone still decides
    phone = m.loc["MBR-1042", "phone_254"]
    assert rec.match_row("1200", phone, "", index, 1200)[:2] == ("MBR-1042", rec.EXACT_PHONE)
    assert rec.match_row("MBR-1042 1200", phone, "", index, 1200)[0] == "MBR-1042"
    # the payer's own first name in the reference is not someone else
    payer = "PETER " + m.loc["MBR-1042", "surname"].upper().replace("'", "")
    assert rec.match_row("MBR1042 FROM PETER", unknown, payer, index)[1] != rec.AMBIGUOUS or \
        rec._name_points_elsewhere(rec.normalize_name(payer), "MBR-1042", index)


def test_transposed_ids_never_credit_the_wrong_member(data):
    index = rec.MemberIndex(data.members)
    m = data.members.set_index("member_id")
    for mid in m.index:
        digits = mid.split("-")[1]
        swapped = digits[0] + digits[2] + digits[1] + digits[3]
        if swapped == digits or f"MBR-{swapped}" not in m.index:
            continue
        payer = " ".join(m.loc[mid, "full_name"].upper().split()[-2:])
        assert rec.match_row(f"MBR {swapped}", "254700000009", payer, index)[0] in (None, mid)


def test_formatted_amounts_and_receiptless_reexports(data):
    statement = data.statement.head(10).copy().astype({"paid_in_ksh": object})
    statement.loc[0, "paid_in_ksh"] = "5,160.00"
    statement.loc[1, "paid_in_ksh"] = "KES 5,160"
    statement.loc[2, "paid_in_ksh"] = "KSh 3,600"
    cleaned = rec.clean_statement(statement)
    assert list(cleaned["paid_in_ksh"].head(3)) == [5160.0, 5160.0, 3600.0]
    again = data.statement.head(10).assign(receipt_no=None)
    r = rec.reconcile(pd.concat([data.statement.head(10), again], ignore_index=True), data.members)
    assert r.duplicates_caught >= 10


def test_round_four_reference_cases(data):
    index = rec.MemberIndex(data.members)
    m = data.members.set_index("member_id")
    unknown = "254700000999"
    # MBR before a phone or national ID number is not a member number
    for ref in ("MBR 0712345678", "MBR 23456789", "ACC NBR 0712345678"):
        assert rec.match_row(ref, unknown, "", index, 3600.0)[0] is None, ref
    # a reference carrying another member's registered phone is not credited to the payer's phone
    other = m.loc["MBR-1010", "phone_254"]
    assert rec.match_row("0" + other[3:], m.loc["MBR-1042", "phone_254"], "", index, 3600.0)[1] == rec.AMBIGUOUS
    # an MBR ID equal to the amount still names that member
    assert rec.match_row("MBR1001", other, "", index, 1001.0)[1] == rec.AMBIGUOUS
    # joint references in other spellings
    for ref in ("MRB-1001/02", "MBR-1001 NA 02", "MBR1001-02", "MBR-1001 / MBR-1O02"):
        assert rec.match_row(ref, unknown, "", index, 7200.0)[1] == rec.AMBIGUOUS, ref
    # an amount or a year after the ID is not a second member
    own = m.loc["MBR-1042"]
    for ref, amount in (("MBR-1042, 5160", 5160.0), ("MBR-1042/2026", 5160.0)):
        assert rec.match_row(ref, own["phone_254"], own["full_name"], index, amount)[0] == "MBR-1042", ref


def test_own_phone_and_reference_always_credit(data):
    index = rec.MemberIndex(data.members)
    for row in data.members.itertuples():
        digits = row.member_id.split("-")[1]
        assert rec.match_row(f"MBR {digits}", row.phone_254, row.full_name, index, 3600.0)[0] == row.member_id


def test_far_transpositions_never_credit_the_wrong_member(data):
    index = rec.MemberIndex(data.members)
    m = data.members.set_index("member_id")
    for mid in m.index:
        d = mid.split("-")[1]
        for swapped in {d[0] + d[3] + d[2] + d[1], d[0] + d[2] + d[3] + d[1], d[2] + d[1] + d[0] + d[3]}:
            if swapped == d or f"MBR-{swapped}" not in m.index:
                continue
            payer = " ".join(m.loc[mid, "full_name"].upper().split()[-2:])
            assert rec.match_row(f"MBR {swapped}", "254700000009", payer, index, 3600.0)[0] in (None, mid)


def test_receiptless_copy_is_held_in_either_order(data):
    first = data.statement.head(10)
    copy = first.assign(receipt_no=None)
    for frame in (pd.concat([first, copy]), pd.concat([copy, first])):
        r = rec.reconcile(frame.reset_index(drop=True), data.members, include_checkoff=False)
        assert r.duplicates_caught == 10


@pytest.mark.parametrize("text,expected", [
    ("5,160.00", 5160.0), ("KES 5,160", 5160.0), ("Ksh5,160", 5160.0), ("KSH5160", 5160.0), ("kes5160", 5160.0),
    ("5,160/=", 5160.0), ("5.160,00", 5160.0), ("5160.", 5160.0), ("Sh 3,600", 3600.0),
])
def test_amount_formats(text, expected):
    assert rec._to_amount(text) == expected


@pytest.mark.parametrize("text", ["5.160", "1,0000", "(5,160.00)", "N/A", ""])
def test_ambiguous_amounts_go_to_a_person(text):
    assert np.isnan(rec._to_amount(text))


def test_round_five_reference_cases(data):
    index = rec.MemberIndex(data.members)
    m = data.members.set_index("member_id")
    unknown = "254700000999"
    own = m.loc["MBR-1042"]
    # an exact ID one slip from the paying member goes to a person; a far-off member's ID is a payment for them
    assert rec.match_row("MBR-1043", own["phone_254"], own["full_name"], index, 3600.0)[1] == rec.AMBIGUOUS
    assert rec.match_row("MBR-1024", own["phone_254"], own["full_name"], index, 3600.0)[1] == rec.AMBIGUOUS
    far = m.index[-1]
    assert rec.match_row(far, own["phone_254"], own["full_name"], index, 3600.0) == (far, rec.EXACT_ID, 100.0)
    # months, years and instalments after the ID are not a second member
    for ref in ("MBR-1042-10", "MBR-1042/11", "MBR-1042/26", "MBR-1042-1", "MBR-1042/2026"):
        assert rec.match_row(ref, own["phone_254"], own["full_name"], index, 3600.0)[0] == "MBR-1042", ref
    # joint references in still more spellings
    for ref in ("MBR 1001 ; 02", "MBR1001 n 02", "MBR-1I01/02", "MBR-1041/2"):
        assert rec.match_row(ref, unknown, "", index, 7200.0)[1] == rec.AMBIGUOUS, ref
    assert rec.match_row("1001/02", m.loc["MBR-1001", "phone_254"], "", index, 7200.0)[1] == rec.AMBIGUOUS


def test_exact_ids_never_credit_a_one_slip_neighbour(data):
    index = rec.MemberIndex(data.members)
    m = data.members.set_index("member_id")
    for mid in m.index:
        d = mid.split("-")[1]
        for i in range(1, 4):
            for digit in "0123456789":
                typed = f"MBR-{d[:i]}{digit}{d[i + 1:]}"
                if typed == mid or typed not in m.index:
                    continue
                got = rec.match_row(typed, m.loc[mid, "phone_254"], m.loc[mid, "full_name"], index, 3600.0)[0]
                assert got in (None, mid), (typed, mid)


@pytest.mark.parametrize("text,expected", [("5 160", 5160.0), ("KSh 5 160.00", 5160.0), ("5160 KES", 5160.0)])
def test_space_grouped_amounts(text, expected):
    assert rec._to_amount(text) == expected


def test_badly_grouped_spaces_go_to_a_person():
    assert np.isnan(rec._to_amount("1 0000"))


def test_round_six_reference_cases(data):
    index = rec.MemberIndex(data.members)
    m = data.members.set_index("member_id")
    unknown = "254700000999"
    # an exact ID a slip from the member whose two names the payer uses
    for mid in m.index[:60]:
        two = " ".join(m.loc[mid, "full_name"].split()[-2:])
        d = mid.split("-")[1]
        for typed in (f"MBR-{d[:3]}{(int(d[3]) + 1) % 10}", f"MBR-{d[:2]}{(int(d[2]) + 1) % 10}{d[3]}"):
            if typed in m.index and typed != mid:
                assert rec.match_row(typed, unknown, two, index, 3600.0)[0] in (None, mid), (typed, mid)
    # "&", "NA" and "AND" always join two members, counting up or down
    for ref in ("MBR-1042 & 41", "MBR 1042 NA 41", "MBR1042 AND 43", "MBR1042 & O3"):
        assert rec.match_row(ref, unknown, "", index, 7200.0)[1] == rec.AMBIGUOUS, ref
    # a name after the ID is not a second member
    assert rec.match_row("MBR-1042 & OTIENO", m.loc["MBR-1042", "phone_254"], "", index, 3600.0)[0] == "MBR-1042"


def test_review_reasons_are_specific(data):
    index = rec.MemberIndex(data.members)
    m = data.members.set_index("member_id")
    own = m.loc["MBR-1042"]
    assert "one keying slip" in rec.review_reason("MBR-1043", own["phone_254"], own["full_name"], index, 3600.0)
    assert "names two members" in rec.review_reason("MBR-1001/02", "", "", index, 7200.0)
    assert "came from MBR-1008's phone" in rec.review_reason("MBR 1001", m.loc["MBR-1008", "phone_254"], "", index)
    assert "several members" in rec.review_reason("MBR-104", "", "", index)


def test_round_seven_reasons_and_comma_suffixes(data):
    index = rec.MemberIndex(data.members)
    m = data.members.set_index("member_id")
    unknown = "254700000999"
    reason = rec.review_reason("MBR 1093", unknown, "Esther Nekesa Wanyama", index, 3600.0)
    assert "is exactly MBR-1100's" in reason and "close" not in reason
    assert "fits MBR-1003, whose number is similar" in rec.review_reason("MBR 1014", unknown, "Mugo Onyango", index)
    own = m.loc["MBR-1042"]
    for ref in ("MBR-1042, 10", "MBR-1042; 26"):  # a month or a year after a comma is not a second member
        assert rec.match_row(ref, own["phone_254"], own["full_name"], index, 3600.0)[0] == "MBR-1042", ref
    assert rec.match_row("MBR-1041, 2", unknown, "", index, 7200.0)[1] == rec.AMBIGUOUS  # counting up: two members
