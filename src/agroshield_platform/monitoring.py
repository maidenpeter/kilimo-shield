"""Daily ward monitoring, the Payout Tracker and missed-payout reports.

    run_monitoring()  for each pilot ward: index status on the latest data (agroshield_pricing.monitor),
                      stored and audited; CONFIRMED triggers create payouts for active cover
    approve() / hold()  the underwriter approves each calculated payout or holds it with a reason (audited);
                      the farmer is told only once it is approved
    pay()             pay an approved payout (M-Pesa B2C, or credit to the SACCO loan); mark a voucher used
    report_missed()   a farmer says the crop failed but the payout did not match: recorded and
                      reviewed, never changes a payout (basis-risk channel)

Payouts are due within `monitoring.payout_within_days` of the day the index confirmed.
Only policies whose cover was ACTIVE are paid. Nothing here reads the weather module.
"""
from __future__ import annotations

import logging
import secrets
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from agroshield_pricing.monitor import LEVELS, ward_status
from agroshield_pricing.pet import make_pet_source
from agroshield_pricing.rainfall import make_source
from agroshield_pricing.rainfall.chirps import fetch_chunk, ward_geometry

from . import sms
from .crypto import scrub
from .db import audit
from .models import Farmer, MissedPayoutReport, Payout, Policy, WardStatus
from .services import NAIROBI, Context

log = logging.getLogger("agroshield.monitoring")
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
ALERT_LEVELS = ("watch", "alert", "payout")
MISSED_CATEGORIES = ("failed_no_payout", "payout_too_small", "other")
REVIEW_OUTCOMES = ("matched_local_conditions", "basis_risk_recorded", "data_problem", "other")


class PayoutError(ValueError):
    pass


# ------------------------------------------------------------------ data
def season_for(cfg, ward_id: str, season: str, as_of: date) -> int:
    """The planting year worth watching on a date: this year's season until it can have ended, then next year's."""
    cal = cfg.calendar(ward_id, season)
    m, d = (int(x) for x in cal.planting_window.end.split("-"))
    extra = cfg.product.layer_b.germination_dry_spell.restart_search_extra_dekads
    latest_end = date(as_of.year, m, d) + timedelta(days=10 * (cal.lgp_dekads + extra + 1))
    return as_of.year if as_of <= latest_end else as_of.year + 1


def _fetch_live(cfg, dataset: str, ward, start: date, as_of: date) -> pd.Series:
    """Download observed rain for monitoring from the dataset that monitors this season."""
    if dataset == "chirps3":
        src = make_source(cfg, "chirps3", allow_download=True, log=log.info)
        return src.fetch_range(ward, f"{start:%Y-%m-%d}", f"{as_of:%Y-%m-%d}")
    return fetch_chunk(ward_geometry(ward), f"{start:%m/%d/%Y}", f"{as_of:%m/%d/%Y}", log=log.info)


def _live_rain(cfg, ward, year: int, as_of: date, allow_download: bool, dataset: str = "chirps") -> pd.Series:
    """Rain for a year beyond the committed history, cached under monitoring.live_cache_dir.

    CHIRPS v3 live data is cached apart from v2 (<ward>_<year>.chirps3.csv): the two
    datasets must never be mixed in one season's series.
    """
    suffix = "" if dataset == "chirps" else f".{dataset}"
    path = Path(cfg.root).parent / cfg.monitoring.live_cache_dir / f"{ward.id}_{year}{suffix}.csv"
    cached = pd.read_csv(path, parse_dates=["date"]).set_index("date")["rain_mm"] if path.exists() else pd.Series(dtype=float)
    fresh_enough = len(cached) and cached.index.max() >= pd.Timestamp(as_of) - pd.Timedelta(days=1)
    if allow_download and not fresh_enough:
        start = date(year - 1, 10, 1)
        try:
            got = _fetch_live(cfg, dataset, ward, start, as_of)
            path.parent.mkdir(parents=True, exist_ok=True)
            got.rename("rain_mm").rename_axis("date").to_csv(path, lineterminator="\n")
            cached = got
        except Exception as e:                     # monitoring degrades to "data unavailable", never guesses
            log.warning("%s live fetch failed for %s: %s", dataset.upper(), ward.id, type(e).__name__)
    return cached


