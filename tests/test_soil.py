"""Soil water holding capacity from SoilGrids: the AWC maths, the polygon mean,
the raw-data cache checks and the ward config that uses the result."""
import json
from pathlib import Path

import numpy as np
import pytest
import yaml

from agroshield_pricing import soil
from agroshield_pricing.config import load_config
from agroshield_pricing.rainfall.chirps import ward_geometry

REPO = Path(__file__).resolve().parents[1]
RAW = REPO / "data" / "raw" / "soil" / "soilgrids"
SUMMARY = REPO / "data" / "soil" / "ward_awc.json"


# ------------------------------------------------------------------ AWC maths
def test_layer_overlap():
    assert soil.layer_overlap_cm(0, 5, 100) == 5
    assert soil.layer_overlap_cm(60, 100, 100) == 40
    assert soil.layer_overlap_cm(100, 200, 100) == 0
    assert soil.layer_overlap_cm(100, 200, 150) == 50
    assert soil.layer_overlap_cm(30, 60, 45) == 15


def test_awc_uniform_profile_is_difference_times_depth():
    # 0.30 at field capacity, 0.18 at wilting point: 0.12 x 1000 mm = 120 mm over 1 m
    fc, wp = [0.30] * 6, [0.18] * 6
    assert soil.awc_mm(fc, wp, 100) == pytest.approx(120.0)
    assert soil.awc_mm(fc, wp, 60) == pytest.approx(72.0)
    assert soil.awc_mm(fc, wp, 150) == pytest.approx(180.0)    # half of the 100-200 cm layer


def test_awc_sums_layers_by_thickness():
    fc = [0.40, 0.38, 0.36, 0.34, 0.32, 0.30]
    wp = [0.20, 0.20, 0.20, 0.20, 0.20, 0.20]
    # layers in the top metre: 5, 10, 15, 30, 40 cm
    expected = 10 * (0.20 * 5 + 0.18 * 10 + 0.16 * 15 + 0.14 * 30 + 0.12 * 40)
    assert soil.awc_mm(fc, wp, 100) == pytest.approx(expected)
    # the 100-200 cm layer only counts below 100 cm
    assert soil.awc_mm(fc, wp, 200) == pytest.approx(expected + 10 * 0.10 * 100)


def test_awc_never_negative_and_stones_reduce_it():
    fc, wp = [0.20] * 6, [0.25] * 6
    assert soil.awc_mm(fc, wp, 100) == 0.0
    fc, wp = [0.30] * 6, [0.20] * 6
    assert soil.awc_mm(fc, wp, 100, coarse_fraction=[0.25] * 6) == pytest.approx(75.0)


@pytest.mark.parametrize("kwargs, msg", [
    ({"theta_fc": [0.3] * 5, "theta_wp": [0.2] * 6, "depth_cm": 100}, "one value per layer"),
    ({"theta_fc": [300] * 6, "theta_wp": [200] * 6, "depth_cm": 100}, "fraction"),     # unscaled SoilGrids units
    ({"theta_fc": [0.3] * 6, "theta_wp": [0.2] * 6, "depth_cm": 250}, "below the deepest layer"),
    ({"theta_fc": [0.3] * 6, "theta_wp": [0.2] * 6, "depth_cm": 0}, "positive"),
])
def test_awc_rejects_bad_input(kwargs, msg):
    with pytest.raises(ValueError, match=msg):
        soil.awc_mm(**kwargs)


def test_grid_awc_matches_layer_awc_per_pixel():
    rng = np.random.default_rng(1)
    wp = rng.uniform(0.15, 0.25, size=(6, 4, 3))
    fc = wp + rng.uniform(-0.02, 0.15, size=(6, 4, 3))
    grid = soil.awc_grid_mm(fc, wp, 100)
    for i in range(4):
        for j in range(3):
            assert grid[i, j] == pytest.approx(soil.awc_mm(fc[:, i, j], wp[:, i, j], 100))


# ------------------------------------------------------------------ rasters
try:
    import rasterio
except ImportError:     # optional dependency: pip install -e .[soil]
    rasterio = None
needs_rasterio = pytest.mark.skipif(rasterio is None, reason="rasterio not installed (optional 'soil' extra)")


def _write_tif(path, data, transform, crs="EPSG:4326"):
    with rasterio.open(path, "w", driver="GTiff", width=data.shape[1], height=data.shape[0], count=1,
                       dtype="int16", crs=crs, transform=transform) as dst:
        dst.write(data.astype("int16"), 1)


@needs_rasterio
def test_polygon_pixels_takes_centres_inside_and_drops_zero(tmp_path):
    from rasterio.transform import from_origin
    data = np.full((10, 10), 300)
    data[4, 4] = 0                                   # no-data pixel inside the box
    tif = tmp_path / "x.tif"
    _write_tif(tif, data, from_origin(35.0, 0.0, 0.01, 0.01))
    # box from 35.02 to 35.07 E, -0.07 to -0.02: pixel centres 35.025..35.065 -> 5 x 5
    box = {"type": "Polygon", "coordinates": [[[35.02, -0.07], [35.07, -0.07], [35.07, -0.02],
                                               [35.02, -0.02], [35.02, -0.07]]]}
    vals = soil.polygon_pixels(tif, box, 1000)
    assert vals.size == 24
    assert np.allclose(vals, 0.3)


