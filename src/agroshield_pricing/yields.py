"""SYNTHETIC ward yields, used by the backtest until real yield history exists.

Daily FAO-56 soil-water balance over the season, then FAO-33 yield response:
  * soil holds up to TAW mm of plant-available water; it starts the season with
    half of the previous 30 days' rain (capped at TAW), and rain above TAW is lost
  * each day the crop wants ETc (water_need_mm_per_day for its phase); it gets
    ETa = Ks * ETc, where Ks falls linearly from 1 to 0 once the soil is drier
    than (1 - p) * TAW
  * 1 - Ya/Ym = Ky_p * (1 - sum ETa / sum ETc), multiplied across phases
then multiplicative lognormal noise and occasional non-weather shocks (pests,
disease, hail).

Because these yields are computed from the same rainfall as the index, they
correlate with it by construction. They exercise the backtest code; they say
nothing about how well the product would track real farm losses.
"""
from __future__ import annotations

import zlib

import numpy as np
import pandas as pd

from .config import SeasonCalendar, SyntheticYield
from .phenology import season_windows


def season_water_ratios(rain: pd.Series, cal: SeasonCalendar, year: int,
                        cfg: SyntheticYield) -> dict[str, float]:
    """ETa / ETc per phase for one season from a daily soil-water bucket."""
    windows = season_windows(cal, year)
    taw, p = cfg.soil_water_capacity_mm, cfg.depletion_fraction
    start = windows[0].start
    pre = float(rain.loc[start - pd.Timedelta(days=30):start - pd.Timedelta(days=1)].sum())
    store = min(taw, 0.5 * pre)
    ratios = {}
    for w in windows:
        etc_day = cfg.water_need_mm_per_day.get(w.phase, 0.0)
        eta_sum = etc_sum = 0.0
        for r in rain.loc[w.start:w.end].to_numpy():
            store = min(taw, store + r)
            ks = 1.0 if store >= (1 - p) * taw else store / ((1 - p) * taw)
            eta = ks * etc_day
            store = max(0.0, store - eta)
            eta_sum += eta
            etc_sum += etc_day
        ratios[w.phase] = eta_sum / etc_sum if etc_sum else 1.0
    return ratios


def synthetic_yields(rain_eff: pd.Series, cal: SeasonCalendar, years: list[int],
                     cfg: SyntheticYield, ward_id: str, season: str) -> pd.Series:
    rng = np.random.default_rng([cfg.seed, zlib.crc32(f"{ward_id}:{season}".encode())])
    out = {}
    for y in years:
        factor = 1.0
        for phase, ratio in season_water_ratios(rain_eff, cal, y, cfg).items():
            factor *= max(0.0, 1.0 - cfg.ky.get(phase, 0.0) * (1.0 - ratio))
        noise = rng.lognormal(-cfg.noise_sd ** 2 / 2, cfg.noise_sd)
        shock = 1.0
        if rng.random() < cfg.shock_probability:
            shock = 1.0 - rng.uniform(*cfg.shock_loss_range)
        out[y] = round(cfg.potential_t_per_ha * factor * noise * shock, 3)
    s = pd.Series(out, name="yield_t_per_ha")
    s.index.name = "year"
    return s
