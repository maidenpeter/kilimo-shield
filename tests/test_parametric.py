from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from engine import parametric_engine as pe


@pytest.fixture(scope="module")
def njoro():
    weather, source, _ = pe.load_weather("njoro")
    assert source == pe.SOURCE_CACHE, "the committed cache should be used without touching the network"
    return weather


def test_cache_covers_ten_years_for_every_ward():
    for key in pe.WARDS:
        weather, source, meta = pe.load_weather(key)
        assert source == pe.SOURCE_CACHE
        assert weather["date"].min() == pd.Timestamp("2015-01-01")
        assert weather["date"].max() == pd.Timestamp("2024-12-31")
        assert len(weather) == 3653
        assert weather[["rain_mm", "et0_mm", "tmax_c"]].notna().all().all()
        assert meta["licence"] == "CC BY 4.0"


def test_indices_stay_in_range(njoro):
    daily = pe.daily_indices(njoro)
    assert daily["sm_index"].between(0, 100).all()
    assert daily["ndvi"].between(0.15, 0.75).all()
    assert daily["water_fraction"].between(0, 1).all()
    # 50 means normal for the date, so the long-run median sits close to it.
    assert 40 < daily["sm_index"].median() < 60


def test_default_terms():
    p = pe.TriggerParams()
    assert (p.crop_allocation, p.fodder_allocation, p.health_payout) == pytest.approx((30_000, 20_000, 10_000))
    assert p.aggregate_cap == pytest.approx(50_000)


def test_payout_a_scales_from_25_to_100_percent():
    p = pe.TriggerParams()
    assert pe.payout_a_fraction(p.sm_trigger, p) == 0
    assert pe.payout_a_fraction(p.sm_trigger - 1e-6, p) == pytest.approx(0.25)
    assert pe.payout_a_fraction((p.sm_trigger + p.sm_exit) / 2, p) == pytest.approx(0.625)
    assert pe.payout_a_fraction(p.sm_exit, p) == pytest.approx(1.0)
    assert pe.payout_a_fraction(0, p) == pytest.approx(1.0)


def test_fodder_needs_a_severe_crop_loss():
    p = pe.TriggerParams()  # gate 50% of the crop limit, NDVI below the 25th percentile
    assert pe.payout_b_fraction(0.0, 5, 0, p) == 0
    assert pe.payout_b_fraction(0.25, 5, 0, p) == 0          # mild crop loss: stover still grows
    assert pe.payout_b_fraction(0.49, 5, 0, p) == 0
    assert pe.payout_b_fraction(0.5, 26, 0, p) == 0           # pasture not poor enough
    assert pe.payout_b_fraction(0.5, p.ndvi_trigger - 1e-6, 0, p) == pytest.approx(0.5)
    assert pe.payout_b_fraction(1.0, 0, 0, p) == pytest.approx(1.0)
    assert pe.payout_b_fraction(0.8, 12.5, 4.0, p) == pytest.approx(1.0)  # heat adds severity, capped at 100%
    no_gate = replace(p, fodder_gate=0.0)
    assert pe.payout_b_fraction(0.25, 5, 0, no_gate) > 0


def test_payout_c_fires_on_rain_or_heat():
    p = pe.TriggerParams()
    assert not pe.payout_c_fires(180, 6, 180, p)
    assert pe.payout_c_fires(180.1, 0, 180, p)
    assert pe.payout_c_fires(0, 7, 180, p)
    assert pe.longest_run([True, True, False, True, True, True]) == 3


def test_rain_line_is_set_per_ward():
    p = pe.TriggerParams()
    lines = {k: pe.kpis(pe.run_backtest(pe.load_weather(k)[0], p), p).rain10_line_mm for k in pe.WARDS}
    assert lines["bureti"] > lines["kimilili"]  # wet Kericho highlands need a higher line
    fixed = replace(p, rain10_mode="fixed")
    assert pe.kpis(pe.run_backtest(pe.load_weather("bureti")[0], fixed), fixed).rain10_line_mm == 180
    for key in pe.WARDS:  # the 90th percentile line lets the rain part fire in about one season in ten
        seasons = pe.run_backtest(pe.load_weather(key)[0], p)
        assert (seasons["max_rain10_mm"] > seasons["rain10_line_mm"]).sum() <= 3


