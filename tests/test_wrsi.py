import numpy as np
import pandas as pd
import pytest

from agroshield_pricing.wrsi import (SeasonWRSI, dekad_end, dekad_label, dekad_number, dekad_start,
                                     first_planting_rain, flowering_payout, kc_by_dekad, longest_dry_spell,
                                     season_wrsi, to_dekads, water_balance, wrsi_from, wrsi_payout)


# ------------------------------------------------------------------ dekads
@pytest.mark.parametrize("day, part", [(1, 0), (10, 0), (11, 1), (20, 1), (21, 2), (31, 2)])
def test_dekad_boundaries(day, part):
    assert dekad_number(pd.Timestamp(2020, 1, day)) == 2020 * 36 + part


def test_dekad_round_trip_and_label():
    t = dekad_number(pd.Timestamp(1984, 4, 15))
    assert dekad_start(t) == pd.Timestamp(1984, 4, 11)
    assert dekad_end(t) == pd.Timestamp(1984, 4, 20)
    assert dekad_label(t) == "Apr d2 1984"
    assert dekad_end(dekad_number(pd.Timestamp(2021, 2, 25))) == pd.Timestamp(2021, 2, 28)


def test_to_dekads_sums_days_including_short_and_long_months():
    days = pd.date_range("2021-02-01", "2021-03-31")
    s = to_dekads(pd.Series(1.0, index=days))
    feb3, mar3 = 2021 * 36 + 5, 2021 * 36 + 8
    assert s[feb3] == 8      # 21-28 Feb
    assert s[mar3] == 11     # 21-31 Mar
    assert s.sum() == len(days)


# ------------------------------------------------------------------ planting rain
def test_first_planting_rain():
    rain = pd.Series([10, 24.9, 25, 40], index=range(100, 104), dtype=float)
    assert first_planting_rain(rain, 100, 103, 25) == 102
    assert first_planting_rain(rain, 100, 101, 25) is None


# ------------------------------------------------------------------ early-season triggers
def _season(cfg, daily: pd.Series, year=2000, whc=100):
    lb = cfg.product.layer_b
    pet = pd.Series(4.0, index=daily.index)
    return season_wrsi(daily, to_dekads(daily), to_dekads(pet), cfg.calendar("ward-a", "LR"), year, lb, whc)


def _days():
    return pd.Series(0.0, index=pd.date_range("1999-01-01", "2001-12-31"))


def test_failed_onset_when_window_rain_is_below_threshold(cfg):
    rain = _days()
    rain["2000-03-05"] = 70.0                      # whole window: 70 mm < 80 mm
    s = _season(cfg, rain)
    assert s.failed_onset and s.wrsi is None and s.window_rain_mm == 70.0
    assert wrsi_payout(s, 80, 50) == 0.0           # the WRSI component does not also pay


def test_germination_dry_spell_restarts_the_season(cfg):
    rain = _days()
    rain["2000-03-05"] = 30.0                      # planting rain, Mar d1
    rain["2000-03-11":"2000-03-30"] = 0.5          # 10 mm in the next 20 days -> dry spell
    rain["2000-04-12"] = 30.0                      # next planting rain, Apr d2
    rain["2000-04-21":"2000-09-30"] = 5.0
    s = _season(cfg, rain)
    assert not s.failed_onset
    assert s.germination_failed and s.germination_rain_mm == pytest.approx(10.0)
    assert dekad_label(s.planting_rain_dekad) == "Mar d1 2000"
    assert dekad_label(s.sos) == "Apr d2 2000"
    assert s.sos_rule.startswith("replanting rain")


def test_good_germination_keeps_the_first_planting_rain(cfg):
    rain = _days()
    rain["2000-03-05"] = 30.0
    rain["2000-03-11":"2000-09-30"] = 5.0
    s = _season(cfg, rain)
    assert not s.germination_failed and dekad_label(s.sos) == "Mar d1 2000"


def test_no_planting_rain_starts_at_window_end(cfg):
    rain = _days()
    rain["2000-03-01":"2000-04-30"] = 2.0          # 122 mm, never 25 mm in one dekad
    s = _season(cfg, rain)
    assert not s.failed_onset and dekad_label(s.sos) == "Apr d3 2000"
    assert s.germination_rain_mm is None


# ------------------------------------------------------------------ crop and water balance
def test_kc_curve_follows_fews_points():
    kc = kc_by_dekad(10, [0, 16, 44, 76, 100], [0.3, 0.3, 1.2, 1.2, 0.35])
    assert kc[0] == pytest.approx(0.3)
    assert kc[5] == pytest.approx(1.2)          # 55% of the season
    assert kc[-1] == pytest.approx(np.interp(95, [76, 100], [1.2, 0.35]))


