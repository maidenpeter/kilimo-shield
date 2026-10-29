"""Business rules shared by the portal, USSD, bulk import and tests.

    preview()   validate an enrolment and quote it, writing nothing
    enrol()     the same, then save farmer, plot, consents and policy in one transaction
    bulk_check() / bulk_commit()   CSV enrolment: dry run reporting every row, then all-or-nothing
    record_payment()               a premium instalment (M-Pesa or SACCO deduction)
    close_sales_windows()          daily: lapse cover not fully paid by the close date; reminders
    portfolio() SACCO dashboard figures
    export_policies_csv()          policy export with national ID and phone masked

Prices always come from agroshield_pricing.quote against the engine's rate book.
"""
from __future__ import annotations

import csv
import hashlib
import io
import math
import secrets
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

import yaml
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from agroshield_pricing.config import Config
from agroshield_pricing.quote import QuoteError, RateBook, quote

from . import sms
from .crypto import PIIError, Vault, mask_national_id, mask_phone, normalise_national_id, normalise_phone
from .db import audit
from .kiamis import KiamisAdapter, NotConnected
from .locale import LANGUAGES
from .models import Consent, Farmer, Officer, Payment, Plot, Policy, Sacco

PAYMENT_ROUTES = ("sacco_deduction", "mpesa")
PAYMENT_METHODS = ("mpesa", "sacco_deduction")
GENDERS = ("female", "male", "other", "undisclosed")
NAIROBI = timezone(timedelta(hours=3))     # East Africa Time, no daylight saving
MIN_INSTALMENT_KES = 50
REMINDER_DAYS = (7, 1)                     # SMS reminders this many days before sales close
PAY_REF_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # no 0/O or 1/I


class EnrolmentError(ValueError):
    def __init__(self, errors: dict[str, str]):
        super().__init__("; ".join(f"{k}: {v}" for k, v in errors.items()))
        self.errors = errors


class PaymentError(ValueError):
    pass


@dataclass
class EnrolmentInput:
    member_no: str
    full_name: str
    phone: str
    national_id: str
    ward_id: str
    acreage: float
    layers: list[str] = field(default_factory=lambda: ["B"])
    sum_insured_kes_per_acre: float | None = None
    gender: str = "undisclosed"
    lat: float | None = None
    lon: float | None = None
    payment_route: str = "sacco_deduction"
    loan_linked: bool = False
    loan_ref: str | None = None
    consent_data_processing: bool = False
    consent_sms: bool = False
    consent_loan_linked_payout: bool = False
    resilience: dict[str, bool] = field(default_factory=dict)
    season: str = "LR"
    year: int | None = None            # must match the open sales window if given
    language: str = "en"               # for SMS and USSD


def load_consent_wording(cfg: Config) -> dict:
    raw = (cfg.root / "consent.yaml").read_bytes()
    data = yaml.safe_load(raw)
    for p in data["purposes"].values():
        p["sha256"] = hashlib.sha256((p["en"] + "\n" + p["sw"]).encode()).hexdigest()
    review = data.get("review") or {}
    data["reviewed"] = all(isinstance(review.get(k), dict) and review[k].get("reviewer") and review[k].get("date")
                           for k in ("legal", "kiswahili"))
    return data


@dataclass
class Context:
    cfg: Config
    book: RateBook
    vault: Vault
    kiamis: KiamisAdapter = field(default_factory=NotConnected)
    today: date | None = None          # fixed "today" for tests and replays; default: the Nairobi date
    mpesa: object | None = None        # mpesa.DarajaClient or mpesa.SimulatedDaraja
    ussd_code: str = "*384*000#"

    def now(self) -> datetime:
        n = datetime.now(NAIROBI)
        return n if self.today is None else datetime.combine(self.today, n.timetz())

    def date(self) -> date:
        return self.today or datetime.now(NAIROBI).date()


