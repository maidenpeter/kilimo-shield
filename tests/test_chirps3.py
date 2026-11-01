"""CHIRPS v3.0 loader and the monitoring switch from CHIRPS v2 to v3."""
import hashlib
import json
from datetime import date

import numpy as np
import pandas as pd
import pytest

from agroshield_pricing.config import load_config
from agroshield_pricing.provenance import Label
from agroshield_pricing.rainfall import Chirps3Source, make_source
from agroshield_pricing.rainfall import chirps3 as c3
from agroshield_pricing.rainfall.chirps import ward_geometry

from conftest import REPO

GRID_LATS = np.round(np.arange(-59.975, 60, 0.05), 3)
GRID_LONS = np.round(np.arange(-179.975, 180, 0.05), 3)


# ------------------------------------------------------------------ pixel selection
def test_ward_boxes_take_the_four_pixels_whose_centres_are_inside(cfg):
    a = c3.pixels_in_polygon(ward_geometry(cfg.ward("ward-a")), GRID_LATS, GRID_LONS)
    centres = sorted((float(GRID_LATS[r]), float(GRID_LONS[c])) for r, c in a)
    assert centres == [(-0.175, 35.825), (-0.175, 35.875), (-0.125, 35.825), (-0.125, 35.875)]
    b = c3.pixels_in_polygon(ward_geometry(cfg.ward("ward-b")), GRID_LATS, GRID_LONS)
    assert sorted((float(GRID_LATS[r]), float(GRID_LONS[c])) for r, c in b) == \
        [(-0.275, 35.725), (-0.275, 35.775), (-0.225, 35.725), (-0.225, 35.775)]


def test_point_in_ring_handles_a_triangle():
    tri = [[0, 0], [1, 0], [0, 1], [0, 0]]
    assert c3.point_in_ring(0.2, 0.2, tri)
    assert not c3.point_in_ring(0.8, 0.8, tri)


def test_polygon_without_a_pixel_centre_is_refused():
    tiny = {"type": "Polygon", "coordinates": [[[35.801, 0.001], [35.802, 0.001], [35.802, 0.002],
                                                [35.801, 0.002], [35.801, 0.001]]]}
    with pytest.raises(ValueError, match="no CHIRPS pixel"):
        c3.pixels_in_polygon(tiny, GRID_LATS, GRID_LONS)


def test_polygon_mean_weights_pixels_equally():
    df = pd.DataFrame({"p1": [0.0, 4.0], "p2": [2.0, 4.0], "p3": [4.0, 4.0], "p4": [2.0, 0.0]})
    assert c3.polygon_mean(df).tolist() == [2.0, 3.0]


# ------------------------------------------------------------------ remote NetCDF reading (served locally)
class _LocalRangeSession:
    """Serves HTTP range requests from a local file; counts requests."""

    def __init__(self, path):
        self.data = open(path, "rb").read()
        self.ranges = []

    class _R:
        def __init__(self, status, content=b"", headers=None):
            self.status_code, self.content, self.headers = status, content, headers or {}

        def raise_for_status(self):
            pass

    def head(self, url, **kw):
        return self._R(200, headers={"Content-Length": str(len(self.data))})

    def get(self, url, headers=None, **kw):
        a, b = (int(x) for x in headers["Range"].split("=")[1].split("-"))
        self.ranges.append((a, b))
        return self._R(206, self.data[a:b + 1])


def _fake_year_file(path, year, shape=(5, 8), chunks=(31, 4, 4)):
    h5py = pytest.importorskip("h5py")
    days = pd.date_range(f"{year}-01-01", f"{year}-12-31")
    rng = np.random.default_rng(year)
    precip = rng.gamma(0.5, 6.0, size=(len(days), *shape)).astype("float32")
    precip[-3:, 0, 0] = -9999.0      # a few unpublished days at one pixel
    with h5py.File(path, "w") as h:
        h["latitude"] = np.round(np.arange(shape[0]) * 0.05 - 0.325, 3).astype("float32")
        h["longitude"] = np.round(np.arange(shape[1]) * 0.05 + 35.625, 3).astype("float32")
        t = h.create_dataset("time", data=(days - pd.Timestamp("1980-01-01")).days.astype("float32"))
        t.attrs["units"] = b"days since 1980-1-1 0:0:0"
        p = h.create_dataset("precip", data=precip, chunks=chunks, compression="gzip", compression_opts=5)
        p.attrs["_FillValue"] = np.array([-9999.0], dtype="float32")
    return days, precip