def test_backtest_shape_and_money(njoro):
    p = pe.TriggerParams()
    seasons = pe.run_backtest(njoro, p)
    assert len(seasons) == 20
    assert set(seasons["season"]) == {"LR", "SR"}
    assert (seasons["payout_a"] <= p.crop_allocation + 1e-6).all()
    assert (seasons["payout_b"] <= p.fodder_allocation + 1e-6).all()
    assert (seasons["payout_c"] <= p.health_payout + 1e-6).all()
    assert ((seasons["payout_b"] > 0) <= (seasons["payout_a"] >= p.fodder_gate * p.crop_allocation - 1e-6)).all()
    assert (seasons["payout_total"] <= p.aggregate_cap + 1e-6).all()
    assert seasons["payout_total"].sum() == pytest.approx(seasons[["payout_a", "payout_b", "payout_c"]].sum().sum())
    assert sorted(seasons.loc[seasons["season"] == "LR", "ndvi_pct"]) == pytest.approx(list(range(5, 100, 10)))


def test_aggregate_cap_scales_layers_down_together(njoro):
    p = replace(pe.TriggerParams(), aggregate_cap_share=0.3, fodder_gate=0.0, ndvi_trigger=50)
    seasons = pe.run_backtest(njoro, p)
    capped = seasons[seasons["payout_uncapped"] > p.aggregate_cap]
    assert len(capped) > 0
    assert capped["payout_total"].tolist() == pytest.approx([p.aggregate_cap] * len(capped))
    uncapped = pe.run_backtest(njoro, replace(p, aggregate_cap_share=1.0))
    assert seasons["payout_total"].sum() < uncapped["payout_total"].sum()


def test_target_pricing_hits_the_loss_ratio():
    p = pe.TriggerParams()
    for key in pe.WARDS:
        k = pe.kpis(pe.run_backtest(pe.load_weather(key)[0], p), p)
        assert k.loss_ratio_pct <= 60.0 + 1e-6
        assert k.loss_ratio_pct > 55.0  # rounding up to 0.1% only moves it a little
        assert k.premium_ksh == pytest.approx(p.sum_insured * k.premium_rate_pct / 100)


def test_flat_pricing_and_subsidy(njoro):
    p = replace(pe.TriggerParams(), pricing_mode="flat", premium_rate=0.06, subsidy_share=0.5)
    k = pe.kpis(pe.run_backtest(njoro, p), p)
    assert k.premium_rate_pct == pytest.approx(6.0)
    assert k.premium_ksh == pytest.approx(3_600)
    assert k.farmer_premium_ksh == pytest.approx(1_800)
    assert pe.commercial_rate(0.05, pe.TriggerParams()) == pytest.approx(0.084)  # 5% / 60% = 8.33%, rounded up


def test_backtest_is_deterministic(njoro):
    pd.testing.assert_frame_equal(pe.run_backtest(njoro), pe.run_backtest(njoro))


def test_drought_seasons_read_dry_and_flood_seasons_wet():
    """2022 long rains were a drought in Machakos; the 2020 long rains were very wet. The proxy must agree."""
    seasons = pe.run_backtest(pe.load_weather("kangundo")[0]).set_index("label")
    assert seasons.loc["2022 LR", "sm_weighted"] < 32 < seasons.loc["2020 LR", "sm_weighted"]
    assert seasons.loc["2022 LR", "payout_a"] > 0
    assert seasons.loc["2020 LR", "payout_a"] == 0


def test_kpis_match_the_rows(njoro):
    p = pe.TriggerParams()
    seasons = pe.run_backtest(njoro, p)
    k = pe.kpis(seasons, p)
    assert k.burn_cost_pct == pytest.approx(100 * seasons["payout_total"].mean() / p.sum_insured)
    assert k.loss_ratio_pct == pytest.approx(100 * k.burn_cost_pct / k.premium_rate_pct)
    assert k.seasons == 20
    stressed = seasons["wrsi"] < 60
    assert k.basis.mismatches_index == int(((seasons["payout_a"] > 0) != stressed).sum())


