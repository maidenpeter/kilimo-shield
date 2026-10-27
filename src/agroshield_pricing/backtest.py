"""Backtest the index against yields: correlation, basis risk, false payouts.

Definitions (thresholds from product.yaml `backtest`):
  bad season       yield < bad_yield_threshold x the ward's median yield
  paid season      payout >= meaningful_payout (share of sum insured)
  basis-risk rate  share of bad seasons that were NOT paid
                   (the farmer's crop failed but the index did not trigger)
  false payout     share of paid seasons that were NOT bad
                   (the index paid although the crop was fine)
"""
from __future__ import annotations

import pandas as pd
from scipy import stats


def backtest_yields(payout_frac: pd.Series, yields: pd.Series,
                    bad_yield_threshold: float, meaningful_payout: float) -> dict:
    df = pd.concat({"payout": payout_frac, "yield": yields}, axis=1, join="inner").dropna()
    if len(df) < 5:
        return {"available": False, "reason": f"only {len(df)} seasons with both payout and yield"}
    median = float(df["yield"].median())
    if median <= 0:
        return {"available": False, "reason": "median yield is zero; yield series unusable"}
    loss = 1 - df["yield"] / median          # yield shortfall vs median; positive = worse
    bad = df["yield"] < bad_yield_threshold * median
    paid = df["payout"] >= meaningful_payout

    def corr(fn):
        if df["payout"].nunique() < 2:
            return None
        r, p = fn(df["payout"], loss)
        return {"r": float(r), "p_value": float(p)}

    n_bad, n_paid = int(bad.sum()), int(paid.sum())
    return {
        "available": True,
        "seasons": len(df),
        "median_yield_t_per_ha": median,
        "bad_season_cutoff_t_per_ha": bad_yield_threshold * median,
        "spearman_payout_vs_yield_loss": corr(stats.spearmanr),
        "pearson_payout_vs_yield_loss": corr(stats.pearsonr),
        "bad_seasons": n_bad,
        "paid_seasons": n_paid,
        "bad_and_paid": int((bad & paid).sum()),
        "bad_not_paid": int((bad & ~paid).sum()),
        "paid_not_bad": int((paid & ~bad).sum()),
        "basis_risk_rate": float((bad & ~paid).sum() / n_bad) if n_bad else None,
        "false_payout_rate": float((paid & ~bad).sum() / n_paid) if n_paid else None,
        "basis_risk_years": [int(y) for y in df.index[bad & ~paid]],
        "false_payout_years": [int(y) for y in df.index[paid & ~bad]],
        "season_detail": [
            {"year": int(y), "payout_frac": float(r["payout"]), "yield_t_per_ha": float(r["yield"]),
             "bad": bool(bad[y]), "paid": bool(paid[y])}
            for y, r in df.iterrows()
        ],
    }


def rainfall_season_stats(phase_rain: pd.DataFrame) -> dict:
    """Mean and coefficient of variation of each phase total (mm)."""
    return {p: {"mean_mm": float(phase_rain[p].mean()),
                "cv": float(phase_rain[p].std(ddof=1) / phase_rain[p].mean()) if phase_rain[p].mean() else None,
                "min_mm": float(phase_rain[p].min()), "max_mm": float(phase_rain[p].max())}
            for p in phase_rain.columns}