def test_year_window_is_read_from_chunks_with_range_requests(tmp_path, monkeypatch):
    monkeypatch.setattr(c3, "PAUSE_S", 0)
    f = tmp_path / "chirps-v3.0.rnl.2001.days_p05.nc"
    days, precip = _fake_year_file(f, 2001)
    sess = _LocalRangeSession(f)
    dates, arr, info = c3.read_year_window("http://x/y.nc", 1, 3, 2, 5, sess)
    assert list(dates) == list(days)
    expect = precip[:, 1:4, 2:6].astype("float64")
    assert np.allclose(arr, expect)
    assert info["direct_chunk_read"]
    # Only the chunks that hold the window: 12 time chunks x 1 row chunk x 2 column chunks.
    assert len(info["chunks"]) == 12 * 1 * 2
    assert {(c[1], c[2]) for c in info["chunks"]} == {(0, 0), (0, 4)}


def test_fill_values_become_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(c3, "PAUSE_S", 0)
    f = tmp_path / "y.nc"
    _fake_year_file(f, 2002)
    _, arr, _ = c3.read_year_window("http://x/y.nc", 0, 1, 0, 1, _LocalRangeSession(f))
    assert np.isnan(arr[-3:, 0, 0]).all() and not np.isnan(arr[:-3]).any()


# ------------------------------------------------------------------ cache
def _fake_cache(d, ward, start=2000, end=2001, extra_days=0):
    days = pd.date_range(f"{start}-01-01", pd.Timestamp(f"{end}-12-31") + pd.Timedelta(days=extra_days))
    d.mkdir(parents=True, exist_ok=True)
    csv, pix = d / f"{ward.id}.csv", d / f"{ward.id}.pixels.csv"
    pd.DataFrame({"date": days.strftime("%Y-%m-%d"), "rain_mm": 3.0}).to_csv(csv, index=False, lineterminator="\n")
    pd.DataFrame({"date": days.strftime("%Y-%m-%d"), "p1": 3.0}).to_csv(pix, index=False, lineterminator="\n")
    meta = {"request": {"geometry": ward_geometry(ward)}, "start_year": start, "end_year": end,
            "sha256": hashlib.sha256(csv.read_bytes()).hexdigest(),
            "pixels_sha256": hashlib.sha256(pix.read_bytes()).hexdigest()}
    (d / f"{ward.id}.meta.json").write_text(json.dumps(meta))
    return csv, pix


def test_cache_is_read_offline_and_labelled_real(cfg, tmp_path):
    ward = cfg.ward("ward-a")
    _fake_cache(tmp_path, ward, extra_days=40)
    src = Chirps3Source(tmp_path, allow_download=False)
    s = src.daily(ward, 2000, 2001)
    assert len(s) == 731 and s.sum() == pytest.approx(3.0 * 731)
    assert src.latest(ward).index.max() == pd.Timestamp("2002-02-09")
    p = src.provenance(ward)
    assert p.label is Label.REAL and "v3.0" in p.source


def test_cache_detects_tampering_in_either_file(cfg, tmp_path):
    ward = cfg.ward("ward-a")
    csv, pix = _fake_cache(tmp_path / "a", ward)
    csv.write_text(csv.read_text().replace("3.0", "9.0", 1))
    with pytest.raises(ValueError, match="SHA-256"):
        Chirps3Source(tmp_path / "a", allow_download=False).daily(ward, 2000, 2001)
    csv, pix = _fake_cache(tmp_path / "b", ward)
    pix.write_text(pix.read_text().replace("3.0", "9.0", 1))
    with pytest.raises(ValueError, match="SHA-256"):
        Chirps3Source(tmp_path / "b", allow_download=False).daily(ward, 2000, 2001)


def test_cache_refuses_changed_geometry(cfg, tmp_path):
    ward = cfg.ward("ward-a")
    _fake_cache(tmp_path, ward)
    moved = ward.model_copy(update={"centroid": ward.centroid.model_copy(update={"lat": -0.5})})
    with pytest.raises(ValueError, match="different geometry"):
        Chirps3Source(tmp_path, allow_download=False).daily(moved, 2000, 2001)


def test_offline_without_cache_fails_clearly(cfg, tmp_path):
    with pytest.raises(FileNotFoundError, match="--dataset chirps3"):
        Chirps3Source(tmp_path, allow_download=False).daily(cfg.ward("ward-a"), 2000, 2001)


