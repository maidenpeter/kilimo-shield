"""Farm quotes: what one farmer pays for a season, and who pays the rest. ILLUSTRATIVE.

Cover follows the farm. The standard farm is 2 acres of maize and 2 dairy cows, and its sum insured is the product's
(KSh 60,000 by default: KSh 15,000 of crop inputs per acre, KSh 10,000 of fodder and KSh 5,000 of vet and health
cover per cow). A bigger product sum insured scales every per-acre and per-cow amount with it.

The quote prices this farm's own mix with the same engine and the same product settings as the backtest, so a
standard farm's rate, premium and cap equal its ward's in the zone pricing table. Then it splits who pays, as
AgroShield did:

    gross premium      = sum insured x commercial rate (the risk price; never changed by what follows)
    government share   = subsidy share x gross, if the farm has 0.5 to 20 acres (no subsidy is agreed)
    farmer share       = gross - government share
    Resilience         = min(15%, 1% per point) x farmer share, paid by the platform out of its fee
    farmer pays        = farmer share - Resilience discount

Money is rounded to whole shillings, half up, from exact decimal arithmetic. The insurer always receives the full
gross premium. A ward the engine does not offer gets no quote, and neither does a farm whose own mix prices above
the sellable ceiling.
"""
from __future__ import annotations

import hashlib
import json
import math
import numbers
from dataclasses import asdict, dataclass, field, replace
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction

import pandas as pd

from engine.parametric_engine import (
    SEASONS, WARDS, TriggerParams, commercial_rate, kpis, run_backtest, whole_shillings,
)

STANDARD_ACRES = 2
STANDARD_COWS = 2
MAX_ACRES = 20.0
MAX_COWS = 20
SUBSIDY_ACRES = (0.5, 20.0)
DISCOUNT_PER_POINT = 0.01
DISCOUNT_CAP = 0.15
DISCOUNT_FUNDER = "platform"
CHECKOFF_DAYS = 90                 # milk check-off spread over the three months before enrolment closes
CLOSE_DAYS_BEFORE_SEASON = 14      # enrolment closes 14 days before the season window opens
COVER_YEAR = 2027
SEASON_WORDS = {"LR": "long rains", "SR": "short rains"}


@dataclass(frozen=True)
class ResilienceItem:
    id: str
    label: str
    points: int
    verified_by: str
    group: str | None = None


RESILIENCE_ITEMS = (
    ResilienceItem("certified_seed", "Bought certified maize seed last season", 5, "agro-dealer receipt"),
    ResilienceItem("photos_on_schedule", "Sent crop photos at every growth stage", 4, "photo app"),
    ResilienceItem("fodder_stored", "Has hay or silage stored for the dry season", 3, "lead farmer visit"),
    ResilienceItem("irrigation_full", "Full irrigation", 3, "officer visit", "irrigation"),
    ResilienceItem("irrigation_partial", "Partial or supplementary irrigation", 2, "officer visit", "irrigation"),
    ResilienceItem("sacco_good_standing", "SACCO member in good standing", 2, "SACCO records"),
)
ITEMS = {item.id: item for item in RESILIENCE_ITEMS}


class QuoteError(ValueError):
    """A farm the product cannot quote."""


class WardNotOffered(QuoteError):
    """The ward's standard bundle is above the sellable ceiling."""


class FarmNotValid(QuoteError):
    """The farm's inputs are outside what the product covers."""


class FarmAboveCeiling(QuoteError):
    """This farm's own mix prices above the sellable ceiling."""

    def __init__(self, message: str, rate: float):
        super().__init__(message)
        self.rate = rate


@dataclass
class Quote:
    quote_id: str
    ward_key: str
    season: str
    acres: float
    cows: int
    unit_cover: dict             # KSh per acre (crop) and per cow (fodder, vet)
    cover: dict                  # layer name -> KSh sum insured
    sum_insured: float
    seasonal_cap: float
    burn_cost_rate: float
    pricing_mode: str
    premium_rate: float
    gross_premium: int
    subsidy_share: float
    subsidy_eligible: bool
    government_share: int
    farmer_share: int
    resilience_points: int
    resilience_counted: list
    discount_rate: float
    discount: int
    farmer_pays: int
    platform_fee: int
    discount_exceeds_fee: bool
    per_day_checkoff: float | None   # None for a farm without cows: no milk cheque to deduct from
    enrolment_closes: date
    cover_starts: date
    history: pd.DataFrame = field(repr=False)   # this farm's payouts, per season of the chosen type

    def as_dict(self) -> dict:
        d = asdict(self)
        d["history"] = self.history[["year", "payout_total"]].to_dict("records")
        d["enrolment_closes"] = self.enrolment_closes.isoformat()
        d["cover_starts"] = self.cover_starts.isoformat()
        return d


