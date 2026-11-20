"""ShambaRecon: match M-Pesa paybill rows to SACCO members, allocate every shilling by waterfall, and build the
underwriter bordereau and the claim-split settlement.

Matching runs in a fixed order and stops at the first rule that finds exactly one member:
  0. Duplicate receipt number         -> held, never credited twice
  1. Exact member ID, then exact phone (deterministic)
  2. National ID in the reference     (deterministic)
  3. Fuzzy reference (RapidFuzz WRatio >= 82 on a cleaned reference)
  4. Spouse name match (payer name against the member's recorded spouse, surname hint as tie-break)
  5. Member name match (payer name against member names, stricter threshold)
  otherwise                           -> suspense, for a person to review

Allocation waterfall, per member, in time order:
  Priority 1  seasonal premium for the member's ward (zone pricing): ACTIVE when complete, GRACE_PERIOD from 50%
  Priority 2  overdue SACCO loan interest
  Priority 3  loan principal, then member savings
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass

import numpy as np
import pandas as pd
from rapidfuzz import fuzz, process

FUZZY_THRESHOLD = 82
NAME_THRESHOLD = 90  # payer name alone is weaker evidence than a reference, so the bar is higher
PREMIUM_TARGET = 3_600.0
GRACE_SHARE = 0.5

EXACT_ID = "Exact ID"
EXACT_PHONE = "Exact Phone"
NATIONAL_ID = "National ID Reference"
FUZZY_REF = "Fuzzy Reference"
SPOUSE = "Spouse Name Match"
MEMBER_NAME = "Member Name Match"
CHECKOFF = "Milk Check-off"
DUPLICATE = "Duplicate (held)"
AMBIGUOUS = "Ambiguous (review)"
UNMATCHED = "Unmatched (suspense)"
SUSPENSE_METHODS = (AMBIGUOUS, UNMATCHED)

ACTIVE, GRACE, PENDING = "ACTIVE", "GRACE_PERIOD", "PENDING"
NOT_OFFERED = "NOT_OFFERED"  # the member's ward is not sold this product, so nothing goes to premium


# ------------------------------------------------------------------------------------------ cleaning

def normalize_phone(raw) -> str:
    """Any Kenyan mobile format to 254XXXXXXXXX; '' when it is not one."""
    digits = re.sub(r"\D", "", str(raw or ""))
    if len(digits) == 10 and digits.startswith("0"):
        return "254" + digits[1:]
    if len(digits) == 9 and digits[0] in "71":
        return "254" + digits
    if len(digits) == 12 and digits.startswith("254"):
        return digits
    return ""


def mask_phone(phone254: str) -> str:
    return f"{phone254[:6]}***{phone254[-3:]}" if len(phone254) == 12 else "***"


def mask_id(national_id: str) -> str:
    return f"****{str(national_id)[-3:]}" if national_id else ""


def canonical_ref(raw) -> str:
    """Upper-case letters and digits only, with common keying slips repaired (MRB -> MBR, O -> 0 in numbers)."""
    ref = re.sub(r"[^A-Z0-9]", "", str(raw or "").upper())
    ref = re.sub(r"^(MRB|BMR|MBRR|NBR)", "MBR", ref)
    match = re.match(r"^(.*?MBR)([0-9OIL]{4})(.*)$", ref)
    if match:
        digits = match.group(2).replace("O", "0").replace("I", "1").replace("L", "1")
        ref = "MBR" + digits + match.group(3)
    return ref


def split_other_party(info) -> tuple[str, str]:
    """'254712345678 - JANE WANJIKU' -> ('254712345678', 'JANE WANJIKU')."""
    phone, _, name = str(info or "").partition(" - ")
    return normalize_phone(phone), name.strip()


# ------------------------------------------------------------------------------------------- matching

@dataclass
class MemberIndex:
    members: pd.DataFrame

    def __post_init__(self):
        m = self.members
        self.by_id = {mid.upper(): mid for mid in m["member_id"]}
        self.id_choices = {mid.replace("-", "").upper(): mid for mid in m["member_id"]}
        self.by_phone = {normalize_phone(p): mid for p, mid in zip(m["phone"], m["member_id"]) if normalize_phone(p)}
        self.by_national_id = {str(n).split(".")[0]: mid for n, mid in zip(m["national_id"], m["member_id"])
                               if pd.notna(n)}
        self.names = {mid: str(name).upper() for mid, name in zip(m["member_id"], m["full_name"])}
        self.spouses = {mid: s.upper() for mid, s in zip(m["member_id"], m["spouse_name"].fillna(""))
                        if isinstance(s, str) and s.strip()}
        self.surnames = {mid: s.upper().replace("'", "") for mid, s in zip(m["member_id"], m["surname"])}


def _surname_support(ref: str, member_id: str, index: MemberIndex) -> float:
    tokens = [t for t in re.split(r"[^A-Z]+", str(ref).upper()) if len(t) >= 3]
    surname = index.surnames[member_id]
    return max((fuzz.partial_ratio(t, surname) for t in tokens), default=0.0)


def _same_words(payer: str, name: str) -> bool:
    return bool(payer) and bool(name) and set(payer.split()) == set(name.split())


def _settle_tie(candidates: list[tuple[str, str]], payer: str, ref: str, index: MemberIndex):
    """Pick one (member_id, record name) from equally close candidates, or None for a person to review.

    Only strong evidence settles a tie, because a wrong credit is worse than a short review queue: the payer's
    name has exactly the same words as one candidate's record (member or spouse), or the reference names exactly
    one candidate's surname. A partial name ("STEPHEN OWINO" against "STEPHEN MWANGI OWINO") is not enough when
    ten member IDs fit the reference equally well.
    """
    same = {(mid, name) for mid, name in candidates if _same_words(payer, name)}
    holders = {mid for mid, name in candidates if payer and set(payer.split()) <= set(name.split())}
    if len({mid for mid, _ in same}) == 1 and holders == {next(iter(same))[0]}:
        return next(iter(same))
    hinted = {mid for mid, _ in candidates if _surname_support(ref, mid, index) >= 85}
    if len(hinted) == 1:
        mid = next(iter(hinted))
        return mid, next(name for m, name in candidates if m == mid)
    return None


def match_row(ref, phone: str, payer: str, index: MemberIndex) -> tuple[str | None, str, float]:
    """Return (member_id, method, confidence 0-100) for one statement row."""
    raw = str(ref or "").strip().upper()
    if raw in index.by_id:
        return index.by_id[raw], EXACT_ID, 100.0
    if phone and phone in index.by_phone:
        return index.by_phone[phone], EXACT_PHONE, 100.0

    for digits in re.findall(r"\d{7,8}", raw):
        if digits in index.by_national_id:
            return index.by_national_id[digits], NATIONAL_ID, 100.0

    cref = canonical_ref(raw)
    if len(cref) >= 4 and any(ch.isdigit() for ch in cref):
        hits = process.extract(cref, list(index.id_choices), scorer=fuzz.WRatio, limit=None,
                               score_cutoff=FUZZY_THRESHOLD)
        if hits:
            best_score = hits[0][1]
            tied = [index.id_choices[h[0]] for h in hits if best_score - h[1] < 2]
            if len(tied) == 1:
                return tied[0], FUZZY_REF, round(best_score, 1)
            # Several IDs are equally close (a truncated MBR-104 fits ten): only a full-name match settles it.
            candidates = [(mid, index.names[mid]) for mid in tied] + \
                         [(mid, index.spouses[mid]) for mid in tied if mid in index.spouses]
            chosen = _settle_tie(candidates, payer, raw, index)
            return (chosen[0], FUZZY_REF, round(best_score, 1)) if chosen else (None, AMBIGUOUS, round(best_score, 1))

    if payer:
        # Name only: no ID and no registered phone, so the name must point at one person without doubt. Member and
        # spouse names are checked together. A payment is credited only when the payer's name has exactly the
        # words of one record AND no other member or spouse carries all of those words ("NEKESA WANYAMA" is one
        # member's full name but also part of "ESTHER NEKESA WANYAMA", so it goes to review). A close but not
        # exact name ("NEKESA" against "WEKESA") is a person's call, never the matcher's.
        words = set(payer.split())
        records = [(mid, name, MEMBER_NAME) for mid, name in index.names.items()] + \
                  [(mid, name, SPOUSE) for mid, name in index.spouses.items()]
        same = [(mid, kind) for mid, name, kind in records if _same_words(payer, name)]
        holders = {mid for mid, name, _ in records if words <= set(name.split())}
        if len({mid for mid, _ in same}) == 1 and holders == {same[0][0]}:
            return same[0][0], same[0][1], 100.0
        near = process.extractOne(payer, index.names, scorer=fuzz.token_sort_ratio, score_cutoff=FUZZY_THRESHOLD)
        near_spouse = process.extractOne(payer, index.spouses, scorer=fuzz.token_sort_ratio,
                                         score_cutoff=FUZZY_THRESHOLD)
        best = max((h[1] for h in (near, near_spouse) if h), default=0.0)
        if same or best:
            return None, AMBIGUOUS, round(max(best, 100.0 if same else 0.0), 1)
    return None, UNMATCHED, 0.0


def naive_exact_match(statement: pd.DataFrame, members: pd.DataFrame) -> pd.Series:
    """What a clerk's exact lookup does: the account reference must equal a member ID character for character."""
    ids = set(members["member_id"])
    return statement["account_reference"].fillna("").str.strip().isin(ids)


