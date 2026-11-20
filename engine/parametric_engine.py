"""ShambaShield 360 parametric engine: weather, derived indices and the three payout layers.

Weather comes from the Open-Meteo Historical Weather API (ERA5-based reanalysis, CC BY 4.0). Each ward's
2015-2024 record is cached in ``data/weather_cache/`` so the app runs offline. If neither the cache nor the
network is available, a deterministic synthetic record is generated and labelled as such.

The soil moisture index and the pasture NDVI are *synthetic proxies* computed from that weather. They stand in
for Sentinel-1 SAR soil moisture and Sentinel-2 NDVI until real satellite feeds are connected; nothing here is
read from a satellite.
"""
from __future__ import annotations

import json
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

    @property
    def label(self) -> str:
        return f"{self.name}, {self.county} County"


WARDS: dict[str, Ward] = {w.key: w for w in (
    Ward("njoro", "Njoro Ward", "Nakuru", -0.3306, 35.9436, "Maize, beans and dairy"),
    Ward("imenti_north", "Imenti North", "Meru", 0.0470, 37.6559, "Potatoes, maize and zero-grazing dairy"),
    Ward("kangundo", "Kangundo", "Machakos", -1.2981, 37.3481, "Maize, pigeon peas, shoats and cattle"),
    Ward("kimilili", "Kimilili", "Bungoma", 0.7897, 34.7186, "Maize, sugarcane and dairy"),
    Ward("bureti", "Bureti", "Kericho", -0.6167, 35.2500, "Tea, maize and dairy"),
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
    """Every number that shapes a payout. Defaults follow the ShambaShield 360 specification."""
    sum_insured: float = 60_000.0
    premium_rate: float = 0.06            # commercial rate per season, share of sum insured
    crop_share: float = 35_000 / 60_000   # Payout A allocation
    fodder_share: float = 20_000 / 60_000  # Payout B allocation
    health_share: float = 5_000 / 60_000   # Payout C flat amount
    germination_weight: float = 0.35
    flowering_weight: float = 0.65
    sm_trigger: float = 32.0              # soil moisture index (0-100) below which Payout A starts
    sm_exit: float = 12.0                 # index at or below which Payout A reaches 100%
    ndvi_trigger: float = 30.0            # pasture NDVI percentile below which Payout B can fire
    rain10_trigger_mm: float = 180.0      # 10-day rainfall that fires Payout C
    heat_temp_c: float = 31.0             # daily maximum above which a day counts as a heat day
    heat_days: int = 7                    # consecutive heat days that fire Payout C
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
    def premium(self) -> float:
        return self.sum_insured * self.premium_rate


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
    frame = pd.read_csv(path, parse_dates=["date"])
    meta_path = cache_dir / f"{ward.key}.meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    return _clean(frame), meta


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

    doy = np.minimum(weather["date"].dt.day_of_year.to_numpy(), 365)
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
    window["dekad"] = (window["day"] - 1) // 10 + 1
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
    """Crop layer: 0 at or above the trigger; 25% just below it, rising linearly to 100% at the exit level."""
    if weighted_sm >= params.sm_trigger:
        return 0.0
    span = max(params.sm_trigger - params.sm_exit, 1e-9)
    depth = min(1.0, (params.sm_trigger - weighted_sm) / span)
    return 0.25 + 0.75 * depth


def payout_b_fraction(crop_paid: bool, ndvi_pct: float, tmax_anomaly_c: float, params: TriggerParams) -> float:
    """Fodder-gap cross-trigger: needs a crop payout AND pasture below the NDVI percentile trigger.

    Pays 50% at the trigger, rising to 100% as the percentile approaches 0. A hotter-than-usual season (the
    land surface temperature anomaly, approximated here by the air temperature anomaly) adds severity: each
    1 degree C above the ward's usual seasonal maximum counts as a quarter of the way to full payment.
    """
    if not crop_paid or ndvi_pct >= params.ndvi_trigger:
        return 0.0
    ndvi_severity = (params.ndvi_trigger - ndvi_pct) / max(params.ndvi_trigger, 1e-9)
    heat_severity = 0.25 * max(0.0, tmax_anomaly_c)
    return 0.5 + 0.5 * min(1.0, ndvi_severity + heat_severity)


def payout_c_fires(max_rain10_mm: float, hot_run_days: int, params: TriggerParams) -> bool:
    return max_rain10_mm > params.rain10_trigger_mm or hot_run_days >= params.heat_days


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
                "ndvi_late": _days(w, (46, 92))["ndvi"].mean(), "tmax_mean": w["tmax_c"].mean(),
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
        payout_b_fraction(pa > 0, pct, anom, params) * params.fodder_allocation
        for pa, pct, anom in zip(seasons["payout_a"], seasons["ndvi_pct"], seasons["tmax_anomaly_c"])
    ]
    seasons["payout_c"] = [
        params.health_payout if payout_c_fires(r10, hot, params) else 0.0
        for r10, hot in zip(seasons["max_rain10_mm"], seasons["hot_run_days"])
    ]
    seasons["payout_total"] = seasons[["payout_a", "payout_b", "payout_c"]].sum(axis=1)
    seasons["premium"] = params.premium
    seasons["label"] = seasons["year"].astype(str) + " " + seasons["season"]
    return seasons


# --------------------------------------------------------------------------------------------- KPIs

@dataclass
class BacktestKPIs:
    burn_cost_pct: float           # average payout per season, % of sum insured
    loss_ratio_pct: float          # total payouts / total premiums
    worst_year: int | None
    worst_year_payout: float       # KSh per farm, both seasons
    worst_year_pct: float          # % of the two seasons' sum insured
    seasons_paying: int
    seasons: int
    basis_risk_score: float | None  # % fewer mismatches than a rainfall-only trigger; None if not defined
    mismatches_multi: int
    mismatches_rain_only: int

    def as_dict(self) -> dict:
        return asdict(self)


def basis_risk(seasons: pd.DataFrame, wrsi_stress: float = 60.0, rain_only_ratio: float = 0.75):
    """Compare two triggers against a modelled stress signal and count the seasons where each one is wrong.

    The reference is the season's Water Requirement Satisfaction Index (WRSI, FAO) for maize from the same water
    balance: below 60 is a "poor" or "failed" season on the FEWS NET scale. A season is a mismatch when a trigger pays and the
    crop was not stressed, or the crop was stressed and it does not pay. The rainfall-only benchmark pays when
    the season's total rain is below 75% of the ward's average for that season. This is a model-internal check;
    it needs real yield or loan-default records to become a basis-risk measurement.
    """
    stressed = seasons["wrsi"] < wrsi_stress
    multi = seasons["payout_a"] > 0
    rain_only = seasons["rain_vs_mean"] < rain_only_ratio
    mm_multi = int((multi != stressed).sum())
    mm_rain = int((rain_only != stressed).sum())
    score = None if mm_rain == 0 else 100.0 * (mm_rain - mm_multi) / mm_rain
    return score, mm_multi, mm_rain


def kpis(seasons: pd.DataFrame, params: TriggerParams = TriggerParams()) -> BacktestKPIs:
    if seasons.empty:
        return BacktestKPIs(0, 0, None, 0, 0, 0, 0, None, 0, 0)
    burn = 100.0 * seasons["payout_total"].mean() / params.sum_insured
    loss_ratio = 100.0 * seasons["payout_total"].sum() / max(seasons["premium"].sum(), 1e-9)
    by_year = seasons.groupby("year")["payout_total"].sum()
    worst = int(by_year.idxmax()) if by_year.max() > 0 else None
    worst_amount = float(by_year.max()) if worst else 0.0
    score, mm_multi, mm_rain = basis_risk(seasons)
    return BacktestKPIs(
        burn_cost_pct=burn, loss_ratio_pct=loss_ratio, worst_year=worst, worst_year_payout=worst_amount,
        worst_year_pct=100.0 * worst_amount / (2 * params.sum_insured),
        seasons_paying=int((seasons["payout_total"] > 0).sum()), seasons=len(seasons),
        basis_risk_score=score, mismatches_multi=mm_multi, mismatches_rain_only=mm_rain,
    )


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
