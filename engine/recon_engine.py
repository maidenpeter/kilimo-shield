"""ShambaRecon: match M-Pesa paybill rows to SACCO members, allocate every shilling by waterfall, and build the
underwriter bordereau and the claim-split settlement.

Matching weighs every piece of evidence on a row, and a wrong credit is treated as worse than a review:
  - a repeated receipt number (ignoring case and spaces) is held, never credited twice;
  - a blank, zero or negative amount is held for review;
  - an exact member ID, or a national ID standing alone, is the payer's instruction;
  - a mistyped ID (RapidFuzz WRatio >= 82 on a cleaned reference) counts when it points at one member and nothing on
    the row points at someone else; equally close IDs are settled only by exact names;
  - a registered phone decides when there is no usable reference;
  - a name alone credits only a unique, exact, three-word record;
  - anything that disagrees (two members in one reference, a shared phone, a reference naming someone else) goes to
    Ambiguous (review); anything with no evidence stays Unmatched (suspense).

Allocation waterfall, per member, in time order:
  Priority 1  seasonal premium for the member's ward (zone pricing): ACTIVE when complete, GRACE_PERIOD from 50%
  Priority 2  overdue SACCO loan interest
  Priority 3  loan principal, then member savings
"""
from __future__ import annotations

import re
from itertools import permutations
import time
from dataclasses import dataclass

import numpy as np
import pandas as pd
from rapidfuzz import fuzz, process

FUZZY_THRESHOLD = 82
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
BAD_AMOUNT = "Bad amount (review)"
SUSPENSE_METHODS = (AMBIGUOUS, UNMATCHED, BAD_AMOUNT)

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


_LETTER_DIGIT = {"O": "0", "I": "1", "L": "1"}
_PREFIX = r"(?:MBRR|MBR|MRB|BMR|NBR)"
_ID_RUN = re.compile(_PREFIX + r"[^A-Z0-9]{0,3}([0-9OIL]+)")
# "MBR-1001/02", "MRB 1001 NA 1002", "MBR1001-02", "1001/02": one reference for two members. The second number is a
# whole member number or a one- or two-digit shorthand for the end of the first.
_JOINT = re.compile(r"(?:(" + _PREFIX + r")[^A-Z0-9]{0,3}|(?<![A-Z0-9]))(\d[\dOIL]{2,3})(?![\dOIL])\s*"
                    r"(/|&|\+|,|;|-|\bAND\b|\bNA\b|\bN\b)\s*(?:" + _PREFIX + r"[^A-Z0-9]{0,3})?(O?\d[\dO]*)(?!\d)")
# Words in a reference that say what the money is for rather than who it is for.
REFERENCE_WORDS = {"FOR", "ACC", "ACCOUNT", "MILK", "PREMIUM", "SHAMBA", "LOAN", "FEES", "FEE", "PAYMENT", "PAY",
                   "INSURANCE", "DEPOSIT", "SAVINGS", "CHAMA", "TEST", "TERM", "SCHOOL", "MBR", "THE", "AND", "FULL",
                   "FROM", "BY"}


def _repair(run: str, after: str) -> str:
    """Digits of an ID run. O, I and L count as digits only inside the number or where it ends, never when they
    start the next word ("104OTIENO" is 104 followed by a name)."""
    digits = []
    for i, ch in enumerate(run):
        if ch.isdigit():
            digits.append(ch)
            continue
        nxt = run[i + 1] if i + 1 < len(run) else after
        if nxt.isdigit() or not nxt.isalpha():
            digits.append(_LETTER_DIGIT[ch])
        else:
            break
    return "".join(digits)


def reference_ids(raw) -> list[str]:
    """Every MBR-prefixed ID in a reference, repaired, in order: "MBR LOAN mbr-1O42" -> ["MBR1042"]."""
    text = str(raw or "").upper()
    ids = []
    for match in _ID_RUN.finditer(text):
        digits = _repair(match.group(1), text[match.end(1):match.end(1) + 1])
        if digits:
            ids.append("MBR" + digits)
    return ids


