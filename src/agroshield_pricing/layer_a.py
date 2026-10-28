"""Layer A: anticipatory seed voucher triggered by the pre-season forecast.

Trigger: the seasonal outlook's probability of below-normal (lower-tercile)
rainfall over the forecast months is at or above `trigger_prob_below_normal`.
Payout: a fixed drought-tolerant seed voucher per acre, before planting.

Until KMD / ICPAC hindcasts are available, the forecast is SYNTHETIC with a set
skill. For each season, with z the observed forecast-season rainfall as a normal
score (rank-based, so skewed rainfall is handled):
    f            = rho x z + sqrt(1 - rho^2) x e,  e ~ N(0, 1)   (forecast signal, corr(f, z) = rho)
    P(below)     = Phi((z_1/3 - rho x f) / sqrt(1 - rho^2))       (calibrated: z | f ~ N(rho f, 1 - rho^2))
With rho = 0 the forecast is climatology (P = 1/3 every year) and never
triggers; with rho -> 1 it knows the outcome. Each draw is one possible
45-season hindcast; the report summarises many draws, because with so few
seasons the realised hit rate and cost vary a lot by chance.

Verification against an observed event E (per season):
    hit rate (POD)          = triggered and E / E
    false alarm rate (POFD) = triggered and not E / not E
    false alarm ratio (FAR) = triggered and not E / triggered
Two events are scored: below-normal rainfall (what the forecast predicts) and a
Layer B payout (what the voucher is meant to get ahead of).
"""
from __future__ import annotations

import zlib

import numpy as np
import pandas as pd
from scipy import stats

from .config import Config
from .provenance import Label, Provenance

Z_TERCILE = stats.norm.ppf(1 / 3)


def season_rainfall(rain_daily: pd.Series, months: list[int], years: list[int]) -> pd.Series:
    """Observed total rain over the forecast months for each season year."""
    r = rain_daily[rain_daily.index.month.isin(months)]
    return r.groupby(r.index.year).sum().reindex(years).rename("forecast_season_rain_mm")


def normal_scores(x: pd.Series) -> np.ndarray:
    ranks = stats.rankdata(x.to_numpy(), method="average")
    return stats.norm.ppf(ranks / (len(x) + 1))


def synthetic_prob_below(z: np.ndarray, rho: float, rng: np.random.Generator, n_draws: int = 1) -> np.ndarray:
    """P(below normal) for each season, shape (n_draws, n_seasons)."""
    e = rng.standard_normal((n_draws, len(z)))
    if rho >= 0.9999:
        return np.broadcast_to((z < Z_TERCILE).astype(float), (n_draws, len(z))).copy()
    s = np.sqrt(1 - rho ** 2)
    f = rho * z + s * e
    return stats.norm.cdf((Z_TERCILE - rho * f) / s)


