"""SYNTHETIC bimodal rainfall for Kenyan maize wards.

Used when real data is unavailable and in tests. Every output carries the
SYNTHETIC label. The generator is deterministic for a given seed and ward.

Model, per day:
  * wet/dry occurrence from a first-order Markov chain whose wet probability
    follows a two-peak seasonal curve (long rains peak ~late April, short rains
    ~mid November),
  * wet-day amounts from a gamma distribution whose mean also follows the curve,
  * a per-season, per-year intensity multiplier (lognormal) so some seasons fail
    and others flood, which is what a burn cost needs to see.
Highland wards (higher elevation_m) get proportionally wetter seasons.
"""
from __future__ import annotations

import zlib

import numpy as np
import pandas as pd

from ..config import Ward
from ..provenance import Label, Provenance
from .base import RainfallSource, validate_series

LR_PEAK_DOY, LR_WIDTH = 112, 32
SR_PEAK_DOY, SR_WIDTH = 315, 26


def _bump(doy: np.ndarray, centre: float, width: float) -> np.ndarray:
    d = np.minimum(np.abs(doy - centre), 365 - np.abs(doy - centre))  # circular distance
    return np.exp(-0.5 * (d / width) ** 2)


class SyntheticRainfallSource(RainfallSource):
    def __init__(self, seed: int = 0, season_cv: float = 0.30):
        self.seed = seed
        self.season_cv = season_cv

    def daily(self, ward: Ward, start_year: int, end_year: int) -> pd.Series:
        rng = np.random.default_rng([self.seed, zlib.crc32(ward.id.encode())])
        dates = pd.date_range(f"{start_year}-01-01", f"{end_year}-12-31", freq="D")
        doy = dates.dayofyear.to_numpy()
        wetness = 1.0 + 0.25 * np.clip(((ward.elevation_m or 1900) - 1900) / 600, -1, 1.5)

        lr, sr = _bump(doy, LR_PEAK_DOY, LR_WIDTH), _bump(doy, SR_PEAK_DOY, SR_WIDTH)
        # Per-year season multipliers; sigma chosen so seasonal totals vary ~season_cv.
        sigma = np.sqrt(np.log(1 + self.season_cv ** 2))
        years = np.arange(start_year, end_year + 1)
        m_lr = dict(zip(years, rng.lognormal(-sigma ** 2 / 2, sigma, len(years))))
        m_sr = dict(zip(years, rng.lognormal(-sigma ** 2 / 2, sigma, len(years))))
        mult = np.array([1 + (m_lr[y] - 1) * a + (m_sr[y] - 1) * b
                         for y, a, b in zip(dates.year, lr, sr)])

        p_wet = np.clip((0.12 + 0.50 * lr + 0.42 * sr) * np.sqrt(mult) * wetness ** 0.5, 0.02, 0.92)
        mean_amt = (3.0 + 7.5 * lr + 6.0 * sr) * np.sqrt(mult) * wetness ** 0.5

        wet = np.zeros(len(dates), dtype=bool)
        u = rng.random(len(dates))
        for i in range(len(dates)):
            p = p_wet[i]
            if i and wet[i - 1]:
                p = min(0.95, p + 0.18)  # wet spells persist
            wet[i] = u[i] < p
        shape = 0.75
        amounts = rng.gamma(shape, mean_amt / shape)
        rain = np.where(wet, np.round(amounts, 2), 0.0)
        s = pd.Series(rain, index=dates)
        return validate_series(s, start_year, end_year, f"synthetic {ward.id}")

    def provenance(self, ward: Ward) -> Provenance:
        return Provenance(Label.SYNTHETIC, "agroshield bimodal rainfall generator", {
            "seed": self.seed,
            "caveat": "Generated data with no link to observed weather. Not for pricing decisions.",
        })
