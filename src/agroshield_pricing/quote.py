"""Quotes: the gross premium from the engine, then the subsidy split and the Resilience discount.

The quote never prices risk itself. Per-acre gross premiums come from a RateBook
built by running the engine (`price_ward`) for each pilot ward; the quote only
multiplies by acreage and splits who pays:

    gross            = sum over chosen layers of (gross per acre x acres)
    government share = subsidy.government_share x gross of subsidised layers,
                       if acres is inside subsidy.eligible_acres, else 0
    farmer share     = gross - government share
    Resilience       = min(cap, points x discount_per_point) x farmer share
    farmer pays      = farmer share - Resilience discount

The discount reduces only the farmer's share; the gross premium (the risk price)
and the government share never change with it.
"""
from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .config import Config
from .engine import price_ward
from .pet import PetSource
from .rainfall import RainfallSource


class QuoteError(ValueError):
    """A request the product cannot quote (unknown ward, layer not offered, ...)."""


@dataclass
class WardRates:
    ward_id: str
    ward_name: str
    season: str
    layer_b_gross_per_acre: dict[float, float]   # sum insured per acre -> gross KES per acre
    layer_a_gross_per_acre: float | None         # None where Layer A is not offered
    layer_a_voucher_kes_per_acre: float | None
    index_versions: dict[str, str]
    provenance_labels: list[str]


@dataclass
class RateBook:
    """Per-acre gross premiums for every ward and season, from one engine run each."""
    rates: dict[tuple[str, str], WardRates]
    config_sha256: dict[str, str]
    built_at: str
    notes: list[str] = field(default_factory=list)

    @classmethod
    def build(cls, cfg: Config, rain: RainfallSource, pet: PetSource) -> "RateBook":
        rates = {}
        for wid in cfg.pilot.wards:
            res = price_ward(cfg, wid, rain, pet)
            for season, sr in res.seasons.items():
                s = sr.summary
                la = s["layer_a"]
                rates[(wid, season)] = WardRates(
                    ward_id=wid, ward_name=res.summary["ward"]["name"], season=season,
                    layer_b_gross_per_acre={float(o["sum_insured_kes_per_acre"]): float(o["gross_premium_kes"])
                                            for o in s["premium"]["per_acre"]},
                    layer_a_gross_per_acre=float(la["gross_kes"]) if la.get("available") else None,
                    layer_a_voucher_kes_per_acre=float(la["terms"]["voucher_kes_per_acre"]) if la.get("available") else None,
                    index_versions={"layer_b": s["terms"]["version"],
                                    **({"layer_a": la["version"]} if la.get("available") else {})},
                    provenance_labels=sorted({p["label"] for p in res.summary["provenance"]}),
                )
        return cls(rates, dict(cfg.file_hashes), datetime.now(timezone.utc).isoformat(timespec="seconds"))


def resilience_points(cfg: Config, verified: dict[str, bool]) -> tuple[float, list[dict]]:
    """Points from verified items; within a group only the highest-scoring item counts."""
    table = {p.id: p for p in cfg.product.resilience.points}
    unknown = sorted(set(verified) - set(table))
    if unknown:
        raise QuoteError(f"unknown Resilience items: {unknown}; known: {sorted(table)}")
    best_in_group: dict[str, str] = {}
    for pid, ok in verified.items():
        p = table[pid]
        if ok and p.group:
            cur = best_in_group.get(p.group)
            if cur is None or table[cur].points < p.points:
                best_in_group[p.group] = pid
    counted = []
    for pid, ok in verified.items():
        p = table[pid]
        if ok and (p.group is None or best_in_group[p.group] == pid):
            counted.append({"id": pid, "label": p.label, "points": p.points, "verified_by": p.verified_by})
    return sum(c["points"] for c in counted), counted


def _kes(x: float) -> float:
    return round(x + 1e-9, 2)


