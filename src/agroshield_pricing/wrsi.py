"""Layer B v1: seasonal WRSI on a dekadal water balance (FAO / FEWS NET method).

Steps for one ward and season:
  1. Daily CHIRPS rain and daily PET are summed to dekads (days 1-10, 11-20, 21-end).
  2. Start of season (SOS): the first dekad in the planting window with
     >= first_dekad_mm of rain, followed by >= next_two_dekads_mm over the next
     two dekads. No such dekad means a failed onset.
  3. From SOS, for each of the LGP dekads i:
        Kc_i  = crop coefficient interpolated at the dekad's share of the LGP
        WR_i  = Kc_i x PET_i                              (water requirement)
        W     = soil water + rain_i
        Ks    = min(1, W / ((1 - p) x WHC))               (stress once soil is dry)
        AET_i = min(Ks x WR_i, W)
        soil  = min(WHC, W - AET_i)                       (excess drains away)
     preceded by `spinup_dekads` of bare-soil balance (Kc of the first stage)
     so pre-season rain is in the soil when the crop starts.
  4. End-of-season WRSI = 100 x sum(AET) / sum(WR).
Payout: failed onset -> fixed failed_onset_payout; otherwise linear from the
WRSI trigger (no payout) to the exit (full payout).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .config import LayerB, MonthDay, SeasonCalendar, _parse_md
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


# ------------------------------------------------------------- the season
def find_onset(rain_dk: pd.Series, first_t: int, last_t: int,
               first_mm: float, next_two_mm: float) -> int | None:
    """First dekad in [first_t, last_t] meeting the onset rule, else None."""
    for t in range(first_t, last_t + 1):
        if rain_dk.get(t, 0.0) >= first_mm and rain_dk.get(t + 1, 0.0) + rain_dk.get(t + 2, 0.0) >= next_two_mm:
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


@dataclass
class SeasonWRSI:
    year: int
    sos: int | None              # absolute dekad of start of season
    wrsi: float | None           # None when the onset failed
    trace: pd.DataFrame | None   # dekad-by-dekad water balance

    @property
    def failed_onset(self) -> bool:
        return self.sos is None


def season_wrsi(rain_dk: pd.Series, pet_dk: pd.Series, cal: SeasonCalendar, year: int,
                lb: LayerB, whc: float) -> SeasonWRSI:
    t0, t1 = window_dekads(cal.planting_window, year)
    sos = find_onset(rain_dk, t0, t1, lb.onset.first_dekad_mm, lb.onset.next_two_dekads_mm)
    if sos is None:
        return SeasonWRSI(year, None, None, None)
    n = cal.lgp_dekads
    crop = list(range(sos, sos + n))
    spin = list(range(sos - lb.spinup_dekads, sos))
    kc = kc_by_dekad(n, lb.kc.points_pct, lb.kc.values)
    trace = water_balance(rain_dk.reindex(crop).to_numpy(), pet_dk.reindex(crop).to_numpy(), kc, whc,
                          lb.depletion_fraction, rain_dk.reindex(spin).to_numpy(),
                          pet_dk.reindex(spin).to_numpy())
    trace.insert(0, "dekad", [dekad_label(t) for t in crop])
    return SeasonWRSI(year, sos, wrsi_from(trace), trace)


def wrsi_payout(s: SeasonWRSI, failed_onset_payout: float, trigger: float, exit_: float) -> float:
    if s.failed_onset:
        return failed_onset_payout
    return round(float(payout_fraction(s.wrsi, trigger, exit_)), 6)


def season_years(cal: SeasonCalendar, first_year: int, last_year: int, last_dekad: int) -> list[int]:
    """Planting years whose latest possible season still ends inside the data."""
    out = []
    for y in range(first_year, last_year + 1):
        _, t1 = window_dekads(cal.planting_window, y)
        if t1 + max(2, cal.lgp_dekads - 1) <= last_dekad:
            out.append(y)
    return out