money = whole_shillings  # one rounding rule for every shilling the product shows


def discount_rate_for(points: int) -> Decimal:
    """The Resilience discount: 1% of the farmer's share a point, at most 15%."""
    return min(Decimal(points) * Decimal(repr(DISCOUNT_PER_POINT)), Decimal(repr(DISCOUNT_CAP)))


def discount_for(farmer_share: int, points: int) -> int:
    """The discount in whole shillings, half up: what the quote takes off and what the live panel shows."""
    return money(Decimal(farmer_share) * discount_rate_for(points))


def rate_text(rate: float) -> str:
    """A premium rate to 0.1%, half up like every other figure: 0.0625 reads "6.3%", never Python's "6.2%"."""
    return f"{Decimal(repr(round(rate * 100, 9))).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)}%"


def _exact(value: float) -> Fraction:
    """A setting as an exact fraction: shares like 20,000/60,000 come back as 1/3, not 0.3333333333333333. A value
    that is not a simple fraction (a cap share of 0.82004...) is kept exactly as given."""
    simple = Fraction(value).limit_denominator(10_000)
    return simple if abs(float(simple) - value) < 1e-12 else Fraction(value)


def _exact_units(base: TriggerParams) -> dict:
    si = _exact(base.sum_insured)
    return {"crop": si * _exact(base.crop_share) / STANDARD_ACRES,
            "fodder": si * _exact(base.fodder_share) / STANDARD_COWS,
            "vet": si * _exact(base.health_share) / STANDARD_COWS}


def _exact_cover(acres: float, cows: int, base: TriggerParams) -> dict:
    unit = _exact_units(base)
    return {"crop": _exact(acres) * unit["crop"], "fodder": cows * unit["fodder"], "vet": cows * unit["vet"]}


def unit_cover(base: TriggerParams) -> dict:
    """KSh per acre of maize and per dairy cow, so that the standard farm gets exactly the product's sum insured."""
    return {k: float(v) for k, v in _exact_units(base).items()}


def farm_cover(acres: float, cows: int, base: TriggerParams = TriggerParams()) -> dict:
    return {k: float(v) for k, v in _exact_cover(acres, cows, base).items()}


def farm_params(base: TriggerParams, acres: float, cows: int) -> TriggerParams:
    """The product settings, resized to this farm's cover. The cap stays the same share of the sum insured."""
    cover = _exact_cover(acres, cows, base)
    total = sum(cover.values())
    return replace(base, sum_insured=float(total), crop_share=float(cover["crop"] / total),
                   fodder_share=float(cover["fodder"] / total), health_share=float(cover["vet"] / total))


def _decimal(value: Fraction) -> Decimal:
    """An exact fraction as a decimal, to well past the shilling (cover amounts can be thirds of a shilling)."""
    return Decimal(value.numerator) / Decimal(value.denominator)


def farm_words(acres: float, cows: int) -> str:
    maize = f"{acres:g} acre{'' if acres == 1 else 's'} of maize" if acres else "no maize"
    dairy = f"{cows} dairy cow{'' if cows == 1 else 's'}" if cows else "no dairy cows"
    return f"{maize} and {dairy}"


def resilience(selected: dict) -> tuple[int, list[dict]]:
    """Points from verified practices; within a group (irrigation) only the higher item counts."""
    unknown = sorted(set(selected) - set(ITEMS))
    if unknown:
        raise QuoteError(f"unknown Resilience items: {unknown}")
    chosen = [ITEMS[k] for k, on in selected.items() if on]
    best_in_group = {}
    for item in chosen:
        if item.group and (item.group not in best_in_group or best_in_group[item.group].points < item.points):
            best_in_group[item.group] = item
    counted = [i for i in chosen if i.group is None or best_in_group[i.group] is i]
    return sum(i.points for i in counted), [{"id": i.id, "label": i.label, "points": i.points,
                                             "verified_by": i.verified_by} for i in counted]


