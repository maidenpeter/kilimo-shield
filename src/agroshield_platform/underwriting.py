"""Underwriter workspace: the insurer's view of its own book (and nothing else).

Every query here is scoped to one insurer (Policy.insurer_id, set at sale from the SACCO).

    portfolio()     policies, acres, sum insured, gross premium by SACCO, ward and season; exposure per ward
    triggers()      latest index status per ward and season; payouts awaiting approval; the 10-day clock per event
    money()         premium received, outstanding, KAIP receivable, refunds owed, payouts approved and paid
    bordereaux()    monthly premium and payout bordereaux (CSV, masked) zipped with a manifest of checksums
    pricing_runs()  engine runs (index version, config hashes) and the run audit log
    reinsurer()     one-page summary: exposure, as-if loss distribution from the engine, ESG/TCFD reporting

ESG/TCFD figures are REPORTING ONLY: nothing in agroshield_pricing imports this module, so they can never feed a
price (borrowed idea #6, docs/BORROWED_FROM_MVP.md).
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import zipfile
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import AuditEvent, Insurer, MissedPayoutReport, Payment, Payout, Policy, Sacco, WardStatus
from .monitoring import latest
from .services import Context, season_label

WRITTEN = ("pending_payment", "active", "lapsed_unpaid")       # sold; "in force" is active only


def policies(s: Session, insurer_id: int) -> list[Policy]:
    return s.scalars(select(Policy).where(Policy.insurer_id == insurer_id, Policy.status != "cancelled")).all()


def _si(p: Policy) -> float:
    return (p.sum_insured_per_acre or 0) * p.acres


def _group(pols, key) -> list[dict]:
    g: dict = defaultdict(lambda: {"policies": 0, "active": 0, "acres": 0.0, "sum_insured_kes": 0.0, "gross_kes": 0.0,
                                   "in_force_sum_insured_kes": 0.0})
    for p in pols:
        r = g[key(p)]
        r["policies"] += 1
        r["acres"] += p.acres
        r["sum_insured_kes"] += _si(p)
        r["gross_kes"] += p.gross_kes
        if p.status == "active":
            r["active"] += 1
            r["in_force_sum_insured_kes"] += _si(p)
    return [{"key": k, **v} for k, v in sorted(g.items(), key=lambda kv: str(kv[0]))]


def portfolio(ctx: Context, s: Session, insurer: Insurer) -> dict:
    pols = policies(s, insurer.id)
    saccos = {x.id: x.name for x in s.scalars(select(Sacco).where(Sacco.insurer_id == insurer.id))}
    in_force = [p for p in pols if p.status == "active"]
    # Exposure: if the index fully triggers (WRSI at or below exit), every active policy in the ward pays its full
    # sum insured. Pending cover is shown too because it becomes exposure once paid by the close date.
    exposure = []
    for (w, season, y), grp in sorted(_by(pols, lambda p: (p.ward_id, p.season, p.year)).items(), key=lambda kv: (-kv[0][2], kv[0][0])):
        active = sum(_si(p) for p in grp if p.status == "active")
        pending = sum(_si(p) for p in grp if p.status == "pending_payment")
        exposure.append({"ward_id": w, "ward": ctx.cfg.ward(w).label, "season": season, "year": y,
                         "label": season_label(season, y), "max_loss_kes": active, "pending_kes": pending,
                         "policies": len([p for p in grp if p.status == "active"])})
    seasons = sorted({(e["season"], e["year"]) for e in exposure}, key=lambda x: -x[1])
    for e in exposure:
        tot = sum(x["max_loss_kes"] for x in exposure if (x["season"], x["year"]) == (e["season"], e["year"]))
        e["share_of_season"] = e["max_loss_kes"] / tot if tot else None
    return {"insurer": insurer, "policies": len(pols), "active": len(in_force),
            "acres": sum(p.acres for p in pols), "sum_insured_kes": sum(_si(p) for p in pols),
            "in_force_sum_insured_kes": sum(_si(p) for p in in_force), "gross_kes": sum(p.gross_kes for p in pols),
            "by_sacco": [{**r, "name": saccos.get(r["key"], r["key"])} for r in _group(pols, lambda p: p.sacco_id)],
            "by_ward": [{**r, "name": ctx.cfg.ward(r["key"]).label} for r in _group(pols, lambda p: p.ward_id)],
            "by_season": [{**r, "name": season_label(*r["key"])} for r in _group(pols, lambda p: (p.season, p.year))],
            "exposure": exposure, "seasons": seasons,
            "largest": max(exposure, key=lambda e: e["max_loss_kes"]) if exposure else None}


def _by(items, key) -> dict:
    out: dict = defaultdict(list)
    for i in items:
        out[key(i)].append(i)
    return out


def triggers(ctx: Context, s: Session, insurer: Insurer, today: date) -> dict:
    pols = policies(s, insurer.id)
    seasons = sorted({(p.ward_id, p.season, p.year) for p in pols}, key=lambda r: (-r[2], r[0]))
    status = [{"ward_id": w, "ward": ctx.cfg.ward(w).label, "season": season, "year": y, "st": latest(s, w, season, y),
               "active": sum(1 for p in pols if (p.ward_id, p.season, p.year) == (w, season, y) and p.status == "active")}
              for w, season, y in seasons]
    ids = [p.id for p in pols]
    pays = s.scalars(select(Payout).where(Payout.policy_id.in_(ids)).order_by(Payout.due_by, Payout.id)).all() if ids else []
    events = []
    for sid, grp in _by(pays, lambda p: p.ward_status_id).items():
        st = s.get(WardStatus, sid)
        ref = st.as_of if st.mode == "replay" else today          # a replay is judged on its own calendar
        due = min(p.due_by for p in grp)
        open_ = [p for p in grp if p.status in ("calculated", "held", "approved")]
        events.append({"st": st, "ward": ctx.cfg.ward(st.ward_id).label, "label": season_label(st.season, st.year),
                       "confirmed_on": st.as_of, "due_by": due, "days_left": (due - ref).days, "open": len(open_),
                       "count": len(grp), "amount_kes": sum(p.amount_kes for p in grp),
                       "by_status": {k: len(v) for k, v in _by(grp, lambda p: p.status).items()},
                       "done": not open_})
    return {"status": status, "pending": [p for p in pays if p.status in ("calculated", "held")],
            "approved": [p for p in pays if p.status == "approved"], "events": sorted(events, key=lambda e: e["due_by"])}


def money(s: Session, insurer: Insurer) -> dict:
    pols = policies(s, insurer.id)
    ids = [p.id for p in pols]
    pays = s.scalars(select(Payment).where(Payment.policy_id.in_(ids))).all() if ids else []
    payouts = s.scalars(select(Payout).where(Payout.policy_id.in_(ids))).all() if ids else []
    saccos = {x.id: x.name for x in s.scalars(select(Sacco).where(Sacco.insurer_id == insurer.id))}
    by_sacco = defaultdict(lambda: {"farmer_kes": 0.0, "mpesa_kes": 0.0, "sacco_deduction_kes": 0.0, "due_kes": 0.0,
                                    "subsidy_kes": 0.0, "refunds_kes": 0.0, "gross_kes": 0.0})
    by_policy = {p.id: p for p in pols}
    for pm in pays:
        r = by_sacco[by_policy[pm.policy_id].sacco_id]
        r["farmer_kes"] += pm.amount_kes
        r["mpesa_kes" if pm.method == "mpesa" else "sacco_deduction_kes"] += pm.amount_kes
    for p in pols:
        r = by_sacco[p.sacco_id]
        r["gross_kes"] += p.gross_kes
        r["refunds_kes"] += p.refund_due_kes
        if p.status == "pending_payment":
            r["due_kes"] += p.balance_kes
        if p.subsidy_status == "not yet received" and p.status != "lapsed_unpaid":
            r["subsidy_kes"] += p.government_share_kes
    rows = [{"name": saccos.get(k, k), **v} for k, v in by_sacco.items()]
    tot = {k: sum(r[k] for r in rows) for k in ("farmer_kes", "mpesa_kes", "sacco_deduction_kes", "due_kes",
                                                 "subsidy_kes", "refunds_kes", "gross_kes")}
    return {"rows": rows, "total": tot,
            "payouts": {st: sum(p.amount_kes for p in payouts if p.status == st)
                        for st in ("calculated", "held", "approved", "issued", "paid", "redeemed")}}


# ------------------------------------------------------------------ bordereaux
PREMIUM_COLS = ["policy_no", "insurer_policy_number", "sacco", "member_no", "national_id", "phone", "ward_id", "season",
                "year", "layers", "acres", "sum_insured_kes", "gross_premium_kes", "government_share_kes", "subsidy_status",
                "farmer_share_kes", "resilience_discount_kes", "discount_funder", "farmer_paid_kes", "status",
                "written_on", "cover_active_from", "index_version"]
PAYOUT_COLS = ["policy_no", "insurer_policy_number", "sacco", "member_no", "national_id", "phone", "ward_id", "season",
               "year", "kind", "share_of_sum_insured", "amount_kes", "index_version", "confirmed_on", "due_by", "status",
               "approved_by", "approved_at", "method", "reference", "paid_at"]


def _month_bounds(month: str) -> tuple[date, date]:
    y, m = (int(x) for x in month.split("-"))
    start = date(y, m, 1)
    return start, date(y + (m == 12), m % 12 + 1, 1)


def bordereaux(s: Session, insurer: Insurer, month: str, cfg_hashes: dict) -> tuple[bytes, dict]:
    """ZIP of premium.csv (policies written in the month) and payouts.csv (payouts confirmed in the month),
    with manifest.json holding each file's SHA-256 and row count. IDs and phones are masked."""
    start, end = _month_bounds(month)
    pols = policies(s, insurer.id)
    saccos = {x.id: x.code for x in s.scalars(select(Sacco))}
    written = [p for p in pols if start <= p.created_at.date() < end]

    def out(cols, rows) -> bytes:
        b = io.StringIO()
        w = csv.writer(b, lineterminator="\n")
        w.writerow(cols)
        w.writerows(rows)
        return b.getvalue().encode()

    prem = out(PREMIUM_COLS, [[p.policy_no, p.insurer_policy_number or "", saccos.get(p.sacco_id), p.farmer.member_no,
                               p.farmer.national_id_masked, p.farmer.phone_masked, p.ward_id, p.season, p.year, p.layers,
                               p.acres, _si(p), p.gross_kes, p.government_share_kes, p.subsidy_status, p.farmer_share_kes,
                               p.discount_kes, p.discount_funder, p.paid_kes, p.status, p.created_at.date().isoformat(),
                               p.cover_active_from.isoformat(timespec="seconds") if p.cover_active_from else "",
                               p.quote_snapshot.get("basis", {}).get("index_versions", {}).get("layer_b", "")]
                              for p in sorted(written, key=lambda p: p.policy_no)])
    ids = [p.id for p in pols]
    pos = s.scalars(select(Payout).where(Payout.policy_id.in_(ids))).all() if ids else []
    confirmed = sorted((p for p in pos if start <= p.confirmed_on < end), key=lambda p: (p.policy.policy_no, p.kind))
    pay = out(PAYOUT_COLS, [[p.policy.policy_no, p.policy.insurer_policy_number or "", saccos.get(p.policy.sacco_id),
                             p.policy.farmer.member_no, p.policy.farmer.national_id_masked, p.policy.farmer.phone_masked,
                             p.policy.ward_id, p.policy.season, p.policy.year, p.kind, p.share if p.share is not None else "",
                             p.amount_kes, p.index_version, p.confirmed_on.isoformat(), p.due_by.isoformat(), p.status,
                             p.approved_by or "", p.approved_at.isoformat(timespec="seconds") if p.approved_at else "",
                             p.method, p.reference or "", p.paid_at.isoformat(timespec="seconds") if p.paid_at else ""]
                            for p in confirmed])
    manifest = {"insurer": insurer.code, "month": month, "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "files": {"premium.csv": {"sha256": hashlib.sha256(prem).hexdigest(), "rows": len(written)},
                          "payouts.csv": {"sha256": hashlib.sha256(pay).hexdigest(), "rows": len(confirmed)}},
                "basis": {"premium": "policies written (enrolled) in the month",
                          "payouts": "payouts whose trigger was confirmed in the month"},
                "masking": "national IDs and phone numbers are masked; no personal data in clear",
                "config_sha256": cfg_hashes, "illustrative": True}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("premium.csv", prem)
        z.writestr("payouts.csv", pay)
        z.writestr("manifest.json", json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return buf.getvalue(), manifest


def months_with_activity(s: Session, insurer: Insurer) -> list[str]:
    pols = policies(s, insurer.id)
    ids = [p.id for p in pols]
    ms = {p.created_at.strftime("%Y-%m") for p in pols}
    if ids:
        ms |= {p.confirmed_on.strftime("%Y-%m") for p in s.scalars(select(Payout).where(Payout.policy_id.in_(ids)))}
    return sorted(ms, reverse=True)


# ------------------------------------------------------------------ pricing runs and audit
def pricing_runs(repo: Path) -> list[dict]:
    out = []
    for m in sorted((repo / "runs").glob("*/manifest.json"), reverse=True):
        d = json.loads(m.read_text(encoding="utf-8"))
        out.append({"run_id": d["run_id"], "created_at": d["created_at"], "ward_id": d.get("ward_id"),
                    "index_version": d.get("index_version"), "command": d.get("command"),
                    "config_sha256": d.get("config_sha256", {}), "results_sha256": d.get("results_sha256"),
                    "git": d.get("git", {}), "rainfall_label": d.get("rainfall", {}).get("label"),
                    "pet_source": d.get("pet", {}).get("source"), "has_report": (m.parent / "report.html").exists()})
    return out


def run_log(repo: Path, limit: int = 100) -> list[dict]:
    p = repo / "runs" / "audit_log.jsonl"
    if not p.exists():
        return []
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()][-limit:][::-1]