def sales_status(ctx: Context, ward_id: str, season: str) -> dict:
    """Whether cover for this ward and season can be bought today, and for which planting year."""
    try:
        cal = ctx.cfg.calendar(ward_id, season)
    except KeyError:
        return {"open": False, "reason": f"no {season} cover is sold at {ward_id}"}
    today = ctx.date()
    year = cal.open_sales_year(today)
    if year is not None:
        opens, closes = cal.sales_window_for(year)
        return {"open": True, "year": year, "opens": opens, "closes": closes}
    upcoming = [w for y in (today.year, today.year + 1, today.year + 2) if (w := cal.sales_window_for(y)) and w[0] > today]
    nxt = upcoming[0][0] if upcoming else None
    return {"open": False, "next_opens": nxt,
            "reason": f"sales for {season} cover at {ward_id} are closed"
                      + (f"; the next window opens {nxt:%d %b %Y}" if nxt else "")}


def consent_gate(ctx: Context, sacco: Sacco | None) -> str | None:
    """Live (non-demo) enrolment needs consent wording with a recorded legal and Kiswahili review."""
    if sacco is None or sacco.is_demo:
        return None
    w = load_consent_wording(ctx.cfg)
    if w["reviewed"]:
        return None
    return (f"consent wording {w['version']} is pending legal and Kiswahili review; live enrolment is blocked "
            "until a reviewed version is recorded in config/consent.yaml")


def _validate(ctx: Context, inp: EnrolmentInput) -> tuple[dict, dict]:
    """Returns (clean values, errors)."""
    errors, clean = {}, {}
    for f in ("member_no", "full_name"):
        v = (getattr(inp, f) or "").strip()
        if not v:
            errors[f] = "required"
        clean[f] = v
    try:
        clean["phone"] = normalise_phone(inp.phone)
    except PIIError as e:
        errors["phone"] = str(e)
    try:
        clean["national_id"] = normalise_national_id(inp.national_id)
    except PIIError as e:
        errors["national_id"] = str(e)
    if inp.ward_id not in ctx.cfg.pilot.wards:
        errors["ward_id"] = f"must be one of {', '.join(ctx.cfg.pilot.wards)}"
    else:
        st = sales_status(ctx, inp.ward_id, inp.season)
        if not st["open"]:
            errors["ward_id"] = st["reason"]
        elif inp.year is not None and inp.year != st["year"]:
            errors["ward_id"] = f"sales are open for {inp.season} {st['year']}, not {inp.year}"
        else:
            clean["year"], clean["sales_closes_on"] = st["year"], st["closes"]
    if not inp.acreage or inp.acreage <= 0:
        errors["acreage"] = "must be more than 0"
    if inp.gender not in GENDERS:
        errors["gender"] = f"must be one of {', '.join(GENDERS)}"
    if inp.language not in LANGUAGES:
        errors["language"] = f"must be one of {', '.join(LANGUAGES)}"
    if inp.payment_route not in PAYMENT_ROUTES:
        errors["payment_route"] = f"must be one of {', '.join(PAYMENT_ROUTES)}"
    if (inp.lat is None) != (inp.lon is None):
        errors["lat"] = "give both latitude and longitude, or neither"
    elif inp.lat is not None and not (-5 <= inp.lat <= 5 and 33 <= inp.lon <= 42):
        errors["lat"] = "point is outside Kenya"
    if not inp.consent_data_processing:
        errors["consent_data_processing"] = "the farmer must agree to data processing to be enrolled"
    if inp.loan_linked:
        if not inp.consent_loan_linked_payout:
            errors["consent_loan_linked_payout"] = "loan-linked payout needs the farmer's explicit consent"
        if not (inp.loan_ref or "").strip():
            errors["loan_ref"] = "required for a loan-linked payout"
    return clean, errors


