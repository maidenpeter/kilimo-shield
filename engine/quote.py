"""Farm quotes: what one farmer pays for a season, and who pays the rest. ILLUSTRATIVE.

Cover follows the farm. The standard farm (2 acres of maize, 2 dairy cows) is the KSh 60,000 package:

    crop inputs   KSh 15,000 per acre of maize
    fodder gap    KSh 10,000 per dairy cow
    vet & health  KSh  5,000 per dairy cow

The quote prices this farm's own mix with the same engine and the same product settings as the backtest, so a
standard farm's rate equals its ward's rate in the zone pricing table. Then it splits who pays, as AgroShield did:

    gross premium      = sum insured x commercial rate (the risk price; never changed by what follows)
    government share   = subsidy share x gross, if the farm has 0.5 to 20 acres (no subsidy is agreed)
    farmer share       = gross - government share
    Resilience         = min(15%, 1% per point) x farmer share, paid by the platform out of its fee
    farmer pays        = farmer share - Resilience discount

The insurer always receives the full gross premium. A ward the engine does not offer gets no quote.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field, replace
from datetime import date

import pandas as pd

from engine.parametric_engine import SEASONS, WARDS, TriggerParams, commercial_rate, kpis, run_backtest

CROP_PER_ACRE = 15_000.0
FODDER_PER_COW = 10_000.0
VET_PER_COW = 5_000.0
MAX_ACRES = 20.0
MAX_COWS = 20
SUBSIDY_ACRES = (0.5, 20.0)
PLATFORM_FEE_RATE = 0.10           # calculating-agent fee, share of gross premium
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


@dataclass
class Quote:
    quote_id: str
    ward_key: str
    season: str
    acres: float
    cows: int
    cover: dict                  # layer name -> KSh sum insured
    sum_insured: float
    seasonal_cap: float
    burn_cost_rate: float
    premium_rate: float
    gross_premium: float
    subsidy_eligible: bool
    government_share: float
    farmer_share: float
    resilience_points: int
    resilience_counted: list
    discount_rate: float
    discount: float
    farmer_pays: float
    platform_fee: float
    discount_exceeds_fee: bool
    per_day_checkoff: float
    enrolment_closes: date
    cover_starts: date
    history: pd.DataFrame = field(repr=False)   # this farm's payouts, per season of the chosen type

    def as_dict(self) -> dict:
        d = asdict(self)
        d["history"] = self.history[["year", "payout_total"]].to_dict("records")
        d["enrolment_closes"] = self.enrolment_closes.isoformat()
        d["cover_starts"] = self.cover_starts.isoformat()
        return d


def farm_cover(acres: float, cows: int) -> dict:
    return {"crop": acres * CROP_PER_ACRE, "fodder": cows * FODDER_PER_COW, "vet": cows * VET_PER_COW}


def farm_params(base: TriggerParams, acres: float, cows: int) -> TriggerParams:
    """The product settings, resized to this farm's cover. The cap stays the same share of the sum insured."""
    cover = farm_cover(acres, cows)
    total = sum(cover.values())
    return replace(base, sum_insured=total, crop_share=cover["crop"] / total, fodder_share=cover["fodder"] / total,
                   health_share=cover["vet"] / total)


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
    return sum(i.points for i in counted), [{"label": i.label, "points": i.points, "verified_by": i.verified_by}
                                           for i in counted]


def season_dates(season: str, year: int = COVER_YEAR) -> tuple[date, date]:
    month, day = SEASONS[season]["start"]
    starts = date(year, month, day)
    return date.fromordinal(starts.toordinal() - CLOSE_DAYS_BEFORE_SEASON), starts


def _id(payload: dict) -> str:
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
    return f"SS360-Q-{digest[:8].upper()}"


