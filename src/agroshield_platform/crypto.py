"""Protection of personal data (Kenya Data Protection Act).

National ID and phone numbers are:
  * encrypted at rest with AES-256-GCM (random nonce per value),
  * findable through a keyed HMAC-SHA256 of the normalised value (never the value),
  * masked everywhere they are shown or logged.
Officer passwords are stored as scrypt hashes.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import re
import secrets

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class PIIError(ValueError):
    """A national ID or phone number that cannot be valid."""


# ------------------------------------------------------------------ normalising
def normalise_phone(raw: str) -> str:
    """Kenyan mobile numbers to E.164 (+2547XXXXXXXX or +2541XXXXXXXX)."""
    d = re.sub(r"[^\d+]", "", raw or "")
    if d.startswith("+"):
        d = d[1:]
    if d.startswith("254"):
        d = d[3:]
    elif d.startswith("0"):
        d = d[1:]
    if not re.fullmatch(r"[71]\d{8}", d):
        raise PIIError("phone must be a Kenyan mobile number, e.g. 0712 345 678")
    return "+254" + d


def normalise_national_id(raw: str) -> str:
    d = re.sub(r"\s", "", raw or "")
    if not re.fullmatch(r"\d{6,9}", d):
        raise PIIError("national ID must be 6 to 9 digits")
    return d


# ------------------------------------------------------------------ masking
def mask_national_id(nid: str) -> str:
    return "*" * max(0, len(nid) - 3) + nid[-3:]


def mask_phone(phone: str) -> str:
    """+254712345678 -> +254 7** *** 678"""
    return f"{phone[:4]} {phone[4]}** *** {phone[-3:]}"


_DIGITS = re.compile(r"(?<!\d)(\+?\d[\d ]{5,13}\d)(?!\d)")


def scrub(text: str) -> str:
    """Mask any run of 7+ digits (IDs, phones) in free text, keeping the last 3."""
    def repl(m: re.Match) -> str:
        digits = re.sub(r"\D", "", m.group(1))
        return m.group(1) if len(digits) < 7 else "*" * (len(digits) - 3) + digits[-3:]
    return _DIGITS.sub(repl, text)


class ScrubFilter(logging.Filter):
    """Logging filter that masks ID- and phone-like numbers in every record."""
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = scrub(str(record.msg))
        if record.args:
            # Keep non-text arguments (e.g. a %d status code) as they are unless masking changes them.
            record.args = tuple(a if not isinstance(a, str) and scrub(str(a)) == str(a) else scrub(str(a))
                                for a in record.args)
        return True


_CALLBACK_PATH = re.compile(r"(/ussd/|/mpesa/callback/)[^/?\s\"]+")


class CallbackTokenFilter(logging.Filter):
    """Redacts the shared secret in callback paths (/ussd/<token>, /mpesa/callback/<token>) from log lines."""
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = _CALLBACK_PATH.sub(r"\1[token]", str(record.msg))
        if record.args:
            record.args = tuple(_CALLBACK_PATH.sub(r"\1[token]", a) if isinstance(a, str) else a for a in record.args)
        return True


# ------------------------------------------------------------------ encryption
class Vault:
    def __init__(self, key: bytes, lookup_key: bytes):
        if len(key) != 32 or len(lookup_key) < 32:
            raise ValueError("encryption key must be 32 bytes and lookup key at least 32 bytes")
        self._aead = AESGCM(key)
        self._lookup = lookup_key

    def encrypt(self, value: str, purpose: str) -> str:
        nonce = secrets.token_bytes(12)
        ct = self._aead.encrypt(nonce, value.encode(), purpose.encode())   # purpose bound as associated data
        return base64.b64encode(nonce + ct).decode()

    def decrypt(self, token: str, purpose: str) -> str:
        raw = base64.b64decode(token)
        return self._aead.decrypt(raw[:12], raw[12:], purpose.encode()).decode()

    def lookup_hash(self, value: str, purpose: str) -> str:
        return hmac.new(self._lookup, f"{purpose}:{value}".encode(), hashlib.sha256).hexdigest()


# ------------------------------------------------------------------ passwords
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(password.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    return f"scrypt$16384$8$1${base64.b64encode(salt).decode()}${base64.b64encode(h).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, h = stored.split("$")
        got = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p), dklen=32)
        return hmac.compare_digest(got, base64.b64decode(h))
    except Exception:
        return False
