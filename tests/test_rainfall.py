import json

import pandas as pd
import pytest

from agroshield_pricing.provenance import Label
from agroshield_pricing.rainfall import ChirpsClimateServSource, SyntheticRainfallSource
from agroshield_pricing.rainfall.chirps import ward_geometry


def test_synthetic_rainfall_is_deterministic_complete_and_labelled(cfg):
    ward = cfg.ward("ward-a")
    a = SyntheticRainfallSource(seed=1).daily(ward, 2000, 2004)
    b = SyntheticRainfallSource(seed=1).daily(ward, 2000, 2004)
    assert a.equals(b)
    assert len(a) == len(pd.date_range("2000-01-01", "2004-12-31"))
    assert SyntheticRainfallSource().provenance(ward).label is Label.SYNTHETIC


def test_synthetic_rainfall_is_bimodal(cfg):
    s = SyntheticRainfallSource(seed=3).daily(cfg.ward("ward-a"), 1981, 2020)
    monthly = s.groupby(s.index.month).mean()
    assert monthly[4] > 2 * monthly[1]       # long rains peak
    assert monthly[11] > 2 * monthly[1]      # short rains peak
    assert monthly[7] < monthly[4]           # mid-year dip


def _fake_cache(tmp_path, ward, start=2000, end=2001):
    days = pd.date_range(f"{start}-01-01", f"{end}-12-31")
    csv = tmp_path / f"{ward.id}.csv"
    pd.DataFrame({"date": days.strftime("%Y-%m-%d"), "rain_mm": 2.0}).to_csv(csv, index=False, lineterminator="\n")
    import hashlib
    meta = {"request": {"geometry": ward_geometry(ward)}, "start_year": start, "end_year": end,
            "sha256": hashlib.sha256(csv.read_bytes()).hexdigest()}
    (tmp_path / f"{ward.id}.meta.json").write_text(json.dumps(meta))
    return csv


def test_chirps_cache_is_read_offline(cfg, tmp_path):
    ward = cfg.ward("ward-a")
    _fake_cache(tmp_path, ward)
    s = ChirpsClimateServSource(tmp_path, allow_download=False).daily(ward, 2000, 2001)
    assert s.sum() == pytest.approx(2.0 * 731)


def test_chirps_cache_detects_tampering(cfg, tmp_path):
    ward = cfg.ward("ward-a")
    csv = _fake_cache(tmp_path, ward)
    csv.write_text(csv.read_text().replace("2.0", "9.0", 1))
    with pytest.raises(ValueError, match="SHA-256"):
        ChirpsClimateServSource(tmp_path, allow_download=False).daily(ward, 2000, 2001)


def test_chirps_cache_refuses_changed_geometry(cfg, tmp_path):
    ward = cfg.ward("ward-a")
    _fake_cache(tmp_path, ward)
    moved = ward.model_copy(update={"centroid": ward.centroid.model_copy(update={"lat": -0.5})})
    with pytest.raises(ValueError, match="different geometry"):
        ChirpsClimateServSource(tmp_path, allow_download=False).daily(moved, 2000, 2001)


def test_chirps_offline_without_cache_fails_clearly(cfg, tmp_path):
    with pytest.raises(FileNotFoundError, match="fetch-rainfall"):
        ChirpsClimateServSource(tmp_path, allow_download=False).daily(cfg.ward("ward-a"), 2000, 2001)


def test_committed_chirps_inputs_match_their_checksums(cfg):
    src = ChirpsClimateServSource(cfg.root.parent / "data" / "raw" / "chirps", allow_download=False)
    h = cfg.rainfall.history
    for wid in cfg.pilot.wards:
        assert src.is_cached(cfg.ward(wid), h.start_year, h.end_year)
