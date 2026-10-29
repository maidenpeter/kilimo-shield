"""Runtime settings from the environment (see .env.example).

Secrets come only from environment variables, or from a local `.env` file in the
repo root (git-ignored; real environment variables win). For local development,
if a key is missing, one is generated once into var/dev-keys.json (git-ignored)
and a warning is logged; production must set every key explicitly.

Integrations default to safe local modes, so nothing reaches a real phone or
M-Pesa account unless it is configured:
  MPESA_ENV  simulated (default: no network, completed from the dev page) | sandbox | production
  SMS_MODE   log (default: recorded in the outbox, not sent) | sandbox | live
"""
from __future__ import annotations

import base64
import json
import logging
import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
log = logging.getLogger("agroshield.settings")

KEYS = {
    "NATIONAL_ID_ENCRYPTION_KEY": 32,   # AES-256-GCM key for national IDs and phone numbers
    "LOOKUP_HMAC_KEY": 32,              # HMAC key for searchable hashes of IDs and phones
    "SESSION_SECRET": 32,               # signs portal session cookies
    "CALLBACK_TOKEN": 24,               # secret path segment of the M-Pesa and USSD callback URLs
}


@dataclass(frozen=True)
class Mpesa:
    env: str = "simulated"
    consumer_key: str = ""
    consumer_secret: str = ""
    shortcode: str = ""
    passkey: str = ""
    callback_base_url: str = ""          # public https base URL Safaricom can reach
    confirm_with_query: bool = True      # re-check each callback with an STK query before crediting


@dataclass(frozen=True)
class Sms:
    mode: str = "log"
    username: str = "sandbox"
    api_key: str = ""
    sender_id: str = ""


@dataclass(frozen=True)
class Settings:
    database_url: str
    encryption_key: bytes
    lookup_key: bytes
    session_secret: str
    config_dir: Path
    dev_keys: bool
    callback_token: str = "dev-callback-token"
    ussd_code: str = "*384*000#"
    mpesa: Mpesa = field(default_factory=Mpesa)
    sms: Sms = field(default_factory=Sms)


def load_dotenv(path: Path = REPO / ".env") -> None:
    """Minimal KEY=VALUE reader for a local .env. Never overrides the real environment."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.split(" #", 1)[0].strip().strip('"').strip("'")
        if v:
            os.environ.setdefault(k.strip(), v)


def _dev_keys() -> dict[str, str]:
    path = REPO / "var" / "dev-keys.json"
    keys = json.loads(path.read_text()) if path.exists() else {}
    missing = [k for k in KEYS if k not in keys]
    if missing:
        path.parent.mkdir(parents=True, exist_ok=True)
        keys.update({k: secrets.token_urlsafe(KEYS[k]) if k == "CALLBACK_TOKEN"   # goes in a URL path
                     else base64.b64encode(secrets.token_bytes(KEYS[k])).decode() for k in missing})
        path.write_text(json.dumps(keys, indent=2) + "\n")
        log.warning("generated development keys %s in %s; set real keys in the environment for any shared "
                    "deployment", ", ".join(missing), path)
    return keys


def load_settings() -> Settings:
    load_dotenv()
    env = {k: os.environ.get(k) for k in KEYS}
    dev = not all(env.values())
    if dev:
        dk = _dev_keys()
        env = {k: env[k] or dk[k] for k in KEYS}
    e = os.environ.get
    mpesa = Mpesa(env=e("MPESA_ENV", "simulated"), consumer_key=e("MPESA_CONSUMER_KEY", ""),
                  consumer_secret=e("MPESA_CONSUMER_SECRET", ""), shortcode=e("MPESA_SHORTCODE", ""),
                  passkey=e("MPESA_PASSKEY", ""), callback_base_url=e("MPESA_CALLBACK_BASE_URL", ""),
                  confirm_with_query=e("MPESA_CONFIRM_WITH_QUERY", "true").lower() != "false")
    if mpesa.env not in ("simulated", "sandbox", "production"):
        raise ValueError("MPESA_ENV must be simulated, sandbox or production")
    sms = Sms(mode=e("SMS_MODE", "log"), username=e("AFRICASTALKING_USERNAME", "sandbox"),
              api_key=e("AFRICASTALKING_API_KEY", ""), sender_id=e("AFRICASTALKING_SENDER_ID", ""))
    if sms.mode not in ("log", "sandbox", "live"):
        raise ValueError("SMS_MODE must be log, sandbox or live")
    if dev and (mpesa.env == "production" or sms.mode == "live"):
        raise ValueError("production M-Pesa or live SMS needs real keys set in the environment, not development keys")
    db = e("DATABASE_URL", f"sqlite:///{(REPO / 'var' / 'agroshield.db').as_posix()}")
    return Settings(database_url=db,
                    encryption_key=base64.b64decode(env["NATIONAL_ID_ENCRYPTION_KEY"]),
                    lookup_key=base64.b64decode(env["LOOKUP_HMAC_KEY"]),
                    session_secret=env["SESSION_SECRET"],
                    config_dir=Path(e("AGROSHIELD_CONFIG", REPO / "config")),
                    dev_keys=dev, callback_token=env["CALLBACK_TOKEN"],
                    ussd_code=e("USSD_SERVICE_CODE", "*384*000#"), mpesa=mpesa, sms=sms)