def canonical_ref(raw) -> str:
    """The member-ID part of a reference with keying slips repaired: "mbr 1O42-milk" -> "MBR1042".

    The first MBR word that carries a number counts ("MBR LOAN MBR-1042" -> "MBR1042"). A reference without one comes
    back as upper-case letters and digits only ("1042", "KAMAUMILK").
    """
    ids = reference_ids(raw)
    return ids[0] if ids else re.sub(r"[^A-Z0-9]", "", str(raw or "").upper())


def normalize_name(raw) -> str:
    """Upper case, letters and single spaces only: "Jane  Wanjiku-Kamau." -> "JANE WANJIKU KAMAU", "Ndung'u" ->
    "NDUNGU"."""
    text = re.sub(r"['\u2019`]", "", str(raw or "").upper())
    return " ".join(re.sub(r"[^A-Z ]", " ", text).split())


def split_other_party(info) -> tuple[str, str]:
    """'254712345678 - JANE WANJIKU' -> ('254712345678', 'JANE WANJIKU')."""
    phone, _, name = str(info or "").partition(" - ")
    return normalize_phone(phone), normalize_name(name)


# ------------------------------------------------------------------------------------------- matching

@dataclass
class MemberIndex:
    members: pd.DataFrame

    def __post_init__(self):
        m = self.members
        self.by_id = {mid.upper(): mid for mid in m["member_id"]}
        self.id_choices = {mid.replace("-", "").upper(): mid for mid in m["member_id"]}
        # A phone or national ID registered to more than one member identifies nobody on its own.
        self.phone_members: dict[str, set] = {}
        for p, mid in zip(m["phone"], m["member_id"]):
            if normalize_phone(p):
                self.phone_members.setdefault(normalize_phone(p), set()).add(mid)
        self.nid_members: dict[str, set] = {}
        for n, mid in zip(m["national_id"], m["member_id"]):
            if pd.notna(n) and str(n).strip():
                self.nid_members.setdefault(str(n).split(".")[0].strip(), set()).add(mid)
        self.names = {mid: normalize_name(name) for mid, name in zip(m["member_id"], m["full_name"])}
        self.spouses = {mid: normalize_name(s) for mid, s in zip(m["member_id"], m["spouse_name"].fillna(""))
                        if isinstance(s, str) and normalize_name(s)}
        self.surnames = {mid: normalize_name(s) for mid, s in zip(m["member_id"], m["surname"])}
        self.records = [(mid, name, MEMBER_NAME) for mid, name in self.names.items()] + \
                       [(mid, name, SPOUSE) for mid, name in self.spouses.items()]
        self.name_words = {word for _, name, _ in self.records for word in name.split()}
        self.id_lengths = {len(re.sub(r"\D", "", key)) for key in self.id_choices}

    def full_length(self, digits: str) -> bool:
        """A member number, or one missing its last digit (a truncated "MBR-104")."""
        return len(digits) in self.id_lengths or len(digits) + 1 in self.id_lengths

    def searchable(self, digits: str) -> bool:
        """Close enough in length to a member number to be a keying slip of one (a digit dropped or doubled). A phone
        or national ID number written after "MBR" is not."""
        return self.full_length(digits) or len(digits) - 1 in self.id_lengths

    def words_of(self, member_id: str) -> set:
        return set(self.names.get(member_id, "").split()) | set(self.spouses.get(member_id, "").split())


def _same_words(payer: str, name: str) -> bool:
    return bool(payer) and bool(name) and set(payer.split()) == set(name.split())


def _holders(payer: str, records) -> set:
    """Members whose own or spouse's name contains every word of the payer's name."""
    words = set(payer.split())
    return {mid for mid, name, *_ in records if words and words <= set(name.split())}


def _number(member_id: str) -> str:
    return re.sub(r"\D", "", member_id)