def preview(ctx: Context, s: Session, inp: EnrolmentInput, sacco: Sacco | None = None) -> dict:
    """Validate, check KIAMIS and quote. Writes nothing."""
    clean, errors = _validate(ctx, inp)
    gate = consent_gate(ctx, sacco)
    if gate:
        errors["consent"] = gate
    kiamis = None
    resilience = dict(inp.resilience)
    if "national_id" in clean and not errors.get("acreage"):
        kiamis = ctx.kiamis.check(s, clean["national_id"], inp.acreage)
        if kiamis.certified_seed_purchased:
            resilience["certified_seed_verified"] = True   # verified at source
    q = None
    if not errors:
        try:
            q = quote(ctx.cfg, ctx.book, ward_id=inp.ward_id, season=inp.season, acres=inp.acreage, layers=inp.layers,
                      sum_insured_kes_per_acre=inp.sum_insured_kes_per_acre, resilience=resilience)
        except QuoteError as e:
            errors["layers"] = str(e)
    return {"ok": not errors, "errors": errors, "quote": q, "kiamis": kiamis.__dict__ if kiamis else None,
            "resilience_used": resilience, "sales": {k: clean[k] for k in ("year", "sales_closes_on") if k in clean}}


def enrol(ctx: Context, s: Session, sacco: Sacco, officer: Officer | None, inp: EnrolmentInput,
          channel: str = "portal") -> Policy:
    pv = preview(ctx, s, inp, sacco)
    if not pv["ok"]:
        raise EnrolmentError(pv["errors"])
    clean, q = _validate(ctx, inp)[0], pv["quote"]
    year = clean["year"]
    actor = officer.username if officer else "system"
    nid_hash = ctx.vault.lookup_hash(clean["national_id"], "national_id")

    farmer = s.scalar(select(Farmer).where(Farmer.sacco_id == sacco.id, Farmer.national_id_hash == nid_hash))
    if farmer and farmer.member_no != clean["member_no"]:
        raise EnrolmentError({"member_no": "this national ID is already registered under another member number"})
    if farmer is None:
        if s.scalar(select(Farmer).where(Farmer.sacco_id == sacco.id, Farmer.member_no == clean["member_no"])):
            raise EnrolmentError({"member_no": "this member number belongs to a different national ID"})
        farmer = Farmer(sacco_id=sacco.id, member_no=clean["member_no"], full_name=clean["full_name"],
                        national_id_enc=ctx.vault.encrypt(clean["national_id"], "national_id"), national_id_hash=nid_hash,
                        national_id_masked=mask_national_id(clean["national_id"]),
                        phone_enc=ctx.vault.encrypt(clean["phone"], "phone"),
                        phone_hash=ctx.vault.lookup_hash(clean["phone"], "phone"), phone_masked=mask_phone(clean["phone"]),
                        gender=inp.gender, ward_id=inp.ward_id, language=inp.language,
                        kiamis_status=pv["kiamis"]["status"] if pv["kiamis"] else "not_checked",
                        created_by=officer.id if officer else None)
        s.add(farmer)
        s.flush()
        audit(s, actor, "farmer.created", "farmer", farmer.id, member_no=farmer.member_no, ward=farmer.ward_id, channel=channel)

    if existing_policy(s, farmer, inp.ward_id, inp.season, year):
        raise EnrolmentError({"member_no": f"already has a {inp.season} {year} policy in {inp.ward_id}"})

    wording = load_consent_wording(ctx.cfg)
    for purpose, granted in (("data_processing", inp.consent_data_processing), ("sms", inp.consent_sms),
                             ("loan_linked_payout", inp.consent_loan_linked_payout)):
        s.add(Consent(farmer_id=farmer.id, purpose=purpose, granted=bool(granted), wording_version=wording["version"],
                      wording_sha256=wording["purposes"][purpose]["sha256"], channel=channel,
                      captured_by=officer.id if officer else None))

    plot = Plot(farmer_id=farmer.id, ward_id=inp.ward_id, acreage=inp.acreage, lat=inp.lat, lon=inp.lon,
                source="csv" if channel == "csv" else "officer")
    s.add(plot)
    s.flush()

    seq = (s.scalar(select(func.count()).select_from(Policy).where(Policy.sacco_id == sacco.id)) or 0) + 1
    pol = Policy(policy_no=f"AGS-{sacco.code}-{inp.season}{year % 100:02d}-{seq:05d}", pay_ref=_new_pay_ref(s),
                 farmer_id=farmer.id, plot_id=plot.id, sacco_id=sacco.id, ward_id=inp.ward_id, season=inp.season,
                 year=year, layers=",".join(sorted(set(inp.layers))), acres=inp.acreage,
                 sum_insured_per_acre=q["sum_insured_kes_per_acre"], gross_kes=q["gross_premium_kes"],
                 government_share_kes=q["subsidy"]["government_share_kes"],
                 farmer_share_kes=q["farmer_share_before_discount_kes"], resilience_points=q["resilience"]["points"],
                 discount_kes=q["resilience"]["discount_kes"], discount_funder=q["resilience"]["funder"],
                 farmer_pays_kes=q["farmer_pays_kes"], amount_due_kes=math.ceil(q["farmer_pays_kes"] - 1e-9),
                 sales_closes_on=clean["sales_closes_on"],
                 subsidy_status=q["subsidy"]["status"], payment_route=inp.payment_route,
                 loan_linked=inp.loan_linked, loan_ref=(inp.loan_ref or None) if inp.loan_linked else None,
                 quote_id=q["quote_id"], quote_snapshot=q, created_by=officer.id if officer else None)
    s.add(pol)
    s.flush()
    audit(s, actor, "policy.created", "policy", pol.id, policy_no=pol.policy_no, layers=pol.layers,
          gross_kes=pol.gross_kes, farmer_pays_kes=pol.farmer_pays_kes, quote_id=pol.quote_id, channel=channel,
          index_versions=q["basis"]["index_versions"])
    sms.queue(s, farmer, "enrolled", pol, dedupe_key=f"enrolled:{pol.id}", ussd_code=ctx.ussd_code)
    return pol


