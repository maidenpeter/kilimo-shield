"""SACCO-to-insurer premium settlement: a record of what each SACCO collected from members and sent on to the insurer.

This is a ledger only. It moves no money and never changes a policy, a payment or a payout.

    collected    farmer premium recorded against the SACCO's policies for this insurer (M-Pesa and SACCO deduction)
    remitted     what the SACCO says it sent: amount, date, method and the bank or M-Pesa reference
    outstanding  collected minus remitted (never shown below zero; an over-remittance is shown as a credit)

A SACCO manager records a remittance; the insurer's underwriter confirms it arrived or queries it with a reason.
Entries are never edited or deleted: a mistake is reversed by a new negative entry, and every step is audited.
Open question for approval: whether the SACCO deducts its distribution fee before remitting (docs/overnight/REVIEW.md).
"""
from __future__ import annotations

import re
import secrets
from collections import defaultdict
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .crypto import scrub
from .db import audit
from .models import Officer, Payment, Policy, PremiumRemittance, Sacco

METHODS = {"bank_transfer": "Bank transfer", "mpesa": "M-Pesa", "cheque": "Cheque", "other": "Other"}
_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ./_-]{2,39}$")


class SettlementError(ValueError):
    """A problem the person can fix; the message is shown on the form."""


def _parse_amount(raw: str) -> float:
    t = (raw or "").strip().replace(",", "").replace(" ", "")
    t = t[3:] if t.upper().startswith("KES") else t
    try:
        v = round(float(t), 2)
    except ValueError:
        raise SettlementError("Enter the amount in shillings, for example 12500.") from None
    if v == 0 or abs(v) > 100_000_000:
        raise SettlementError("Enter an amount above zero (or below zero to reverse an earlier entry).")
    return v


def record(s: Session, off: Officer, amount: str, remitted_on: str, method: str, reference: str, note: str = "",
           period: str = "", today: date | None = None) -> PremiumRemittance:
    """A SACCO manager records money sent to the SACCO's insurer."""
    if off.role != "manager" or off.sacco is None:
        raise SettlementError("Only a SACCO manager can record a remittance.")
    if off.sacco.insurer_id is None:
        raise SettlementError("This SACCO is not linked to an insurer yet.")
    value = _parse_amount(amount)
    try:
        on = date.fromisoformat(remitted_on)
    except ValueError:
        raise SettlementError("Enter the date the money was sent.") from None
    if on > (today or date.today()):
        raise SettlementError("The date cannot be in the future.")
    if method not in METHODS:
        raise SettlementError("Choose how the money was sent.")
    ref = " ".join((reference or "").split())
    if not _REF.match(ref):
        raise SettlementError("Enter the bank or M-Pesa reference (3 to 40 letters and numbers).")
    if s.scalar(select(PremiumRemittance).where(PremiumRemittance.sacco_id == off.sacco_id,
                                                PremiumRemittance.reference == ref, PremiumRemittance.amount_kes == value)):
        raise SettlementError("A remittance with this reference and amount is already recorded.")
    r = PremiumRemittance(ref="RM-" + secrets.token_hex(3).upper(), sacco_id=off.sacco_id, insurer_id=off.sacco.insurer_id,
                          amount_kes=value, remitted_on=on, method=method, reference=ref,
                          period=(period or "").strip()[:20] or None, note=(scrub(note.strip())[:300] or None),
                          recorded_by=off.username)
    s.add(r)
    s.flush()
    audit(s, off.username, "remittance.recorded", "premium_remittance", r.ref, amount_kes=value, remitted_on=on.isoformat(),
          method=method, reference=ref, sacco=off.sacco.code)
    return r


def review(s: Session, off: Officer, ref: str, decision: str, note: str = "") -> PremiumRemittance:
    """The insurer's underwriter confirms receipt, or queries the entry with a reason."""
    r = s.scalar(select(PremiumRemittance).where(PremiumRemittance.ref == ref))
    if off.role != "underwriter" or r is None or r.insurer_id != off.insurer_id:
        raise SettlementError("No such remittance for your insurer.")
    if decision not in ("confirmed", "queried"):
        raise SettlementError("Choose confirm or query.")
    if r.status == "confirmed":
        raise SettlementError("This remittance is already confirmed.")
    note = scrub((note or "").strip())[:300]
    if decision == "queried" and not note:
        raise SettlementError("Say what is wrong so the SACCO can check.")
    r.status, r.reviewed_by, r.reviewed_at, r.review_note = decision, off.username, datetime.now(timezone.utc), note or None
    audit(s, off.username, f"remittance.{decision}", "premium_remittance", r.ref, amount_kes=r.amount_kes, note=note)
    return r


def summary(s: Session, insurer_id: int, sacco_id: int | None = None) -> dict:
    """Collected, remitted and outstanding per SACCO, plus the ledger. sacco_id limits it to one SACCO (managers)."""
    q = select(Sacco).where(Sacco.insurer_id == insurer_id)
    if sacco_id is not None:
        q = q.where(Sacco.id == sacco_id)
    saccos = list(s.scalars(q.order_by(Sacco.name)))
    ids = [x.id for x in saccos]
    collected = defaultdict(float)
    last_paid = {}
    if ids:
        for pm, sid in s.execute(select(Payment, Policy.sacco_id).join(Policy, Payment.policy_id == Policy.id)
                                 .where(Policy.sacco_id.in_(ids), Policy.insurer_id == insurer_id)):
            collected[sid] += pm.amount_kes
            last_paid[sid] = max(last_paid.get(sid, pm.received_at), pm.received_at)
    ledger = list(s.scalars(select(PremiumRemittance).where(PremiumRemittance.insurer_id == insurer_id,
                                                            PremiumRemittance.sacco_id.in_(ids or [-1]))
                            .order_by(PremiumRemittance.remitted_on.desc(), PremiumRemittance.id.desc())))
    rows = []
    for x in saccos:
        mine = [r for r in ledger if r.sacco_id == x.id]
        remitted = round(sum(r.amount_kes for r in mine), 2)
        confirmed = round(sum(r.amount_kes for r in mine if r.status == "confirmed"), 2)
        col = round(collected[x.id], 2)
        rows.append({"sacco": x, "collected_kes": col, "remitted_kes": remitted, "confirmed_kes": confirmed,
                     "unconfirmed_kes": round(remitted - confirmed, 2), "outstanding_kes": max(0.0, round(col - remitted, 2)),
                     "credit_kes": max(0.0, round(remitted - col, 2)), "queried": sum(1 for r in mine if r.status == "queried"),
                     "last_remitted_on": max((r.remitted_on for r in mine), default=None), "last_collected_at": last_paid.get(x.id)})
    tot = {k: round(sum(r[k] for r in rows), 2) for k in ("collected_kes", "remitted_kes", "confirmed_kes", "unconfirmed_kes",
                                                           "outstanding_kes", "credit_kes")}
    tot["queried"] = sum(r["queried"] for r in rows)
    return {"rows": rows, "total": tot, "ledger": ledger, "saccos": {x.id: x for x in saccos}}