def _digit_gap(a: str, b: str) -> int:
    """How many digits differ between two member numbers of the same length (99 when the lengths differ)."""
    x, y = _number(a), _number(b)
    return sum(p != q for p, q in zip(x, y)) if len(x) == len(y) else 99


def _one_slip(a: str, b: str) -> bool:
    """Two member numbers one keying slip apart: one digit different, or two digits swapped."""
    x, y = _number(a), _number(b)
    diff = [i for i in range(len(x)) if len(x) == len(y) and x[i] != y[i]]
    return len(diff) == 1 or (len(diff) == 2 and x[diff[0]] == y[diff[1]] and x[diff[1]] == y[diff[0]])


def _name_points_elsewhere(payer: str, member_id: str, index: MemberIndex, near: set = frozenset(),
                           phone_agrees: bool = False) -> bool:
    """True when the payer's name points at another member than this one:
    - the payer's name has exactly the words of someone's record (member or spouse) and does not fit this member; or
    - two or more of the payer's names fit a member whose number is also close to the reference (in ``near``) but
      do not fit this member: "NJERI MWANGI" paying "MBR 1103" when Njeri Mwangi is MBR-1013 is a transposed ID; or
    - two or more of the payer's names fit one or two members only, one of them two digits or fewer from this one:
      "MUGO ONYANGO" paying "MBR 1014" when only MBR-1003 carries both names.
    The near cases apply even when the name also fits this member: "MUTHONI OTIENO" typing "MBR 1042" may be MBR-1402
    transposing digits or MBR-1042's spouse, and only a person can tell. They do not apply when the member's own
    registered phone agrees with the reference. A name that merely fits some member somewhere is too common to count
    against a reference."""
    holders = _holders(payer, index.records)
    if len(payer.split()) >= 2 and not phone_agrees:
        if holders & (set(near) - {member_id}):
            return True
        if 1 <= len(holders) <= 2 and member_id not in holders and any(_digit_gap(h, member_id) <= 2
                                                                         for h in holders):
            return True
    if member_id in holders:
        return False
    return any(_same_words(payer, name) for _, name, _ in index.records)


def _name_fits(payer: str, member_id: str, index: MemberIndex) -> bool:
    """At least two of the payer's names, all found in the member's or the spouse's record."""
    words = set(payer.split())
    return len(words) >= 2 and words <= index.words_of(member_id)


def _ref_names_someone_else(raw: str, member_id: str, index: MemberIndex, payer: str = "") -> bool:
    """True when the reference spells a name that is on the register but not in this member's or spouse's name. The
    payer's own names, and names after FROM or BY, do not count: "MBR1042 FROM PETER" says who paid, not whom for."""
    text = re.sub(r"\b(?:FROM|BY)\b(?:(?!\bFOR\b).)*", " ", normalize_name(raw))
    tokens = {tok for tok in re.split(r"[^A-Z]+", text) if len(tok) >= 3} - REFERENCE_WORDS
    tokens -= set(payer.split())
    return bool((tokens & index.name_words) - index.words_of(member_id))


def _name_owner(payer: str, index: MemberIndex):
    """(member_id, method) when a name ALONE identifies someone, else None.

    Three or more names, in the same order as one record, and nobody else (member or spouse) carries all of those
    words. Two names are too common, and reversed names can be different people.
    """
    if len(payer.split()) < 3:
        return None
    exact = [(mid, kind) for mid, name, kind in index.records if name == payer]
    if len({mid for mid, _ in exact}) == 1 and _holders(payer, index.records) == {exact[0][0]}:
        return exact[0]
    return None


