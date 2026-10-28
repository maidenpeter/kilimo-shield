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


class PetSettings(BaseModel):
    # hargreaves_nasapower = FAO-56 Hargreaves from NASA POWER temperature (fallback)
    # synthetic            = labelled seasonal curve, tests only
    source: Literal["hargreaves_nasapower", "synthetic"]
    lapse_rate_c_per_km: float = Field(default=6.5, ge=0, le=12)
    # FEWS NET daily PET per ward as <dir>/<ward>.csv (date, pet_mm). When present,
    # it is used from 2001 and Hargreaves is calibrated to it for earlier years.
    fewsnet_pet_dir: str = "data/raw/fewsnet_pet"
    fewsnet_status: str = ""


class ValidationSettings(BaseModel):
    fewsnet_wrsi_dir: str
    large_gap_wrsi: float = Field(gt=0)
    fewsnet_status: str = ""
    yields_dir: str


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
    soil_whc_mm: float = Field(gt=0, le=400)   # plant-available water holding capacity
    soil_illustrative: bool = True
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
    planting_window: MonthDay      # v1: dekads searched for the start of season
    variety: str
    lgp_days: int = Field(gt=0, le=300)   # length of growing period (v1 WRSI)
    planting_date: str             # v0 only: fixed planting date
    phases: list[Phase]            # v0 only: fixed phase lengths

    @field_validator("planting_date")
    @classmethod
    def _valid_md(cls, v: str) -> str:
        _parse_md(v)
        return v

    @property
    def lgp_dekads(self) -> int:
        return max(1, round(self.lgp_days / 10))

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


class LayerBV0(BaseModel):
    """Superseded per-phase percentile index, kept for side-by-side comparison."""
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


class KcCurve(BaseModel):
    points_pct: list[float]
    values: list[float]

    @model_validator(mode="after")
    def _shape(self):
        pts = self.points_pct
        if len(pts) != len(self.values) or len(pts) < 2:
            raise ValueError("kc points_pct and values must have the same length (>= 2)")
        if pts[0] != 0 or pts[-1] != 100 or any(b <= a for a, b in zip(pts, pts[1:])):
            raise ValueError("kc points_pct must rise strictly from 0 to 100")
        if any(not 0 < v <= 2 for v in self.values):
            raise ValueError("kc values must be in (0, 2]")
        return self


class FailedOnset(BaseModel):
    """Total rain over the whole planting window below a threshold: the season never started."""
    window_rain_below_mm: float = Field(gt=0)
    payout: float = Field(ge=0, le=1)          # share of sum insured


class GerminationDrySpell(BaseModel):
    """After a planting rain, too little rain for germination: pays a fixed replanting amount."""
    days_after_planting: int = Field(gt=0, le=60)
    rain_below_mm: float = Field(gt=0)
    replant_cost_kes_per_acre: float = Field(gt=0)
    # How far past the planting window to look for the replanting rain (dekads).
    restart_search_extra_dekads: int = Field(ge=0, le=9)


class FloweringComponent(BaseModel):
    """EXPERIMENTAL: extra cover for drought at flowering, priced separately, off by default."""
    enabled: bool = False
    window_pct_of_lgp: tuple[float, float]
    metric: Literal["longest_dry_spell", "rainfall_deficit"]
    dry_day_mm: float = Field(gt=0)            # longest_dry_spell: a day below this is dry
    trigger: float = Field(gt=0)               # dry-spell days, or % deficit vs crop water need
    exit: float = Field(gt=0)
    max_payout: float = Field(gt=0, le=1)

    @model_validator(mode="after")
    def _shape(self):
        a, b = self.window_pct_of_lgp
        if not 0 <= a < b <= 100:
            raise ValueError("flowering window_pct_of_lgp must rise within 0-100")
        if not self.exit > self.trigger:
            raise ValueError("flowering exit must exceed trigger (longer spell / bigger deficit pays more)")
        if self.metric == "rainfall_deficit" and self.exit > 100:
            raise ValueError("flowering rainfall_deficit exit is a % and cannot exceed 100")
        return self