PUBLIC_ACTIONS = ("trigger.calculated",)              # ward-level, no book data


def audit_events(s: Session, insurer: Insurer, limit: int = 200) -> list[AuditEvent]:
    """Ward-level trigger runs, plus policy and payout events on this insurer's own policies only."""
    ids = {p.id for p in policies(s, insurer.id)}
    rows = s.scalars(select(AuditEvent).where(AuditEvent.action.in_(PUBLIC_ACTIONS) | AuditEvent.action.like("payout.%")
                                              | AuditEvent.action.like("policy.%") | AuditEvent.action.like("payment.%"))
                     .order_by(AuditEvent.at.desc()).limit(limit * 5)).all()
    return [e for e in rows if e.action in PUBLIC_ACTIONS or e.entity_id in ids][:limit]


# ------------------------------------------------------------------ reinsurer summary
def as_if_losses(ctx: Context, s: Session, insurer: Insurer, tables: dict, season: str, year: int) -> dict:
    """The current in-force book run through every historical season of the engine (1981-2025 CHIRPS):
    each year's per-ward payout share times today's sum insured in that ward. Gives expected loss and the
    1-in-10 and 1-in-20 annual loss for the portfolio, with ward correlation kept (same years)."""
    pols = [p for p in policies(s, insurer.id) if (p.season, p.year) == (season, year)
            and p.status in ("active", "pending_payment")]
    si = defaultdict(float)
    for p in pols:
        si[p.ward_id] += _si(p)
    years = sorted(set.intersection(*[set(tables[w].index) for w in si])) if si else []
    per_year = {y: sum(float(tables[w].loc[y, "payout_share"]) * si[w] for w in si) for y in years}
    losses = np.array(list(per_year.values())) if per_year else np.array([0.0])
    ward_rows = []
    for w, amount in sorted(si.items()):
        sh = tables[w].loc[years, "payout_share"].to_numpy() if years else np.array([0.0])
        ward_rows.append({"ward_id": w, "ward": ctx.cfg.ward(w).label, "sum_insured_kes": amount,
                          "expected_loss_kes": float(sh.mean() * amount), "loss_1_in_10_kes": float(np.quantile(sh, 0.9) * amount),
                          "loss_1_in_20_kes": float(np.quantile(sh, 0.95) * amount), "payout_frequency": float((sh > 0).mean())})
    worst = sorted(per_year.items(), key=lambda kv: -kv[1])[:3]
    return {"season": season, "year": year, "label": season_label(season, year), "sum_insured_kes": sum(si.values()),
            "seasons": len(years), "years": [years[0], years[-1]] if years else None,
            "expected_loss_kes": float(losses.mean()), "loss_1_in_10_kes": float(np.quantile(losses, 0.9)),
            "loss_1_in_20_kes": float(np.quantile(losses, 0.95)), "max_kes": float(losses.max()),
            "worst_years": [{"year": int(y), "loss_kes": v} for y, v in worst], "wards": ward_rows,
            "gross_premium_kes": sum(p.gross_kes for p in pols)}


