"""ShambaShield360 parametric engine: weather, derived indices and the three payout layers.

Weather comes from the Open-Meteo Historical Weather API (ERA5-based reanalysis, CC BY 4.0). Each ward's
2015-2024 record is cached in ``data/weather_cache/`` so the app runs offline. If neither the cache nor the
network is available, a deterministic synthetic record is generated and labelled as such.

The soil moisture index and the pasture NDVI are *synthetic proxies* computed from that weather. They stand in
for Sentinel-1 SAR soil moisture and Sentinel-2 NDVI until real satellite feeds are connected; nothing here is
read from a satellite.
"""
from __future__ import annotations

import json
import math
import zlib
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
START_DATE, END_DATE = "2015-01-01", "2024-12-31"
YEARS = list(range(2015, 2025))
DAILY_VARS = ("precipitation_sum", "et0_fao_evapotranspiration", "temperature_2m_max")
CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "weather_cache"

SOURCE_CACHE = "Open-Meteo archive (cached copy)"
SOURCE_LIVE = "Open-Meteo archive (live)"
SOURCE_FALLBACK = "Offline fallback (synthetic weather)"


@dataclass(frozen=True)
class Ward:
    key: str
    name: str
    county: str
    lat: float
    lon: float
    enterprise: str
    zone: str

    @property
    def label(self) -> str:
        return f"{self.name}, {self.county} County"


WARDS: dict[str, Ward] = {w.key: w for w in (
    Ward("njoro", "Njoro Ward", "Nakuru", -0.3306, 35.9436, "Maize, beans and dairy", "Transitional"),
    Ward("imenti_north", "Imenti North", "Meru", 0.0470, 37.6559, "Potatoes, maize and zero-grazing dairy",
         "Transitional"),
    Ward("kangundo", "Kangundo", "Machakos", -1.2981, 37.3481, "Maize, pigeon peas, shoats and cattle",
         "Semi-arid"),
    Ward("kimilili", "Kimilili", "Bungoma", 0.7897, 34.7186, "Maize, sugarcane and dairy", "High potential (wet)"),
    Ward("bureti", "Bureti", "Kericho", -0.6167, 35.2500, "Tea, maize and dairy", "Wet highland"),
)}

# Kenya's two rainy seasons. Each is 92 days, so "day 1" is the first day of the season window.
SEASONS = {
    "LR": {"name": "Long rains (MAM)", "start": (3, 1), "end": (5, 31)},
    "SR": {"name": "Short rains (OND)", "start": (10, 1), "end": (12, 31)},
}
GERMINATION_DAYS = (1, 30)
FLOWERING_DAYS = (45, 75)