def verify(triggered: np.ndarray, event: np.ndarray) -> dict:
    """Scores for one or many draws (triggered may be 2-D: draws x seasons)."""
    trig = np.atleast_2d(triggered).astype(bool)
    ev = np.asarray(event, dtype=bool)
    hits = (trig & ev).sum(axis=1)
    false_alarms = (trig & ~ev).sum(axis=1)
    n_trig = trig.sum(axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        return {
            "trigger_frequency": trig.mean(axis=1),
            "hit_rate": hits / ev.sum() if ev.sum() else np.full(len(trig), np.nan),
            "false_alarm_rate": false_alarms / (~ev).sum() if (~ev).sum() else np.full(len(trig), np.nan),
            "false_alarm_ratio": np.where(n_trig > 0, false_alarms / np.maximum(n_trig, 1), np.nan),
        }


def _summ(x: np.ndarray) -> dict:
    x = x[~np.isnan(x)]
    if not len(x):
        return {"median": None, "p05": None, "p95": None}
    return {"median": float(np.median(x)), "p05": float(np.quantile(x, 0.05)), "p95": float(np.quantile(x, 0.95))}


def _voucher_price(freq: float, cfg: Config) -> dict:
    """Gross premium per acre for a fixed voucher V paid with probability `freq`.

    The voucher payout is Bernoulli, so its statistics are exact: mean freq x V,
    standard deviation V x sqrt(freq (1 - freq)), and a tail quantile of V when
    the voucher is paid more often than the tail probability, else 0. The same
    risk margin and loadings as Layer B are applied.
    """
    v = cfg.product.layer_a.voucher_kes_per_acre
    prem = cfg.product.premium
    rm_cfg = prem.risk_margin
    el = freq
    if rm_cfg.method == "std_dev":
        rm = rm_cfg.factor * np.sqrt(freq * (1 - freq))
    else:
        tail = 1.0 if freq > 1 - rm_cfg.percentile / 100 else 0.0
        rm = rm_cfg.factor * max(0.0, tail - el)
    gross = (el + rm) / (1 - sum(prem.loadings.values()))
    return {"expected_cost_kes": round(el * v, 2), "gross_kes": round(gross * v, 2)}


def run_layer_a(cfg: Config, ward_id: str, season: str, rain_daily: pd.Series,
                layer_b_payout: pd.Series) -> dict:
    la, sf = cfg.product.layer_a, cfg.product.synthetic_forecast
    if season not in la.forecast_months or season not in sf.skill_correlation:
        return {"available": False, "reason": f"No Layer A terms or forecast skill configured for {season}."}
    years = [int(y) for y in layer_b_payout.index]
    obs = season_rainfall(rain_daily, la.forecast_months[season], years)
    z = normal_scores(obs)
    below = z < Z_TERCILE
    b_pays = (layer_b_payout.to_numpy() > 0)
    events = {"below_normal_rain": below, "layer_b_payout": b_pays}
    rho = sf.skill_correlation[season]
    thr = la.trigger_prob_below_normal
    # Deterministic per ward and season; every skill level reuses the same noise
    # draws, so the sweep compares skill, not luck.
    seed = [sf.seed, zlib.crc32(f"{ward_id}:{season}".encode())]

    def simulate(r: float, n: int) -> np.ndarray:
        return synthetic_prob_below(z, r, np.random.default_rng(seed), n)

    probs = simulate(rho, sf.draws)
    trig = probs >= thr
    scores = {name: {k: _summ(v) for k, v in verify(trig, ev).items()} for name, ev in events.items()}
    freq_med = scores["layer_b_payout"]["trigger_frequency"]["median"]
    freq_mean = float(trig.mean())

    # One reference hindcast (draw 0) for the season-by-season table.
    ref_p, ref_t = probs[0], trig[0]
    ref_scores = {name: {k: float(v[0]) if not np.isnan(v[0]) else None for k, v in verify(ref_t, ev).items()}
                  for name, ev in events.items()}

    skill_sweep = []
    for r in sf.skill_sweep:
        t = simulate(r, sf.draws) >= thr
        v = verify(t, b_pays)
        vb = verify(t, below)
        f = float(t.mean())
        skill_sweep.append({"skill": r, "is_current": r == rho, "trigger_frequency": f,
                            "hit_rate_layer_b": _summ(v["hit_rate"]), "false_alarm_ratio_layer_b": _summ(v["false_alarm_ratio"]),
                            "hit_rate_below_normal": _summ(vb["hit_rate"]), **_voucher_price(f, cfg)})

    threshold_sweep = []
    for th in la.sensitivity_thresholds:
        t = probs >= th
        v = verify(t, b_pays)
        f = float(t.mean())
        threshold_sweep.append({"threshold": th, "is_current": th == thr, "trigger_frequency": f,
                                "hit_rate_layer_b": _summ(v["hit_rate"]),
                                "false_alarm_ratio_layer_b": _summ(v["false_alarm_ratio"]), **_voucher_price(f, cfg)})

    price = _voucher_price(freq_mean, cfg)
    cost = trig.mean(axis=1) * la.voucher_kes_per_acre
    return {
        "available": True,
        "version": la.version,
        "season": season,
        "forecast": {"months": la.forecast_months[season], "issue_month": la.issue_month[season],
                     "skill_correlation": rho, "draws": sf.draws,
                     "provenance": Provenance(Label.SYNTHETIC, "agroshield synthetic tercile forecast",
                                              {"note": "Generated from observed rainfall at the configured skill (measured "
                                                       "from C3S hindcasts in research 3b). Not a forecast."}).to_dict()},
        "terms": {"trigger_prob_below_normal": thr, "voucher_kes_per_acre": la.voucher_kes_per_acre},
        "seasons": len(years),
        "events": {"below_normal_rain": int(below.sum()), "layer_b_payout": int(b_pays.sum())},
        "trigger_frequency_mean": freq_mean,
        "trigger_frequency_median": freq_med,
        "scores": scores,
        "reference_draw": ref_scores,
        "expected_cost_kes": price["expected_cost_kes"],
        "gross_kes": price["gross_kes"],
        "cost_per_acre_range_kes": _summ(cost),
        "skill_sweep": skill_sweep,
        "threshold_sweep": threshold_sweep,
        "history": [{"year": y, "forecast_season_rain_mm": round(float(obs.loc[y]), 1), "below_normal": bool(below[i]),
                     "prob_below": round(float(ref_p[i]), 3), "voucher": bool(ref_t[i]),
                     "layer_b_pays": bool(b_pays[i]), "layer_b_payout": float(layer_b_payout.iloc[i])}
                    for i, y in enumerate(years)],
    }