def quote(weather: pd.DataFrame, base: TriggerParams, *, ward_key: str, season: str, acres: float, cows: int,
          practices: dict | None = None, ward_offered: bool = True) -> Quote:
    if ward_key not in WARDS:
        raise QuoteError(f"unknown ward {ward_key!r}")
    if season not in SEASONS:
        raise QuoteError(f"unknown season {season!r}")
    if not ward_offered:
        raise QuoteError(f"{WARDS[ward_key].label} is not offered on the standard bundle: its price is above the "
                         f"{base.max_sellable_rate:.0%} sellable ceiling. It needs a custom tier.")
    if not (0 <= acres <= MAX_ACRES) or not (0 <= cows <= MAX_COWS):
        raise QuoteError(f"acres must be 0 to {MAX_ACRES:g} and cows 0 to {MAX_COWS}")
    if acres < 0.5 and cows < 1:
        raise QuoteError("a farm needs at least half an acre of maize or one dairy cow")

    params = farm_params(base, acres, cows)
    seasons = run_backtest(weather, params)
    k = kpis(seasons, params)
    rate = commercial_rate(k.burn_cost_pct / 100, params)
    gross = round(params.sum_insured * rate)
    low, high = SUBSIDY_ACRES
    eligible = low <= acres <= high
    government = round(gross * base.subsidy_share) if eligible else 0
    farmer_share = gross - government
    points, counted = resilience(practices or {})
    discount_rate = min(DISCOUNT_CAP, points * DISCOUNT_PER_POINT)
    discount = round(farmer_share * discount_rate)
    farmer_pays = farmer_share - discount
    fee = round(gross * PLATFORM_FEE_RATE)
    closes, starts = season_dates(season)
    payload = {"ward": ward_key, "season": season, "acres": acres, "cows": cows, "practices": practices or {},
               "params": asdict(params)}
    return Quote(
        quote_id=_id(payload), ward_key=ward_key, season=season, acres=acres, cows=cows,
        cover=farm_cover(acres, cows), sum_insured=params.sum_insured, seasonal_cap=params.aggregate_cap,
        burn_cost_rate=k.burn_cost_pct / 100, premium_rate=rate, gross_premium=gross, subsidy_eligible=eligible,
        government_share=government, farmer_share=farmer_share, resilience_points=points, resilience_counted=counted,
        discount_rate=discount_rate, discount=discount, farmer_pays=farmer_pays, platform_fee=fee,
        discount_exceeds_fee=DISCOUNT_FUNDER == "platform" and discount > fee,
        per_day_checkoff=farmer_pays / CHECKOFF_DAYS, enrolment_closes=closes, cover_starts=starts,
        history=seasons[seasons["season"] == season].reset_index(drop=True),
    )


def long_date(d: date) -> str:
    return f"{d.day} {d:%B %Y}"


def quote_text(q: Quote) -> str:
    """A plain-text copy of the quote for the SACCO officer to share or print."""
    ward = WARDS[q.ward_key]
    paid = q.history[q.history["payout_total"] > 0]
    lines = [
        f"ShambaShield360 quote {q.quote_id} (ILLUSTRATIVE: not a filed product, not for sale)",
        f"{ward.label}, {SEASONS[q.season]['name']} {COVER_YEAR}",
        f"Farm: {q.acres:g} acres of maize, {q.cows} dairy cows",
        "",
        "Cover",
        f"  Crop inputs   KSh {q.cover['crop']:>9,.0f}",
        f"  Fodder gap    KSh {q.cover['fodder']:>9,.0f}",
        f"  Vet & health  KSh {q.cover['vet']:>9,.0f}",
        f"  Sum insured   KSh {q.sum_insured:>9,.0f} (most paid in one season: KSh {q.seasonal_cap:,.0f})",
        "",
        "Price",
        f"  Gross premium            KSh {q.gross_premium:>8,.0f} ({q.premium_rate:.1%})",
        f"  Government share         KSh {-q.government_share:>8,.0f}",
        f"  Resilience discount      KSh {-q.discount:>8,.0f} ({q.resilience_points} points)",
        f"  Farmer pays              KSh {q.farmer_pays:>8,.0f}",
        f"  or about KSh {q.per_day_checkoff:,.0f} a day by milk check-off over {CHECKOFF_DAYS} days",
        "",
        f"Enrolment closes {long_date(q.enrolment_closes)}; cover starts {long_date(q.cover_starts)}.",
        f"On 2015-2024 weather this cover would have paid in {len(paid)} of {len(q.history)} "
        f"{SEASON_WORDS[q.season]} seasons.",
        "Insurer: Partner insurer (to be named). Calculating agent: ShambaShield360.",
    ]
    return "\n".join(lines) + "\n"