def _new_pay_ref(s: Session) -> str:
    while True:
        ref = "AG" + "".join(secrets.choice(PAY_REF_ALPHABET) for _ in range(8))
        if not s.scalar(select(Policy).where(Policy.pay_ref == ref)):
            return ref


def existing_policy(s: Session, farmer: Farmer | None, ward_id: str, season: str, year: int) -> Policy | None:
    if farmer is None or farmer.id is None:
        return None
    return s.scalar(select(Policy).where(Policy.farmer_id == farmer.id, Policy.ward_id == ward_id, Policy.season == season,
                                         Policy.year == year, Policy.status != "cancelled"))


# ------------------------------------------------------------------ payments
def record_payment(ctx: Context, s: Session, pol: Policy, amount: float, method: str, reference: str, actor: str,
                   received_at: datetime | None = None) -> Payment:
    """Record one instalment. Cover becomes active only once the farmer share is fully paid by the close date;
    money received after the close date, or above the amount due, is owed back to the farmer."""
    if method not in PAYMENT_METHODS:
        raise PaymentError(f"method must be one of {', '.join(PAYMENT_METHODS)}")
    reference = (reference or "").strip()
    if not reference:
        raise PaymentError("a payment reference is required (M-Pesa receipt or SACCO deduction reference)")
    if s.scalar(select(Payment).where(Payment.reference == reference)):
        raise PaymentError(f"payment reference {reference} is already recorded")
    if not amount or amount <= 0:
        raise PaymentError("amount must be more than 0")
    if pol.status == "cancelled":
        raise PaymentError("this policy is cancelled")
    at = received_at or ctx.now()
    within = at.astimezone(NAIROBI).date() <= pol.sales_closes_on
    pay = Payment(policy_id=pol.id, amount_kes=float(amount), method=method, reference=reference, received_at=at,
                  within_window=within, recorded_by=actor)
    s.add(pay)
    pol.paid_kes = round(pol.paid_kes + float(amount), 2)
    template = None
    if pol.status == "active":
        pol.refund_due_kes = round(pol.paid_kes - pol.amount_due_kes, 2)       # paid again after full payment
        template = "overpaid"
    elif not within or pol.status == "lapsed_unpaid":
        pol.status, pol.refund_due_kes = "lapsed_unpaid", round(pol.paid_kes, 2)
        template = "late_payment"
    elif pol.paid_kes >= pol.amount_due_kes:
        pol.status, pol.cover_active_from, pol.payment_status = "active", at, "paid"
        pol.refund_due_kes = round(pol.paid_kes - pol.amount_due_kes, 2)
        template = "cover_active"
    else:
        pol.payment_status = "part_paid"
        template = "payment_received"
    s.flush()
    audit(s, actor, "payment.recorded", "policy", pol.id, policy_no=pol.policy_no, method=method,
          amount_kes=float(amount), within_window=within, status=pol.status, paid_kes=pol.paid_kes)
    sms.queue(s, pol.farmer, template, pol, dedupe_key=f"{template}:{pol.id}:{reference}", ussd_code=ctx.ussd_code,
              amount=f"{math.ceil(float(amount) - 1e-9):,}")
    if template == "cover_active" and pol.refund_due_kes > 0:
        sms.queue(s, pol.farmer, "overpaid", pol, dedupe_key=f"overpaid:{pol.id}:{reference}")
    return pay