def test_verified_basis_view_follows_its_assumption(njoro):
    seasons = pe.run_backtest(njoro)
    perfect = pe.basis_risk(seasons, replace(pe.TriggerParams(), verifier_accuracy=1.0))
    useless = pe.basis_risk(seasons, replace(pe.TriggerParams(), verifier_accuracy=0.0))
    assert perfect.mismatches_verified <= perfect.mismatches_index
    assert useless.mismatches_verified >= perfect.mismatches_verified
    no_band = pe.basis_risk(seasons, replace(pe.TriggerParams(), amber_band=-1))
    assert no_band.amber_seasons == 0 and no_band.mismatches_verified == no_band.mismatches_index


def test_zone_pricing_covers_every_ward():
    zones = pe.zone_pricing()
    assert list(zones["ward_key"]) == list(pe.WARDS)
    assert zones["premium_rate_pct"].nunique() > 1  # wards are priced differently
    assert set(zones["zone"]) >= {"Semi-arid", "Wet highland", "Transitional"}


def test_wards_above_the_ceiling_are_not_offered():
    zones = pe.zone_pricing().set_index("ward_key")
    over = zones["premium_rate_pct"] > 12.0 + 1e-9
    assert (zones.loc[over, "offered"].str.startswith("No")).all()
    assert (zones.loc[~over, "offered"] == "Yes").all()
    assert zones.loc["bureti", "offered"].startswith("No")  # the wet tea-dairy highland
    relaxed = pe.zone_pricing(replace(pe.TriggerParams(), max_sellable_rate=0.25))
    assert (relaxed["offered"] == "Yes").all()


def test_higher_trigger_never_pays_less(njoro):
    low = pe.run_backtest(njoro, pe.TriggerParams(sm_trigger=25))["payout_a"].sum()
    high = pe.run_backtest(njoro, pe.TriggerParams(sm_trigger=40))["payout_a"].sum()
    assert high >= low


def test_offline_fallback_without_cache_or_network(tmp_path, monkeypatch):
    def no_network(*_args, **_kwargs):
        raise pe.requests.ConnectionError("offline")

    monkeypatch.setattr(pe.requests, "get", no_network)
    weather, source, _ = pe.load_weather("bureti", cache_dir=tmp_path)
    assert source == pe.SOURCE_FALLBACK
    assert len(weather) == 3653
    again, _, _ = pe.load_weather("bureti", cache_dir=tmp_path)
    pd.testing.assert_frame_equal(weather, again)
    seasons = pe.run_backtest(weather)
    assert len(seasons) == 20 and np.isfinite(seasons["payout_total"]).all()


def test_refresh_falls_back_to_cache_when_offline(monkeypatch):
    def slow(*_args, **_kwargs):
        raise pe.requests.Timeout("slow")

    monkeypatch.setattr(pe.requests, "get", slow)
    weather, source, _ = pe.load_weather("njoro", refresh=True)
    assert source == pe.SOURCE_CACHE and len(weather) == 3653


def test_trajectory_has_nine_dekads(njoro):
    traj = pe.dekadal_trajectory(njoro, 2022, "LR")
    assert list(traj["dekad"]) == list(range(1, 10))  # days 81-92 form the last dekad, not a 2-day stub


def test_missing_data_never_pays():
    p = pe.TriggerParams()
    nan = float("nan")
    assert pe.payout_a_fraction(nan, p) == 0
    assert pe.payout_b_fraction(0.8, nan, 0, p) == 0
    assert pe.payout_b_fraction(nan, 5, 0, p) == 0


def test_leap_years_compare_like_with_like(njoro):
    daily = pe.daily_indices(njoro)
    march_first = daily[(daily["date"].dt.month == 3) & (daily["date"].dt.day == 1)]
    # 1 March is compared with the same climatology day in every year, leap or not
    assert len(march_first) == 10


def test_minimum_premium_rate():
    p = replace(pe.TriggerParams(), sm_trigger=15, rain10_mode="fixed", rain10_trigger_mm=300, heat_temp_c=36,
                heat_days=14)
    zones = pe.zone_pricing(p)
    assert (zones["premium_rate_pct"] >= 1.0 - 1e-9).all()
    assert pe.commercial_rate(0.0, pe.TriggerParams()) == 0.01
