"""Synthetic SACCO member ledger and a deliberately messy M-Pesa paybill statement.

Everyone here is fictional: names are random combinations, and phone numbers and national IDs are random
digits. A fixed seed makes every run identical, so a demo shows the same numbers each time.

The statement mixes the errors that stall real SACCO reconciliations:
  ~53% clean payments (exact member ID in the account reference)
  ~18% mistyped member IDs (MBR1042, MBR-1042-MILK, MRB-1042, MBR-1O42, truncated MBR-104 ...)
  ~14% payments from a spouse's unregistered phone (reference is the national ID, part of the surname, or blank)
  ~10% partial micro-payments (KSh 150, 300, 500, 1,000)
  ~5%  duplicate export rows and payments that belong to nobody

``generate_statement`` also returns the ground truth for each row, so the matcher's accuracy can be measured.

    python -m data.seed_generator          # writes the three CSV files to data/generated/
"""
from __future__ import annotations

import string
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 2027
N_MEMBERS = 500
N_TRANSACTIONS = 520
PREMIUM_TARGET = 3_600
STATEMENT_START = pd.Timestamp("2026-10-15")
STATEMENT_END = pd.Timestamp("2026-11-18")
CHECKOFF_POSTED = pd.Timestamp("2026-10-31 23:00")
CHECKOFF_DAYS = 31
OUT_DIR = Path(__file__).resolve().parent / "generated"

WARD_WEIGHTS = {"njoro": 0.26, "imenti_north": 0.22, "kangundo": 0.18, "kimilili": 0.18, "bureti": 0.16}

CHRISTIAN_F = ["Grace", "Mary", "Jane", "Esther", "Faith", "Mercy", "Ann", "Lucy", "Joyce", "Ruth", "Purity", "Beatrice"]
CHRISTIAN_M = ["John", "Peter", "Joseph", "James", "David", "Samuel", "Daniel", "Paul", "Stephen", "Francis", "Moses"]
KENYAN_F = ["Wanjiku", "Akinyi", "Makena", "Nyambura", "Chebet", "Wairimu", "Atieno", "Mwende", "Njeri", "Kerubo",
            "Jepkosgei", "Nekesa", "Wambui", "Kawira", "Mumbua", "Auma", "Naliaka", "Cherono", "Muthoni", "Kanini"]
KENYAN_M = ["Kamau", "Kiprop", "Mutua", "Odhiambo", "Otieno", "Mwangi", "Kipkemboi", "Wafula", "Njoroge", "Kimani",
            "Ochieng", "Musyoka", "Kiplagat", "Barasa", "Mugo", "Omondi", "Mutiso", "Wekesa", "Koech", "Gitonga"]
SURNAMES = ["Kamau", "Korir", "Musyoka", "Otieno", "Mwenda", "Mwangi", "Kiprotich", "Wanyama", "Njoroge", "Ochieng",
            "Mutua", "Cheruiyot", "Wafula", "Kariuki", "Onyango", "Kilonzo", "Rotich", "Simiyu", "Gitonga", "Muriuki",
            "Langat", "Nyaga", "Ndung'u", "Owino", "Kibet", "Mbugua", "Muthama", "Wekesa", "Kirui", "Kathure",
            "Macharia", "Kiptoo", "Mueni", "Wasike", "Njagi", "Chepkwony", "Kioko", "Odongo", "Murithi", "Sang"]
# Payers that are not members: shops, agents and people whose surnames are not in the member list.
OUTSIDERS = ["MAMA MBOGA STORES", "UPENDO AGROVET", "BAHATI HARDWARE", "NEEMA TRADERS", "SALIM HASSAN ALI",
             "ABDI NUR ADAN", "FATUMA SAID MOHAMED", "AHMED OMAR YUSUF", "ROSE KHADIJA JUMA", "TUMAINI MINI MART"]
OUTSIDER_REFS = ["SCHOOL FEES", "", "LOAN", "ACCOUNT", "SHAMBA", "FEES TERM 3", "DEPOSIT", "CHAMA", "TEST"]
SAFARICOM_PREFIXES = ["710", "711", "712", "713", "714", "715", "716", "717", "718", "719", "720", "721", "722",
                      "723", "724", "725", "726", "727", "728", "729", "740", "741", "742", "743", "745", "746",
                      "748", "757", "758", "759", "768", "769", "790", "791", "792", "793", "794", "795", "796",
                      "797", "798", "799"]

SCENARIO_SHARES = {"clean": 0.531, "mistyped_id": 0.18, "spouse_phone": 0.14, "partial": 0.10}
FULL_AMOUNTS = ([3_600, 1_800, 2_000, 4_000, 5_000, 7_200], [0.55, 0.20, 0.08, 0.07, 0.06, 0.04])
PARTIAL_AMOUNTS = [150, 300, 500, 1_000]


@dataclass
class SyntheticData:
    members: pd.DataFrame
    statement: pd.DataFrame
    truth: pd.DataFrame


