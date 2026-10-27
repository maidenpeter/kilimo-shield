"""Layer B: phase-weighted rainfall-deficit index and its payout function.

For each insured crop phase p in a season:
    R_p = sum over the phase of daily rainfall, with days below daily_min_mm
          counted as 0 and days above daily_cap_mm clipped to the cap
    f_p = 0                                      if R_p >= trigger_p
        = (trigger_p - R_p) / (trigger_p - exit_p)  if exit_p < R_p < trigger_p
        = 1                                      if R_p <= exit_p
Season payout, as a share of sum insured:
    payout = sum_p weight_p * f_p          (weights sum to 1, so payout <= 1)

Everything here is a pure function of the daily rainfall and the resolved terms,
so a payout can be reproduced exactly from the raw inputs and the run manifest.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from .config import PhaseTerms, SeasonCalendar
from .phenology import season_windows


@dataclass(frozen=True)
class ResolvedPhase:
    """Phase terms with percentile levels turned into fixed mm values."""
    phase: str
    weight: float
    trigger_mm: float
    exit_mm: float
    trigger_basis: str    # e.g. "fixed" or "P15 of 1981-2025"
    exit_basis: str

    def to_dict(self) -> dict:
        return asdict(self)


def payout_fraction(rain_mm, trigger_mm: float, exit_mm: float):
    """Linear payout between trigger (0) and exit (1). Works on scalars or arrays."""
    if not trigger_mm > exit_mm:
        raise ValueError(f"trigger ({trigger_mm}) must be above exit ({exit_mm})")
    f = (trigger_mm - np.asarray(rain_mm, dtype=float)) / (trigger_mm - exit_mm)
    f = np.clip(f, 0.0, 1.0)
    return float(f) if np.ndim(f) == 0 else f


def effective_daily(rain: pd.Series, daily_min_mm: float, daily_cap_mm: float) -> pd.Series:
    return rain.where(rain >= daily_min_mm, 0.0).clip(upper=daily_cap_mm)


def phase_rainfall(rain_eff: pd.Series, cal: SeasonCalendar, years: list[int]) -> pd.DataFrame:
    """Phase totals (mm) per planting year: rows are years, columns are phases."""
    rows = {}
    for y in years:
        rows[y] = {w.phase: float(rain_eff.loc[w.start:w.end].sum()) for w in season_windows(cal, y)}
    df = pd.DataFrame.from_dict(rows, orient="index")
    df.index.name = "year"
    return df


def resolve_terms(terms: dict[str, PhaseTerms], phase_rain: pd.DataFrame,
                  calibration: tuple[int, int]) -> dict[str, ResolvedPhase]:
    """Turn percentile levels into mm using the ward's own calibration years."""
    lo, hi = calibration
    calib = phase_rain.loc[(phase_rain.index >= lo) & (phase_rain.index <= hi)]
    span = f"{int(calib.index.min())}-{int(calib.index.max())}" if len(calib) else "n/a"

    def level(lv, phase: str) -> tuple[float, str]:
        if lv.mm is not None:
            return float(lv.mm), "fixed"
        if len(calib) < 10:
            raise ValueError(f"only {len(calib)} calibration seasons for {phase}; need 10+")
        return float(np.percentile(calib[phase], lv.percentile)), f"P{lv.percentile:g} of {span}"

    out = {}
    for phase, t in terms.items():
        trig, trig_basis = level(t.trigger, phase)
        ex, ex_basis = level(t.exit, phase)
        trig, ex = round(trig, 1), round(ex, 1)
        if not trig > ex:
            raise ValueError(f"{phase}: resolved trigger {trig} mm is not above exit {ex} mm")
        out[phase] = ResolvedPhase(phase, t.weight, trig, ex, trig_basis, ex_basis)
    return out


def season_payouts(phase_rain: pd.DataFrame, resolved: dict[str, ResolvedPhase]) -> pd.DataFrame:
    """Per-phase payout fractions and the weighted season payout per year."""
    out = pd.DataFrame(index=phase_rain.index)
    total = np.zeros(len(out))
    for phase, r in resolved.items():
        f = payout_fraction(phase_rain[phase].to_numpy(), r.trigger_mm, r.exit_mm)
        out[f"f_{phase}"] = f
        total += r.weight * f
    out["payout_frac"] = np.round(np.minimum(total, 1.0), 6)
    return out