@dataclass(frozen=True)
class TriggerParams:
    """Every number that shapes a payout or a price. ILLUSTRATIVE defaults, version 2 of the product:

    sub-limits KSh 30,000 crop + 20,000 fodder + 10,000 vet and health under a KSh 50,000 seasonal cap; the
    fodder layer needs a severe crop loss; the excess-rain line is set per ward; premiums are priced per ward
    to a target loss ratio instead of one flat rate.
    """
    sum_insured: float = 60_000.0          # the standard farm: 2 acres of maize and 2 dairy cows
    crop_share: float = 30_000 / 60_000    # Payout A sub-limit
    fodder_share: float = 20_000 / 60_000  # Payout B sub-limit
    health_share: float = 10_000 / 60_000  # Payout C flat amount
    aggregate_cap_share: float = 50_000 / 60_000  # most a policy pays in one season, all layers together
    germination_weight: float = 0.35
    flowering_weight: float = 0.65
    sm_trigger: float = 32.0              # soil moisture index (50 = normal) below which Payout A starts
    sm_exit: float = 12.0                 # index at or below which Payout A reaches 100%
    fodder_gate: float = 0.5              # Payout A must reach this share of its sub-limit before B can pay
    ndvi_trigger: float = 25.0            # pasture NDVI percentile below which Payout B can fire
    fodder_ndvi_days: tuple = (61, 92)    # pasture is read from day 61, 16 days after flowering opens
    rain10_mode: str = "percentile"       # "percentile": a line per ward; "fixed": rain10_trigger_mm everywhere
    rain10_percentile: float = 90.0       # percentile of the ward's wettest 10 days in each season
    rain10_trigger_mm: float = 180.0      # fixed line, used when rain10_mode == "fixed"
    heat_temp_c: float = 31.0             # daily maximum above which a day counts as a heat day
    heat_days: int = 7                    # consecutive heat days that fire Payout C
    # Pricing
    pricing_mode: str = "target"          # "target": burn cost / target loss ratio per ward; "flat": premium_rate
    target_loss_ratio: float = 0.60
    min_premium_rate: float = 0.01        # target pricing never goes below this, even if history never paid
    premium_rate: float = 0.06            # flat commercial rate per season, used when pricing_mode == "flat"
    subsidy_share: float = 0.0            # share of the premium paid by a subsidy (none is agreed)
    platform_fee_rate: float = 0.10       # calculating-agent fee, share of gross premium
    max_sellable_rate: float = 0.12       # above this commercial rate a ward is not sold the standard bundle
    # WhatsApp verification, for the post-verification basis-risk view
    amber_band: float = 5.0               # seasons this close to the soil moisture trigger go to verification
    verifier_accuracy: float = 0.8        # assumed share of verified seasons the photos settle correctly
    # Soil water balance behind the soil moisture proxy (a single root-zone bucket).
    capacity_mm: float = 100.0            # plant-available water held by the root zone
    stress_point: float = 0.5             # below this share of capacity, ET is reduced linearly
    # The index is relative to the ward's own record: 50 is normal for the date, 25 points per standard deviation.
    anomaly_scale: float = 25.0
    climatology_halfwidth_days: int = 15
    ndvi_lag_days: float = 16.0           # vegetation greenness follows soil moisture with a lag

    @property
    def crop_allocation(self) -> float:
        return self.sum_insured * self.crop_share

    @property
    def fodder_allocation(self) -> float:
        return self.sum_insured * self.fodder_share

    @property
    def health_payout(self) -> float:
        return self.sum_insured * self.health_share

    @property
    def aggregate_cap(self) -> float:
        return self.sum_insured * self.aggregate_cap_share


def commercial_rate(burn_rate: float, params: TriggerParams) -> float:
    """Premium rate per season. Target pricing rounds up to 0.1% so the loss ratio stays at or under target, and
    never goes below the minimum rate: ten seasons without a payout do not make the cover free."""
    if params.pricing_mode == "flat":
        return params.premium_rate
    return max(math.ceil(burn_rate / params.target_loss_ratio * 1000 - 1e-9) / 1000, params.min_premium_rate)


# --------------------------------------------------------------------------------------------- weather