def _settle_tie(tied: list[str], payer: str, ref: str, index: MemberIndex) -> str | None:
    """Pick one member from equally close reference candidates, or None for a person to review.

    Only exact evidence settles a tie: the payer's name has the same words as one candidate's (or their spouse's)
    record and no other candidate's record contains those words; or the reference spells exactly one candidate's
    surname and no other candidate carries that word in any name. "NEKESA" never stands in for "WEKESA".
    """
    candidates = [(mid, index.names[mid]) for mid in tied] + [(mid, index.spouses[mid]) for mid in tied
                                                               if mid in index.spouses]
    same = {mid for mid, name in candidates if _same_words(payer, name)}
    if len(same) == 1 and _holders(payer, candidates) == same:
        return next(iter(same))
    tokens = {tok for tok in re.split(r"[^A-Z]+", normalize_name(ref)) if len(tok) >= 3}
    hinted = {mid for mid in tied if index.surnames[mid] in tokens}
    carriers = {mid for mid, name in candidates if tokens & set(name.split())}
    if len(hinted) == 1 and carriers == hinted:
        return next(iter(hinted))
    return None


def _from_reference(raw: str, payer: str, index: MemberIndex):
    """(member_id or None, the tied candidates when none could be chosen, score, every member number close to the
    reference) from a mistyped reference."""
    cref = canonical_ref(raw)
    runs = [run for run in re.findall(r"\d+", cref) if index.searchable(run)]
    if len(cref) < 4 or not runs:
        return None, [], 0.0, set()
    hits = process.extract(cref, list(index.id_choices), scorer=fuzz.WRatio, limit=None, score_cutoff=FUZZY_THRESHOLD)
    if not hits:
        return None, [], 0.0, set()
    # Close member numbers, and every member number with the same digits in another order ("1310" for MBR-1013).
    near = {index.id_choices[h[0]] for h in hits}
    near |= {index.id_choices[f"MBR{p}"] for p in {"".join(p) for p in permutations(runs[0])}
             if f"MBR{p}" in index.id_choices} if len(runs[0]) <= 5 else set()
    best = round(hits[0][1], 1)
    tied = [index.id_choices[h[0]] for h in hits if hits[0][1] - h[1] < 2]
    if len(tied) == 1:
        return tied[0], [], best, near
    chosen = _settle_tie(tied, payer, raw, index)
    return (chosen, [], best, near) if chosen else (None, tied, best, near)


def _amount_digits(amount) -> str | None:
    try:
        value = float(amount)
    except (TypeError, ValueError):
        return None
    return str(int(value)) if np.isfinite(value) and value.is_integer() else None


def _slip_of_another(member_id: str, phone: str, payer: str, index: MemberIndex) -> bool:
    """True when a well-formed ID may be a slip of the member who paid: the paying phone is another member's, or the
    payer's full name is another member's alone, that member's number is one keying slip from the ID, unless the
    payer's name fits only the ID's member (or spouse), not the one who paid. "MBR-1043" sent from MBR-1042's phone is
    a slip or a payment for a neighbour, and only a person can tell. A payment for a member whose number is far off
    still decides."""
    phones = index.phone_members.get(phone, set()) if phone else set()
    if phones == {member_id}:
        return False  # the member's own registered phone and their own number: no slip
    others = set(phones) if len(phones) == 1 else set()
    owner = _name_owner(payer, index)
    if owner:
        others.add(owner[0])
    if len(payer.split()) >= 2:  # two names are enough when they fit the member a slip away ("MAKENA MURIUKI")
        others |= _holders(payer, index.records)
    fits_typed = _name_fits(payer, member_id, index)
    return any(o != member_id and _one_slip(o, member_id) and (not fits_typed or _name_fits(payer, o, index))
               for o in others)


def _drop_amount(raw: str, amount) -> str:
    """A bare number equal to the amount is the amount, not a member number ("1200" on a KSh 1,200 payment). A number
    written as an MBR ID stays: "MBR1001" on a KSh 1,001 payment still names MBR-1001."""
    digits = _amount_digits(amount)
    if not digits:
        return raw
    inside = [m.span(1) for m in _ID_RUN.finditer(raw)]
    return re.sub(rf"(?<!\d){digits}(?!\d)",
                  lambda m: m.group(0) if any(a <= m.start() < b for a, b in inside) else " ", raw).strip()


def _digits(text: str) -> str:
    return "".join(_LETTER_DIGIT.get(ch, ch) for ch in text)


