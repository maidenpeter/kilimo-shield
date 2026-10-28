import numpy as np
import pandas as pd
import pytest

from agroshield_pricing.wrsi import (SeasonWRSI, dekad_label, dekad_number, dekad_start, find_onset,
                                     kc_by_dekad, season_wrsi, to_dekads, water_balance, wrsi_from,
                                     wrsi_payout)


# ------------------------------------------------------------------ dekads
@pytest.mark.parametrize("day, part", [(1, 0), (10, 0), (11, 1), (20, 1), (21, 2), (31, 2)])
def test_dekad_boundaries(day, part):
    assert dekad_number(pd.Timestamp(2020, 1, day)) == 2020 * 36 + part


def test_dekad_round_trip_and_label():
    t = dekad_number(pd.Timestamp(1984, 4, 15))
    assert dekad_start(t) == pd.Timestamp(1984, 4, 11)
    assert dekad_label(t) == "Apr d2 1984"


def test_to_dekads_sums_days_including_short_and_long_months():
    days = pd.date_range("2021-02-01", "2021-03-31")
    s = to_dekads(pd.Series(1.0, index=days))
    feb3, mar3 = 2021 * 36 + 5, 2021 * 36 + 8
    assert s[feb3] == 8      # 21-28 Feb
    assert s[mar3] == 11     # 21-31 Mar
    assert s.sum() == len(days)


# ------------------------------------------------------------------ onset rule
def _rain(values, start_t=100):
    return pd.Series(values, index=range(start_t, start_t + len(values)), dtype=float)


def test_onset_needs_first_dekad_and_follow_up():
    rain = _rain([10, 30, 5, 10, 40, 15, 10])
    # dekad 101 has 30 mm but only 15 mm follows; dekad 104 has 40 then 25 -> onset
    assert find_onset(rain, 100, 106, 25, 20) == 104


def test_onset_follow_up_may_fall_after_the_window():
    rain = _rain([0, 0, 30, 10, 12])
    assert find_onset(rain, 100, 102, 25, 20) == 102


def test_failed_onset_when_no_dekad_qualifies():
    rain = _rain([24, 24, 145, 10, 4, 0])
    assert find_onset(rain, 100, 103, 25, 20) is None


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
    dry = np.zeros(n)
    pet = np.full(n, 30.0)
    kc = np.full(n, 1.0)
    no_store = wrsi_from(water_balance(dry, pet, kc, 150, 0.5, np.zeros(3), np.full(3, 30.0)))
    stored = wrsi_from(water_balance(dry, pet, kc, 150, 0.5, np.full(3, 80.0), np.full(3, 30.0)))
    assert stored > no_store


def test_water_balance_conserves_water():
    rng = np.random.default_rng(1)
    rain, pet = rng.uniform(0, 80, 15), rng.uniform(25, 50, 15)
    tr = water_balance(rain, pet, np.full(15, 1.1), 120, 0.55, np.zeros(0), np.zeros(0))
    # rain in = AET + surplus + change in soil (soil starts empty)
    assert rain.sum() == pytest.approx(tr["aet"].sum() + tr["surplus"].sum() + tr["soil"].iloc[-1])


# ------------------------------------------------------------------ payout
@pytest.mark.parametrize("wrsi, expected", [(100, 0.0), (80, 0.0), (65, 0.5), (50, 1.0), (30, 1.0)])
def test_wrsi_payout_is_linear_between_trigger_and_exit(wrsi, expected):
    assert wrsi_payout(SeasonWRSI(2000, 1, wrsi, None), 0.25, 80, 50) == pytest.approx(expected)


def test_failed_onset_pays_the_fixed_amount():
    assert wrsi_payout(SeasonWRSI(2000, None, None, None), 0.25, 80, 50) == 0.25


def test_season_wrsi_end_to_end_on_a_constructed_season(cfg):
    cal = cfg.calendar("ward-a", "LR")
    lb = cfg.product.layer_b
    days = pd.date_range("1999-01-01", "2001-12-31")
    rain = pd.Series(0.0, index=days)
    rain["2000-03-11":"2000-03-20"] = 4.0          # 40 mm dekad -> onset Mar d2
    rain["2000-03-21":"2000-09-30"] = 5.0          # 50 mm per dekad afterwards
    pet = pd.Series(4.0, index=days)
    s = season_wrsi(to_dekads(rain), to_dekads(pet), cal, 2000, lb, 100)
    assert dekad_label(s.sos) == "Mar d2 2000"
    # Soil starts empty (dry spin-up), so the first crop dekad's 40 mm sits just under
    # the (1 - p) x capacity stress threshold of 45 mm: a slight shortfall, then none.
    assert 99 < s.wrsi < 100
    assert s.trace["deficit"].iloc[1:].sum() == pytest.approx(0)
    assert len(s.trace) == cal.lgp_dekads
