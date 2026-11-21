"""Underwriting measures per ward, from the same season-by-season backtest that sets the price.

An underwriter prices on more than the average payout (burn cost): how often the cover pays (frequency), how much
when it does (severity), how bad a 1-in-10 season is (the tail that drives reinsurance and capital), how lumpy the
payouts are (volatility, the case for a risk margin), how variable the rain itself is (the hazard before any product
terms), and which wards pay in the same seasons (accumulation).
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class WardRisk:
    seasons: int
    paid: int
    frequency_pct: float        # share of seasons with any payout
    burn_pct: float             # average payout a season, % of the sum insured
    severity_pct: float         # average payout in the seasons that paid, % of the sum insured
    p90_pct: float              # 1-in-10 season: the 90th percentile of seasonal payouts, % of the sum insured
    worst_pct: float            # largest single season, % of the sum insured
    worst_label: str            # "2022 LR", or "" when it never paid
    volatility: float | None    # coefficient of variation of seasonal payouts; None when it never paid
    rain_mean_mm: float         # average seasonal rainfall
    rain_cv: float              # coefficient of variation of seasonal rainfall: the hazard before product terms


def ward_risk(seasons: pd.DataFrame, sum_insured: float) -> WardRisk:
    """The measures for one ward over the given seasons (one row per season, as run_backtest returns)."""
    share = (100 * seasons["payout_total"] / sum_insured).to_numpy(float)
    rain = seasons["rain_mm"].to_numpy(float)
    n = len(share)
    paid = share > 0
    mean = float(share.mean()) if n else 0.0
    return WardRisk(
        seasons=n, paid=int(paid.sum()),
        frequency_pct=100.0 * paid.sum() / n if n else 0.0,
        burn_pct=mean,
        severity_pct=float(share[paid].mean()) if paid.any() else 0.0,
        p90_pct=float(np.quantile(share, 0.9)) if n else 0.0,
        worst_pct=float(share.max()) if n else 0.0,
        worst_label=str(seasons["label"].iloc[int(share.argmax())]) if paid.any() else "",
        volatility=float(share.std(ddof=1) / mean) if paid.any() and n > 1 and mean > 0 else None,
        rain_mean_mm=float(rain.mean()) if n else 0.0,
        rain_cv=float(rain.std(ddof=1) / rain.mean()) if n > 1 and rain.mean() > 0 else 0.0,
    )


@dataclass(frozen=True)
class PayTogether:
    a: str
    b: str
    correlation: float | None   # Pearson correlation of the two wards' seasonal payouts; None if either never paid
    both_paid: int              # seasons in which both wards paid


def pay_together(backtests: dict, season_keys) -> list[PayTogether]:
    """For every pair of wards: how closely their payouts move together, season by season. Losses that arrive in
    the same season add up for the insurer and the reinsurer: that is accumulation."""
    shares = {}
    for key, frame in backtests.items():
        seasons = frame[frame["season"].isin(season_keys)].set_index("label")["payout_total"]
        shares[key] = seasons
    out = []
    for a, b in combinations(shares, 2):
        x, y = shares[a].align(shares[b], join="inner")
        both = int(((x > 0) & (y > 0)).sum())
        r = float(np.corrcoef(x, y)[0, 1]) if len(x) > 1 and x.std() > 0 and y.std() > 0 else None
        out.append(PayTogether(a, b, r, both))
    return out


def season_load(backtests: dict, season_keys, exposure: dict) -> pd.Series:
    """Total payout of the whole book in each season (KSh), when each ward's payout per farm is multiplied by its
    insured farms: the seasons where the wards' losses stack up."""
    total = None
    for key, frame in backtests.items():
        seasons = frame[frame["season"].isin(season_keys)].set_index("label")["payout_total"] * exposure.get(key, 0)
        total = seasons if total is None else total.add(seasons, fill_value=0)
    return total if total is not None else pd.Series(dtype=float)