def _is_joint(raw: str, index: MemberIndex) -> bool:
    """True when the reference names a second member after the first: "MBR-1001/02", "MRB 1001 NA 1002", "1001/02".

    "&", "AND", "NA", "+", "," and ";" always join two members ("MBR-1042 & 41"). "/" and "-" also write dates,
    years and instalments, so after them a shorthand counts only when it counts up from the first number by at most
    nine, the way members who joined together are numbered ("1001/02", "1041/2"): "MBR-1042-10" or "MBR-1042/26" is
    a month, a year or an instalment. A number that is not a member's ("MBR-1042/2026") is never a second member, and
    without MBR the first number must itself be a member's.
    """
    for m in _JOINT.finditer(raw):
        prefix, first, joiner, second = m.group(1), _digits(m.group(2)), m.group(3), _digits(m.group(4))
        if not prefix and f"MBR{first}" not in index.id_choices:
            continue
        if len(second) <= 2 < len(first):
            second = first[:len(first) - len(second)] + second
            if joiner in "/-" and not 0 < int(second) - int(first) <= 9:
                continue
        elif len(second) != len(first):
            continue
        if second != first and f"MBR{second}" in index.id_choices:
            return True
    return False


def match_row(ref, phone: str, payer: str, index: MemberIndex, amount=None) -> tuple[str | None, str, float]:
    """Return (member_id, method, confidence 0-100) for one statement row.

    The account reference is the payer's instruction, so an exact member ID or a national ID decides on its own.
    Anything weaker is weighed with the other evidence, and when the reference, the registered phone and the payer's
    name point at different members, a person decides: a wrong credit is worse than a short review queue.
    """
    raw = str(ref if isinstance(ref, str) else "" if ref is None or pd.isna(ref) else ref).strip().upper()
    payer = normalize_name(payer)
    if raw in index.by_id:
        member = index.by_id[raw]
        if _slip_of_another(member, phone, payer, index):
            return None, AMBIGUOUS, 100.0
        return member, EXACT_ID, 100.0
    raw = _drop_amount(raw, amount)
    if _is_joint(raw, index):
        return None, AMBIGUOUS, 100.0          # "MBR-1001/02": one payment for two members

    # Everything in the reference that names a member: MBR IDs, bare member numbers, national IDs, registered phones.
    prefixed = reference_ids(raw)
    named = {index.id_choices[i] for i in prefixed if i in index.id_choices}
    bare = {index.id_choices[f"MBR{d}"] for d in re.findall(r"(?<!\d)\d{4}(?!\d)", raw)
            if f"MBR{d}" in index.id_choices}
    nids = [index.nid_members[d] for d in re.findall(r"(?<!\d)\d{7,8}(?!\d)", raw) if d in index.nid_members]
    ref_phones = set().union(*(index.phone_members.get(normalize_phone(d), set())
                               for d in re.findall(r"(?<!\d)\d{9,12}(?!\d)", raw)))
    if len(named | bare | set().union(*nids) | ref_phones) > 1:
        return None, AMBIGUOUS, 100.0          # two members in one reference, or an ID shared by members
    if nids:
        member = next(iter(nids[0]))
        if _ref_names_someone_else(raw, member, index, payer):
            return None, AMBIGUOUS, 100.0
        return member, NATIONAL_ID, 100.0
    member, method, confidence = _weigh(raw, prefixed, phone, payer, index)
    if ref_phones and member not in ref_phones:
        # The reference carries a member's registered phone number: anyone else, or no one, is for a person to check.
        return None, AMBIGUOUS, 100.0
    return member, method, confidence