def fetch_open_meteo(ward: Ward, start: str = START_DATE, end: str = END_DATE, timeout: float = 30.0):
    """Download daily rainfall, reference ET and maximum temperature for one ward. Returns (frame, meta)."""
    params = {
        "latitude": ward.lat, "longitude": ward.lon, "start_date": start, "end_date": end,
        "daily": ",".join(DAILY_VARS), "timezone": "Africa/Nairobi",
    }
    resp = requests.get(ARCHIVE_URL, params=params, timeout=timeout)
    resp.raise_for_status()
    body = resp.json()
    daily = body["daily"]
    frame = pd.DataFrame({
        "date": pd.to_datetime(daily["time"]),
        "rain_mm": daily["precipitation_sum"],
        "et0_mm": daily["et0_fao_evapotranspiration"],
        "tmax_c": daily["temperature_2m_max"],
    })
    meta = {
        "source": "Open-Meteo Historical Weather API", "url": resp.url, "licence": "CC BY 4.0",
        "attribution": "Weather data by Open-Meteo.com", "ward": ward.label,
        "requested_lat": ward.lat, "requested_lon": ward.lon,
        "grid_lat": body.get("latitude"), "grid_lon": body.get("longitude"), "elevation_m": body.get("elevation"),
        "retrieved_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }
    return _clean(frame), meta


def _clean(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.sort_values("date").reset_index(drop=True)
    for col in ("rain_mm", "et0_mm", "tmax_c"):
        frame[col] = pd.to_numeric(frame[col], errors="coerce").interpolate(limit_direction="both")
    frame["rain_mm"] = frame["rain_mm"].clip(lower=0)
    frame["et0_mm"] = frame["et0_mm"].clip(lower=0)
    if frame[["rain_mm", "et0_mm", "tmax_c"]].isna().any().any():
        raise ValueError("weather record has a column with no values")
    return frame


def save_cache(ward: Ward, frame: pd.DataFrame, meta: dict, cache_dir: Path = CACHE_DIR) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    frame.assign(date=frame["date"].dt.strftime("%Y-%m-%d")).to_csv(
        cache_dir / f"{ward.key}.csv", index=False, float_format="%.2f", lineterminator="\n")
    (cache_dir / f"{ward.key}.meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")


def read_cache(ward: Ward, cache_dir: Path = CACHE_DIR):
    path = cache_dir / f"{ward.key}.csv"
    if not path.exists():
        return None, None
    try:
        frame = _clean(pd.read_csv(path, parse_dates=["date"]))
    except (ValueError, KeyError):
        return None, None  # an unusable cache is treated as no cache
    meta_path = cache_dir / f"{ward.key}.meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    return frame, meta


def synthetic_weather(ward: Ward) -> pd.DataFrame:
    """Deterministic stand-in weather for when there is no cache and no network.

    A bimodal Kenyan rainfall climatology with gamma-distributed daily rain, a dry 2017 long rains and a dry
    2022 (both seasons), so the demo still shows the drought years. Clearly not observed data.
    """
    rng = np.random.default_rng(zlib.crc32(ward.key.encode()))
    dates = pd.date_range(START_DATE, END_DATE, freq="D")
    month_mm = np.array([40, 45, 110, 200, 140, 45, 35, 40, 45, 90, 150, 80], dtype=float)
    month_mm *= 1.0 + 0.15 * np.cos(np.radians(ward.lat * 40))
    drought = {(2017, "LR"): 0.45, (2022, "LR"): 0.5, (2022, "SR"): 0.45, (2016, "SR"): 0.6}
    rain = np.zeros(len(dates))
    for i, d in enumerate(dates):
        season = "LR" if d.month in (3, 4, 5) else "SR" if d.month in (10, 11, 12) else None
        scale = drought.get((d.year, season), 1.0)
        mean_day = month_mm[d.month - 1] / d.days_in_month * scale
        wet_prob = min(0.85, 0.15 + mean_day / 12)
        if rng.random() < wet_prob:
            rain[i] = rng.gamma(0.8, mean_day / wet_prob / 0.8)
    doy = dates.day_of_year.to_numpy()
    altitude_cooling = 4.0 if ward.key in ("njoro", "bureti") else 1.5
    tmax = 28.5 - altitude_cooling + 1.8 * np.cos(2 * np.pi * (doy - 45) / 365) + rng.normal(0, 1.1, len(dates))
    et0 = np.clip(4.6 + 0.9 * np.cos(2 * np.pi * (doy - 45) / 365) - 0.08 * rain + rng.normal(0, 0.4, len(dates)),
                  1.5, 7.5)
    return pd.DataFrame({"date": dates, "rain_mm": rain.round(2), "et0_mm": et0.round(2), "tmax_c": tmax.round(1)})


def load_weather(ward_key: str, refresh: bool = False, cache_dir: Path = CACHE_DIR):
    """Return (frame, source label, meta). Order: cache, then live API, then the synthetic fallback."""
    ward = WARDS[ward_key]
    if not refresh:
        frame, meta = read_cache(ward, cache_dir)
        if frame is not None:
            return frame, SOURCE_CACHE, meta
    try:
        frame, meta = fetch_open_meteo(ward)
        try:
            save_cache(ward, frame, meta, cache_dir)
        except OSError:
            pass  # a read-only deployment still serves the live data
        return frame, SOURCE_LIVE, meta
    except (requests.RequestException, KeyError, ValueError):
        frame, meta = read_cache(ward, cache_dir)
        if frame is not None:
            return frame, SOURCE_CACHE, meta
        return synthetic_weather(ward), SOURCE_FALLBACK, {"source": SOURCE_FALLBACK}


# ------------------------------------------------------------------------------------ derived indices

def maize_kc(day: np.ndarray) -> np.ndarray:
    """FAO-56 style maize crop coefficient over the 92-day season window."""
    return np.interp(day, [1, 20, 50, 80, 92], [0.3, 0.3, 1.2, 1.2, 0.6])


def daily_indices(weather: pd.DataFrame, params: TriggerParams = TriggerParams()) -> pd.DataFrame:
    """Run the root-zone water balance and derive the soil moisture index (0-100) and a pasture NDVI proxy.

    The bucket holds ``capacity_mm`` of plant-available water; evapotranspiration runs at ET0 while the bucket is
    above ``stress_point`` of capacity and falls linearly below it. The soil moisture index compares each day's
    water with the same time of year across the ward's record (a +-15-day window): 50 is normal, and every
    standard deviation below normal takes ``anomaly_scale`` points off. Drought years therefore read low in a wet
    ward and a dry ward alike, which is what lets one trigger level work across wards.
    """
    rain = weather["rain_mm"].to_numpy(float)
    et0 = weather["et0_mm"].to_numpy(float)
    cap = params.capacity_mm
    fraction = np.empty(len(rain))
    w = cap * 0.5  # spin-up start; the record begins two months before the first season
    for i in range(len(rain)):
        stress = min(1.0, w / (params.stress_point * cap))
        aet = min(et0[i] * stress, w + rain[i])
        w = min(cap, max(0.0, w + rain[i] - aet))
        fraction[i] = w / cap

    # Day of a 365-day year, so 1 March is day 60 in leap years too (29 February shares 28 February's day).
    dates = weather["date"].dt
    doy = dates.day_of_year.to_numpy() - (dates.is_leap_year.to_numpy() & (dates.day_of_year.to_numpy() >= 60))
    mean = np.zeros(366)
    std = np.ones(366)
    for d in range(1, 366):
        gap = np.abs(doy - d)
        near = fraction[np.minimum(gap, 365 - gap) <= params.climatology_halfwidth_days]
        mean[d], std[d] = near.mean(), max(near.std(), 0.02)
    anomaly = (fraction - mean[doy]) / std[doy]
    sm_index = np.clip(50.0 + params.anomaly_scale * anomaly, 0.0, 100.0)

    # Greenness responds to soil water with a lag: an exponential moving average, scaled to an NDVI range.
    alpha = 1.0 / params.ndvi_lag_days
    green = np.empty(len(fraction))
    g = fraction[0]
    for i, f in enumerate(fraction):
        g += alpha * (f - g)
        green[i] = g
    out = weather[["date", "rain_mm", "et0_mm", "tmax_c"]].copy()
    out["water_fraction"] = fraction
    out["water_stress"] = np.minimum(1.0, fraction / params.stress_point)  # 1 = no stress
    out["sm_index"] = sm_index
    out["ndvi"] = 0.15 + 0.60 * green
    return out


def season_window(daily: pd.DataFrame, year: int, season: str) -> pd.DataFrame:
    spec = SEASONS[season]
    start = pd.Timestamp(year, *spec["start"])
    end = pd.Timestamp(year, *spec["end"])
    window = daily[(daily["date"] >= start) & (daily["date"] <= end)].copy()
    window["day"] = np.arange(1, len(window) + 1)
    window["dekad"] = np.minimum((window["day"] - 1) // 10 + 1, 9)  # days 81-92 form the last dekad
    return window


def _days(window: pd.DataFrame, span: tuple[int, int]) -> pd.DataFrame:
    return window[(window["day"] >= span[0]) & (window["day"] <= span[1])]


def longest_run(flags) -> int:
    best = run = 0
    for flag in flags:
        run = run + 1 if flag else 0
        best = max(best, run)
    return best


# ------------------------------------------------------------------------------------- payout layers

def payout_a_fraction(weighted_sm: float, params: TriggerParams) -> float:
    """Crop layer: 0 at or above the trigger; 25% just below it, rising linearly to 100% at the exit level.
    A missing reading (NaN) pays nothing: a gap in the data is held for review, never paid in full."""
    if not math.isfinite(weighted_sm) or weighted_sm >= params.sm_trigger:
        return 0.0
    span = max(params.sm_trigger - params.sm_exit, 1e-9)
    depth = min(1.0, (params.sm_trigger - weighted_sm) / span)
    return 0.25 + 0.75 * depth


def payout_b_fraction(crop_fraction: float, ndvi_pct: float, tmax_anomaly_c: float, params: TriggerParams) -> float:
    """Fodder-gap cross-trigger: needs a SEVERE crop loss AND late pasture below the NDVI percentile trigger.

    Severe means Payout A at or above ``fodder_gate`` of its sub-limit, so a mild mid-season dry spell (when
    maize stover still grows) does not also pay for fodder. Pays 50% at the NDVI trigger, rising to 100% as the
    percentile approaches 0. A hotter-than-usual season (the land surface temperature anomaly, approximated here
    by the air temperature anomaly) adds severity: each 1 degree C above the ward's usual seasonal maximum counts
    as a quarter of the way to full payment.
    """
    if not (math.isfinite(crop_fraction) and math.isfinite(ndvi_pct)):
        return 0.0
    if crop_fraction <= 0 or crop_fraction < params.fodder_gate or ndvi_pct >= params.ndvi_trigger:
        return 0.0
    ndvi_severity = (params.ndvi_trigger - ndvi_pct) / max(params.ndvi_trigger, 1e-9)
    heat_severity = 0.25 * max(0.0, tmax_anomaly_c) if math.isfinite(tmax_anomaly_c) else 0.0
    return 0.5 + 0.5 * min(1.0, ndvi_severity + heat_severity)


def payout_c_fires(max_rain10_mm: float, hot_run_days: int, rain10_line_mm: float, params: TriggerParams) -> bool:
    return max_rain10_mm > rain10_line_mm or hot_run_days >= params.heat_days


def rain10_line(max_rain10_by_season: pd.Series, params: TriggerParams) -> float:
    """The excess-rain line for one ward. A fixed 180 mm fires every few seasons in a wet highland and almost never
    in a dry ward, so by default the line is the ward's own Nth percentile of its wettest 10 days per season."""
    if params.rain10_mode == "fixed" or max_rain10_by_season.empty:
        return params.rain10_trigger_mm
    return float(np.percentile(max_rain10_by_season, params.rain10_percentile))


def run_backtest(weather: pd.DataFrame, params: TriggerParams = TriggerParams(), years=YEARS) -> pd.DataFrame:
    """One row per season with every input, the three payouts in KSh and the premium."""
    daily = daily_indices(weather, params)
    rows = []
    for year in years:
        for season in SEASONS:
            w = season_window(daily, year, season)
            if len(w) < FLOWERING_DAYS[1]:
                continue
            germ = _days(w, GERMINATION_DAYS)["sm_index"].mean()
            flower = _days(w, FLOWERING_DAYS)["sm_index"].mean()
            weighted = params.germination_weight * germ + params.flowering_weight * flower
            rain10 = w["rain_mm"].rolling(10, min_periods=1).sum().max()
            hot_run = longest_run(w["tmax_c"] > params.heat_temp_c)
            demand = maize_kc(w["day"].to_numpy()) * w["et0_mm"].to_numpy()
            wrsi = 100.0 * (demand * w["water_stress"].to_numpy()).sum() / max(demand.sum(), 1e-9)
            rows.append({
                "year": year, "season": season, "rain_mm": w["rain_mm"].sum(),
                "sm_germination": germ, "sm_flowering": flower, "sm_weighted": weighted,
                "ndvi_late": _days(w, params.fodder_ndvi_days)["ndvi"].mean(), "tmax_mean": w["tmax_c"].mean(),
                "max_rain10_mm": rain10, "hot_run_days": hot_run, "wrsi": min(wrsi, 100.0),
            })
    seasons = pd.DataFrame(rows)
    if seasons.empty:
        return seasons
    # Pasture NDVI percentile and temperature anomaly are relative to the ward's own record for that season.
    grouped = seasons.groupby("season")
    seasons["ndvi_pct"] = grouped["ndvi_late"].rank(method="average").sub(0.5).div(
        grouped["ndvi_late"].transform("count")).mul(100)
    seasons["tmax_anomaly_c"] = seasons["tmax_mean"] - grouped["tmax_mean"].transform("mean")
    seasons["rain_vs_mean"] = seasons["rain_mm"] / grouped["rain_mm"].transform("mean")

    a = seasons["sm_weighted"].map(lambda v: payout_a_fraction(v, params))
    seasons["payout_a"] = a * params.crop_allocation
    seasons["payout_b"] = [
        payout_b_fraction(fa, pct, anom, params) * params.fodder_allocation
        for fa, pct, anom in zip(a, seasons["ndvi_pct"], seasons["tmax_anomaly_c"])
    ]
    line = rain10_line(seasons["max_rain10_mm"], params)
    seasons["rain10_line_mm"] = line
    seasons["payout_c"] = [
        params.health_payout if payout_c_fires(r10, hot, line, params) else 0.0
        for r10, hot in zip(seasons["max_rain10_mm"], seasons["hot_run_days"])
    ]
    # The seasonal cap scales every layer down together, so the stacked bars still add up to what is paid.
    seasons["payout_uncapped"] = seasons[["payout_a", "payout_b", "payout_c"]].sum(axis=1)
    scale = (params.aggregate_cap / seasons["payout_uncapped"].where(seasons["payout_uncapped"] > 0)).clip(upper=1.0)
    scale = scale.fillna(1.0)
    for col in ("payout_a", "payout_b", "payout_c"):
        seasons[col] = seasons[col] * scale
    seasons["payout_total"] = seasons[["payout_a", "payout_b", "payout_c"]].sum(axis=1)
    rate = commercial_rate(seasons["payout_total"].mean() / params.sum_insured, params)
    seasons["premium_rate"] = rate
    seasons["premium"] = params.sum_insured * rate
    seasons["label"] = seasons["year"].astype(str) + " " + seasons["season"]
    return seasons


# --------------------------------------------------------------------------------------------- KPIs

@dataclass
class BasisRisk:
    score: float | None            # % fewer mismatched seasons than a rainfall-only trigger; None if undefined
    mismatches_index: int
    mismatches_rain_only: int
    amber_seasons: int             # seasons close enough to the trigger to go to WhatsApp verification
    mismatches_verified: float     # expected mismatches once those seasons are verified
    score_verified: float | None


@dataclass
class BacktestKPIs:
    burn_cost_pct: float           # average payout per season, % of sum insured
    premium_rate_pct: float        # commercial premium rate per season
    premium_ksh: float
    farmer_premium_ksh: float      # after any subsidy
    loss_ratio_pct: float          # total payouts / total premiums
    worst_year: int | None
    worst_year_payout: float       # KSh per farm, both seasons
    worst_year_pct: float          # % of the two seasons' sum insured
    seasons_paying: int
    seasons: int
    basis: BasisRisk
    rain10_line_mm: float
    offered: bool = True           # False when the rate is above the sellable ceiling

    def as_dict(self) -> dict:
        return asdict(self)


def basis_risk(seasons: pd.DataFrame, params: TriggerParams = TriggerParams(), wrsi_stress: float = 60.0,
               rain_only_ratio: float = 0.75) -> BasisRisk:
    """Compare two triggers against a modelled stress signal and count the seasons where each one is wrong.

    The reference is the season's Water Requirement Satisfaction Index (WRSI, FAO) for maize from the same water
    balance: below 60 is a "poor" or "failed" season on the FEWS NET scale. A season is a mismatch when a trigger
    pays and the crop was not stressed, or the crop was stressed and it does not pay. The rainfall-only benchmark
    pays when the season's total rain is below 75% of the ward's average for that season. This is a model-internal
    check; it needs real yield or loan-default records to become a basis-risk measurement.

    The verified view sends seasons within ``amber_band`` points of the trigger to the WhatsApp photo check and
    ASSUMES the photos settle a share ``verifier_accuracy`` of them correctly. It is a scenario, not a result: the
    photo network has not run in the field.
    """
    stressed = seasons["wrsi"] < wrsi_stress
    index_pays = seasons["payout_a"] > 0
    rain_only = seasons["rain_vs_mean"] < rain_only_ratio
    wrong_index = index_pays != stressed
    mm_index = int(wrong_index.sum())
    mm_rain = int((rain_only != stressed).sum())
    amber = (seasons["sm_weighted"] - params.sm_trigger).abs() <= params.amber_band
    mm_verified = float(wrong_index[~amber].sum() + (1 - params.verifier_accuracy) * amber.sum())

    def score(mm):
        return None if mm_rain == 0 else 100.0 * (mm_rain - mm) / mm_rain

    return BasisRisk(score(mm_index), mm_index, mm_rain, int(amber.sum()), mm_verified, score(mm_verified))


def kpis(seasons: pd.DataFrame, params: TriggerParams = TriggerParams()) -> BacktestKPIs:
    if seasons.empty:
        return BacktestKPIs(0, 0, 0, 0, 0, None, 0, 0, 0, 0, BasisRisk(None, 0, 0, 0, 0, None), 0)
    burn = 100.0 * seasons["payout_total"].mean() / params.sum_insured
    rate = float(seasons["premium_rate"].iloc[0])
    premium = params.sum_insured * rate
    loss_ratio = 100.0 * seasons["payout_total"].sum() / max(seasons["premium"].sum(), 1e-9)
    by_year = seasons.groupby("year")["payout_total"].sum()
    worst = int(by_year.idxmax()) if by_year.max() > 0 else None
    worst_amount = float(by_year.max()) if worst else 0.0
    return BacktestKPIs(
        burn_cost_pct=burn, premium_rate_pct=100.0 * rate, premium_ksh=premium,
        farmer_premium_ksh=premium * (1 - params.subsidy_share), loss_ratio_pct=loss_ratio,
        worst_year=worst, worst_year_payout=worst_amount,
        worst_year_pct=100.0 * worst_amount / (2 * params.sum_insured),
        seasons_paying=int((seasons["payout_total"] > 0).sum()), seasons=len(seasons),
        basis=basis_risk(seasons, params), rain10_line_mm=float(seasons["rain10_line_mm"].iloc[0]),
        offered=rate <= params.max_sellable_rate + 1e-9,
    )


def zone_pricing(params: TriggerParams = TriggerParams(), loader=load_weather) -> pd.DataFrame:
    """Price every pilot ward on the same product terms: one row per ward.

    A ward whose commercial rate is above ``max_sellable_rate`` is marked not offered: rather than sell the
    standard bundle at a price farmers will not pay (or underprice it with a flat rate), it is referred for a
    custom tier built on its own enterprise (for example tea and dairy in the Kericho highlands).
    """
    rows = []
    for key, ward in WARDS.items():
        k = kpis(run_backtest(loader(key)[0], params), params)
        rows.append({
            "ward_key": key, "ward": ward.label, "zone": ward.zone, "burn_cost_pct": k.burn_cost_pct,
            "premium_rate_pct": k.premium_rate_pct, "premium_ksh": k.premium_ksh,
            "farmer_premium_ksh": k.farmer_premium_ksh, "loss_ratio_pct": k.loss_ratio_pct,
            "seasons_paying": k.seasons_paying, "rain10_line_mm": k.rain10_line_mm,
            "basis_score": k.basis.score, "basis_score_verified": k.basis.score_verified,
            "offered": "Yes" if k.offered else f"No: above {params.max_sellable_rate:.0%}, needs a custom tier",
        })
    return pd.DataFrame(rows)


def dekadal_trajectory(weather: pd.DataFrame, year: int, season: str,
                       params: TriggerParams = TriggerParams()) -> pd.DataFrame:
    """Dekad (10-day) means of the soil moisture index and NDVI proxy for one season, for the trajectory chart."""
    w = season_window(daily_indices(weather, params), year, season)
    return w.groupby("dekad").agg(sm_index=("sm_index", "mean"), ndvi=("ndvi", "mean"),
                                  rain_mm=("rain_mm", "sum")).reset_index()


def refresh_all_caches() -> dict[str, str]:
    """Fetch every ward from Open-Meteo and rewrite the committed cache (python -m engine.parametric_engine)."""
    done = {}
    for key in WARDS:
        frame, source, _ = load_weather(key, refresh=True)
        done[key] = f"{source}: {len(frame)} days"
    return done


if __name__ == "__main__":
    for ward_key, status in refresh_all_caches().items():
        print(f"{ward_key}: {status}")
