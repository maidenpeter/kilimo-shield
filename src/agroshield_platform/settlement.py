"""SACCO-to-insurer premium settlement: a record of what each SACCO collected from members and sent on to the insurer.

This is a ledger only. It moves no money and never changes a policy, a payment or a payout.

    collected    GROSS farmer premium received on the SACCO's policies for this insurer (M-Pesa and SACCO
                 deduction), before any refund
    remitted     what the SACCO says it sent: amount, date, method and the bank or M-Pesa reference
    outstanding  collected minus remitted (never shown below zero; an over-remittance is shown as a credit)
    refunds      owed back to farmers (overpaid, or paid after the sales close) and refunds actually paid,
                 tracked separately: they are not netted out of collected or of what is remitted

Decisions (docs/DECISIONS_LOG.md, pending owner confirmation): the SACCO remits gross premium to the insurer,
with no distribution fee deducted first (fees are settled separately), to the insurer's premium paybill, which
is a per-insurer setting (Insurer.premium_paybill).

A SACCO manager records a remittance; the insurer's underwriter confirms it arrived or queries it with a reason.
Entries are never edited or deleted: a mistake is reversed by a new negative entry, and every step is audited.
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
from .models import Insurer, Officer, Payment, Policy, PremiumRemittance, Refund, Sacco

METHODS = {"bank_transfer": "Bank transfer", "mpesa": "M-Pesa", "cheque": "Cheque", "other": "Other"}
REFUND_METHODS = {"mpesa": "M-Pesa", "sacco_account": "Paid into the member's SACCO account",
                  "bank_transfer": "Bank transfer", "other": "Other"}
PAYBILL_UNSET = "the insurer's paybill (to be configured)"


def paybill(insurer: Insurer | None) -> str:
    """Where premium goes, in words for the remittance screen."""
    return (insurer.premium_paybill if insurer and insurer.premium_paybill else PAYBILL_UNSET)
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
    owed, paid_back = defaultdict(float), defaultdict(float)
    last_paid = {}
    if ids:
        for pm, sid in s.execute(select(Payment, Policy.sacco_id).join(Policy, Payment.policy_id == Policy.id)
                                 .where(Policy.sacco_id.in_(ids), Policy.insurer_id == insurer_id)):
            collected[sid] += pm.amount_kes
            last_paid[sid] = max(last_paid.get(sid, pm.received_at), pm.received_at)
        for due, sid in s.execute(select(Policy.refund_due_kes, Policy.sacco_id)
                                  .where(Policy.sacco_id.in_(ids), Policy.insurer_id == insurer_id)):
            owed[sid] += due or 0.0
        for amt, sid in s.execute(select(Refund.amount_kes, Policy.sacco_id).join(Policy, Refund.policy_id == Policy.id)
                                  .where(Policy.sacco_id.in_(ids), Policy.insurer_id == insurer_id)):
            paid_back[sid] += amt
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
                     "last_remitted_on": max((r.remitted_on for r in mine), default=None), "last_collected_at": last_paid.get(x.id),
                     "refunds_owed_kes": round(owed[x.id], 2), "refunds_paid_kes": round(paid_back[x.id], 2),
                     "refunds_outstanding_kes": max(0.0, round(owed[x.id] - paid_back[x.id], 2))})
    tot = {k: round(sum(r[k] for r in rows), 2) for k in ("collected_kes", "remitted_kes", "confirmed_kes", "unconfirmed_kes",
                                                           "outstanding_kes", "credit_kes", "refunds_owed_kes",
                                                           "refunds_paid_kes", "refunds_outstanding_kes")}
    tot["queried"] = sum(r["queried"] for r in rows)
    return {"rows": rows, "total": tot, "ledger": ledger, "saccos": {x.id: x for x in saccos},
            "paybill": paybill(s.get(Insurer, insurer_id))}


def record_refund(s: Session, off: Officer, pol: Policy, amount: str, paid_on: str, method: str, reference: str,
                  note: str = "", today: date | None = None) -> Refund:
    """A SACCO manager records money paid back to a farmer. It cannot be more than is still owed on the policy."""
    from .services import refund_outstanding
    if off.role != "manager" or off.sacco_id != pol.sacco_id:
        raise SettlementError("Only a manager of this SACCO can record a refund.")
    value = _parse_amount(amount)
    if value < 0:
        raise SettlementError("Enter the amount paid back, above zero.")
    left = refund_outstanding(s, pol)
    if value > left + 0.005:
        raise SettlementError(f"Only KES {left:,.0f} is owed back on this policy.")
    try:
        on = date.fromisoformat(paid_on)
    except ValueError:
        raise SettlementError("Enter the date the refund was paid.") from None
    if on > (today or date.today()):
        raise SettlementError("The date cannot be in the future.")
    if method not in REFUND_METHODS:
        raise SettlementError("Choose how the refund was paid.")
    ref = " ".join((reference or "").split())
    if not _REF.match(ref):
        raise SettlementError("Enter the M-Pesa, bank or SACCO reference (3 to 40 letters and numbers).")
    if s.scalar(select(Refund).where(Refund.reference == ref, Refund.policy_id == pol.id)):
        raise SettlementError("A refund with this reference is already recorded on this policy.")
    r = Refund(ref="RF-" + secrets.token_hex(3).upper(), policy_id=pol.id, amount_kes=value, paid_on=on, method=method,
               reference=ref, note=scrub((note or "").strip())[:300] or None, recorded_by=off.username)
    s.add(r)
    s.flush()
    audit(s, off.username, "refund.recorded", "policy", pol.id, policy_no=pol.policy_no, refund=r.ref, amount_kes=value,
          paid_on=on.isoformat(), method=method, reference=ref)
    return r
