"""External checks on the WRSI index: FEWS NET WRSI comparison and real-yield basis risk.

Both run only when their data files are present; otherwise they report what is
missing. Rainfall-derived synthetic yields are never used for basis risk: they
would agree with a rainfall index by construction.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from .backtest import backtest_yields
from .config import Config


def _repo(cfg: Config) -> Path:
    return Path(cfg.root).parent


def load_fewsnet_wrsi(cfg: Config, ward_id: str, season: str) -> pd.Series | None:
    path = _repo(cfg) / cfg.validation.fewsnet_wrsi_dir / f"{ward_id}_{season}.csv"
    if not path.exists():
        return None
    df = pd.read_csv(path)
    return df.set_index("year")["eos_wrsi"].astype(float)


def compare_fewsnet(ours: pd.Series, fews: pd.Series | None, large_gap: float, status: str) -> dict:
    """Correlation and gaps between our end-of-season WRSI and FEWS NET's, by year.

    `ours` holds WRSI per year (NaN for failed onsets, which FEWS reports as
    'no start' and are excluded from the correlation).
    """
    if fews is None:
        return {"available": False, "reason": status}
    df = pd.concat({"ours": ours, "fewsnet": fews}, axis=1, join="inner").dropna()
    if len(df) < 5:
        return {"available": False, "reason": f"only {len(df)} overlapping seasons with FEWS NET values"}
    diff = df["ours"] - df["fewsnet"]
    gaps = diff[diff.abs() >= large_gap]
    return {
        "available": True,
        "seasons": len(df),
        "first_year": int(df.index.min()), "last_year": int(df.index.max()),
        "pearson_r": float(stats.pearsonr(df["ours"], df["fewsnet"])[0]),
        "spearman_r": float(stats.spearmanr(df["ours"], df["fewsnet"])[0]),
        "mean_difference": float(diff.mean()),
        "rmse": float(np.sqrt((diff ** 2).mean())),
        "large_gap_threshold": large_gap,
        "large_gaps": [{"year": int(y), "ours": float(df.loc[y, "ours"]), "fewsnet": float(df.loc[y, "fewsnet"]),
                        "difference": float(d)} for y, d in gaps.items()],
        "pairs": [{"year": int(y), "ours": float(r["ours"]), "fewsnet": float(r["fewsnet"])}
                  for y, r in df.iterrows()],
    }


def real_yield_backtest(cfg: Config, ward_id: str, season: str, payouts: pd.Series) -> dict:
    path = _repo(cfg) / cfg.validation.yields_dir / f"{ward_id}_{season}.csv"
    if not path.exists():
        return {"available": False,
                "reason": "Not measurable until real ward yields are available. Rainfall-derived synthetic "
                          "yields were dropped because they agree with a rainfall index by construction."}
    yields = pd.read_csv(path).set_index("year")["yield_t_per_ha"].astype(float)
    bt = backtest_yields(payouts, yields, cfg.product.backtest.bad_yield_threshold,
                         cfg.product.backtest.meaningful_payout)
    return {**bt, "source_file": str(path.relative_to(_repo(cfg)))}