def _weigh(raw: str, prefixed: list[str], phone: str, payer: str, index: MemberIndex):
    """The reference, the registered phone and the payer's name, weighed together (see ``match_row``)."""
    phones = index.phone_members.get(phone, set()) if phone else set()
    phone_member = next(iter(phones)) if len(phones) == 1 else None
    ref_member, tied, score, near = _from_reference(raw, payer, index)
    if ref_member:
        # The member's own registered phone agreeing with the reference outweighs a name that also fits a member
        # with a close number.
        conflict = (phones and ref_member not in phones) \
            or _name_points_elsewhere(payer, ref_member, index, near, phone_agrees=phones == {ref_member}) \
            or _ref_names_someone_else(raw, ref_member, index, payer)
        if not any(index.full_length(i[3:]) for i in prefixed):
            # A bare number, or MBR with a digit too many, is weak evidence: the phone or the payer's name must agree.
            conflict = conflict or not (ref_member in phones or _name_fits(payer, ref_member, index))
        if conflict:
            return None, AMBIGUOUS, score
        return ref_member, FUZZY_REF, score
    if tied:
        both = set(tied) & phones
        if len(both) == 1:
            member = next(iter(both))
            if not _name_points_elsewhere(payer, member, index) and \
                    not _ref_names_someone_else(raw, member, index, payer):
                return member, EXACT_PHONE, 100.0
        return None, AMBIGUOUS, score
    if phones:
        if phone_member is None or _name_points_elsewhere(payer, phone_member, index) \
                or _ref_names_someone_else(raw, phone_member, index, payer):
            return None, AMBIGUOUS, 100.0
        return phone_member, EXACT_PHONE, 100.0
    if payer:
        owner = _name_owner(payer, index)
        if owner and not _ref_names_someone_else(raw, owner[0], index, payer):
            return owner[0], owner[1], 100.0
        near = [h[1] for h in (process.extractOne(payer, index.names, scorer=fuzz.token_sort_ratio,
                                                  score_cutoff=FUZZY_THRESHOLD),
                               process.extractOne(payer, index.spouses, scorer=fuzz.token_sort_ratio,
                                                  score_cutoff=FUZZY_THRESHOLD)) if h]
        if near or owner:
            return None, AMBIGUOUS, round(max(near or [100.0]), 1)
    return None, UNMATCHED, 0.0


def review_reason(ref, phone: str, payer: str, index: MemberIndex, amount=None) -> str | None:
    """For a payment the matcher sent to review: the plainest true reason, or None when it is a mix of signals.
    Each check below is one of the matcher's own; this only words it for a person."""
    raw = str(ref if isinstance(ref, str) else "" if ref is None or pd.isna(ref) else ref).strip().upper()
    payer = normalize_name(payer)
    if raw in index.by_id and _slip_of_another(index.by_id[raw], phone, payer, index):
        return (f"{index.by_id[raw]} is one keying slip from the member whose phone or name made this payment: a "
                "slip, or a payment for a neighbour.")
    raw = _drop_amount(raw, amount)
    if _is_joint(raw, index):
        return "The reference names two members, so a person splits the money."
    named = {index.id_choices[i] for i in reference_ids(raw) if i in index.id_choices}
    bare = {index.id_choices[f"MBR{d}"] for d in re.findall(r"(?<!\d)\d{4}(?!\d)", raw) if f"MBR{d}" in index.id_choices}
    if len(named | bare) > 1:
        return "The reference names more than one member."
    phones = index.phone_members.get(phone, set()) if phone else set()
    if len(phones) > 1:
        return "This phone is registered to more than one member."
    ref_member, tied, _, near = _from_reference(raw, payer, index)
    if ref_member and phones and ref_member not in phones:
        return f"The reference points at {ref_member}, but the money came from {next(iter(phones))}'s phone."
    if tied:
        return "The reference fits several members equally well (a number cut short?), and nothing settles which."
    if ref_member and _name_points_elsewhere(payer, ref_member, index, near, phone_agrees=phones == {ref_member}):
        return (f"The reference points at {ref_member}, but the name on the M-Pesa account fits another member with a "
                "close number: a mistyped number?")
    if ref_member and _ref_names_someone_else(raw, ref_member, index, payer):
        return f"The reference points at {ref_member}, but it also names someone else on the register."
    return None


