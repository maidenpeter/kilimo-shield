"""Runtime settings from the environment (see .env.example).

Secrets come only from environment variables. For local development, if a key is
missing, one is generated once into var/dev-keys.json (git-ignored) and a warning
is logged; production must set every key explicitly.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import secrets
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
log = logging.getLogger("agroshield.settings")

KEYS = {
    "NATIONAL_ID_ENCRYPTION_KEY": 32,   # AES-256-GCM key for national IDs and phone numbers
    "LOOKUP_HMAC_KEY": 32,              # HMAC key for searchable hashes of IDs and phones
    "SESSION_SECRET": 32,               # signs portal session cookies
}


@dataclass(frozen=True)
class Settings:
    database_url: str
    encryption_key: bytes
    lookup_key: bytes
    session_secret: str
    config_dir: Path
    dev_keys: bool


def _dev_keys() -> dict[str, str]:
    path = REPO / "var" / "dev-keys.json"
    if path.exists():
        return json.loads(path.read_text())
    path.parent.mkdir(parents=True, exist_ok=True)
    keys = {k: base64.b64encode(secrets.token_bytes(n)).decode() for k, n in KEYS.items()}
    path.write_text(json.dumps(keys, indent=2) + "\n")
    log.warning("generated development keys in %s; set real keys in the environment for any shared deployment", path)
    return keys


def load_settings() -> Settings:
    env = {k: os.environ.get(k) for k in KEYS}
    dev = not all(env.values())
    if dev:
        dk = _dev_keys()
        env = {k: env[k] or dk[k] for k in KEYS}
    db = os.environ.get("DATABASE_URL", f"sqlite:///{(REPO / 'var' / 'agroshield.db').as_posix()}")
    return Settings(database_url=db,
                    encryption_key=base64.b64decode(env["NATIONAL_ID_ENCRYPTION_KEY"]),
                    lookup_key=base64.b64decode(env["LOOKUP_HMAC_KEY"]),
                    session_secret=env["SESSION_SECRET"],
                    config_dir=Path(os.environ.get("AGROSHIELD_CONFIG", REPO / "config")),
                    dev_keys=dev)
