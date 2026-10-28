import hashlib
import json

import numpy as np
import pandas as pd
import pytest

from agroshield_pricing.pet.hargreaves import extraterrestrial_radiation, hargreaves_et0
from agroshield_pricing.pet.nasapower import HargreavesNasaPowerSource
from agroshield_pricing.validation import compare_fewsnet, real_yield_backtest


# ------------------------------------------------------------------ Hargreaves
def test_extraterrestrial_radiation_matches_fao56_example_8():
    # FAO-56 Example 8: 20 deg S on 3 September (day 246) -> Ra = 32.2 MJ m-2 day-1
    assert extraterrestrial_radiation(-20.0, 246) == pytest.approx(32.2, abs=0.1)


def test_hargreaves_formula():
    ra_mm = 0.408 * extraterrestrial_radiation(0.0, 100)
    expected = 0.0023 * (17.5 + 17.8) * np.sqrt(15.0) * ra_mm
    assert hargreaves_et0(25.0, 10.0, 0.0, 100) == pytest.approx(expected)


def test_hargreaves_rises_with_temperature_range():
    assert hargreaves_et0(28, 8, -0.2, 120) > hargreaves_et0(22, 14, -0.2, 120)


# ------------------------------------------------------------------ NASA POWER cache
def _fake_power_cache(tmp_path, ward, grid_elev=2300.0):
    days = pd.date_range("2000-01-01", "2001-12-31")
    csv = tmp_path / f"{ward.id}.csv"
    pd.DataFrame({"date": days.strftime("%Y-%m-%d"), "tmax_c": 24.0, "tmin_c": 12.0}).to_csv(
        csv, index=False, lineterminator="\n")
    meta = {"request": {"point": {"lat": ward.centroid.lat, "lon": ward.centroid.lon}},
            "grid_elevation_m": grid_elev, "start_year": 2000, "end_year": 2001,
            "sha256": hashlib.sha256(csv.read_bytes()).hexdigest()}
    (tmp_path / f"{ward.id}.meta.json").write_text(json.dumps(meta))
    return csv


def test_power_cache_gives_complete_pet_with_lapse_shift(cfg, tmp_path):
    ward = cfg.ward("ward-a")                      # 1900 m, grid cell 2300 m -> 2.6 C warmer
    _fake_power_cache(tmp_path, ward)
    src = HargreavesNasaPowerSource(tmp_path, 6.5, allow_download=False)
    pet = src.daily(ward, 2000, 2001)
    assert len(pet) == 731 and (pet > 0).all()
    unshifted = HargreavesNasaPowerSource(tmp_path, 0.0, allow_download=False).daily(ward, 2000, 2001)
    assert (pet > unshifted).all()
    assert src.provenance(ward).details["lapse_shift_c"] == pytest.approx(2.6)


def test_power_cache_detects_tampering(cfg, tmp_path):
    ward = cfg.ward("ward-a")
    csv = _fake_power_cache(tmp_path, ward)
    csv.write_text(csv.read_text().replace("24.0", "30.0", 1))
    with pytest.raises(ValueError, match="SHA-256"):
        HargreavesNasaPowerSource(tmp_path, allow_download=False).daily(ward, 2000, 2001)


def test_committed_power_inputs_match_their_checksums(cfg):
    src = HargreavesNasaPowerSource(cfg.root.parent / "data" / "raw" / "nasapower", allow_download=False)
    h = cfg.rainfall.history
    for wid in cfg.pilot.wards:
        assert src.is_cached(cfg.ward(wid), h.start_year, h.end_year)


# ------------------------------------------------------------------ FEWS NET comparison
def test_fewsnet_comparison_reports_correlation_and_gaps():
    years = range(2001, 2011)
    ours = pd.Series([90, 80, 70, 95, 60, np.nan, 85, 75, 100, 65], index=years, dtype=float)
    fews = pd.Series([88, 82, 72, 93, 85, 50, 86, 70, 98, 66], index=years, dtype=float)
    r = compare_fewsnet(ours, fews, large_gap=15, status="")
    assert r["available"] and r["seasons"] == 9          # failed onset (NaN) excluded
    assert [g["year"] for g in r["large_gaps"]] == [2005]
    assert 0 < r["pearson_r"] < 1


def test_fewsnet_comparison_pending_without_data():
    r = compare_fewsnet(pd.Series([80.0]), None, 15, "server down")
    assert r == {"available": False, "reason": "server down"}


def test_basis_risk_not_measurable_without_real_yields(cfg, tmp_path):
    r = real_yield_backtest(cfg, "ward-a", "LR", pd.Series([0.1, 0.0], index=[2000, 2001]))
    assert r["available"] is False and "Not measurable" in r["reason"]
