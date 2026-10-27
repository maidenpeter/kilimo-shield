"""Load and validate the YAML config in config/.

Everything that drives a price lives in config, never in code, so changing a
ward, phenology date, trigger level or loading is a config edit. Each file's
SHA-256 is kept so every run manifest can say exactly which terms it used.
"""
from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

Season = Literal["LR", "SR"]
CONFIG_FILES = ("pilot.yaml", "wards.yaml", "phenology.yaml", "product.yaml")


# ----------------------------------------------------------------- pilot.yaml
class History(BaseModel):
    start_year: int
    end_year: int

    @model_validator(mode="after")
    def _order(self):
        if self.end_year < self.start_year:
            raise ValueError("history.end_year is before start_year")
        return self


class RainfallSettings(BaseModel):
    source: Literal["chirps", "synthetic"]
    history: History
    synthetic_seed: int = 0


class Pilot(BaseModel):
    county: str
    crop: str
    default_ward: str
    wards: list[str]
    sacco: str = "TBD"
    underwriter: str = "TBD"


# ----------------------------------------------------------------- wards.yaml
class LatLon(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class Ward(BaseModel):
    id: str
    name: str
    illustrative: bool
    centroid: LatLon
    extraction_box_deg: float = Field(gt=0, le=1)
    elevation_m: float | None = None
    seasons: list[Season]
    notes: str = ""


# ------------------------------------------------------------- phenology.yaml
class Phase(BaseModel):
    name: str
    days: int = Field(gt=0)


class MonthDay(BaseModel):
    start: str
    end: str


def _parse_md(md: str) -> tuple[int, int]:
    month, day = (int(x) for x in md.split("-"))
    date(2001, month, day)  # raises on an impossible date; 2001 is not a leap year
    return month, day


class SeasonCalendar(BaseModel):
    planting_window: MonthDay
    planting_date: str
    phases: list[Phase]

    @field_validator("planting_date")
    @classmethod
    def _valid_md(cls, v: str) -> str:
        _parse_md(v)
        return v

    @property
    def planting_month_day(self) -> tuple[int, int]:
        return _parse_md(self.planting_date)

    @model_validator(mode="after")
    def _unique_phases(self):
        names = [p.name for p in self.phases]
        if len(names) != len(set(names)):
            raise ValueError(f"duplicate phase names: {names}")
        return self


class Phenology(BaseModel):
    illustrative: bool
    wards: dict[str, dict[Season, SeasonCalendar]]


# --------------------------------------------------------------- product.yaml
class Level(BaseModel):
    """A trigger or exit level: a fixed mm value or a historical percentile."""
    mm: float | None = Field(default=None, ge=0)
    percentile: float | None = Field(default=None, ge=0, le=100)

    @model_validator(mode="after")
    def _exactly_one(self):
        if (self.mm is None) == (self.percentile is None):
            raise ValueError("a level needs exactly one of `mm` or `percentile`")
        return self


class PhaseTerms(BaseModel):
    weight: float = Field(ge=0, le=1)
    trigger: Level
    exit: Level


class PhaseOverride(BaseModel):
    weight: float | None = Field(default=None, ge=0, le=1)
    trigger: Level | None = None
    exit: Level | None = None


class LayerB(BaseModel):
    version: str
    daily_min_mm: float = Field(ge=0)
    daily_cap_mm: float = Field(gt=0)
    phases: dict[str, PhaseTerms]
    calibration: History
    overrides: dict[str, dict[Season, dict[str, PhaseOverride]]] = {}

    def terms_for(self, ward_id: str, season: Season) -> dict[str, PhaseTerms]:
        """Phase terms for one ward and season, with any overrides applied."""
        terms = {k: v.model_copy(deep=True) for k, v in self.phases.items()}
        for phase, ov in self.overrides.get(ward_id, {}).get(season, {}).items():
            if phase not in terms:
                raise ValueError(f"override for unknown phase {phase!r} ({ward_id} {season})")
            # Take the field objects themselves: model_dump() would turn Levels into dicts.
            update = {k: getattr(ov, k) for k in ov.model_fields_set if getattr(ov, k) is not None}
            terms[phase] = terms[phase].model_copy(update=update)
        _check_weights(terms, f"{ward_id} {season}")
        return terms


def _check_weights(terms: dict[str, PhaseTerms], where: str) -> None:
    total = sum(t.weight for t in terms.values())
    if abs(total - 1.0) > 1e-9:
        raise ValueError(f"Layer B phase weights must sum to 1, got {total:.4f} ({where})")


class SumInsured(BaseModel):
    options_kes_per_acre: list[float]
    default_kes_per_acre: float

    @model_validator(mode="after")
    def _default_listed(self):
        if self.default_kes_per_acre not in self.options_kes_per_acre:
            raise ValueError("sum_insured.default_kes_per_acre must be one of the options")
        return self


class RiskMargin(BaseModel):
    method: Literal["std_dev", "tail"]
    factor: float = Field(ge=0)
    percentile: float | None = Field(default=None, gt=0, lt=100)

    @model_validator(mode="after")
    def _tail_needs_percentile(self):
        if self.method == "tail" and self.percentile is None:
            raise ValueError("risk_margin method 'tail' needs a percentile")
        return self


class Premium(BaseModel):
    risk_margin: RiskMargin
    loadings: dict[str, float]

    @field_validator("loadings")
    @classmethod
    def _below_one(cls, v: dict[str, float]) -> dict[str, float]:
        if any(x < 0 for x in v.values()) or sum(v.values()) >= 1:
            raise ValueError("loadings must be non-negative and sum to less than 1")
        return v


class Backtest(BaseModel):
    bad_yield_threshold: float = Field(gt=0, lt=1)
    meaningful_payout: float = Field(ge=0, lt=1)


class SyntheticYield(BaseModel):
    potential_t_per_ha: float = Field(gt=0)
    soil_water_capacity_mm: float = Field(gt=0)
    depletion_fraction: float = Field(gt=0, lt=1)
    water_need_mm_per_day: dict[str, float]
    ky: dict[str, float]
    noise_sd: float = Field(ge=0)
    shock_probability: float = Field(ge=0, le=1)
    shock_loss_range: tuple[float, float]
    seed: int = 0


class Product(BaseModel):
    illustrative: bool
    layer_b: LayerB
    sum_insured: SumInsured
    premium: Premium
    backtest: Backtest
    synthetic_yield: SyntheticYield


# --------------------------------------------------------------- whole config
class Config(BaseModel):
    pilot: Pilot
    rainfall: RainfallSettings
    wards: dict[str, Ward]
    phenology: Phenology
    product: Product
    root: Path
    file_hashes: dict[str, str]

    def ward(self, ward_id: str) -> Ward:
        if ward_id not in self.wards:
            raise KeyError(f"unknown ward {ward_id!r}; known: {sorted(self.wards)}")
        return self.wards[ward_id]

    def calendar(self, ward_id: str, season: Season) -> SeasonCalendar:
        try:
            return self.phenology.wards[ward_id][season]
        except KeyError:
            raise KeyError(f"no phenology for {ward_id} {season} in phenology.yaml") from None

    @model_validator(mode="after")
    def _cross_checks(self):
        for wid in self.pilot.wards + [self.pilot.default_ward]:
            if wid not in self.wards:
                raise ValueError(f"pilot ward {wid!r} is not defined in wards.yaml")
        for ward in self.wards.values():
            for season in ward.seasons:
                cal = self.calendar(ward.id, season)
                names = {p.name for p in cal.phases}
                missing = set(self.product.layer_b.phases) - names
                if missing:
                    raise ValueError(f"{ward.id} {season}: phenology has no phase {sorted(missing)}")
                self.product.layer_b.terms_for(ward.id, season)  # validates overrides + weights
        return self


def load_config(config_dir: str | Path = "config") -> Config:
    root = Path(config_dir).resolve()
    raw, hashes = {}, {}
    for name in CONFIG_FILES:
        data = (root / name).read_bytes()
        hashes[name] = hashlib.sha256(data).hexdigest()
        raw[name] = yaml.safe_load(data) or {}
    wards = {w["id"]: w for w in raw["wards.yaml"]["wards"]}
    return Config(
        pilot=raw["pilot.yaml"]["pilot"],
        rainfall=raw["pilot.yaml"]["rainfall"],
        wards=wards,
        phenology=raw["phenology.yaml"],
        product=raw["product.yaml"],
        root=root,
        file_hashes=hashes,
    )