def test_make_source_builds_each_dataset(cfg):
    assert isinstance(make_source(cfg, "chirps3", allow_download=False), Chirps3Source)
    assert make_source(cfg, "chirps3", allow_download=False).cache_dir == REPO / "data" / "raw" / "chirps3"


def test_committed_chirps3_inputs_match_their_checksums(cfg):
    src = Chirps3Source(REPO / "data" / "raw" / "chirps3", allow_download=False)
    if not (src.cache_dir / "ward-a.meta.json").exists():
        pytest.skip("CHIRPS v3 cache not committed")
    h = cfg.rainfall.history
    for wid in cfg.pilot.wards:
        assert src.is_cached(cfg.ward(wid), h.start_year, h.end_year)
        m = src.meta(cfg.ward(wid))
        assert m["request"]["disaggregation"] == "rnl" and len(m["request"]["pixels"]) == 4


# ------------------------------------------------------------------ dataset selection
def test_rainfall_source_is_selectable_in_config(config_copy):
    p = config_copy / "pilot.yaml"
    p.write_text(p.read_text(encoding="utf-8").replace("  source: chirps\n", "  source: chirps3\n", 1),
                 encoding="utf-8")
    assert load_config(config_copy).rainfall.source == "chirps3"


def test_monitoring_reads_chirps3_for_seasons_after_2026(cfg):
    r = cfg.rainfall
    assert r.monitoring_chirps3_from_year == 2027
    assert r.monitoring_source(2008) == r.source == "chirps"      # history stays on CHIRPS v2
    assert r.monitoring_source(2026) == "chirps"
    assert r.monitoring_source(2027) == "chirps3"
    assert r.monitoring_source(2030) == "chirps3"
    assert r.model_copy(update={"source": "synthetic"}).monitoring_source(2027) == "synthetic"
    assert r.model_copy(update={"source": "chirps3"}).monitoring_source(2008) == "chirps3"


class _StubSource:
    def __init__(self, name, end="2025-12-31", value=1.0):
        self.name, self.end, self.value = name, end, value

    def daily(self, ward, start_year, end_year):
        d = pd.date_range(f"{start_year}-01-01", f"{end_year}-12-31")
        return pd.Series(self.value, index=d, name="rain_mm")

    def latest(self, ward):
        return pd.Series(self.value, index=pd.date_range("1981-01-01", self.end), name="rain_mm")


def test_ward_inputs_switch_dataset_by_season(cfg, monkeypatch, tmp_path):
    from agroshield_platform import monitoring as mon

    asked = []

    def fake_make_source(c, name=None, allow_download=True, log=print):
        asked.append(name)
        return _StubSource(name, end="2026-09-30", value=3.0) if name == "chirps3" else \
            type("V2", (), {"daily": _StubSource(name).daily})()

    monkeypatch.setattr(mon, "make_source", fake_make_source)
    monkeypatch.setattr(mon, "make_pet_source", lambda c, allow_download=False: _StubSource("pet"))
    fetched = []

    def fake_live(c, ward, year, as_of, allow_download, dataset="chirps"):
        fetched.append(dataset)
        return pd.Series(dtype=float)

    monkeypatch.setattr(mon, "_live_rain", fake_live)

    rain, _ = mon.ward_inputs(cfg, "ward-a", 2008, date(2008, 6, 1))
    assert asked == ["chirps"] and rain.attrs["dataset"] == "chirps" and fetched == []

    asked.clear()
    rain, _ = mon.ward_inputs(cfg, "ward-a", 2027, date(2027, 5, 1))
    assert asked == ["chirps3"] and rain.attrs["dataset"] == "chirps3" and fetched == ["chirps3"]
    assert rain.index.max() == pd.Timestamp("2026-09-30")          # v3 cache past the history window
    assert (rain == 3.0).all()                                     # no CHIRPS v2 value mixed in