def match_statement(statement: pd.DataFrame, members: pd.DataFrame) -> pd.DataFrame:
    index = MemberIndex(members)
    seen: set[str] = set()
    out = []
    for row in statement.itertuples(index=False):
        phone, payer = split_other_party(row.other_party_info)
        if row.receipt_no in seen:
            member_id, method, confidence = None, DUPLICATE, 100.0
        else:
            seen.add(row.receipt_no)
            member_id, method, confidence = match_row(row.account_reference, phone, payer, index)
        out.append({"member_id": member_id, "match_method": method, "confidence": confidence,
                    "payer_phone": phone, "payer_name": payer})
    return pd.concat([statement.reset_index(drop=True), pd.DataFrame(out)], axis=1)


# ----------------------------------------------------------------------------------------- waterfall

def premium_due(members: pd.DataFrame, premium_target) -> pd.Series:
    """Premium each member owes: one figure for everyone, or a {ward: KSh} map for zone pricing.

    A ward missing from the map is not offered the product: its members owe no premium.
    """
    if isinstance(premium_target, dict):
        return members["ward"].map(premium_target).fillna(0.0).astype(float)
    return pd.Series(float(premium_target), index=members.index)


def checkoff_rows(members: pd.DataFrame, posted: str = "2026-10-31 23:00:00") -> pd.DataFrame:
    """Milk weighbridge check-off: already tied to a member ID by the SACCO's system, so no matching needed."""
    dairy = members[members["milk_checkoff_month"] > 0]
    return pd.DataFrame({
        "receipt_no": "CHK-" + dairy["member_id"].str.replace("MBR-", "", regex=False),
        "completion_time": posted, "details": "Milk check-off (October)", "transaction_status": "Posted",
        "paid_in_ksh": dairy["milk_checkoff_month"].astype(float), "account_reference": dairy["member_id"],
        "other_party_info": "Weighbridge check-off", "member_id": dairy["member_id"], "match_method": CHECKOFF,
        "confidence": 100.0, "payer_phone": "", "payer_name": "",
    })