def close_sales_windows(ctx: Context, s: Session) -> dict:
    """Daily job: lapse cover not fully paid after the close date, and remind farmers before it."""
    today = ctx.date()
    lapsed = reminded = 0
    for pol in s.scalars(select(Policy).where(Policy.status == "pending_payment")):
        days_left = (pol.sales_closes_on - today).days
        if days_left < 0:
            pol.status, pol.refund_due_kes = "lapsed_unpaid", round(pol.paid_kes, 2)
            audit(s, "system", "policy.lapsed_unpaid", "policy", pol.id, policy_no=pol.policy_no, paid_kes=pol.paid_kes)
            sms.queue(s, pol.farmer, "lapsed", pol, dedupe_key=f"lapsed:{pol.id}")
            lapsed += 1
        elif days_left in REMINDER_DAYS and sms.queue(s, pol.farmer, "reminder", pol, ussd_code=ctx.ussd_code,
                                                      dedupe_key=f"reminder:{pol.id}:{days_left}"):
            reminded += 1
    return {"date": str(today), "lapsed": lapsed, "reminders": reminded}


# ------------------------------------------------------------------ bulk CSV
BULK_COLUMNS = ["member_no", "full_name", "phone", "national_id", "gender", "ward_id", "acreage", "lat", "lon",
                "layers", "sum_insured_kes_per_acre", "payment_route", "loan_linked", "loan_ref",
                "consent_data_processing", "consent_sms", "consent_loan_linked_payout", "resilience"]
OPTIONAL_COLUMNS = ["language"]       # en (default) or sw


def _yes(v: str | None) -> bool:
    return (v or "").strip().lower() in ("yes", "y", "true", "1")


def bulk_template() -> str:
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(BULK_COLUMNS + OPTIONAL_COLUMNS)
    w.writerow(["M-0001", "Example Farmer (fictional)", "0712 000 000", "10000001", "female", "ward-a", "2", "", "",
                "B", "10000", "sacco_deduction", "no", "", "yes", "yes", "no",
                "certified_seed_verified;sacco_good_standing", "sw"])
    return out.getvalue()