def test_live_chirps3_never_calls_climateserv(cfg, monkeypatch, tmp_path):
    from agroshield_platform import monitoring as mon

    def no_v2(*a, **k):
        raise AssertionError("CHIRPS v2 (ClimateSERV) must not be used for a 2027 season")

    class FakeV3:
        def fetch_range(self, ward, start, end):
            assert (start, end) == ("2026-10-01", "2027-04-30")
            return pd.Series(2.5, index=pd.date_range(start, "2027-04-20"), name="rain_mm")

    monkeypatch.setattr(mon, "fetch_chunk", no_v2)
    monkeypatch.setattr(mon, "make_source", lambda c, name=None, allow_download=True, log=print: FakeV3())
    c = cfg.model_copy(update={"root": tmp_path / "config",
                               "monitoring": cfg.monitoring.model_copy(update={"live_cache_dir": "live"})})
    got = mon._live_rain(c, cfg.ward("ward-a"), 2027, date(2027, 4, 30), True, "chirps3")
    assert got.index.max() == pd.Timestamp("2027-04-20")
    assert (tmp_path / "live" / "ward-a_2027.chirps3.csv").exists()
    assert not (tmp_path / "live" / "ward-a_2027.csv").exists()      # never mixed with the v2 live cache


# ------------------------------------------------------------------ follow-up checks (phase 6 completion)
def test_v3_uses_the_same_polygon_as_the_v2_request(cfg):
    """Same polygon-mean definition as CHIRPS v2: the polygon in data/raw/chirps/<ward>.meta.json."""
    for wid in cfg.pilot.wards:
        v2 = json.loads((REPO / "data" / "raw" / "chirps" / f"{wid}.meta.json").read_text())
        assert ward_geometry(cfg.ward(wid)) == v2["request"]["geometry"]


def test_default_config_still_prices_on_chirps_v2(cfg):
    # The reference hashes in docs/overnight/pricing_reference.json assume CHIRPS v2.
    assert cfg.rainfall.source == "chirps"
    assert make_source(cfg, allow_download=False).__class__.__name__ == "ChirpsClimateServSource"


def test_cli_run_accepts_chirps3_as_the_pricing_source(cfg, tmp_path, monkeypatch):
    from agroshield_pricing import cli

    asked = []

    def fake(c, name=None, allow_download=True):
        asked.append(name)
        return Chirps3Source(tmp_path / "empty", allow_download=False)

    monkeypatch.setattr(cli, "make_source", fake)
    with pytest.raises(FileNotFoundError, match="CHIRPS3"):
        cli.main(["--config", str(cfg.root), "run", "--ward", "ward-a", "--source", "chirps3", "--offline",
                  "--out", str(tmp_path / "runs")])
    assert asked == ["chirps3"]


class _Answers:
    """A session that answers HEAD with a scripted list of status codes."""

    def __init__(self, codes, headers=None):
        self.codes, self.headers, self.calls = list(codes), headers or {}, 0

    def head(self, url, **kw):
        self.calls += 1
        return _LocalRangeSession._R(self.codes.pop(0), headers={"Content-Length": "10", **self.headers})


def test_rate_limit_answers_are_waited_out_not_hammered(monkeypatch):
    waits = []
    monkeypatch.setattr(c3.time, "sleep", waits.append)
    s = _Answers([429, 503, 200], headers={"Retry-After": "7"})
    f = c3.HttpRangeFile("http://x/y.nc", s, log=lambda *_: None)
    assert f.size == 10 and s.calls == 3
    assert waits.count(7.0) == 2                       # the server's Retry-After is honoured
    assert waits.count(c3.PAUSE_S) == 3                # and every request waits the polite pause first


def test_unpublished_file_is_reported_as_missing(monkeypatch):
    monkeypatch.setattr(c3.time, "sleep", lambda s: None)
    with pytest.raises(FileNotFoundError, match="not published"):
        c3.HttpRangeFile("http://x/2031.nc", _Answers([404]), log=lambda *_: None)


def test_live_range_skips_a_new_year_not_yet_published(cfg, monkeypatch):
    """January 2027: the 2027 file does not exist yet, so live monitoring keeps Oct-Dec 2026."""
    pytest.importorskip("requests")
    ward = cfg.ward("ward-a")
    pix = c3.pixels_in_polygon(ward_geometry(ward), GRID_LATS, GRID_LONS)
    monkeypatch.setattr(c3, "read_grid", lambda url, session: (GRID_LATS, GRID_LONS))

    def window(url, r_lo, r_hi, c_lo, c_hi, session, log=print):
        if ".2027." in url:
            raise FileNotFoundError(f"not published (HTTP 404): {url}")
        days = pd.date_range("2026-01-01", "2026-12-31")
        arr = np.full((len(days), r_hi - r_lo + 1, c_hi - c_lo + 1), 2.0)
        arr[days > "2026-11-30"] = np.nan                         # December not out yet
        return days, arr, {"url": url, "file_size": 1, "last_modified": None, "requests": 1, "bytes": 1}

    monkeypatch.setattr(c3, "read_year_window", window)
    s = Chirps3Source("unused", log=lambda *_: None).fetch_range(ward, "2026-10-01", "2027-01-20")
    assert s.index.min() == pd.Timestamp("2026-10-01") and s.index.max() == pd.Timestamp("2026-11-30")
    assert (s == 2.0).all() and len(pix) == 4
    # A missing year that is not the last one is still an error.
    with pytest.raises(FileNotFoundError):
        Chirps3Source("unused", log=lambda *_: None)._read_years([ward], [2027, 2026])


