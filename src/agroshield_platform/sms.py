"""SMS to farmers in English or Kiswahili, through an outbox.

Messages are queued in the same transaction as the event that causes them and
sent afterwards. They are queued only for farmers whose latest SMS consent is
"yes" (purpose limitation). The phone number is decrypted only at send time and
never stored in the outbox or logged in clear.

Senders: LogOnlySender (default, SMS_MODE=log: recorded, not sent) and
AfricasTalkingSender (SMS_MODE=sandbox or live).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import locale as L
from .crypto import Vault, scrub
from .models import Consent, Farmer, Policy, SmsMessage
from .settings import Sms

log = logging.getLogger("agroshield.sms")


def sms_consent(s: Session, farmer: Farmer) -> bool:
    c = s.scalar(select(Consent).where(Consent.farmer_id == farmer.id, Consent.purpose == "sms")
                 .order_by(Consent.captured_at.desc(), Consent.id.desc()))
    return bool(c and c.granted)


def policy_values(p: Policy, lang: str, ussd_code: str = "") -> dict:
    return {"cert": p.policy_no, "season": L.season(lang, p.season, p.year), "due": L.kes(p.amount_due_kes),
            "paid": L.kes(p.paid_kes), "balance": L.kes(p.balance_kes), "closes": L.day(p.sales_closes_on),
            "refund": L.kes(p.refund_due_kes), "first_name": L.first_name(p.farmer.full_name), "ussd": ussd_code}


def queue(s: Session, farmer: Farmer, template: str, policy: Policy | None = None, dedupe_key: str | None = None,
          ussd_code: str = "", **values) -> SmsMessage | None:
    """Queue one message in the farmer's language. None if they have not agreed to SMS or it was already queued."""
    if not sms_consent(s, farmer):
        return None
    if dedupe_key and s.scalar(select(SmsMessage).where(SmsMessage.dedupe_key == dedupe_key)):
        return None
    lang = farmer.language if farmer.language in L.LANGUAGES else "en"
    v = {**(policy_values(policy, lang, ussd_code) if policy else {"first_name": L.first_name(farmer.full_name)}), **values}
    body = L.t(lang, f"sms.{template}", **v)
    msg = SmsMessage(farmer_id=farmer.id, policy_id=policy.id if policy else None, template=template, language=lang,
                     body=body, dedupe_key=dedupe_key)
    s.add(msg)
    return msg


class LogOnlySender:
    name = "log"

    def send(self, phone: str, body: str) -> tuple[str, str | None, str | None]:
        return "logged", None, None


class AfricasTalkingSender:
    URLS = {"sandbox": "https://api.sandbox.africastalking.com/version1/messaging",
            "live": "https://api.africastalking.com/version1/messaging"}

    def __init__(self, cfg: Sms, client: httpx.Client | None = None):
        if not cfg.api_key:
            raise ValueError("AFRICASTALKING_API_KEY is not set")
        self.cfg, self.name = cfg, f"africastalking-{cfg.mode}"
        self.http = client or httpx.Client(timeout=30)

    def send(self, phone: str, body: str) -> tuple[str, str | None, str | None]:
        data = {"username": self.cfg.username, "to": phone, "message": body}
        if self.cfg.sender_id:
            data["from"] = self.cfg.sender_id
        r = self.http.post(self.URLS[self.cfg.mode], data=data,
                           headers={"apiKey": self.cfg.api_key, "Accept": "application/json"})
        if r.status_code >= 400:
            return "failed", None, f"HTTP {r.status_code}"
        rec = (r.json().get("SMSMessageData", {}).get("Recipients") or [{}])[0]
        if rec.get("status") == "Success":
            return "sent", rec.get("messageId"), None
        return "failed", rec.get("messageId"), scrub(str(rec.get("status", "unknown")))[:200]


def make_sender(cfg: Sms):
    return LogOnlySender() if cfg.mode == "log" else AfricasTalkingSender(cfg)


def send_pending(s: Session, sender, vault: Vault, limit: int = 200) -> dict:
    counts: dict[str, int] = {}
    for m in s.scalars(select(SmsMessage).where(SmsMessage.status == "queued").order_by(SmsMessage.id).limit(limit)):
        phone = vault.decrypt(m.farmer.phone_enc, "phone")
        try:
            status, mid, err = sender.send(phone, m.body)
        except httpx.HTTPError as e:
            status, mid, err = "failed", None, type(e).__name__
        m.status, m.provider, m.provider_message_id, m.error = status, sender.name, mid, err
        m.sent_at = datetime.now(timezone.utc) if status in ("sent", "logged") else None
        counts[status] = counts.get(status, 0) + 1
        log.info("sms %s %s to %s", m.id, status, m.farmer.phone_masked)
    return counts