def allocate_waterfall(ledger: pd.DataFrame, members: pd.DataFrame, premium_target=PREMIUM_TARGET):
    """Split each matched shilling into premium, overdue interest, principal and savings. Returns (ledger, members).

    ``premium_target`` is one KSh figure for every member, or a {ward: KSh} map when premiums are priced per ward.
    """
    ledger = ledger.sort_values(["completion_time", "receipt_no"], kind="stable").reset_index(drop=True)
    due = premium_due(members, premium_target)
    owed = {mid: {"premium": d, "interest": float(i), "principal": float(p)}
            for mid, d, i, p in zip(members["member_id"], due, members["overdue_interest"], members["loan_balance"])}
    alloc = np.zeros((len(ledger), 4))
    for i, (mid, method, amount) in enumerate(zip(ledger["member_id"], ledger["match_method"],
                                                  ledger["paid_in_ksh"])):
        if mid is None or (isinstance(mid, float) and np.isnan(mid)) or method in SUSPENSE_METHODS + (DUPLICATE,):
            continue
        left = float(amount)
        bucket = owed[mid]
        for j, key in enumerate(("premium", "interest", "principal")):
            take = min(left, bucket[key])
            bucket[key] -= take
            alloc[i, j] = take
            left -= take
        alloc[i, 3] = left  # savings
    ledger[["to_premium", "to_interest", "to_principal", "to_savings"]] = alloc

    allocated = ledger[ledger["member_id"].notna() & ~ledger["match_method"].isin(SUSPENSE_METHODS + (DUPLICATE,))]
    sums = allocated.groupby("member_id")[["paid_in_ksh", "to_premium", "to_interest", "to_principal",
                                           "to_savings"]].sum()
    receipts = allocated[allocated["match_method"] != CHECKOFF].groupby("member_id")["receipt_no"].agg(";".join)
    summary = members.set_index("member_id").join(sums).join(receipts.rename("receipts")).reset_index()
    for col in ("paid_in_ksh", "to_premium", "to_interest", "to_principal", "to_savings"):
        summary[col] = summary[col].fillna(0.0)
    summary["receipts"] = summary["receipts"].fillna("")
    summary["premium_due"] = premium_due(summary, premium_target).to_numpy()
    summary["policy_status"] = np.select(
        [summary["premium_due"] <= 0,
         summary["to_premium"] >= summary["premium_due"] - 1e-6,
         summary["to_premium"] >= GRACE_SHARE * summary["premium_due"]],
        [NOT_OFFERED, ACTIVE, GRACE], PENDING)
    summary["interest_after"] = summary["overdue_interest"] - summary["to_interest"]
    summary["loan_after"] = summary["loan_balance"] - summary["to_principal"]
    summary["savings_after"] = summary["savings_balance"] + summary["to_savings"]
    return ledger, summary


