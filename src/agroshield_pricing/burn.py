"""Burn cost: apply the index to every historical season and summarise the losses.

Losses are shares of sum insured. Return-period losses are empirical quantiles
of the annual loss: the 1-in-10 loss is the 90th percentile, 1-in-20 the 95th.
With ~45 seasons the 1-in-20 figure rests on only two or three seasons, so the
report shows it alongside the full loss history rather than on its own.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def burn_cost(payout_frac: pd.Series, meaningful: float = 0.0) -> dict:
    x = payout_frac.to_numpy(dtype=float)
    n = len(x)
    if n < 2:
        raise ValueError("burn cost needs at least two seasons")
    order = payout_frac.sort_values(ascending=False)
    return {
        "seasons": n,
        "first_year": int(payout_frac.index.min()),
        "last_year": int(payout_frac.index.max()),
        "payout_seasons": int((x > 0).sum()),
        "payout_frequency": float((x > 0).mean()),
        "meaningful_payout_frequency": float((x >= meaningful).mean()) if meaningful > 0 else float((x > 0).mean()),
        "expected_loss": float(x.mean()),
        "std_dev": float(x.std(ddof=1)),
        "loss_1_in_10": float(np.quantile(x, 0.90)),
        "loss_1_in_20": float(np.quantile(x, 0.95)),
        "max_loss": float(x.max()),
        "worst_seasons": [{"year": int(y), "payout_frac": float(v)}
                          for y, v in order.head(5).items() if v > 0],
    }


def exceedance_curve(payout_frac: pd.Series) -> list[dict]:
    """Empirical exceedance probability for each observed loss (for charting)."""
    x = np.sort(payout_frac.to_numpy(dtype=float))[::-1]
    n = len(x)
    return [{"loss": float(v), "exceedance": (i + 1) / (n + 1)} for i, v in enumerate(x)]