def test_committed_chirps3_pixels_are_the_v2_polygon_pixels(cfg):
    d = REPO / "data" / "raw" / "chirps3"
    if not (d / "ward-a.meta.json").exists():
        pytest.skip("CHIRPS v3 cache not committed")
    for wid in cfg.pilot.wards:
        m = json.loads((d / f"{wid}.meta.json").read_text())
        expect = c3.pixels_in_polygon(ward_geometry(cfg.ward(wid)), GRID_LATS, GRID_LONS)
        got = sorted((p["lat"], p["lon"]) for p in m["request"]["pixels"])
        assert got == sorted((round(float(GRID_LATS[r]), 4), round(float(GRID_LONS[c]), 4)) for r, c in expect)
        # The committed polygon mean is the equal-weight mean of the committed pixel columns.
        mean = pd.read_csv(d / f"{wid}.csv", index_col="date")["rain_mm"]
        pix = pd.read_csv(d / f"{wid}.pixels.csv", index_col="date")
        assert np.allclose(pix.mean(axis=1), mean, atol=1e-3)


def test_committed_v3_daily_pixels_sum_to_the_published_v3_monthly_totals():
    """The cached daily pixels add up to the separately published CHIRPS v3.0 monthly GeoTIFFs."""
    d = REPO / "data" / "raw" / "chirps3"
    check = d / "checks" / "v3_monthly_spotcheck.json"
    if not check.exists():
        pytest.skip("CHIRPS v3 monthly spot check not committed")
    meta = json.loads((d / "checks" / "v3_monthly_spotcheck.json.meta.json").read_text())
    assert hashlib.sha256(check.read_bytes()).hexdigest() == meta["sha256"]
    c = json.loads(check.read_text())
    for wid, months in c["wards"].items():
        pix = pd.read_csv(d / f"{wid}.pixels.csv", index_col="date", parse_dates=True)
        order = [f"p{p['row']}_{p['col']}" for p in json.loads((d / f"{wid}.meta.json").read_text())["request"]["pixels"]]
        for ym, v in months.items():
            sums = pix.loc[ym.replace(".", "-"), order].sum()
            assert np.allclose(sums, v["monthly_tif_pixels_mm"], atol=0.02), (wid, ym)


def test_monitoring_on_committed_data_switches_to_v3_for_2027(cfg):
    """End to end on the committed caches: LR 2026 is watched on CHIRPS v2, LR 2027 on CHIRPS v3."""
    from agroshield_platform import monitoring as mon

    d = REPO / "data" / "raw" / "chirps3"
    if not (d / "ward-a.meta.json").exists():
        pytest.skip("CHIRPS v3 cache not committed")
    v2 = pd.read_csv(REPO / "data" / "raw" / "chirps" / "ward-a.csv", index_col="date", parse_dates=True)["rain_mm"]
    v3 = pd.read_csv(d / "ward-a.csv", index_col="date", parse_dates=True)["rain_mm"]
    old, _ = mon.ward_inputs(cfg, "ward-a", 2026, date(2026, 3, 1))
    assert old.attrs["dataset"] == "chirps"
    assert np.allclose(old.loc["1981":"2025"], v2.loc["1981":"2025"])
    new, _ = mon.ward_inputs(cfg, "ward-a", 2027, date(2027, 3, 1))
    assert new.attrs["dataset"] == "chirps3"
    assert np.allclose(new.loc["1981":"2025"], v3.loc["1981":"2025"])      # v3 climatology, not v2
    assert new.index.max() == v3.index.max() > pd.Timestamp("2025-12-31")  # 2026 v3 days already cached


