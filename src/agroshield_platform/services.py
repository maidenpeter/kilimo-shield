"""Business rules shared by the portal, bulk import and tests.

    preview()   validate an enrolment and quote it, writing nothing
    enrol()     the same, then save farmer, plot, consents and policy in one transaction
    bulk_check() / bulk_commit()   CSV enrolment: dry run reporting every row, then all-or-nothing
    portfolio() SACCO dashboard figures
    export_policies_csv()          policy export with national ID and phone masked

Prices always come from agroshield_pricing.quote against the engine's rate book.
"""
from __future__ import annotations

import csv
import hashlib
import io
from dataclasses import dataclass, field
from datetime import date

import yaml
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from agroshield_pricing.config import Config
from agroshield_pricing.quote import QuoteError, RateBook, quote

from .crypto import PIIError, Vault, mask_national_id, mask_phone, normalise_national_id, normalise_phone
from .db import audit
from .kiamis import KiamisAdapter, NotConnected
from .models import Consent, Farmer, Officer, Plot, Policy, Sacco

PAYMENT_ROUTES = ("sacco_deduction", "mpesa")
GENDERS = ("female", "male", "other", "undisclosed")


class EnrolmentError(ValueError):
    def __init__(self, errors: dict[str, str]):
        super().__init__("; ".join(f"{k}: {v}" for k, v in errors.items()))
        self.errors = errors


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
    year: int | None = None


def next_season_year(season: str, today: date | None = None) -> int:
    """Long rains start in March: from June on, cover is sold for next year's long rains."""
    today = today or date.today()
    return today.year + 1 if season == "LR" and today.month >= 6 else today.year


def load_consent_wording(cfg: Config) -> dict:
    raw = (cfg.root / "consent.yaml").read_bytes()
    data = yaml.safe_load(raw)
    for p in data["purposes"].values():
        p["sha256"] = hashlib.sha256((p["en"] + "\n" + p["sw"]).encode()).hexdigest()
    return data


@dataclass
class Context:
    cfg: Config
    book: RateBook
    vault: Vault
    kiamis: KiamisAdapter = field(default_factory=NotConnected)


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
    if not inp.acreage or inp.acreage <= 0:
        errors["acreage"] = "must be more than 0"
    if inp.gender not in GENDERS:
        errors["gender"] = f"must be one of {', '.join(GENDERS)}"
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


def preview(ctx: Context, s: Session, inp: EnrolmentInput) -> dict:
    """Validate, check KIAMIS and quote. Writes nothing."""
    clean, errors = _validate(ctx, inp)
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
            "resilience_used": resilience}


def enrol(ctx: Context, s: Session, sacco: Sacco, officer: Officer | None, inp: EnrolmentInput,
          channel: str = "portal") -> Policy:
    pv = preview(ctx, s, inp)
    if not pv["ok"]:
        raise EnrolmentError(pv["errors"])
    clean, q = _validate(ctx, inp)[0], pv["quote"]
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
                        gender=inp.gender, ward_id=inp.ward_id,
                        kiamis_status=pv["kiamis"]["status"] if pv["kiamis"] else "not_checked",
                        created_by=officer.id if officer else None)
        s.add(farmer)
        s.flush()
        audit(s, actor, "farmer.created", "farmer", farmer.id, member_no=farmer.member_no, ward=farmer.ward_id, channel=channel)

    year = inp.year or next_season_year(inp.season)
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
    pol = Policy(policy_no=f"AGS-{sacco.code}-{inp.season}{year % 100:02d}-{seq:05d}", farmer_id=farmer.id,
                 plot_id=plot.id, sacco_id=sacco.id, ward_id=inp.ward_id, season=inp.season, year=year,
                 layers=",".join(sorted(set(inp.layers))), acres=inp.acreage,
                 sum_insured_per_acre=q["sum_insured_kes_per_acre"], gross_kes=q["gross_premium_kes"],
                 government_share_kes=q["subsidy"]["government_share_kes"],
                 farmer_share_kes=q["farmer_share_before_discount_kes"], resilience_points=q["resilience"]["points"],
                 discount_kes=q["resilience"]["discount_kes"], farmer_pays_kes=q["farmer_pays_kes"],
                 subsidy_status=q["subsidy"]["status"], payment_route=inp.payment_route,
                 loan_linked=inp.loan_linked, loan_ref=(inp.loan_ref or None) if inp.loan_linked else None,
                 quote_id=q["quote_id"], quote_snapshot=q, created_by=officer.id if officer else None)
    s.add(pol)
    s.flush()
    audit(s, actor, "policy.created", "policy", pol.id, policy_no=pol.policy_no, layers=pol.layers,
          gross_kes=pol.gross_kes, farmer_pays_kes=pol.farmer_pays_kes, quote_id=pol.quote_id, channel=channel,
          index_versions=q["basis"]["index_versions"])
    return pol