@needs_rasterio
def test_polygon_outside_raster_is_refused(tmp_path):
    from rasterio.transform import from_origin
    tif = tmp_path / "x.tif"
    _write_tif(tif, np.full((5, 5), 300), from_origin(35.0, 0.0, 0.01, 0.01))
    box = {"type": "Polygon", "coordinates": [[[35.02, -0.2], [35.2, -0.2], [35.2, -0.02],
                                               [35.02, -0.02], [35.02, -0.2]]]}
    with pytest.raises(ValueError, match="does not cover"):
        soil.polygon_pixels(tif, box, 1000)


@needs_rasterio
def test_native_bbox_is_on_the_soilgrids_grid(cfg):
    geoms = [ward_geometry(cfg.ward(w)) for w in cfg.pilot.wards]
    xmin, ymin, xmax, ymax = soil.native_bbox(geoms)
    for x in (xmin, xmax):
        assert (x - soil.GRID_X0) % soil.GRID_RES == 0
    for y in (ymin, ymax):
        assert (soil.GRID_Y0 - y) % soil.GRID_RES == 0
    assert xmin < xmax and ymin < ymax


def test_modified_raw_raster_is_refused(tmp_path):
    cov = "wv0033_0-5cm_mean"
    (tmp_path / f"{cov}.tif").write_bytes((RAW / f"{cov}.tif").read_bytes() + b"x")
    (tmp_path / f"{cov}.meta.json").write_text((RAW / f"{cov}.meta.json").read_text())
    with pytest.raises(ValueError, match="SHA-256"):
        soil.check_cached(tmp_path, cov)


# ------------------------------------------------------------------ committed data and config
def test_every_cached_raster_has_meta_and_matching_hash():
    for cov in soil.all_coverages():
        soil.check_cached(RAW, cov)
        m = json.loads((RAW / f"{cov}.meta.json").read_text())
        assert m["licence"] == "CC BY 4.0" and m["retrieved_at"] and m["request"]["url"].startswith("https://")


@needs_rasterio
def test_ward_awc_reproduces_the_committed_summary(cfg):
    committed = json.loads(SUMMARY.read_text())
    for w in cfg.pilot.wards:
        fresh = soil.ward_awc(RAW, ward_geometry(cfg.ward(w)))
        assert fresh["primary"] == committed["wards"][w]["primary"]
        assert committed["wards"][w]["geometry"] == ward_geometry(cfg.ward(w))


def test_ward_config_uses_the_soilgrids_value(cfg):
    committed = json.loads(SUMMARY.read_text())
    for w in cfg.pilot.wards:
        ward = cfg.ward(w)
        assert not ward.soil_illustrative
        assert "SoilGrids" in ward.soil_source and "0-100 cm" in ward.soil_source
        # config is rounded to whole millimetres
        assert ward.soil_whc_mm == round(committed["wards"][w]["primary"]["awc_33kpa_mm"])


def test_real_soil_label_needs_a_source(config_copy):
    path = config_copy / "wards.yaml"
    data = yaml.safe_load(path.read_text())
    data["wards"][0]["soil_illustrative"] = False
    data["wards"][0]["soil_source"] = "  "
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(ValueError, match="soil_source is empty"):
        load_config(config_copy)


def test_placeholder_soil_needs_no_source(config_copy):
    path = config_copy / "wards.yaml"
    data = yaml.safe_load(path.read_text())
    for w in data["wards"]:
        w["soil_illustrative"] = True
        w.pop("soil_source", None)
    path.write_text(yaml.safe_dump(data))
    assert all(w.soil_illustrative for w in load_config(config_copy).wards.values())


# ------------------------------------------------------------------ comparison tool
def _fake_results(whc, wrsi_2009, pay_2009):
    season = {
        "terms": {"soil_whc_mm": whc},
        "wrsi_stats": {"median": 98.0, "min": wrsi_2009, "below_trigger": 1},
        "burn_cost": {"seasons": 2, "payout_frequency": 0.5, "expected_loss": pay_2009 / 2},
        "target": {"main": {"frequency": 0.5}, "combined": {"frequency": 0.5}},
        "premium": {"gross_rate": pay_2009},
        "event_tests": [],
        "history": [{"year": 2008, "wrsi": 99.0, "payout": 0.0},
                    {"year": 2009, "wrsi": wrsi_2009, "payout": pay_2009}],
        "whc_sensitivity": [],
    }
    return {"ward": {"id": "ward-x"}, "seasons": {"LR": season},
            "provenance": [{"input": "Soil water holding capacity", "label": "REAL"}]}


def test_comparison_tool_reports_wrsi_and_payout_changes(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("soil_cmp", REPO / "tools" / "soil_whc_comparison.py")
    cmp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cmp)
    for name, res in (("before", _fake_results(100, 76.0, 0.12)), ("after", _fake_results(130, 81.0, 0.0))):
        d = tmp_path / name / "run1"
        d.mkdir(parents=True)
        (d / "results.json").write_text(json.dumps(res))
    out = tmp_path / "cmp.json"
    assert cmp.main(["x", str(tmp_path / "before"), str(tmp_path / "after"), str(out)]) == 0
    data = json.loads(out.read_text())
    assert data["status"].startswith("Needs owner approval")
    s = data["wards"]["ward-x"]["seasons"]["LR"]
    assert s["years_where_payout_changed"] == [2009]
    assert s["wrsi_change_summary"] == {"seasons_compared": 2, "mean": 2.5, "min": 0.0, "max": 5.0,
                                        "seasons_changed": 1}
    assert s["before"]["soil_whc_mm"] == 100 and s["after"]["soil_whc_mm"] == 130