# --------------------------------------------------------------------------------------- the full run

@dataclass
class ReconResult:
    ledger: pd.DataFrame        # every statement row plus check-off, with method, confidence and waterfall split
    members: pd.DataFrame       # one row per member with totals and policy status
    before_suspense_rows: float  # share of M-Pesa rows a clerk's exact lookup cannot place
    before_suspense_value: float
    after_suspense_rows: float
    after_suspense_value: float
    duplicates_caught: int
    duplicate_value: float
    seconds: float

    @property
    def mpesa(self) -> pd.DataFrame:
        return self.ledger[self.ledger["match_method"] != CHECKOFF]


def reconcile(statement: pd.DataFrame, members: pd.DataFrame, premium_target=PREMIUM_TARGET,
              include_checkoff: bool = True) -> ReconResult:
    started = time.perf_counter()
    matched = match_statement(statement, members)
    naive = naive_exact_match(statement, members)
    ledger = pd.concat([matched, checkoff_rows(members)], ignore_index=True) if include_checkoff else matched
    ledger, summary = allocate_waterfall(ledger, members, premium_target)
    elapsed = time.perf_counter() - started

    total_rows = len(statement)
    total_value = statement["paid_in_ksh"].sum()
    suspense = matched["match_method"].isin(SUSPENSE_METHODS)
    dupes = matched["match_method"] == DUPLICATE
    return ReconResult(
        ledger=ledger, members=summary,
        before_suspense_rows=float((~naive).sum() / total_rows),
        before_suspense_value=float(statement.loc[~naive, "paid_in_ksh"].sum() / total_value),
        after_suspense_rows=float(suspense.sum() / total_rows),
        after_suspense_value=float(matched.loc[suspense, "paid_in_ksh"].sum() / total_value),
        duplicates_caught=int(dupes.sum()), duplicate_value=float(matched.loc[dupes, "paid_in_ksh"].sum()),
        seconds=elapsed,
    )