class LayerB(BaseModel):
    """v1: seasonal WRSI index with dynamic start of season and early-season triggers."""
    version: str
    kc: KcCurve
    depletion_fraction: float = Field(gt=0, lt=1)
    spinup_dekads: int = Field(ge=0, le=12)
    planting_rain_mm: float = Field(gt=0)      # a dekad with at least this is a planting rain
    failed_onset: FailedOnset
    germination_dry_spell: GerminationDrySpell
    trigger_wrsi: float = Field(gt=0, le=100)
    exit_wrsi: float = Field(ge=0, lt=100)
    sensitivity_triggers: list[float]
    sensitivity_whc_mm: list[float] = []
    flowering: FloweringComponent
    overrides: dict[str, dict[Season, "WrsiOverride"]] = {}

    @model_validator(mode="after")
    def _order(self):
        if not self.trigger_wrsi > self.exit_wrsi:
            raise ValueError("layer_b.trigger_wrsi must be above exit_wrsi")
        if any(t <= self.exit_wrsi or t > 100 for t in self.sensitivity_triggers):
            raise ValueError("sensitivity triggers must lie between exit_wrsi and 100")
        return self

    def terms_for(self, ward_id: str, season: Season) -> dict:
        """Trigger, exit and failed-onset payout for one ward and season."""
        t = {"trigger_wrsi": self.trigger_wrsi, "exit_wrsi": self.exit_wrsi,
             "failed_onset_payout": self.failed_onset.payout}
        ov = self.overrides.get(ward_id, {}).get(season)
        if ov:
            t.update({k: v for k, v in ov.model_dump().items() if v is not None})
        if not t["trigger_wrsi"] > t["exit_wrsi"]:
            raise ValueError(f"{ward_id} {season}: WRSI trigger must be above exit")
        return t


class WrsiOverride(BaseModel):
    trigger_wrsi: float | None = Field(default=None, gt=0, le=100)
    exit_wrsi: float | None = Field(default=None, ge=0, lt=100)
    failed_onset_payout: float | None = Field(default=None, ge=0, le=1)


LayerB.model_rebuild()


def _band(periods: tuple[float, float]) -> tuple[float, float]:
    lo, hi = sorted(periods)
    return 1 / hi, 1 / lo


class Target(BaseModel):
    # Payout once every N years, as a band (placeholder pending the underwriter).
    payout_return_period_years: tuple[float, float]
    ward_overrides: dict[str, tuple[float, float]] = {}

    @property
    def frequency_band(self) -> tuple[float, float]:
        return _band(self.payout_return_period_years)

    def periods_for(self, ward_id: str) -> tuple[float, float]:
        return tuple(self.ward_overrides.get(ward_id, self.payout_return_period_years))

    def band_for(self, ward_id: str) -> tuple[float, float]:
        return _band(self.periods_for(ward_id))


class EventTest(BaseModel):
    year: int
    season: Season
    min_payout: float = Field(gt=0, le=1)
    # Wards where the payout is REQUIRED (pass/fail); at every other ward the event is reported only.
    required_for: list[str] = []
    note: str = ""


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


class Product(BaseModel):
    illustrative: bool
    layer_b: LayerB
    layer_b_v0: LayerBV0
    target: Target
    event_tests: list[EventTest] = []
    sum_insured: SumInsured
    premium: Premium
    backtest: Backtest


# --------------------------------------------------------------- whole config
class Config(BaseModel):
    pilot: Pilot
    rainfall: RainfallSettings
    pet: PetSettings
    validation: ValidationSettings
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
                missing = set(self.product.layer_b_v0.phases) - names
                if missing:
                    raise ValueError(f"{ward.id} {season}: phenology has no phase {sorted(missing)}")
                self.product.layer_b_v0.terms_for(ward.id, season)  # validates overrides + weights
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
        pet=raw["pilot.yaml"]["pet"],
        validation=raw["pilot.yaml"]["validation"],
        wards=wards,
        phenology=raw["phenology.yaml"],
        product=raw["product.yaml"],
        root=root,
        file_hashes=hashes,
    )
