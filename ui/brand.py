"""App identity: name, identifier, version and logo. One place, so the header, browser tab and footer agree."""
from __future__ import annotations

import base64
from functools import lru_cache
from pathlib import Path

APP_NAME = "ShambaShield360"
APP_ID = "shambashield360"
APP_VERSION = "2.0.0"
TAGLINE = "Mixed-farm parametric insurance and SACCO reconciliation for Kenya"

ASSETS = Path(__file__).resolve().parent.parent / "assets"
LOGO_SVG = ASSETS / "logo.svg"
LOGO_PNG = ASSETS / "logo-256.png"


@lru_cache(maxsize=1)
def logo_data_uri() -> str:
    return "data:image/svg+xml;base64," + base64.b64encode(LOGO_SVG.read_bytes()).decode("ascii")


def identifier() -> str:
    return f"{APP_ID} v{APP_VERSION}"