def test_ample_rain_gives_wrsi_100():
    n = 12
    tr = water_balance(np.full(n, 80.0), np.full(n, 40.0), np.full(n, 1.0), 100, 0.5, np.zeros(3), np.full(3, 40.0))
    assert wrsi_from(tr) == 100.0


def test_no_rain_and_empty_soil_gives_wrsi_0():
    n = 12
    tr = water_balance(np.zeros(n), np.full(n, 40.0), np.full(n, 1.0), 100, 0.5, np.zeros(3), np.full(3, 40.0))
    assert wrsi_from(tr) == 0.0


def test_stored_soil_water_carries_the_crop():
    n = 6
    dry, pet, kc = np.zeros(n), np.full(n, 30.0), np.full(n, 1.0)
    no_store = wrsi_from(water_balance(dry, pet, kc, 150, 0.5, np.zeros(3), np.full(3, 30.0)))
    stored = wrsi_from(water_balance(dry, pet, kc, 150, 0.5, np.full(3, 80.0), np.full(3, 30.0)))
    assert stored > no_store


def test_water_balance_conserves_water():
    rng = np.random.default_rng(1)
    rain, pet = rng.uniform(0, 80, 15), rng.uniform(25, 50, 15)
    tr = water_balance(rain, pet, np.full(15, 1.1), 120, 0.55, np.zeros(0), np.zeros(0))
    # rain in = AET + surplus + change in soil (soil starts empty)
    assert rain.sum() == pytest.approx(tr["aet"].sum() + tr["surplus"].sum() + tr["soil"].iloc[-1])


# ------------------------------------------------------------------ payouts
@pytest.mark.parametrize("wrsi, expected", [(100, 0.0), (80, 0.0), (65, 0.5), (50, 1.0), (30, 1.0)])
def test_wrsi_payout_is_linear_between_trigger_and_exit(wrsi, expected):
    assert wrsi_payout(SeasonWRSI(2000, 1, wrsi, None), 80, 50) == pytest.approx(expected)


def test_longest_dry_spell():
    assert longest_dry_spell(np.array([5, 0, 0, 1, 0, 3, 0, 0, 0, 0]), 2.0) == 4
    assert longest_dry_spell(np.array([5, 5]), 2.0) == 0


@pytest.mark.parametrize("days, expected", [(10, 0.0), (12, 0.0), (18.5, 0.15), (25, 0.30), (40, 0.30)])
def test_flowering_payout_rises_from_trigger_to_exit(cfg, days, expected):
    fl = cfg.product.layer_b.flowering                  # trigger 12, exit 25, max 30%
    assert flowering_payout({"longest_dry_spell_days": days, "rainfall_deficit_pct": 0}, fl) == pytest.approx(expected)


def test_season_wrsi_end_to_end_on_a_constructed_season(cfg):
    rain = _days()
    rain["2000-03-11":"2000-03-20"] = 4.0          # 40 mm dekad -> planting rain Mar d2
    rain["2000-03-21":"2000-09-30"] = 5.0          # 50 mm per dekad afterwards
    s = _season(cfg, rain)
    assert dekad_label(s.sos) == "Mar d2 2000" and not s.germination_failed
    # Soil starts empty (dry spin-up), so the first crop dekad's 40 mm sits just under
    # the (1 - p) x capacity stress threshold of 45 mm: a slight shortfall, then none.
    assert 99 < s.wrsi < 100
    assert s.trace["deficit"].iloc[1:].sum() == pytest.approx(0)
    assert len(s.trace) == cfg.calendar("ward-a", "LR").lgp_dekads
    assert s.flowering["longest_dry_spell_days"] == 0


def test_planting_rain_search_starts_at_the_ward_date(cfg):
    rain = _days()
    rain["2000-03-05"] = 30.0                      # early rain, before farmers plant
    rain["2000-03-21":"2000-03-30"] = 3.0          # 30 mm, Mar d3
    rain["2000-04-01":"2000-09-30"] = 5.0
    lb = cfg.product.layer_b
    cal = cfg.calendar("ward-a", "LR").model_copy(update={"planting_rain_from": "03-15"})
    pet = pd.Series(4.0, index=rain.index)
    s = season_wrsi(rain, to_dekads(rain), to_dekads(pet), cal, 2000, lb, 100)
    assert dekad_label(s.planting_rain_dekad) == "Mar d3 2000"    # the 5 March rain is ignored
    assert not s.germination_failed