def quote(cfg: Config, book: RateBook, *, ward_id: str, season: str = "LR", acres: float,
          layers: list[str], sum_insured_kes_per_acre: float | None = None,
          resilience: dict[str, bool] | None = None) -> dict:
    if (ward_id, season) not in book.rates:
        raise QuoteError(f"no cover for ward {ward_id!r} in season {season!r}")
    r = book.rates[(ward_id, season)]
    if acres <= 0:
        raise QuoteError("acres must be positive")
    layers = sorted(set(layers))
    if not layers or not set(layers) <= {"A", "B"}:
        raise QuoteError("layers must be a non-empty subset of ['A', 'B']")
    if "A" in layers and not cfg.product.layer_a.enabled:
        raise QuoteError("Layer A is not part of the product: " + (cfg.product.layer_a.disabled_reason.strip()
                                                                  or "switched off"))
    if "A" in layers and r.layer_a_gross_per_acre is None:
        raise QuoteError(f"Layer A is not offered at {ward_id}")
    si = sum_insured_kes_per_acre or cfg.product.sum_insured.default_kes_per_acre
    if "B" in layers and float(si) not in r.layer_b_gross_per_acre:
        raise QuoteError(f"sum insured per acre must be one of {sorted(r.layer_b_gross_per_acre)}")

    # Gross premium, per layer, straight from the engine's rate book.
    lines = []
    if "A" in layers:
        lines.append({"layer": "A", "name": "Pre-season seed voucher (anticipatory)",
                      "gross_per_acre_kes": r.layer_a_gross_per_acre,
                      "cover": f"KES {r.layer_a_voucher_kes_per_acre:,.0f}/acre drought-tolerant seed voucher if triggered"})
    if "B" in layers:
        lines.append({"layer": "B", "name": "In-season rainfall index (WRSI) with replanting voucher",
                      "gross_per_acre_kes": r.layer_b_gross_per_acre[float(si)],
                      "cover": f"up to KES {si:,.0f}/acre"})
    sub = cfg.product.subsidy
    eligible = sub.eligible_acres.min <= acres <= sub.eligible_acres.max
    for ln in lines:
        ln["gross_kes"] = _kes(ln["gross_per_acre_kes"] * acres)
        ln["government_share_kes"] = _kes(ln["gross_kes"] * sub.government_share) \
            if eligible and ln["layer"] in sub.applies_to_layers else 0.0
        ln["farmer_share_kes"] = _kes(ln["gross_kes"] - ln["government_share_kes"])
    gross = _kes(sum(ln["gross_kes"] for ln in lines))
    gov = _kes(sum(ln["government_share_kes"] for ln in lines))
    farmer_share = _kes(gross - gov)

    res = cfg.product.resilience
    points, counted = resilience_points(cfg, resilience or {})
    rate = min(res.discount_cap, points * res.discount_per_point)
    discount = _kes(farmer_share * rate)
    farmer_pays = _kes(farmer_share - discount)
    platform_fee = _kes(gross * cfg.product.premium.loadings.get("platform", 0.0))

    return {
        "quote_id": f"Q-{datetime.now(timezone.utc):%Y%m%d}-{secrets.token_hex(4)}",
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "ward": {"id": r.ward_id, "name": r.ward_name}, "season": season, "acres": acres,
        "sum_insured_kes_per_acre": si if "B" in layers else None,
        "total_sum_insured_kes": _kes(si * acres) if "B" in layers else None,
        "layers": lines,
        "gross_premium_kes": gross,
        "subsidy": {"programme": sub.programme, "eligible": eligible,
                    "eligibility": f"{sub.eligible_acres.min:g} to {sub.eligible_acres.max:g} acres",
                    "government_share_rate": sub.government_share if eligible else 0.0,
                    "government_share_kes": gov,
                    "status": "not applicable" if gov == 0 else "received" if sub.received else "not yet received",
                    "note": None if gov == 0 or sub.received else
                    "The government share is recorded as a receivable until KAIP pays it."},
        "farmer_share_before_discount_kes": farmer_share,
        "resilience": {"points": points, "items_counted": counted, "discount_rate": rate,
                       "discount_cap": res.discount_cap, "capped": points * res.discount_per_point > res.discount_cap,
                       "discount_kes": discount,
                       "applies_to": "farmer share only", "funder": res.funder,
                       "note": "Paid by the funder; the insurer still receives the full gross premium. "
                               "The discount does not reduce the parametric risk."},
        # Who pays the insurer. The three sources always add up to the full gross premium.
        "premium_flows": {"insurer_receives_kes": gross, "government_kes": gov, "farmer_kes": farmer_pays,
                          "discount_funder": res.funder, "discount_funder_kes": discount,
                          "platform_fee_kes": platform_fee,
                          "discount_exceeds_platform_fee": res.funder == "platform" and discount > platform_fee},
        "farmer_pays_kes": farmer_pays,
        "farmer_pays_rounded_kes": int(round(farmer_pays)),
        "payment": "M-Pesa or SACCO deduction (milestone 6)",
        "basis": {"index_versions": r.index_versions, "config_sha256": book.config_sha256,
                  "rate_book_built_at": book.built_at, "inputs": r.provenance_labels,
                  "illustrative": cfg.product.illustrative or sub.illustrative or res.illustrative,
                  "note": "Illustrative pricing: not a filed product and not for sale."},
    }


def audit_quote(path: Path, request: dict, response: dict) -> None:
    """Append one line per quote. Quotes carry no personal data."""
    path.parent.mkdir(parents=True, exist_ok=True)
    line = {"quote_id": response["quote_id"], "created_at": response["created_at"], "request": request,
            "farmer_pays_kes": response["farmer_pays_kes"], "gross_premium_kes": response["gross_premium_kes"],
            "index_versions": response["basis"]["index_versions"], "config_sha256": response["basis"]["config_sha256"],
            "response_sha256": hashlib.sha256(json.dumps(response, sort_keys=True).encode()).hexdigest()}
    with path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(line, sort_keys=True) + "\n")
