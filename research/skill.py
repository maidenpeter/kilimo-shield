"""Research 3b: measured seasonal forecast skill at the pilot wards.

Verifies two forecast sources against our CHIRPS ward rainfall:
  * C3S ECMWF SEAS5.1 hindcasts (25 members, 1981-2016), for MAM (1 Feb start) and
    OND (1 Sep start), at the 1-degree cell holding both wards;
  * GHACOF consensus outlooks (tercile probabilities by zone), MAM 1998 onward and
    OND / SOND, read at each ward point.

Everything is leave-one-out: a season's own value never sets the tercile
boundaries used to judge it. Scores for a "below normal" trigger:
  hit rate         = triggered and below normal / below normal
  false alarm rate = triggered and not below normal / not below normal
plus the correlation of the ensemble mean with observed rain (with a 95%
interval) and the ROC area for below-normal seasons (0.5 = no skill).
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

REPO = Path(__file__).resolve().parents[1]
RAW = REPO / "data" / "raw"
SEASON_MONTHS = {"MAM": [3, 4, 5], "OND": [10, 11, 12]}


def observed_season_totals(ward_id: str, season: str) -> pd.Series:
    df = pd.read_csv(RAW / "chirps" / f"{ward_id}.csv", parse_dates=["date"]).set_index("date")["rain_mm"]
    s = df[df.index.month.isin(SEASON_MONTHS[season])]
    return s.groupby(s.index.year).sum().rename("obs_mm")


def loo_lower_tercile(x: pd.Series) -> pd.Series:
    """Below-normal flag per year, from the lower tercile of all OTHER years."""
    return pd.Series({y: v < np.percentile(x.drop(y), 100 / 3) for y, v in x.items()})


def roc_auc(score: np.ndarray, event: np.ndarray) -> float | None:
    event = event.astype(bool)
    if event.all() or (~event).all():
        return None
    return float(stats.mannwhitneyu(score[event], score[~event], alternative="two-sided").statistic
                 / (event.sum() * (~event).sum()))


def corr_ci(x: np.ndarray, y: np.ndarray) -> dict:
    r, p = stats.pearsonr(x, y)
    z, se = np.arctanh(r), 1 / np.sqrt(len(x) - 3)
    return {"r": float(r), "p_value": float(p), "ci95": [float(np.tanh(z - 1.96 * se)), float(np.tanh(z + 1.96 * se))],
            "spearman": float(stats.spearmanr(x, y)[0]), "n": int(len(x))}


def scores(prob_below: pd.Series, below: pd.Series, thresholds=(0.35, 0.40, 0.45, 0.50, 0.55)) -> dict:
    df = pd.concat({"p": prob_below, "b": below}, axis=1, join="inner").dropna()
    b = df["b"].astype(bool).to_numpy()
    out = {"seasons": len(df), "below_normal_seasons": int(b.sum()), "roc_auc": roc_auc(df["p"].to_numpy(), b),
           "mean_prob_below": float(df["p"].mean()), "by_threshold": []}
    for th in thresholds:
        t = df["p"].to_numpy() >= th - 1e-9
        out["by_threshold"].append({
            "threshold": th, "triggers": int(t.sum()),
            "hit_rate": float((t & b).sum() / b.sum()) if b.sum() else None,
            "false_alarm_rate": float((t & ~b).sum() / (~b).sum()) if (~b).sum() else None,
            "false_alarm_ratio": float((t & ~b).sum() / t.sum()) if t.sum() else None})
    return out


# ------------------------------------------------------------------ C3S
def c3s_members(season: str) -> pd.DataFrame:
    df = pd.read_csv(RAW / "research" / "c3s_seas51_hindcast_36E_0N.csv")
    return df[df["season"] == season].pivot(index="year", columns="member", values="mean_mm_per_day")


def c3s_skill(ward_id: str, season: str) -> dict:
    ens = c3s_members(season)
    obs = observed_season_totals(ward_id, season).reindex(ens.index)
    mean = ens.mean(axis=1)
    # P(below) = share of a year's members below the lower tercile of the OTHER years' members.
    prob = pd.Series({y: float((ens.loc[y] < np.percentile(ens.drop(y).to_numpy().ravel(), 100 / 3)).mean())
                      for y in ens.index})
    below = loo_lower_tercile(obs)
    return {"source": "C3S ECMWF SEAS5.1 hindcast", "season": season, "years": [int(ens.index.min()), int(ens.index.max())],
            "correlation": corr_ci(mean.to_numpy(), obs.to_numpy()),
            "tercile": scores(prob, below),
            "history": [{"year": int(y), "obs_mm": float(obs[y]), "ens_mean_mm_day": float(mean[y]),
                         "prob_below": float(prob[y]), "below_normal": bool(below[y])} for y in ens.index]}


# ------------------------------------------------------------------ GHACOF
def ghacof_probs(ward_id: str, season: str) -> pd.Series:
    rows = json.loads((RAW / "research" / "ghacof_ward_probabilities.json").read_text(encoding="utf-8"))
    out = {}
    for r in rows:
        if r["ward_id"] != ward_id or r["season"] != season or not r["properties"]:
            continue
        props = [p for p in r["properties"] if "Below_Norm" in p and p["Below_Norm"] is not None]
        if not props:
            continue   # e.g. a forecast-in-millimetres layer, not probabilities
        out.setdefault(r["year"], float(props[0]["Below_Norm"]) / 100)
    return pd.Series(out, dtype=float).sort_index()


def ghacof_skill(ward_id: str, season: str) -> dict:
    prob = ghacof_probs(ward_id, season)
    if len(prob) < 5:
        return {"source": "GHACOF consensus outlook", "season": season, "available": False,
                "reason": f"only {len(prob)} outlooks with probabilities at this ward"}
    obs_all = observed_season_totals(ward_id, season)
    below = loo_lower_tercile(obs_all).reindex(prob.index)
    obs = obs_all.reindex(prob.index)
    rho = stats.spearmanr(prob.to_numpy(), -obs.to_numpy())
    return {"source": "GHACOF consensus outlook", "season": season, "available": True,
            "years": [int(prob.index.min()), int(prob.index.max())],
            "max_prob_below": float(prob.max()), "missing_years": [y for y in range(int(prob.index.min()), int(prob.index.max()) + 1)
                                                                   if y not in prob.index],
            "spearman_prob_below_vs_dryness": {"r": float(rho[0]), "p_value": float(rho[1]), "n": int(len(prob))},
            "tercile": scores(prob, below),
            "history": [{"year": int(y), "obs_mm": float(obs[y]), "prob_below": float(prob[y]),
                         "below_normal": bool(below[y])} for y in prob.index]}


def meaningful(c3s: dict) -> dict:
    """Viability rule for Layer A: skill clearly above zero."""
    c, t = c3s["correlation"], c3s["tercile"]
    ok = c["ci95"][0] > 0 and (t["roc_auc"] or 0) >= 0.6
    return {"meaningful": bool(ok),
            "rule": "correlation 95% interval above zero AND ROC area for below-normal >= 0.6",
            "r": c["r"], "ci95": c["ci95"], "roc_auc": t["roc_auc"]}