def ward_inputs(cfg, ward_id: str, year: int, as_of: date, allow_download: bool = False) -> tuple[pd.Series, pd.Series]:
    """Rain and PET for monitoring one season.

    The rainfall dataset follows the season (rainfall.monitoring_source): seasons
    planted from rainfall.monitoring_chirps3_from_year on read CHIRPS v3.0 for both
    the history (climatology) and the observed days, because CHIRPS v2 stops after
    December 2026. Earlier seasons keep the configured source (CHIRPS v2 history).
    """
    ward, hist = cfg.ward(ward_id), cfg.rainfall.history
    dataset = cfg.rainfall.monitoring_source(year)
    src = make_source(cfg, dataset, allow_download=False)
    rain = src.daily(ward, hist.start_year, hist.end_year)
    if hasattr(src, "latest"):                       # CHIRPS v3 cache can run past the history window
        extra = src.latest(ward)
        rain = pd.concat([rain, extra[extra.index > rain.index.max()]])
    pet = make_pet_source(cfg, allow_download=False).daily(ward, hist.start_year, hist.end_year)
    if year > hist.end_year or as_of > date(hist.end_year, 12, 31):
        live = _live_rain(cfg, ward, year, as_of, allow_download, dataset)
        if len(live):
            rain = pd.concat([rain, live[live.index > rain.index.max()]])
    rain.attrs["dataset"] = dataset
    return rain, pet


# ------------------------------------------------------------------ monitoring
def run_monitoring(ctx: Context, s: Session, as_of: date | None = None, mode: str = "live",
                   year: int | None = None, wards: list[str] | None = None, season: str = "LR",
                   allow_download: bool = False) -> list[WardStatus]:
    cfg = ctx.cfg
    as_of = as_of or ctx.date()
    out = []
    for wid in wards or cfg.pilot.wards:
        y = year or season_for(cfg, wid, season, as_of)
        rain, pet = ward_inputs(cfg, wid, y, as_of, allow_download and mode == "live")
        r = ward_status(cfg, wid, season, y, as_of, rain, pet)
        r["rainfall_dataset"] = rain.attrs.get("dataset", cfg.rainfall.source)
        st = WardStatus(ward_id=wid, season=season, year=y, as_of=as_of, mode=mode, phase=r["phase"], level=r["level"],
                        data_through=date.fromisoformat(r["data_through"]) if r["data_through"] else None,
                        projected_wrsi=r.get("projected_wrsi"), projected_share=r.get("projected_share", 0.0),
                        index_version=r["index_version"], inputs_sha256=r.get("inputs_sha256"), result=r)
        s.add(st)
        s.flush()
        audit(s, "monitor", "trigger.calculated", "ward_status", str(st.id), ward=wid, season=season, year=y, mode=mode,
              phase=st.phase, level=st.level, confirmed=r["confirmed"], index_versions=r["index_version"],
              rainfall_dataset=r["rainfall_dataset"],
              source_sha256=r.get("inputs_sha256"), file_sha256=r["config_sha256"].get("product.yaml"))
        apply_confirmed(ctx, s, st)
        out.append(st)
    return out


def _code(s: Session) -> str:
    while True:
        c = "V-" + "".join(secrets.choice(CODE_ALPHABET) for _ in range(6))
        if not s.scalar(select(Payout).where(Payout.voucher_code == c)):
            return c


def apply_confirmed(ctx: Context, s: Session, st: WardStatus) -> list[Payout]:
    """Payouts for every ACTIVE policy in the ward and season, from confirmed triggers only. Idempotent."""
    ev = st.result.get("events", {})
    if not ev:
        return []
    mon, lb = ctx.cfg.monitoring, ctx.cfg.product.layer_b
    confirmed_on = st.as_of
    due = confirmed_on + timedelta(days=mon.payout_within_days)
    made = []
    pols = s.scalars(select(Policy).where(Policy.ward_id == st.ward_id, Policy.season == st.season,
                                          Policy.year == st.year, Policy.status == "active")).all()
    for pol in pols:
        have = {p.kind: p for p in s.scalars(select(Payout).where(Payout.policy_id == pol.id))}
        cap = (pol.sum_insured_per_acre or 0) * pol.acres
        if "germination_dry_spell" in ev and "replant_voucher" not in have:
            amt = round(ev["germination_dry_spell"]["voucher_kes_per_acre"] * pol.acres, 2)
            p = Payout(policy_id=pol.id, kind="replant_voucher", amount_kes=amt, ward_status_id=st.id,
                       index_version=st.index_version, confirmed_on=confirmed_on, due_by=due, method="voucher")
            s.add(p)
            have[p.kind] = p
            made.append(p)
        for kind in ("failed_onset", "wrsi_final"):
            if kind not in ev or ev[kind]["share"] <= 0:
                continue
            key = "failed_onset" if kind == "failed_onset" else "wrsi"
            if key in have:
                continue
            already = sum(x.amount_kes for x in have.values())
            amt = round(max(0.0, min(ev[kind]["share"] * cap, cap - already)), 2)
            if amt <= 0:
                continue
            p = Payout(policy_id=pol.id, kind=key, share=ev[kind]["share"], amount_kes=amt, ward_status_id=st.id,
                       index_version=st.index_version, confirmed_on=confirmed_on, due_by=due,
                       method="sacco_loan" if pol.loan_linked else "mpesa")
            s.add(p)
            have[key] = p
            made.append(p)
    s.flush()
    for p in made:
        audit(s, "monitor", "payout.calculated", "policy", p.policy_id, policy_no=p.policy.policy_no, kind=p.kind,
              amount_kes=p.amount_kes, index_versions=p.index_version, ward_status=st.id)
    return made