def accuracy(result: ReconResult, truth: pd.DataFrame) -> dict:
    """Score the matcher against the generator's ground truth (synthetic data only)."""
    rows = result.mpesa.merge(truth[["receipt_no", "row", "truth_member_id", "scenario"]].drop_duplicates("receipt_no"),
                              on="receipt_no", how="left")
    credited = rows[rows["member_id"].notna() & (rows["match_method"] != DUPLICATE)]
    correct = (credited["member_id"] == credited["truth_member_id"]).sum()
    should_credit = rows[(rows["scenario"] != "not_a_member") & (rows["match_method"] != DUPLICATE)]
    return {
        "credited": int(len(credited)), "correct": int(correct),
        "precision": float(correct / len(credited)) if len(credited) else 0.0,
        "recall": float(correct / len(should_credit)) if len(should_credit) else 0.0,
        "wrong_member": int(len(credited) - correct),
    }


# ------------------------------------------------------------------------------------- outputs

def bordereau(summary: pd.DataFrame, wards: dict, season_label: str = "Long rains 2027",
              sum_insured: float = 60_000.0, gross_premium: dict | None = None) -> pd.DataFrame:
    """Premium bordereau for the underwriter: one row per bound (ACTIVE) policy, identifiers masked.

    ``gross_premium`` ({ward: KSh}) is the full premium; when a subsidy pays part of it, the farmer's share is what
    the SACCO collected (``premium_due``) and the rest is shown as subsidy due.
    """
    active = summary[summary["policy_status"] == ACTIVE].sort_values("member_id")
    gross = active["ward"].map(gross_premium).astype(float) if gross_premium else active["premium_due"]
    return pd.DataFrame({
        "bordereau_period": season_label,
        "policy_number": "SS360-" + active["member_id"].str.replace("MBR-", "", regex=False),
        "member_id": active["member_id"], "insured_name": active["full_name"],
        "national_id_masked": active["national_id"].map(mask_id),
        "phone_masked": active["phone"].map(lambda p: mask_phone(normalize_phone(p))),
        "ward": active["ward"].map(lambda k: wards[k].name), "county": active["ward"].map(lambda k: wards[k].county),
        "cover": "Mixed farm: crop inputs, fodder gap, vet and health",
        "sum_insured_ksh": sum_insured, "gross_premium_ksh": gross, "premium_due_ksh": active["premium_due"],
        "premium_received_ksh": active["to_premium"], "subsidy_due_ksh": gross - active["premium_due"],
        "premium_to_remit_ksh": active["to_premium"],
        "policy_status": active["policy_status"], "payment_receipts": active["receipts"],
        "insurer": "Partner insurer (to be named)",
    })


def claim_split(summary: pd.DataFrame, wards_affected: list[str], payout_per_member: float = 25_000.0,
                farmer_share: float = 0.70) -> pd.DataFrame:
    """Split a triggered payout: the farmer's share by M-Pesa B2C, the SACCO share to the member's loan.

    The SACCO share never exceeds what the member owes (overdue interest plus principal after the waterfall);
    anything above that goes to the farmer. Only ACTIVE policies are paid.
    """
    eligible = summary[(summary["policy_status"] == ACTIVE) & summary["ward"].isin(wards_affected)].copy()
    owed = eligible["interest_after"] + eligible["loan_after"]
    sacco = np.minimum((1 - farmer_share) * payout_per_member, owed)
    eligible["payout_ksh"] = payout_per_member
    eligible["to_sacco_loan_ksh"] = sacco.round(2)
    eligible["to_farmer_b2c_ksh"] = payout_per_member - eligible["to_sacco_loan_ksh"]
    eligible["loan_owed_before_ksh"] = owed
    eligible["loan_owed_after_ksh"] = owed - eligible["to_sacco_loan_ksh"]
    eligible["phone_masked"] = eligible["phone"].map(lambda p: mask_phone(normalize_phone(p)))
    return eligible[["member_id", "full_name", "ward", "phone_masked", "payout_ksh", "to_farmer_b2c_ksh",
                     "to_sacco_loan_ksh", "loan_owed_before_ksh", "loan_owed_after_ksh"]].reset_index(drop=True)
