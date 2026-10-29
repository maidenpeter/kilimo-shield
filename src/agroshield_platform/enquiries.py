"""Public-site forms: "Request a demo" and livestock "Register interest".

Stored in the local database only. Nothing is emailed, posted or sent to any service. Name, email and phone are
encrypted at rest (same vault as farmer data) with a masked copy for listings; free text is scrubbed of IDs and
phone numbers. `agroshield-portal enquiries --delete REF` removes one on request. How long they are kept
is not decided yet (docs/overnight/REVIEW.md, needs approval).
"""
from __future__ import annotations

import re
import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from .crypto import Vault, mask_phone, normalise_phone, scrub
from .db import audit
from .models import PublicEnquiry

KINDS = ("demo", "livestock_interest")
ORG_TYPES = {
    "demo": {"insurer": "Insurer", "reinsurer": "Reinsurer", "sacco": "SACCO", "other": "Other"},
    "livestock_interest": {"herder": "Herder or herders' group", "sacco": "SACCO or cooperative", "insurer": "Insurer",
                           "other": "Other"},
}
CONSENT = {
    "demo": "I agree that AgroShield may store these details to reply to this request. They are not shared or used "
            "for anything else, and I can ask for them to be deleted.",
    "livestock_interest": "I agree that AgroShield may store these details to tell me when livestock cover is "
                          "available. They are not shared or used for anything else, and I can ask for them to be deleted.",
}
_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[A-Za-z]{2,24}$")


class EnquiryError(ValueError):
    """A form problem the person can fix; the message is shown on the form."""


def mask_email(email: str) -> str:
    """jane.doe@example.org -> j***@example.org"""
    local, _, domain = email.partition("@")
    return f"{local[:1]}***@{domain}"


def record(s: Session, vault: Vault, kind: str, form: dict) -> PublicEnquiry:
    if kind not in KINDS:
        raise EnquiryError("Unknown form.")
    name = " ".join((form.get("name") or "").split())[:120]
    email = (form.get("email") or "").strip().lower()
    phone_raw = (form.get("phone") or "").strip()
    org_type = form.get("org_type") or ""
    errors = []
    if len(name) < 2:
        errors.append("Please give your name.")
    if not _EMAIL.match(email):
        errors.append("Please give an email address we can reply to.")
    if org_type not in ORG_TYPES[kind]:
        errors.append("Please choose who you are.")
    phone = None
    if phone_raw:
        try:
            phone = normalise_phone(phone_raw)
        except Exception:
            errors.append("That phone number does not look right. Leave it empty if you prefer.")
    if form.get("consent") != "yes":
        errors.append("Please tick the box to agree that we can store these details.")
    if errors:
        raise EnquiryError(" ".join(errors))
    e = PublicEnquiry(
        ref=secrets.token_hex(4).upper(), kind=kind,
        name_enc=vault.encrypt(name, "enquiry.name"), email_enc=vault.encrypt(email, "enquiry.email"),
        email_masked=mask_email(email),
        phone_enc=vault.encrypt(phone, "enquiry.phone") if phone else None, phone_masked=mask_phone(phone) if phone else None,
        organisation=(" ".join((form.get("organisation") or "").split())[:120] or None),
        org_type=org_type, county=((form.get("county") or "").strip()[:40] or None),
        message=(scrub((form.get("message") or "").strip())[:1000] or None), consent_text=CONSENT[kind])
    s.add(e)
    s.flush()
    audit(s, "public", f"enquiry.{kind}", "public_enquiry", e.ref, org_type=org_type)
    return e


def listing(s: Session) -> list[PublicEnquiry]:
    return list(s.scalars(select(PublicEnquiry).order_by(PublicEnquiry.created_at.desc())))


def delete(s: Session, ref: str, actor: str) -> bool:
    """Remove one enquiry and its contact details, for example when the person asks. The audit keeps only the reference."""
    e = s.scalar(select(PublicEnquiry).where(PublicEnquiry.ref == ref.strip().upper()))
    if e is None:
        return False
    s.delete(e)
    audit(s, actor, "enquiry.deleted", "public_enquiry", e.ref, kind=e.kind)
    return True