# ------------------------------------------------------------------ underwriter approval
def approve(ctx: Context, s: Session, p: Payout, actor: str) -> Payout:
    if p.status not in ("calculated", "held"):
        raise PayoutError(f"only a calculated or held payout can be approved (this one is {p.status})")
    p.approved_by, p.approved_at, p.hold_reason = actor, datetime.now(timezone.utc), None
    mon = ctx.cfg.monitoring
    if p.method == "voucher":
        p.status, p.voucher_code = "issued", p.voucher_code or _code(s)
        sms.queue(s, p.policy.farmer, "voucher_issued", p.policy, dedupe_key=f"voucher:{p.id}",
                  amount=f"{p.amount_kes:,.0f}", code=p.voucher_code,
                  expires=(p.confirmed_on + timedelta(days=mon.voucher_valid_days)).strftime("%d/%m/%Y"))
    else:
        p.status = "approved"
        sms.queue(s, p.policy.farmer, "payout_calculated", p.policy, dedupe_key=f"payout:{p.id}",
                  amount=f"{p.amount_kes:,.0f}", by=p.due_by.strftime("%d/%m/%Y"))
    audit(s, actor, "payout.approved", "policy", p.policy_id, policy_no=p.policy.policy_no, kind=p.kind,
          amount_kes=p.amount_kes)
    return p


def hold(s: Session, p: Payout, reason: str, actor: str) -> Payout:
    reason = scrub((reason or "").strip())[:300]
    if not reason:
        raise PayoutError("a reason is required to hold a payout")
    if p.status not in ("calculated", "held", "approved"):
        raise PayoutError(f"a {p.status} payout cannot be held")
    p.status, p.hold_reason, p.approved_by, p.approved_at = "held", reason, None, None
    audit(s, actor, "payout.held", "policy", p.policy_id, policy_no=p.policy.policy_no, kind=p.kind, reason=reason)
    return p


def latest(s: Session, ward_id: str, season: str, year: int) -> WardStatus | None:
    return s.scalar(select(WardStatus).where(WardStatus.ward_id == ward_id, WardStatus.season == season,
                                             WardStatus.year == year).order_by(WardStatus.as_of.desc(), WardStatus.id.desc()))


def sacco_seasons(s: Session, sacco_id: int) -> list[tuple[str, str, int]]:
    """(ward, season, year) for which this SACCO has cover sold, newest first."""
    rows = s.execute(select(Policy.ward_id, Policy.season, Policy.year).where(Policy.sacco_id == sacco_id,
                                                                              Policy.status != "cancelled").distinct()).all()
    return sorted({tuple(r) for r in rows}, key=lambda r: (-r[2], r[0]))


def alerts_for(s: Session, sacco_id: int) -> list[WardStatus]:
    """The latest status for each ward and season with cover, where there is something to say."""
    out = []
    for w, season, y in sacco_seasons(s, sacco_id):
        st = latest(s, w, season, y)
        if st and st.level in ALERT_LEVELS:
            out.append(st)
    return sorted(out, key=lambda x: -LEVELS.index(x.level))