def parse_bulk(text: str) -> tuple[list[EnrolmentInput], list[dict]]:
    rows = list(csv.DictReader(io.StringIO(text.lstrip("﻿"))))
    problems = []
    if not rows:
        return [], [{"row": 1, "errors": {"file": "no rows"}}]
    missing = [c for c in BULK_COLUMNS if c not in rows[0]]
    if missing:
        return [], [{"row": 1, "errors": {"columns": f"missing {', '.join(missing)}"}}]
    inputs = []
    for r in rows:
        try:
            inputs.append(EnrolmentInput(
                member_no=r["member_no"], full_name=r["full_name"], phone=r["phone"], national_id=r["national_id"],
                gender=(r["gender"] or "undisclosed").strip().lower(), ward_id=r["ward_id"].strip(),
                acreage=float(r["acreage"]) if r["acreage"].strip() else 0.0,
                lat=float(r["lat"]) if r["lat"].strip() else None, lon=float(r["lon"]) if r["lon"].strip() else None,
                layers=[x.strip().upper() for x in r["layers"].replace(";", ",").split(",") if x.strip()] or ["B"],
                sum_insured_kes_per_acre=float(r["sum_insured_kes_per_acre"]) if r["sum_insured_kes_per_acre"].strip() else None,
                payment_route=r["payment_route"].strip() or "sacco_deduction", loan_linked=_yes(r["loan_linked"]),
                loan_ref=r["loan_ref"].strip() or None, consent_data_processing=_yes(r["consent_data_processing"]),
                consent_sms=_yes(r["consent_sms"]), consent_loan_linked_payout=_yes(r["consent_loan_linked_payout"]),
                resilience={x.strip(): True for x in r["resilience"].split(";") if x.strip()},
                language=(r.get("language") or "en").strip().lower()))
        except ValueError:
            # The parser's message would quote the cell, which may be personal data.
            inputs.append(None)
            problems.append({"row": len(inputs) + 1, "member_no": r.get("member_no", ""),
                             "errors": {"format": "acreage, lat, lon and sum_insured_kes_per_acre must be numbers"}})
    return inputs, problems


def bulk_check(ctx: Context, s: Session, text: str, sacco: Sacco | None = None) -> dict:
    inputs, problems = parse_bulk(text)
    results, seen = [], {}
    for i, inp in enumerate(inputs, start=2):
        if inp is None:
            continue
        pv = preview(ctx, s, inp, sacco)
        errs = dict(pv["errors"])
        key = (inp.member_no.strip(), inp.ward_id)
        if key in seen:
            errs["member_no"] = f"duplicate of row {seen[key]} in this file"
        seen.setdefault(key, i)
        if sacco is not None and not errs:
            nid_hash = ctx.vault.lookup_hash(normalise_national_id(inp.national_id), "national_id")
            known = s.scalar(select(Farmer).where(Farmer.sacco_id == sacco.id, Farmer.national_id_hash == nid_hash))
            if existing_policy(s, known, inp.ward_id, inp.season, pv["sales"]["year"]):
                errs["member_no"] = "already enrolled for this season in this ward"
        if errs:
            problems.append({"row": i, "member_no": inp.member_no, "errors": errs})
        else:
            q = pv["quote"]
            results.append({"row": i, "member_no": inp.member_no, "ward_id": inp.ward_id, "acres": inp.acreage,
                            "layers": ",".join(inp.layers), "gross_kes": q["gross_premium_kes"],
                            "farmer_pays_kes": q["farmer_pays_kes"]})
    return {"ok": not problems and bool(results), "valid": results, "problems": sorted(problems, key=lambda p: p["row"]),
            "rows": len(inputs), "sha256": hashlib.sha256(text.encode()).hexdigest()}


def bulk_commit(ctx: Context, s: Session, sacco: Sacco, officer: Officer, text: str) -> list[Policy]:
    """All-or-nothing: the caller's transaction rolls back if any row fails."""
    check = bulk_check(ctx, s, text, sacco)
    if not check["ok"]:
        raise EnrolmentError({"file": f"{len(check['problems'])} rows have problems; fix them and check again"})
    inputs, _ = parse_bulk(text)
    policies = [enrol(ctx, s, sacco, officer, inp, channel="csv") for inp in inputs]
    audit(s, officer.username, "bulk.committed", "sacco", str(sacco.id), rows=len(policies), file_sha256=check["sha256"])
    return policies


