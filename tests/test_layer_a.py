import numpy as np
import pandas as pd
import pytest
from scipy import stats

from agroshield_pricing.layer_a import (Z_TERCILE, _voucher_price, normal_scores, run_layer_a,
                                        season_rainfall, synthetic_prob_below, verify)


def _z(n=45, seed=0):
    return stats.norm.ppf((np.arange(1, n + 1)) / (n + 1))[np.random.default_rng(seed).permutation(n)]


def test_zero_skill_is_climatology_and_never_triggers():
    p = synthetic_prob_below(_z(), 0.0, np.random.default_rng(1), 200)
    assert np.allclose(p, 1 / 3)
    assert not (p >= 0.45).any()


def test_perfect_skill_knows_the_outcome():
    z = _z()
    p = synthetic_prob_below(z, 1.0, np.random.default_rng(1), 3)
    assert ((p[0] >= 0.5) == (z < Z_TERCILE)).all()


def test_forecast_is_calibrated_and_has_the_set_skill():
    z = _z(2000, 3)
    p = synthetic_prob_below(z, 0.5, np.random.default_rng(2), 50)
    assert p.mean() == pytest.approx(1 / 3, abs=0.01)                      # calibrated on average
    below = z < Z_TERCILE
    # Higher P(below) in seasons that really were below normal.
    assert p[:, below].mean() > p[:, ~below].mean() + 0.1
    # Implied signal correlation: corr(-P, z) rises with skill.
    lo = synthetic_prob_below(z, 0.2, np.random.default_rng(2), 1)[0]
    hi = synthetic_prob_below(z, 0.8, np.random.default_rng(2), 1)[0]
    assert -stats.spearmanr(hi, z)[0] > -stats.spearmanr(lo, z)[0]


def test_verification_scores():
    trig = np.array([1, 1, 0, 0, 1, 0], bool)
    event = np.array([1, 0, 1, 0, 1, 0], bool)
    v = verify(trig, event)
    assert v["hit_rate"][0] == pytest.approx(2 / 3)          # 2 of 3 events caught
    assert v["false_alarm_rate"][0] == pytest.approx(1 / 3)  # 1 of 3 non-events got a voucher
    assert v["false_alarm_ratio"][0] == pytest.approx(1 / 3) # 1 of 3 vouchers was a false alarm
    assert v["trigger_frequency"][0] == pytest.approx(0.5)


def test_normal_scores_are_rank_based():
    z = normal_scores(pd.Series([300.0, 10.0, 150.0]))
    assert z[1] < z[2] < z[0] and z.sum() == pytest.approx(0)


def test_season_rainfall_sums_forecast_months():
    days = pd.date_range("2000-01-01", "2001-12-31")
    r = pd.Series(1.0, index=days)
    s = season_rainfall(r, [3, 4, 5], [2000, 2001])
    assert s.tolist() == [92.0, 92.0]


def test_voucher_price_is_expected_cost_plus_margin_and_loadings(cfg):
    v = cfg.product.layer_a.voucher_kes_per_acre
    p = _voucher_price(0.2, cfg)
    assert p["expected_cost_kes"] == pytest.approx(0.2 * v)
    rm = cfg.product.premium.risk_margin.factor * np.sqrt(0.2 * 0.8)
    assert p["gross_kes"] == pytest.approx((0.2 + rm) / (1 - sum(cfg.product.premium.loadings.values())) * v, abs=0.01)
    assert _voucher_price(0.0, cfg)["gross_kes"] == 0


def test_layer_a_is_deterministic_and_does_not_use_layer_b_to_trigger(cfg):
    days = pd.date_range("1981-01-01", "2025-12-31")
    rain = pd.Series(np.random.default_rng(4).gamma(0.8, 4.0, len(days)), index=days)
    years = list(range(1981, 2026))
    pays_a = pd.Series(0.0, index=years)
    pays_b = pd.Series(np.where(np.arange(45) % 4 == 0, 0.5, 0.0), index=years)
    a1 = run_layer_a(cfg, "ward-a", "LR", rain, pays_a)
    a2 = run_layer_a(cfg, "ward-a", "LR", rain, pays_b)
    # Vouchers depend only on the forecast; Layer B only changes how they are scored.
    assert [h["voucher"] for h in a1["history"]] == [h["voucher"] for h in a2["history"]]
    assert a1["trigger_frequency_mean"] == a2["trigger_frequency_mean"]
    assert run_layer_a(cfg, "ward-a", "LR", rain, pays_b)["history"] == a2["history"]
    freqs = [r["trigger_frequency"] for r in a1["skill_sweep"]]
    assert freqs == sorted(freqs) and freqs[0] == 0.0


def test_layer_a_unavailable_for_an_unconfigured_season(cfg):
    r = run_layer_a(cfg, "ward-a", "SR", pd.Series(dtype=float), pd.Series(dtype=float))
    assert r["available"] is False
