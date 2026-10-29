"""USSD menu for enrolled farmers (Africa's Talking callback), English or Kiswahili.

Africa's Talking POSTs sessionId, serviceCode, phoneNumber and the full input so
far as `text` ("" first, then "2", "2*1", ...). We answer "CON <screen>" to
continue or "END <screen>" to finish. Screens are at most 182 characters.

    main  1 My cover   2 Pay premium (full or instalment, M-Pesa STK push)
          3 Payouts (ward rainfall status and this farmer's payouts)   4 Language
          5 Report crop loss (missed-payout report; never changes a payout)   0 Help

Enrolment stays with the SACCO officer, who reads the consent statements to the
farmer; USSD serves members who are already enrolled.
"""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import locale as L
from .crypto import PIIError, normalise_phone
from .models import Farmer, Policy
from .services import MIN_INSTALMENT_KES, Context, PaymentError

log = logging.getLogger("agroshield.ussd")


def _farmer(ctx: Context, s: Session, phone: str) -> Farmer | None:
    try:
        h = ctx.vault.lookup_hash(normalise_phone(phone), "phone")
    except PIIError:
        return None
    farmers = s.scalars(select(Farmer).where(Farmer.phone_hash == h)).all()
    if not farmers:
        return None
    # Same phone in more than one SACCO: the one with the most recent policy.
    return max(farmers, key=lambda f: max((p.created_at for p in f.policies), default=f.created_at))


def _policy(s: Session, f: Farmer) -> Policy | None:
    return s.scalar(select(Policy).where(Policy.farmer_id == f.id, Policy.status != "cancelled")
                    .order_by(Policy.created_at.desc()))


def _end(text: str) -> str:
    return "END " + text


def _con(text: str) -> str:
    return "CON " + text


def handle(ctx: Context, s: Session, phone: str, text: str) -> str:
    f = _farmer(ctx, s, phone)
    if f is None:
        return _end(L.t("en", "ussd.not_registered") + "\n" + L.t("sw", "ussd.not_registered"))
    lang = f.language if f.language in L.LANGUAGES else "en"
    steps = [x.strip() for x in (text or "").split("*")] if text else []
    if not steps:
        return _con(L.t(lang, "ussd.main", first_name=L.first_name(f.full_name)))
    choice, rest = steps[0], steps[1:]
    if choice == "1":
        return _cover(s, f, lang)
    if choice == "2":
        return _pay(ctx, s, f, lang, rest)
    if choice == "3":
        return _payouts(ctx, s, f, lang)
    if choice == "5":
        return _report(ctx, s, f, lang, rest)
    if choice == "4":
        if not rest:
            return _con(L.t(lang, "ussd.language_menu"))
        new = {"1": "en", "2": "sw"}.get(rest[0])
        if new is None:
            return _end(L.t(lang, "ussd.invalid"))
        f.language = new
        return _end(L.t(new, "ussd.language_set"))
    if choice == "0":
        return _end(L.t(lang, "ussd.help", sacco=f.sacco.name))
    return _end(L.t(lang, "ussd.invalid"))


def _cover(s: Session, f: Farmer, lang: str) -> str:
    p = _policy(s, f)
    if p is None:
        return _end(L.t(lang, "ussd.no_policy"))
    out = L.t(lang, "ussd.cover", cert=p.policy_no, season=L.season(lang, p.season, p.year), acres=f"{p.acres:g}",
              status=L.status(lang, p.status), paid=L.kes(p.paid_kes), due=L.kes(p.amount_due_kes))
    if p.status == "pending_payment":
        out += L.t(lang, "ussd.cover_due", closes=L.day(p.sales_closes_on))
    if p.refund_due_kes > 0:
        out += L.t(lang, "ussd.cover_refund", refund=L.kes(p.refund_due_kes))
    return _end(out)


def _payouts(ctx: Context, s: Session, f: Farmer, lang: str) -> str:
    from .models import Payout
    from .monitoring import latest, ward_key
    p = _policy(s, f)
    if p is None:
        return _end(L.t(lang, "ussd.no_policy"))
    out = [L.t(lang, "ussd.payouts_head", ward=ctx.cfg.ward(p.ward_id).label, season=L.season(lang, p.season, p.year))]
    if p.status != "active":
        out.append(L.t(lang, "ussd.not_active", cert=p.policy_no, status=L.status(lang, p.status)))
        return _end("\n".join(out))
    out.append(L.t(lang, f"ward.{ward_key(latest(s, p.ward_id, p.season, p.year))}"))
    pays = s.scalars(select(Payout).where(Payout.policy_id == p.id).order_by(Payout.id)).all()
    if any(po.status in ("calculated", "held") for po in pays):
        out.append(L.t(lang, "ussd.payout_checking"))          # nothing promised before the insurer approves
    for po in pays:
        amount = f"{po.amount_kes:,.0f}"
        if po.status in ("calculated", "held"):
            continue
        if po.kind == "replant_voucher":
            out.append(L.t(lang, "ussd.voucher", code=po.voucher_code, amount=amount))
        elif po.status == "paid":
            out.append(L.t(lang, "ussd.payout_paid", amount=amount, on=po.paid_at.strftime("%d/%m/%Y")))
        else:
            out.append(L.t(lang, "ussd.payout_due", amount=amount, by=po.due_by.strftime("%d/%m/%Y")))
    return _end("\n".join(out))


def _report(ctx: Context, s: Session, f: Farmer, lang: str, rest: list[str]) -> str:
    from .monitoring import report_missed
    if not rest:
        return _con(L.t(lang, "ussd.report_menu"))
    category = {"1": "failed_no_payout", "2": "payout_too_small"}.get(rest[0])
    if category is None:
        return _end(L.t(lang, "ussd.report_back"))
    r = report_missed(ctx, s, f, category, "ussd", "ussd")
    return _end(L.t(lang, "ussd.report_done", ref=r.ref))


def _pay(ctx: Context, s: Session, f: Farmer, lang: str, rest: list[str]) -> str:
    from .mpesa import MpesaError, request_premium
    p = _policy(s, f)
    if p is None:
        return _end(L.t(lang, "ussd.no_policy"))
    if p.status != "pending_payment" or p.balance_kes <= 0:
        return _end(L.t(lang, "ussd.nothing_due", cert=p.policy_no, status=L.status(lang, p.status)))
    if ctx.date() > p.sales_closes_on:
        return _end(L.t(lang, "ussd.sales_closed", season=L.season(lang, p.season, p.year),
                        closes=L.day(p.sales_closes_on)))
    balance = int(round(p.balance_kes))
    low = min(MIN_INSTALMENT_KES, balance)
    if not rest:
        return _con(L.t(lang, "ussd.pay_menu", cert=p.policy_no, balance=f"{balance:,}"))
    if rest[0] == "1":
        amount = balance
    elif rest[0] == "2":
        if len(rest) < 2:
            return _con(L.t(lang, "ussd.pay_amount", min=low, balance=f"{balance:,}"))
        raw = rest[1].replace(",", "")
        if not raw.isdigit() or not low <= int(raw) <= balance:
            return _end(L.t(lang, "ussd.bad_amount", min=low, balance=f"{balance:,}"))
        amount = int(raw)
    else:
        return _end(L.t(lang, "ussd.invalid"))
    try:
        request_premium(ctx, s, p, amount, requested_by="ussd")
    except (MpesaError, PaymentError) as e:
        log.warning("USSD STK push failed for policy %s: %s", p.policy_no, type(e).__name__)
        return _end(L.t(lang, "ussd.stk_failed"))
    return _end(L.t(lang, "ussd.stk_sent", amount=f"{amount:,}"))