def naive_exact_match(statement: pd.DataFrame, members: pd.DataFrame) -> pd.Series:
    """What a clerk's exact lookup does: the account reference must equal a member ID character for character."""
    ids = set(members["member_id"])
    return statement["account_reference"].fillna("").astype(str).str.strip().isin(ids)


MATCH_COLUMNS = ["member_id", "match_method", "confidence", "payer_phone", "payer_name"]


def _amount_ok(amount) -> bool:
    try:
        value = float(amount)
    except (TypeError, ValueError):
        return False
    return value > 0 and np.isfinite(value)


def _receipt_key(receipt) -> str | None:
    """Receipts compare without case or spaces, so an export that changed either cannot credit a payment twice."""
    if not isinstance(receipt, str):
        return None if receipt is None or pd.isna(receipt) else str(receipt).strip().upper() or None
    key = re.sub(r"\s+", "", receipt).upper()
    return key or None


_CURRENCY_BEFORE = re.compile(r"^(?:KSHS?|KES|SHS?)\.?\s*")
_CURRENCY_AFTER = re.compile(r"\s*(?:/=|/-|KSHS?|KES|SHS?\.?)$")


def _to_amount(value):
    """3600, "3600", "5,160.00", "KES 5,160", "Ksh5,160", "5,160/=" and "5.160,00" are numbers. Anything that could be
    read two ways ("5.160", "1,0000") or not at all ("N/A", blank) is not, so it goes to a person."""
    if isinstance(value, str):
        text = _CURRENCY_AFTER.sub("", _CURRENCY_BEFORE.sub("", value.strip().upper())).strip()
        # thousands grouped by commas or single spaces ("5,160", "5 160"), or not at all
        if re.fullmatch(r"-?(?:\d{1,3}(?:,\d{3})+|\d{1,3}(?: \d{3})+|\d+)(?:\.\d{0,2})?", text):
            return float(text.replace(",", "").replace(" ", "").rstrip("."))
        if re.fullmatch(r"-?\d{1,3}(?:\.\d{3})+,\d{1,2}", text):  # 5.160,00
            return float(text.replace(".", "").replace(",", "."))
        return np.nan
    try:
        return float(value)
    except (TypeError, ValueError):
        return np.nan


def clean_statement(statement: pd.DataFrame) -> pd.DataFrame:
    """Amounts as numbers, whatever the export did to them."""
    statement = statement.copy()
    statement["paid_in_ksh"] = statement["paid_in_ksh"].map(_to_amount).astype(float)
    return statement


def match_statement(statement: pd.DataFrame, members: pd.DataFrame) -> pd.DataFrame:
    statement = clean_statement(statement)
    index = MemberIndex(members)
    parsed = []
    for row in statement.itertuples(index=False):
        phone, payer = split_other_party(row.other_party_info)
        # Without a receipt number, the same time, amount, payer and reference can only be the same payment.
        row_key = (str(row.completion_time).strip(), row.paid_in_ksh, phone, payer,
                   re.sub(r"\s+", "", str(row.account_reference or "")).upper())
        parsed.append((row, phone, payer, _receipt_key(row.receipt_no), row_key))
    # A copy without its receipt is held whether it comes before or after the receipted row.
    receipted = {row_key for *_, receipt, row_key in parsed if receipt is not None}
    seen: set = set()
    seen_rows: set = set()
    out = []
    for row, phone, payer, receipt, row_key in parsed:
        duplicate = receipt in seen if receipt is not None else (row_key in receipted or row_key in seen_rows)
        if duplicate:
            member_id, method, confidence = None, DUPLICATE, 100.0
        elif not _amount_ok(row.paid_in_ksh):
            member_id, method, confidence = None, BAD_AMOUNT, 0.0
        else:
            if receipt is not None:
                seen.add(receipt)
            else:
                seen_rows.add(row_key)
            member_id, method, confidence = match_row(row.account_reference, phone, payer, index, row.paid_in_ksh)
        out.append({"member_id": member_id, "match_method": method, "confidence": confidence,
                    "payer_phone": phone, "payer_name": payer})
    matched = pd.DataFrame(out, columns=MATCH_COLUMNS)
    return pd.concat([statement.reset_index(drop=True), matched], axis=1)