class _Phones:
    """Unique random Safaricom-style numbers, as 254XXXXXXXXX."""

    def __init__(self, rng: np.random.Generator):
        self.rng = rng
        self.used: set[str] = set()

    def new(self) -> str:
        while True:
            number = "254" + self.rng.choice(SAFARICOM_PREFIXES) + f"{self.rng.integers(0, 1_000_000):06d}"
            if number not in self.used:
                self.used.add(number)
                return number


def registry_format(phone254: str, rng: np.random.Generator) -> str:
    """SACCO registers keep phone numbers in whatever format the clerk typed."""
    local = "0" + phone254[3:]
    style = rng.choice(4, p=[0.45, 0.25, 0.2, 0.1])
    if style == 0:
        return local
    if style == 1:
        return f"{local[:4]} {local[4:7]} {local[7:]}"
    if style == 2:
        return phone254
    return f"+254 {phone254[3:6]} {phone254[6:]}"


def generate_members(seed: int = SEED, n: int = N_MEMBERS) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    phones = _Phones(rng)
    national_ids: set[str] = set()
    wards = list(WARD_WEIGHTS)
    rows = []
    for i in range(n):
        female = rng.random() < 0.52
        first = rng.choice(KENYAN_F if female else KENYAN_M)
        christian = rng.choice(CHRISTIAN_F if female else CHRISTIAN_M) if rng.random() < 0.5 else ""
        surname = rng.choice(SURNAMES)
        full_name = " ".join(p for p in (christian, first, surname) if p)
        while True:
            nid = str(rng.integers(20_000_000, 40_000_000))
            if nid not in national_ids:
                national_ids.add(nid)
                break
        phone = phones.new()
        married = rng.random() < 0.75
        if married:
            spouse_first = rng.choice(KENYAN_M if female else KENYAN_F)
            spouse_christian = rng.choice(CHRISTIAN_M if female else CHRISTIAN_F)
            spouse_surname = surname if rng.random() < 0.8 else rng.choice(SURNAMES)
            spouse_name = f"{spouse_christian} {spouse_first} {spouse_surname}"
            spouse_phone = phones.new()
        else:
            spouse_name, spouse_phone = "", ""
        has_loan = rng.random() < 0.7
        loan = float(round(rng.uniform(2_000, 85_000), -2)) if has_loan else 0.0
        overdue = float(round(rng.uniform(200, 6_000), -1)) if has_loan and rng.random() < 0.55 else 0.0
        dairy = rng.random() < 0.6
        milk_daily = float(rng.choice([20, 30, 40, 50, 60, 80, 100])) if dairy else 0.0
        rows.append({
            "member_id": f"MBR-{1001 + i}", "full_name": full_name, "surname": surname,
            "gender": "F" if female else "M", "phone": registry_format(phone, rng), "phone_254": phone,
            "national_id": nid, "ward": rng.choice(wards, p=list(WARD_WEIGHTS.values())),
            "spouse_name": spouse_name, "spouse_phone_254": spouse_phone,
            "loan_balance": loan, "overdue_interest": overdue,
            "savings_balance": float(round(rng.uniform(500, 40_000), -2)),
            "milk_checkoff_daily": milk_daily, "milk_checkoff_month": milk_daily * CHECKOFF_DAYS,
        })
    return pd.DataFrame(rows)


def _mistype(member_id: str, rng: np.random.Generator) -> str:
    digits = member_id.split("-")[1]
    variants = [
        f"MBR{digits}", f"mbr-{digits}", f"MBR {digits}", f"{member_id}-MILK", f"MBR{digits}MILK",
        f"MRB-{digits}", f"MBR-{digits.replace('0', 'O', 1)}" if "0" in digits else f"MBR {digits}",
        digits, f"ACC {member_id}", f"MBR--{digits}", f"Mbr{digits}",
        f"MBR-{digits[:3]}",  # truncated: fits ten members, so only the payer's name can settle it
    ]
    return str(rng.choice(variants))


def _surname_hint(member: pd.Series, rng: np.random.Generator) -> str:
    surname = member["surname"].upper().replace("'", "")
    first_initial = member["full_name"].split()[0][0].upper()
    hints = [surname, surname[:3], f"{first_initial} {surname}", f"{surname} MILK", f"FOR {surname}"]
    return str(rng.choice(hints))


def _receipt(rng: np.random.Generator, used: set[str]) -> str:
    alphabet = np.array(list(string.ascii_uppercase + string.digits))
    while True:
        receipt = "TJ" + "".join(rng.choice(alphabet, 8))
        if receipt not in used:
            used.add(receipt)
            return receipt


def _time(rng: np.random.Generator) -> pd.Timestamp:
    days = (STATEMENT_END - STATEMENT_START).days
    day = STATEMENT_START + pd.Timedelta(days=int(rng.integers(0, days + 1)))
    return day + pd.Timedelta(seconds=int(rng.integers(7 * 3600, 21 * 3600)))