def season_dates(season: str, year: int = COVER_YEAR) -> tuple[date, date]:
    month, day = SEASONS[season]["start"]
    starts = date(year, month, day)
    return date.fromordinal(starts.toordinal() - CLOSE_DAYS_BEFORE_SEASON), starts


def _validate(acres, cows) -> tuple[float, int]:
    if isinstance(acres, bool) or not isinstance(acres, numbers.Real) or not math.isfinite(acres):
        raise FarmNotValid("Acres of maize must be a number.")
    if isinstance(cows, bool) or not isinstance(cows, numbers.Real) or not math.isfinite(cows) \
            or not float(cows).is_integer():
        raise FarmNotValid("Dairy cows must be a whole number.")
    acres, cows = float(acres), int(cows)
    if not (0 <= acres <= MAX_ACRES) or not (0 <= cows <= MAX_COWS):
        raise FarmNotValid(f"The product covers 0 to {MAX_ACRES:g} acres of maize and 0 to {MAX_COWS} dairy cows.")
    if acres < 0.5 and cows < 1:
        raise FarmNotValid("A farm needs at least half an acre of maize or one dairy cow.")
    return acres, cows


def quote(weather: pd.DataFrame, base: TriggerParams, *, ward_key: str, season: str, acres: float, cows: int,
          practices: dict | None = None, ward_offered: bool = True) -> Quote:
    if ward_key not in WARDS:
        raise QuoteError(f"unknown ward {ward_key!r}")
    if season not in SEASONS:
        raise QuoteError(f"unknown season {season!r}")
    acres, cows = _validate(acres, cows)
    points, counted = resilience(practices or {})
    if not ward_offered:
        raise WardNotOffered(f"{WARDS[ward_key].label} is not offered on the standard bundle: its price is above "
                             f"the {base.max_sellable_rate:.0%} sellable ceiling.")

    params = farm_params(base, acres, cows)
    seasons = run_backtest(weather, params)
    burn = kpis(seasons, params).burn_cost_pct / 100
    rate = commercial_rate(burn, params)
    if rate > base.max_sellable_rate + 1e-12:
        raise FarmAboveCeiling(f"This farm's mix prices at {rate_text(rate)} a season, above the "
                               f"{base.max_sellable_rate:.0%} sellable ceiling.", rate)

    exact_rate = Decimal(repr(rate))
    exact_cover = _exact_cover(acres, cows, base)
    exact_si = sum(exact_cover.values())
    gross = money(_decimal(exact_si) * exact_rate)
    exact_cap = _decimal(exact_si * _exact(base.aggregate_cap_share))
    low, high = SUBSIDY_ACRES
    eligible = low <= acres <= high
    government = money(Decimal(gross) * Decimal(repr(base.subsidy_share))) if eligible else 0
    farmer_share = gross - government
    discount_rate = float(discount_rate_for(points))
    discount = discount_for(farmer_share, points)
    farmer_pays = farmer_share - discount
    fee = money(Decimal(gross) * Decimal(repr(base.platform_fee_rate)))
    closes, starts = season_dates(season)
    history = seasons[seasons["season"] == season].reset_index(drop=True)
    # The ID fingerprints everything the quote says (48 bits of SHA-256), so the same quote gets the same ID and any
    # change gets a new one.
    fingerprint = {"ward": ward_key, "season": season, "acres": acres, "cows": cows,
                   "practices": sorted(i["id"] for i in counted), "sum_insured": str(exact_si),
                   "cap": str(exact_cap), "rate": rate, "gross": gross, "government": government,
                   "discount": discount, "fee": fee, "history": [round(v, 2) for v in history["payout_total"]]}
    digest = hashlib.sha256(json.dumps(fingerprint, sort_keys=True).encode()).hexdigest()
    return Quote(
        quote_id=f"SS360-Q-{digest[:12].upper()}", ward_key=ward_key, season=season, acres=acres, cows=cows,
        unit_cover=unit_cover(base), cover=farm_cover(acres, cows, base), sum_insured=float(exact_si),
        seasonal_cap=float(exact_cap), burn_cost_rate=burn, pricing_mode=base.pricing_mode, premium_rate=rate,
        gross_premium=gross, subsidy_share=base.subsidy_share, subsidy_eligible=eligible, government_share=government,
        farmer_share=farmer_share, resilience_points=points, resilience_counted=counted, discount_rate=discount_rate,
        discount=discount, farmer_pays=farmer_pays, platform_fee=fee,
        discount_exceeds_fee=DISCOUNT_FUNDER == "platform" and discount > fee,
        per_day_checkoff=farmer_pays / CHECKOFF_DAYS if cows else None,
        enrolment_closes=closes, cover_starts=starts, history=history,
    )