# ----------------------------------------------------------------------------------------- waterfall

def premium_due(members: pd.DataFrame, premium_target) -> pd.Series:
    """Premium each member owes: one figure for everyone, or a {ward: KSh} map for zone pricing.

    A ward missing from the map is not offered the product: its members get NaN (no premium, status NOT_OFFERED).
    A ward priced at zero is offered and owes nothing.
    """
    if isinstance(premium_target, dict):
        return members["ward"].map(premium_target).astype(float)
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
    ledger = ledger.sort_values(["completion_time", "receipt_no"], kind="stable", na_position="last")
    ledger = ledger.reset_index(drop=True)
    members = members.copy()
    for col in ("loan_balance", "overdue_interest", "savings_balance"):
        members[col] = pd.to_numeric(members[col], errors="coerce").fillna(0.0)  # a blank cell means none
    due = premium_due(members, premium_target)
    owed = {mid: {"premium": 0.0 if pd.isna(d) else float(d), "interest": float(i), "principal": float(p)}
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
    receipts = allocated[allocated["match_method"] != CHECKOFF].groupby("member_id")["receipt_no"].agg(
        lambda s: ";".join(s.dropna().astype(str)))
    summary = members.set_index("member_id").join(sums).join(receipts.rename("receipts")).reset_index()
    for col in ("paid_in_ksh", "to_premium", "to_interest", "to_principal", "to_savings"):
        summary[col] = summary[col].fillna(0.0)
    summary["receipts"] = summary["receipts"].fillna("")
    due = premium_due(summary, premium_target)
    summary["policy_status"] = np.select(
        [due.isna().to_numpy(),
         summary["to_premium"] >= due - 1e-6,
         summary["to_premium"] >= GRACE_SHARE * due],
        [NOT_OFFERED, ACTIVE, GRACE], PENDING)
    summary["premium_due"] = due.fillna(0.0).to_numpy()  # not offered: nothing due
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
    duplicate_value_exact_ref: float  # duplicates an exact lookup would have credited twice (exact member ID)
    seconds: float

    @property
    def mpesa(self) -> pd.DataFrame:
        return self.ledger[self.ledger["match_method"] != CHECKOFF]


def reconcile(statement: pd.DataFrame, members: pd.DataFrame, premium_target=PREMIUM_TARGET,
              include_checkoff: bool = True) -> ReconResult:
    started = time.perf_counter()
    statement = clean_statement(statement)
    matched = match_statement(statement, members)
    naive = naive_exact_match(statement, members)
    ledger = pd.concat([matched, checkoff_rows(members)], ignore_index=True) if include_checkoff else matched
    ledger, summary = allocate_waterfall(ledger, members, premium_target)
    elapsed = time.perf_counter() - started

    amounts = pd.to_numeric(statement["paid_in_ksh"], errors="coerce").fillna(0.0).clip(lower=0)
    total_rows, total_value = len(statement), float(amounts.sum())
    suspense = matched["match_method"].isin(SUSPENSE_METHODS).to_numpy()
    dupes = (matched["match_method"] == DUPLICATE).to_numpy()

    def share(mask, of_value: bool) -> float:
        if of_value:
            return float(amounts[mask].sum() / total_value) if total_value else 0.0
        return float(mask.sum() / total_rows) if total_rows else 0.0

    not_placed = ~naive.to_numpy()
    return ReconResult(
        ledger=ledger, members=summary,
        before_suspense_rows=share(not_placed, False), before_suspense_value=share(not_placed, True),
        after_suspense_rows=share(suspense, False), after_suspense_value=share(suspense, True),
        duplicates_caught=int(dupes.sum()), duplicate_value=float(amounts[dupes].sum()),
        duplicate_value_exact_ref=float(amounts[dupes & naive.to_numpy()].sum()),
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
