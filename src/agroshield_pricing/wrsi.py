"""Layer B v1: seasonal WRSI on a dekadal water balance (FAO / FEWS NET method).

Steps for one ward and season:
  1. Daily CHIRPS rain and daily PET are summed to dekads (days 1-10, 11-20, 21-end).
  2. Failed onset: if total rain over the whole planting window is below
     failed_onset.window_rain_below_mm, the season never started. Fixed payout,
     no WRSI.
  3. Start of season (SOS): the first dekad in the window with at least
     planting_rain_mm. If none, the season starts at the end of the window.
  4. Germination dry spell: if the days_after_planting days after that planting
     dekad bring less than rain_below_mm, the crop failed to establish. Pays the
     replanting seed cost, and SOS moves to the next planting rain (searched up to
     restart_search_extra_dekads past the window; the end of the search if none).
  5. From SOS, for each of the LGP dekads i:
        Kc_i  = crop coefficient interpolated at the dekad's share of the LGP
        WR_i  = Kc_i x PET_i                              (water requirement)
        W     = soil water + rain_i
        Ks    = min(1, W / ((1 - p) x WHC))               (stress once soil is dry)
        AET_i = min(Ks x WR_i, W)
        soil  = min(WHC, W - AET_i)                       (excess drains away)
     preceded by `spinup_dekads` of bare-soil balance (Kc of the first stage)
     so pre-season rain is in the soil when the crop starts.
  6. End-of-season WRSI = 100 x sum(AET) / sum(WR).
WRSI payout: linear from the trigger (no payout) to the exit (full payout).
EXPERIMENTAL flowering metrics are computed for every season from the flowering
window (a share of the growing period); whether they pay is decided by config.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .config import FloweringComponent, LayerB, MonthDay, SeasonCalendar, _parse_md
from .index import payout_fraction

DEKADS_PER_YEAR = 36


# ------------------------------------------------------------------- dekads
def dekad_number(ts: pd.Timestamp) -> int:
    """Absolute dekad number: year x 36 + (month - 1) x 3 + (0, 1 or 2)."""
    return ts.year * DEKADS_PER_YEAR + (ts.month - 1) * 3 + min(2, (ts.day - 1) // 10)


def dekad_start(t: int) -> pd.Timestamp:
    year, k = divmod(t, DEKADS_PER_YEAR)
    month, part = divmod(k, 3)
    return pd.Timestamp(year=year, month=month + 1, day=1 + 10 * part)


def dekad_end(t: int) -> pd.Timestamp:
    return dekad_start(t + 1) - pd.Timedelta(days=1)


def dekad_label(t: int) -> str:
    """e.g. 'Apr d2 1984' for 11-20 April 1984."""
    s = dekad_start(t)
    return f"{s:%b} d{(t % 3) + 1} {s.year}"


def to_dekads(daily: pd.Series) -> pd.Series:
    """Sum a daily series into dekads, indexed by absolute dekad number."""
    year, month, day = daily.index.year, daily.index.month, daily.index.day
    key = year * DEKADS_PER_YEAR + (month - 1) * 3 + np.minimum(2, (day - 1) // 10)
    return daily.groupby(np.asarray(key)).sum()


def window_dekads(window: MonthDay, year: int) -> tuple[int, int]:
    (m0, d0), (m1, d1) = _parse_md(window.start), _parse_md(window.end)
    return (dekad_number(pd.Timestamp(year=year, month=m0, day=d0)),
            dekad_number(pd.Timestamp(year=year, month=m1, day=d1)))


# ------------------------------------------------------------- building blocks
def first_planting_rain(rain_dk: pd.Series, first_t: int, last_t: int, planting_mm: float) -> int | None:
    """First dekad in [first_t, last_t] with at least planting_mm of rain, else None."""
    for t in range(first_t, last_t + 1):
        if rain_dk.get(t, 0.0) >= planting_mm:
            return t
    return None


def kc_by_dekad(n: int, points_pct: list[float], values: list[float]) -> np.ndarray:
    """Crop coefficient at each dekad's midpoint share of an n-dekad season."""
    share = (np.arange(n) + 0.5) / n * 100
    return np.interp(share, points_pct, values)


def water_balance(rain: np.ndarray, pet: np.ndarray, kc: np.ndarray, whc: float, p: float,
                  spin_rain: np.ndarray, spin_pet: np.ndarray) -> pd.DataFrame:
    """Dekadal bucket over the season. Arrays are aligned: one value per crop dekad."""
    threshold = (1 - p) * whc
    soil = 0.0
    for r, e in zip(spin_rain, spin_pet):          # bare-soil spin-up
        w = soil + r
        aet = min(min(1.0, w / threshold) * kc[0] * e, w)
        soil = min(whc, w - aet)
    rows = []
    for r, e, k in zip(rain, pet, kc):
        wr = k * e
        w = soil + r
        ks = min(1.0, w / threshold)
        aet = min(ks * wr, w)
        surplus = max(0.0, w - aet - whc)
        soil = min(whc, w - aet)
        rows.append({"rain": r, "pet": e, "kc": k, "wr": wr, "aet": aet, "deficit": wr - aet,
                     "soil": soil, "surplus": surplus})
    return pd.DataFrame(rows)


def wrsi_from(trace: pd.DataFrame) -> float:
    wr = float(trace["wr"].sum())
    return 100.0 if wr <= 0 else round(min(100.0, 100.0 * float(trace["aet"].sum()) / wr), 2)