def existing_policy(s: Session, farmer: Farmer | None, ward_id: str, season: str, year: int) -> Policy | None:
    if farmer is None or farmer.id is None:
        return None
    return s.scalar(select(Policy).where(Policy.farmer_id == farmer.id, Policy.ward_id == ward_id, Policy.season == season,
                                         Policy.year == year, Policy.status != "cancelled"))


# ------------------------------------------------------------------ bulk CSV
BULK_COLUMNS = ["member_no", "full_name", "phone", "national_id", "gender", "ward_id", "acreage", "lat", "lon",
                "layers", "sum_insured_kes_per_acre", "payment_route", "loan_linked", "loan_ref",
                "consent_data_processing", "consent_sms", "consent_loan_linked_payout", "resilience"]


def _yes(v: str | None) -> bool:
    return (v or "").strip().lower() in ("yes", "y", "true", "1")


def bulk_template() -> str:
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(BULK_COLUMNS)
    w.writerow(["M-0001", "Example Farmer (fictional)", "0712 000 000", "10000001", "female", "ward-a", "2", "", "",
                "B", "10000", "sacco_deduction", "no", "", "yes", "yes", "no", "certified_seed_verified;sacco_good_standing"])
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
                resilience={x.strip(): True for x in r["resilience"].split(";") if x.strip()}))
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
        pv = preview(ctx, s, inp)
        errs = dict(pv["errors"])
        key = (inp.member_no.strip(), inp.ward_id)
        if key in seen:
            errs["member_no"] = f"duplicate of row {seen[key]} in this file"
        seen.setdefault(key, i)
        if sacco is not None and not errs:
            nid_hash = ctx.vault.lookup_hash(normalise_national_id(inp.national_id), "national_id")
            known = s.scalar(select(Farmer).where(Farmer.sacco_id == sacco.id, Farmer.national_id_hash == nid_hash))
            if existing_policy(s, known, inp.ward_id, inp.season, inp.year or next_season_year(inp.season)):
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
        "by_status": {st: sum(1 for p in pols if p.status == st) for st in ("pending_payment", "active")},
        "acres": sum(p.acres for p in pols),
        "sum_insured_kes": sum((p.sum_insured_per_acre or 0) * p.acres for p in pols),
        "gross_kes": sum(p.gross_kes for p in pols),
        "farmer_premium_due_kes": sum(p.farmer_pays_kes for p in pols if p.payment_status == "pending"),
        "subsidy_receivable_kes": sum(p.government_share_kes for p in pols if p.subsidy_status == "not yet received"),
        "with_layer_a": sum(1 for p in pols if "A" in p.layers.split(",")),
        "loan_linked": sum(1 for p in pols if p.loan_linked),
        "by_ward": sorted(by_ward.values(), key=lambda w: w["ward_id"]),
        "gender": {g: n for g, n in genders},
        # Live trigger status (and so "members in wards approaching trigger") comes with the
        # daily monitoring job in milestone 7.
        "trigger_status": {w: {"status": "not monitored yet", "note": "Daily ward monitoring arrives in milestone 7."}
                           for w in ctx.cfg.pilot.wards},
    }


def export_policies_csv(s: Session, sacco: Sacco) -> str:
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(["policy_no", "member_no", "full_name", "national_id", "phone", "ward_id", "season", "year", "layers",
                "acres", "sum_insured_per_acre", "gross_kes", "government_share_kes", "subsidy_status",
                "resilience_points", "discount_kes", "farmer_pays_kes", "payment_route", "payment_status", "status",
                "loan_linked", "loan_ref", "created_at"])
    for p in s.scalars(select(Policy).where(Policy.sacco_id == sacco.id).order_by(Policy.policy_no)):
        f = p.farmer
        w.writerow([p.policy_no, f.member_no, f.full_name, f.national_id_masked, f.phone_masked, p.ward_id, p.season,
                    p.year, p.layers, p.acres, p.sum_insured_per_acre, p.gross_kes, p.government_share_kes,
                    p.subsidy_status, p.resilience_points, p.discount_kes, p.farmer_pays_kes, p.payment_route,
                    p.payment_status, p.status, "yes" if p.loan_linked else "no", p.loan_ref or "",
                    p.created_at.isoformat(timespec="seconds")])
    return out.getvalue()