# ------------------------------------------------------------------ dashboard and export
def portfolio(ctx: Context, s: Session, sacco: Sacco) -> dict:
    pols = s.scalars(select(Policy).where(Policy.sacco_id == sacco.id, Policy.status != "cancelled")).all()
    members = s.scalar(select(func.count()).select_from(Farmer).where(Farmer.sacco_id == sacco.id)) or 0
    by_ward: dict[str, dict] = {}
    for p in pols:
        w = by_ward.setdefault(p.ward_id, {"ward_id": p.ward_id, "name": ctx.cfg.ward(p.ward_id).name, "policies": 0,
                                           "acres": 0.0, "sum_insured_kes": 0.0, "gross_kes": 0.0,
                                           "loan_linked": 0, "loan_linked_sum_insured_kes": 0.0})
        si = (p.sum_insured_per_acre or 0) * p.acres
        w["policies"] += 1
        w["acres"] += p.acres
        w["sum_insured_kes"] += si
        w["gross_kes"] += p.gross_kes
        if p.loan_linked:
            w["loan_linked"] += 1
            w["loan_linked_sum_insured_kes"] += si
    genders = s.execute(select(Farmer.gender, func.count()).where(Farmer.sacco_id == sacco.id).group_by(Farmer.gender)).all()
    return {
        "members": members, "policies": len(pols),
        "by_status": {st: sum(1 for p in pols if p.status == st) for st in ("pending_payment", "active", "lapsed_unpaid")},
        "acres": sum(p.acres for p in pols),
        "sum_insured_kes": sum((p.sum_insured_per_acre or 0) * p.acres for p in pols),
        "gross_kes": sum(p.gross_kes for p in pols),
        "farmer_premium_due_kes": sum(p.balance_kes for p in pols if p.status == "pending_payment"),
        "premium_collected_kes": sum(p.paid_kes for p in pols),
        "refunds_due_kes": sum(p.refund_due_kes for p in pols),
        "subsidy_receivable_kes": sum(p.government_share_kes for p in pols if p.subsidy_status == "not yet received"),
        "discount_by_funder": {f: sum(p.discount_kes for p in pols if p.discount_funder == f)
                               for f in sorted({p.discount_funder for p in pols})},
        "with_layer_a": sum(1 for p in pols if "A" in p.layers.split(",")),
        "loan_linked": sum(1 for p in pols if p.loan_linked),
        "by_ward": sorted(by_ward.values(), key=lambda w: w["ward_id"]),
        "gender": {g: n for g, n in genders},
        "sales": {w: sales_status(ctx, w, "LR") for w in ctx.cfg.pilot.wards},
        # Live trigger status (and so "members in wards approaching trigger") comes with the
        # daily monitoring job in milestone 7.
        "trigger_status": {w: {"status": "not monitored yet", "note": "Daily ward monitoring arrives in milestone 7."}
                           for w in ctx.cfg.pilot.wards},
    }


def export_policies_csv(s: Session, sacco: Sacco) -> str:
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(["policy_no", "insurer_policy_number", "member_no", "full_name", "national_id", "phone", "ward_id",
                "season", "year", "layers", "acres", "sum_insured_per_acre", "gross_kes", "government_share_kes",
                "subsidy_status", "resilience_points", "discount_kes", "discount_funder", "farmer_pays_kes",
                "amount_due_kes", "paid_kes", "refund_due_kes", "sales_closes_on", "payment_route", "payment_status",
                "status", "cover_active_from", "loan_linked", "loan_ref", "created_at"])
    for p in s.scalars(select(Policy).where(Policy.sacco_id == sacco.id).order_by(Policy.policy_no)):
        f = p.farmer
        w.writerow([p.policy_no, p.insurer_policy_number or "", f.member_no, f.full_name, f.national_id_masked,
                    f.phone_masked, p.ward_id, p.season, p.year, p.layers, p.acres, p.sum_insured_per_acre, p.gross_kes,
                    p.government_share_kes, p.subsidy_status, p.resilience_points, p.discount_kes, p.discount_funder,
                    p.farmer_pays_kes, p.amount_due_kes, p.paid_kes, p.refund_due_kes, p.sales_closes_on.isoformat(),
                    p.payment_route, p.payment_status, p.status,
                    p.cover_active_from.isoformat(timespec="seconds") if p.cover_active_from else "",
                    "yes" if p.loan_linked else "no", p.loan_ref or "", p.created_at.isoformat(timespec="seconds")])
    return out.getvalue()