def longest_dry_spell(daily: np.ndarray, dry_day_mm: float) -> int:
    best = run = 0
    for r in daily:
        run = run + 1 if r < dry_day_mm else 0
        best = max(best, run)
    return best


def flowering_metrics(rain_daily: pd.Series, trace: pd.DataFrame, sos: int, n: int,
                      fl: FloweringComponent) -> dict:
    """Longest dry spell and rainfall deficit in the flowering window of one season."""
    a, b = fl.window_pct_of_lgp
    start = dekad_start(sos) + pd.Timedelta(days=round(n * 10 * a / 100))
    end = dekad_start(sos) + pd.Timedelta(days=round(n * 10 * b / 100) - 1)
    days = rain_daily.loc[start:end].to_numpy()
    share = (np.arange(n) + 0.5) / n * 100
    inside = (share >= a) & (share <= b)
    need = float(trace.loc[inside, "wr"].sum())
    rain = float(trace.loc[inside, "rain"].sum())
    deficit = 100.0 * max(0.0, 1 - rain / need) if need > 0 else 0.0
    return {"start": str(start.date()), "end": str(end.date()),
            "longest_dry_spell_days": longest_dry_spell(days, fl.dry_day_mm),
            "window_rain_mm": round(float(days.sum()), 1), "rainfall_deficit_pct": round(deficit, 1)}


def flowering_payout(metrics: dict | None, fl: FloweringComponent) -> float:
    if metrics is None:
        return 0.0
    value = metrics["longest_dry_spell_days"] if fl.metric == "longest_dry_spell" else metrics["rainfall_deficit_pct"]
    # Larger value = worse, so payout rises from trigger to exit.
    return round(fl.max_payout * float(np.clip((value - fl.trigger) / (fl.exit - fl.trigger), 0, 1)), 6)


# ------------------------------------------------------------- one season
@dataclass
class SeasonWRSI:
    year: int
    sos: int | None              # absolute dekad of the (final) start of season
    wrsi: float | None           # None when the onset failed
    trace: pd.DataFrame | None   # dekad-by-dekad water balance
    window_rain_mm: float = 0.0
    failed_onset: bool = False
    planting_rain_dekad: int | None = None     # first planting rain found
    germination_failed: bool = False
    germination_rain_mm: float | None = None   # rain in the days after the first planting rain
    germination_window: tuple[str, str] | None = None
    sos_rule: str = ""
    flowering: dict | None = field(default=None)


def season_wrsi(rain_daily: pd.Series, rain_dk: pd.Series, pet_dk: pd.Series, cal: SeasonCalendar,
                year: int, lb: LayerB, whc: float) -> SeasonWRSI:
    t0, t1 = window_dekads(cal.planting_window, year)
    window_rain = round(float(sum(rain_dk.get(t, 0.0) for t in range(t0, t1 + 1))), 1)
    if window_rain < lb.failed_onset.window_rain_below_mm:
        return SeasonWRSI(year, None, None, None, window_rain, failed_onset=True,
                          sos_rule="failed onset: planting-window rain below threshold")

    gd = lb.germination_dry_spell
    p = first_planting_rain(rain_dk, t0, t1, lb.planting_rain_mm)
    germ_failed, germ_rain, germ_window = False, None, None
    if p is None:
        sos, rule = t1, "no planting rain in window: season starts at window end"
    else:
        g0 = dekad_end(p) + pd.Timedelta(days=1)
        g1 = g0 + pd.Timedelta(days=gd.days_after_planting - 1)
        germ_rain = round(float(rain_daily.loc[g0:g1].sum()), 1)
        germ_window = (str(g0.date()), str(g1.date()))
        if germ_rain < gd.rain_below_mm:
            germ_failed = True
            last = t1 + gd.restart_search_extra_dekads
            q = first_planting_rain(rain_dk, dekad_number(g1) + 1, last, lb.planting_rain_mm)
            sos, rule = (q, "replanting rain after germination dry spell") if q is not None else \
                (last, "germination dry spell, no replanting rain: season starts at end of search")
        else:
            sos, rule = p, "planting rain"

    n = cal.lgp_dekads
    crop = list(range(sos, sos + n))
    spin = list(range(sos - lb.spinup_dekads, sos))
    kc = kc_by_dekad(n, lb.kc.points_pct, lb.kc.values)
    trace = water_balance(rain_dk.reindex(crop).to_numpy(), pet_dk.reindex(crop).to_numpy(), kc, whc,
                          lb.depletion_fraction, rain_dk.reindex(spin).to_numpy(),
                          pet_dk.reindex(spin).to_numpy())
    trace.insert(0, "dekad", [dekad_label(t) for t in crop])
    return SeasonWRSI(year, sos, wrsi_from(trace), trace, window_rain, False, p, germ_failed, germ_rain,
                      germ_window, rule, flowering_metrics(rain_daily, trace, sos, n, lb.flowering))


def wrsi_payout(s: SeasonWRSI, trigger: float, exit_: float) -> float:
    """WRSI component only (share of sum insured); 0 after a failed onset."""
    if s.failed_onset:
        return 0.0
    return round(float(payout_fraction(s.wrsi, trigger, exit_)), 6)


def season_years(cal: SeasonCalendar, first_year: int, last_year: int, last_dekad: int,
                 extra_dekads: int = 0) -> list[int]:
    """Planting years whose latest possible season still ends inside the data."""
    out = []
    for y in range(first_year, last_year + 1):
        _, t1 = window_dekads(cal.planting_window, y)
        if t1 + extra_dekads + max(2, cal.lgp_dekads - 1) <= last_dekad:
            out.append(y)
    return out