# ------------------------------------------------------------------ paying
def pay(ctx: Context, s: Session, p: Payout, actor: str, reference: str | None = None) -> Payout:
    if p.status in ("paid", "redeemed"):
        raise PayoutError("already paid")
    if p.status not in ("approved", "issued"):
        raise PayoutError("waiting for the insurer's approval" if p.status == "calculated"
                          else f"held by the insurer: {p.hold_reason}")
    if p.method == "voucher":
        ref = (reference or "").strip()
        if not ref:
            raise PayoutError("enter the agro-dealer's reference to mark the voucher redeemed")
        p.status, p.reference = "redeemed", ref[:40]
    elif p.method == "sacco_loan":
        ref = (reference or "").strip()
        if not ref:
            raise PayoutError("enter the SACCO reference for the loan credit")
        p.status, p.reference = "paid", ref[:40]
    else:
        if ctx.mpesa is None or not hasattr(ctx.mpesa, "b2c"):
            raise PayoutError("M-Pesa payouts are not configured")
        phone = ctx.vault.decrypt(p.policy.farmer.phone_enc, "phone")
        p.reference = ctx.mpesa.b2c(phone, int(round(p.amount_kes)), f"AgroShield payout {p.policy.pay_ref}")
        p.status = "paid"
    p.paid_at, p.paid_by = datetime.now(timezone.utc), actor
    s.flush()
    late = (p.paid_at.astimezone(NAIROBI).date() - p.due_by).days
    audit(s, actor, "payout.paid", "policy", p.policy_id, policy_no=p.policy.policy_no, kind=p.kind, method=p.method,
          amount_kes=p.amount_kes, days_late=max(0, late))
    if p.method != "voucher":
        sms.queue(s, p.policy.farmer, "payout_paid_loan" if p.method == "sacco_loan" else "payout_paid", p.policy,
                  dedupe_key=f"paid:{p.id}", amount=f"{p.amount_kes:,.0f}", ref=p.reference or "",
                  loan=p.policy.loan_ref or "")
    return p


def overdue(p: Payout, today: date) -> bool:
    return p.status in ("calculated", "approved", "held") and today > p.due_by


# ------------------------------------------------------------------ missed-payout reports (basis risk)
def report_missed(ctx: Context, s: Session, farmer: Farmer, category: str, channel: str, actor: str,
                  note: str | None = None) -> MissedPayoutReport:
    if category not in MISSED_CATEGORIES:
        raise ValueError(f"category must be one of {', '.join(MISSED_CATEGORIES)}")
    pol = s.scalar(select(Policy).where(Policy.farmer_id == farmer.id, Policy.status != "cancelled")
                   .order_by(Policy.year.desc(), Policy.created_at.desc()))
    ward, season, year = (pol.ward_id, pol.season, pol.year) if pol else (farmer.ward_id, "LR", ctx.date().year)
    st = latest(s, ward, season, year)
    snap = {"as_of": str(st.as_of), "level": st.level, "phase": st.phase, "projected_wrsi": st.projected_wrsi,
            "index_version": st.index_version} if st else {}
    while True:
        ref = "MP-" + "".join(secrets.choice(CODE_ALPHABET) for _ in range(6))
        if not s.scalar(select(MissedPayoutReport).where(MissedPayoutReport.ref == ref)):
            break
    r = MissedPayoutReport(ref=ref, farmer_id=farmer.id, policy_id=pol.id if pol else None, ward_id=ward, season=season,
                           year=year, category=category, channel=channel, reported_by=actor,
                           note=scrub(note.strip())[:500] if note and note.strip() else None, index_snapshot=snap)
    s.add(r)
    s.flush()
    audit(s, actor, "missed_payout.reported", "farmer", farmer.id, ref=ref, category=category, channel=channel)
    return r


def review_missed(s: Session, r: MissedPayoutReport, outcome: str, note: str, actor: str) -> MissedPayoutReport:
    if outcome not in REVIEW_OUTCOMES:
        raise ValueError(f"outcome must be one of {', '.join(REVIEW_OUTCOMES)}")
    r.status, r.outcome = "reviewed", outcome
    r.review_note = scrub((note or "").strip())[:500] or None
    r.reviewed_by, r.reviewed_at = actor, datetime.now(timezone.utc)
    audit(s, actor, "missed_payout.reviewed", "farmer", r.farmer_id, ref=r.ref, outcome=outcome)
    return r


def ward_key(st: WardStatus | None) -> str:
    """Which plain-language line (locales `ward.*`) describes a ward status."""
    if st is None:
        return "before_season"
    r, conf = st.result, st.result.get("confirmed", [])
    if "wrsi_final" in conf or "failed_onset" in conf:
        if st.projected_share > 0:
            return "payout_done"
        return "replant" if "germination_dry_spell" in conf else "ended_no_payout"
    if "germination_dry_spell" in conf:
        return "replant"
    if st.level in ("watch", "alert"):
        return st.level
    if r["phase"] in ("before_season", "data_unavailable", "waiting_for_rains"):
        return r["phase"]
    return "normal"