def esg(s: Session, insurer: Insurer, target_days: int) -> dict:
    """ESG / TCFD-style REPORTING for reinsurers and climate funds. Never an input to pricing."""
    pols = policies(s, insurer.id)
    farmers = {p.farmer_id: p.farmer for p in pols}
    ids = [p.id for p in pols]
    pos = s.scalars(select(Payout).where(Payout.policy_id.in_(ids))).all() if ids else []
    paid = [p for p in pos if p.status in ("paid", "redeemed") and p.paid_at]
    # A replayed past season is confirmed on its own (past) calendar but paid today: its timing means nothing.
    live = [p for p in paid if p.ward_status.mode != "replay"]
    days = [(p.paid_at.date() - p.confirmed_on).days for p in live]
    genders = defaultdict(int)
    for f in farmers.values():
        genders[f.gender] += 1
    return {"farmers": len(farmers), "women_share": genders["female"] / len(farmers) if farmers else None,
            "gender": dict(genders),
            "smallholder_share": sum(1 for p in pols if p.acres <= 5) / len(pols) if pols else None,
            "subsidised_share": sum(1 for p in pols if p.government_share_kes > 0) / len(pols) if pols else None,
            "loan_linked_share": sum(1 for p in pols if p.loan_linked) / len(pols) if pols else None,
            "payouts_paid": len(paid), "paid_to_farmers_kes": sum(p.amount_kes for p in paid),
            "median_days_to_pay": float(np.median(days)) if days else None,
            "within_target": sum(1 for d in days if d <= target_days) / len(days) if days else None,
            "target_days": target_days, "replay_excluded": len(paid) - len(live),
            "resilience_points_share": sum(1 for p in pols if p.resilience_points > 0) / len(pols) if pols else None,
            "missed_reports": len(s.scalars(select(MissedPayoutReport).where(MissedPayoutReport.policy_id.in_(ids))).all())
            if ids else 0}