def long_date(d: date) -> str:
    return f"{d.day} {d:%B %Y}"


PREPARED_FOR = (("farmer", "Farmer"), ("farm", "Farm"), ("member", "SACCO member number"), ("phone", "Phone"),
                ("village", "Village or location"))


def quotation_number(q: Quote, prepared_for: dict | None = None) -> str:
    """The quote's ID, with a short suffix for the farmer it is made out to, so two farmers' quotations for the
    same farm terms never share a number."""
    details = {k: (prepared_for or {}).get(k, "").strip() for k, _ in PREPARED_FOR}
    if not any(details.values()):
        return q.quote_id
    suffix = hashlib.sha256(json.dumps(details, sort_keys=True).encode()).hexdigest()[:4].upper()
    return f"{q.quote_id}-{suffix}"


def quote_text(q: Quote, prepared_for: dict | None = None) -> str:
    """A plain-text copy of the quote for the SACCO officer to share or print, made out to the farmer when their
    details are given."""
    ward = WARDS[q.ward_key]
    paid = q.history[q.history["payout_total"] > 0]
    lines = [
        f"ShambaShield360 quotation {quotation_number(q, prepared_for)} (ILLUSTRATIVE: not a filed product, not for "
        "sale)",
        f"{ward.label}, {SEASON_WORDS[q.season]} {COVER_YEAR}",
        f"Farm: {farm_words(q.acres, q.cows)}",
    ]
    given = [(label, (prepared_for or {}).get(key, "").strip()) for key, label in PREPARED_FOR]
    if any(value for _, value in given):
        lines += ["", "Prepared for"] + [f"  {label + ':':<22}{value}" for label, value in given if value]
    lines += [
        "",
        "Cover",
        f"  Crop inputs   KSh {money(q.cover['crop']):>9,}",
        f"  Fodder gap    KSh {money(q.cover['fodder']):>9,}",
        f"  Vet & health  KSh {money(q.cover['vet']):>9,}",
        f"  Sum insured   KSh {money(q.sum_insured):>9,} (most paid in one season: KSh {money(q.seasonal_cap):,})",
        "",
        "Price",
        f"  Gross premium            KSh {q.gross_premium:>8,} ({rate_text(q.premium_rate)})",
        f"  Government share         KSh {-q.government_share:>8,}",
        f"  Resilience discount      KSh {-q.discount:>8,} ({q.resilience_points} points)",
        f"  Farmer pays              KSh {q.farmer_pays:>8,}",
    ]
    if q.per_day_checkoff is not None:
        lines.append(f"  or about KSh {money(q.per_day_checkoff):,} a day by milk check-off over {CHECKOFF_DAYS} days")
    if q.government_share:
        lines.append("  The government share is illustrative: no subsidy is agreed.")
    if q.discount_exceeds_fee:
        lines.append(f"  Note: the discount is larger than the platform fee on this policy (KSh {q.platform_fee:,}).")
    lines += [
        "",
        f"Enrolment closes {long_date(q.enrolment_closes)}; cover starts {long_date(q.cover_starts)}.",
        f"On 2015-2024 weather this cover would have paid in {len(paid)} of {len(q.history)} "
        f"{SEASON_WORDS[q.season]} seasons.",
        "Insurer: Partner insurer (to be named). Calculating agent: ShambaShield360.",
    ]
    return "\n".join(lines) + "\n"
