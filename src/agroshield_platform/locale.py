"""English and Kiswahili strings for USSD and SMS, from locales/*.yaml (never in code)."""
from __future__ import annotations

import math
from datetime import date
from functools import lru_cache
from pathlib import Path

import yaml

LOCALES = Path(__file__).resolve().parents[2] / "locales"
LANGUAGES = ("en", "sw")
SMS_MAX = 160          # one GSM-7 segment
USSD_MAX = 182         # Africa's Talking / Safaricom USSD screen limit

# GSM 03.38 basic character set (no extension table): what fits a single-segment SMS.
_GSM7 = set("@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§"
            "¿abcdefghijklmnopqrstuvwxyzäöñüà")


@lru_cache(maxsize=None)
def strings(lang: str) -> dict:
    if lang not in LANGUAGES:
        raise ValueError(f"unknown language {lang!r}")
    return yaml.safe_load((LOCALES / f"{lang}.yaml").read_text(encoding="utf-8"))


def t(lang: str, key: str, **values) -> str:
    """t("sw", "ussd.main", first_name="Wanjiku")"""
    node = strings(lang)
    for part in key.split("."):
        node = node[part]
    return node.format(**values)


def kes(x: float) -> str:
    return f"{math.ceil(x - 1e-9):,}"


def day(d: date) -> str:
    return d.strftime("%d/%m/%Y")


def season(lang: str, season_code: str, year: int) -> str:
    return t(lang, f"season.{season_code}", year=year)


def status(lang: str, code: str) -> str:
    return strings(lang)["status"].get(code, code)


def is_gsm7(text: str) -> bool:
    return all(c in _GSM7 for c in text)


def first_name(full_name: str) -> str:
    return (full_name.split() or ["Mkulima"])[0]
