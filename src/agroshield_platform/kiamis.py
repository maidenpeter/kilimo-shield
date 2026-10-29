"""KIAMIS (Kenya Integrated Agriculture Management Information System) adapter.

Whether KIAMIS offers an API to private partners is unknown [ASK], so the
platform talks to an interface. Two implementations:
  * NotConnected: the default; every check says "not connected".
  * CsvKiamis: reads records imported from a KIAMIS CSV export by an officer
    (manual fallback). National IDs in the export are hashed on import and the
    file itself is not kept.
"""
from __future__ import annotations

import csv
import hashlib
import io
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from .crypto import PIIError, Vault, normalise_national_id
from .models import KiamisRecord

ACREAGE_TOLERANCE = 0.25   # declared acreage within 25% of KIAMIS counts as consistent


@dataclass
class KiamisCheck:
    status: str                      # not_connected | not_found | verified | acreage_mismatch
    registered_acreage: float | None = None
    certified_seed_purchased: bool | None = None
    subsidy_eligible: bool | None = None


class KiamisAdapter(Protocol):
    def check(self, s: Session, national_id: str, declared_acres: float) -> KiamisCheck: ...


class NotConnected:
    def check(self, s: Session, national_id: str, declared_acres: float) -> KiamisCheck:
        return KiamisCheck("not_connected")


class CsvKiamis:
    COLUMNS = ("national_id", "registered_acreage", "certified_seed_purchased", "subsidy_eligible")

    def __init__(self, vault: Vault):
        self.vault = vault

    def import_csv(self, s: Session, text: str) -> dict:
        sha = hashlib.sha256(text.encode()).hexdigest()
        rows = list(csv.DictReader(io.StringIO(text)))
        if not rows or set(self.COLUMNS) - set(rows[0]):
            raise ValueError(f"KIAMIS CSV needs columns {', '.join(self.COLUMNS)}")
        added = updated = 0
        errors = []
        for i, r in enumerate(rows, start=2):
            try:
                h = self.vault.lookup_hash(normalise_national_id(r["national_id"]), "national_id")
            except PIIError as e:
                errors.append(f"row {i}: {e}")
                continue
            try:
                acres = float(r["registered_acreage"]) if r["registered_acreage"].strip() else None
            except ValueError:
                errors.append(f"row {i}: registered_acreage must be a number")
                continue
            rec = s.scalar(select(KiamisRecord).where(KiamisRecord.national_id_hash == h))
            vals = {"registered_acreage": acres,
                    "certified_seed_purchased": r["certified_seed_purchased"].strip().lower() in ("yes", "true", "1"),
                    "subsidy_eligible": (r["subsidy_eligible"].strip().lower() in ("yes", "true", "1"))
                    if r["subsidy_eligible"].strip() else None, "source_sha256": sha}
            if rec:
                for k, v in vals.items():
                    setattr(rec, k, v)
                updated += 1
            else:
                s.add(KiamisRecord(national_id_hash=h, **vals))
                added += 1
        return {"added": added, "updated": updated, "errors": errors, "source_sha256": sha}

    def check(self, s: Session, national_id: str, declared_acres: float) -> KiamisCheck:
        h = self.vault.lookup_hash(national_id, "national_id")
        rec = s.scalar(select(KiamisRecord).where(KiamisRecord.national_id_hash == h))
        if rec is None:
            return KiamisCheck("not_found")
        status = "verified"
        if rec.registered_acreage and abs(declared_acres - rec.registered_acreage) > ACREAGE_TOLERANCE * rec.registered_acreage:
            status = "acreage_mismatch"
        return KiamisCheck(status, rec.registered_acreage, rec.certified_seed_purchased, rec.subsidy_eligible)