def _live_v3_setup(cfg, tmp_path, monkeypatch, cached_through=None, age_s=None):
    """A live CHIRPS v3 cache for LR 2027 at Ward A, and a fake CHC fetch that counts calls."""
    import os
    import time
    from agroshield_platform import monitoring as mon

    calls = []

    class FakeV3:
        def fetch_range(self, ward, start, end):
            calls.append((start, end))
            return pd.Series(1.0, index=pd.date_range(start, "2027-03-31"), name="rain_mm")

    monkeypatch.setattr(mon, "make_source", lambda c, name=None, allow_download=True, log=print: FakeV3())
    c = cfg.model_copy(update={"root": tmp_path / "config",
                               "monitoring": cfg.monitoring.model_copy(update={"live_cache_dir": "live"})})
    path = tmp_path / "live" / "ward-a_2027.chirps3.csv"
    if cached_through is not None:
        path.parent.mkdir(parents=True)
        days = pd.date_range("2026-10-01", cached_through)
        pd.DataFrame({"date": days.strftime("%Y-%m-%d"), "rain_mm": 2.0}).to_csv(path, index=False)
        if age_s is not None:
            t = time.time() - age_s
            os.utime(path, (t, t))
    return mon, c, calls


def test_live_chirps3_is_not_refetched_when_nothing_newer_can_be_published(cfg, tmp_path, monkeypatch):
    # 20 April 2027: final v3 for April cannot exist yet; March is cached, so no request.
    mon, c, calls = _live_v3_setup(cfg, tmp_path, monkeypatch, cached_through="2027-03-31", age_s=10 * 86400)
    got = mon._live_rain(c, cfg.ward("ward-a"), 2027, date(2027, 4, 20), True, "chirps3")
    assert calls == [] and got.index.max() == pd.Timestamp("2027-03-31")


def test_live_chirps3_waiting_for_a_month_asks_the_server_at_most_daily(cfg, tmp_path, monkeypatch):
    # 10 April 2027, March not out yet. Checked an hour ago: no new request.
    mon, c, calls = _live_v3_setup(cfg, tmp_path, monkeypatch, cached_through="2027-02-28", age_s=3600)
    mon._live_rain(c, cfg.ward("ward-a"), 2027, date(2027, 4, 10), True, "chirps3")
    assert calls == []
    # Checked two days ago: ask again.
    mon, c, calls = _live_v3_setup(cfg, tmp_path / "old", monkeypatch, cached_through="2027-02-28", age_s=2 * 86400)
    got = mon._live_rain(c, cfg.ward("ward-a"), 2027, date(2027, 4, 10), True, "chirps3")
    assert calls == [("2026-10-01", "2027-04-10")] and got.index.max() == pd.Timestamp("2027-03-31")


def test_research_retries_transient_gefs_failures_but_not_404():
    import sys
    sys.path.insert(0, str(REPO / "research"))
    from early_trigger import _retry

    assert not _retry({"gefs_15day_mm": 3.2, "url": "u"})
    assert not _retry({"gefs_15day_mm": None, "url": "u [HTTPError: HTTP Error 404: Not Found]"})
    assert _retry({"gefs_15day_mm": None, "url": "u [HTTPError: HTTP Error 429: Too Many Requests]"})


def test_chirps3_research_pairs_with_the_chirps3_gefs_forecast(monkeypatch):
    import sys
    sys.path.insert(0, str(REPO / "research"))
    import early_trigger as et

    assert et.gefs_for(None) is et.GEFS["chirps"] and et.gefs_for("chirps") is et.GEFS["chirps"]
    g = et.gefs_for("chirps3")
    assert "CHIRPS3-GEFS" in g["product"]
    asked = {}

    def rows(url, rs):
        asked["url"], asked["rows"] = url, rs
        return {r: np.full(7200, 12.0, dtype="<f4") for r in rs}

    monkeypatch.setattr(et, "_tiff_rows", rows)
    mm, url = et.gefs_15day_mm(-0.17, 35.86, pd.Timestamp("2008-04-16"), g)
    assert url.endswith("/chirps3_gefs_global_15day_data/data_20080416_20080416.tif")
    # Global grid, origin 180W 60N: the ward row is (60 + 0.17) / 0.05, the column (180 + 35.86) / 0.05.
    assert asked["rows"] == [1202, 1203, 1204] and mm == 12.0
    # The CHIRPS v2 forecast keeps its Africa grid (origin 20W 40N).
    et.gefs_15day_mm(-0.17, 35.86, pd.Timestamp("2008-04-16"))
    assert asked["rows"] == [802, 803, 804] and "data.2008.107.tif" in asked["url"]