def generate_statement(members: pd.DataFrame, seed: int = SEED, n: int = N_TRANSACTIONS):
    """Return (statement, truth). The statement looks like an M-Pesa organisation paybill export."""
    rng = np.random.default_rng(seed + 1)
    phones = _Phones(rng)
    phones.used |= set(members["phone_254"]) | set(members["spouse_phone_254"])
    receipts: set[str] = set()
    counts = {k: int(round(v * n)) for k, v in SCENARIO_SHARES.items()}
    n_dupes = (n - sum(counts.values())) // 2
    n_outsiders = n - sum(counts.values()) - n_dupes
    married = members[members["spouse_name"] != ""]

    rows: list[dict] = []

    def add(member, scenario, ref, phone, name, amount):
        rows.append({
            "receipt_no": _receipt(rng, receipts), "completion_time": _time(rng), "paid_in_ksh": float(amount),
            "account_reference": ref, "other_party_info": f"{phone} - {name.upper()}",
            "_truth_member_id": None if member is None else member["member_id"], "_scenario": scenario,
        })

    def full_amount():
        return rng.choice(FULL_AMOUNTS[0], p=FULL_AMOUNTS[1])

    def payer_name(member):
        parts = member["full_name"].split()
        return " ".join(parts[-2:]) if len(parts) > 2 and rng.random() < 0.4 else member["full_name"]

    for _ in range(counts["clean"]):
        m = members.iloc[int(rng.integers(len(members)))]
        add(m, "clean", m["member_id"], m["phone_254"], payer_name(m), full_amount())
    for _ in range(counts["mistyped_id"]):
        m = members.iloc[int(rng.integers(len(members)))]
        if rng.random() < 0.35:
            phone, name = m["phone_254"], payer_name(m)  # their own phone, sloppy reference
        else:
            phone = phones.new()  # a second SIM or an agent's phone
            name = payer_name(m) if rng.random() < 0.5 else f"{rng.choice(CHRISTIAN_M)} {rng.choice(SURNAMES)}"
        add(m, "mistyped_id", _mistype(m["member_id"], rng), phone, name, full_amount())
    for _ in range(counts["spouse_phone"]):
        m = married.iloc[int(rng.integers(len(married)))]
        roll = rng.random()
        ref = m["national_id"] if roll < 0.45 else _surname_hint(m, rng) if roll < 0.8 else rng.choice(["", "SHAMBA"])
        add(m, "spouse_phone", ref, m["spouse_phone_254"], m["spouse_name"], full_amount())
    for _ in range(counts["partial"]):
        m = members.iloc[int(rng.integers(len(members)))]
        ref = m["member_id"] if rng.random() < 0.6 else _mistype(m["member_id"], rng)
        phone = m["phone_254"] if rng.random() < 0.7 else phones.new()
        add(m, "partial", ref, phone, payer_name(m), rng.choice(PARTIAL_AMOUNTS))
    for _ in range(n_outsiders):
        add(None, "not_a_member", str(rng.choice(OUTSIDER_REFS)), phones.new(), str(rng.choice(OUTSIDERS)),
            rng.choice([250, 500, 1_200, 3_000, 4_500]))

    rows.sort(key=lambda r: r["completion_time"])
    # Overlapping exports repeat a block of rows: the same receipt appears twice.
    for idx in sorted(rng.choice(len(rows), n_dupes, replace=False), reverse=True):
        dupe = dict(rows[idx])
        dupe["_scenario"] = "duplicate_export"
        rows.insert(idx + 1, dupe)

    frame = pd.DataFrame(rows)
    frame["completion_time"] = frame["completion_time"].dt.strftime("%Y-%m-%d %H:%M:%S")
    frame["details"] = "Pay Bill Online"
    frame["transaction_status"] = "Completed"
    truth = frame[["receipt_no", "_truth_member_id", "_scenario"]].rename(
        columns={"_truth_member_id": "truth_member_id", "_scenario": "scenario"})
    truth["row"] = range(len(truth))
    statement = frame[["receipt_no", "completion_time", "details", "transaction_status", "paid_in_ksh",
                       "account_reference", "other_party_info"]]
    return statement.reset_index(drop=True), truth.reset_index(drop=True)


def generate_all(seed: int = SEED) -> SyntheticData:
    members = generate_members(seed)
    statement, truth = generate_statement(members, seed)
    return SyntheticData(members, statement, truth)


def write_csvs(out_dir: Path = OUT_DIR, seed: int = SEED) -> list[Path]:
    data = generate_all(seed)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = [out_dir / "sacco_members.csv", out_dir / "mpesa_paybill_statement.csv", out_dir / "ground_truth.csv"]
    for frame, path in zip((data.members, data.statement, data.truth), paths):
        frame.to_csv(path, index=False, lineterminator="\n")
    return paths


if __name__ == "__main__":
    for written in write_csvs():
        print("wrote", written)
