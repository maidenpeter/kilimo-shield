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


def test_payout_a_scales_from_25_to_100_percent():
    p = pe.TriggerParams()
    assert pe.payout_a_fraction(p.sm_trigger, p) == 0
    assert pe.payout_a_fraction(p.sm_trigger - 1e-6, p) == pytest.approx(0.25)
    assert pe.payout_a_fraction((p.sm_trigger + p.sm_exit) / 2, p) == pytest.approx(0.625)
    assert pe.payout_a_fraction(p.sm_exit, p) == pytest.approx(1.0)
    assert pe.payout_a_fraction(0, p) == pytest.approx(1.0)


def test_payout_b_needs_a_crop_payout():
    p = pe.TriggerParams()
    assert pe.payout_b_fraction(False, 5, 0, p) == 0
    assert pe.payout_b_fraction(True, 35, 0, p) == 0
    assert pe.payout_b_fraction(True, p.ndvi_trigger - 1e-6, 0, p) == pytest.approx(0.5)
    assert pe.payout_b_fraction(True, 0, 0, p) == pytest.approx(1.0)
    assert pe.payout_b_fraction(True, 15, 2.0, p) == pytest.approx(1.0)  # heat adds severity, capped at 100%


def test_payout_c_fires_on_rain_or_heat():
    p = pe.TriggerParams()
    assert not pe.payout_c_fires(180, 6, p)
    assert pe.payout_c_fires(180.1, 0, p)
    assert pe.payout_c_fires(0, 7, p)
    assert pe.longest_run([True, True, False, True, True, True]) == 3


def test_backtest_shape_and_money(njoro):
    p = pe.TriggerParams()
    seasons = pe.run_backtest(njoro, p)
    assert len(seasons) == 20
    assert set(seasons["season"]) == {"LR", "SR"}
    assert (seasons["payout_a"] <= p.crop_allocation + 1e-6).all()
    assert (seasons["payout_b"] <= p.fodder_allocation + 1e-6).all()
    assert seasons["payout_c"].isin([0.0, p.health_payout]).all()
    assert ((seasons["payout_b"] > 0) <= (seasons["payout_a"] > 0)).all()
    assert (seasons["payout_total"] <= p.sum_insured + 1e-6).all()
    assert seasons["premium"].eq(3_600).all()
    assert sorted(seasons.loc[seasons["season"] == "LR", "ndvi_pct"]) == pytest.approx(list(range(5, 100, 10)))


def test_backtest_is_deterministic(njoro):
    a = pe.run_backtest(njoro)
    b = pe.run_backtest(njoro)
    pd.testing.assert_frame_equal(a, b)


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
    assert k.loss_ratio_pct == pytest.approx(k.burn_cost_pct / (100 * p.premium_rate) * 100)
    assert k.seasons == 20
    stressed = seasons["wrsi"] < 60
    assert k.mismatches_multi == int(((seasons["payout_a"] > 0) != stressed).sum())


def test_higher_trigger_never_pays_less(njoro):
    low = pe.run_backtest(njoro, pe.TriggerParams(sm_trigger=25))["payout_a"].sum()
    high = pe.run_backtest(njoro, pe.TriggerParams(sm_trigger=40))["payout_a"].sum()
    assert high >= low


def test_offline_fallback_without_cache_or_network(tmp_path, monkeypatch):
    def no_network(*args, **kwargs):
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
    monkeypatch.setattr(pe.requests, "get", lambda *a, **k: (_ for _ in ()).throw(pe.requests.Timeout("slow")))
    weather, source, _ = pe.load_weather("njoro", refresh=True)
    assert source == pe.SOURCE_CACHE and len(weather) == 3653


def test_trajectory_has_ten_dekads(njoro):
    traj = pe.dekadal_trajectory(njoro, 2022, "LR")
    assert list(traj["dekad"]) == list(range(1, 11))
