import pytest
import yaml
from pydantic import ValidationError

from agroshield_pricing.config import Level, load_config
from agroshield_pricing.phenology import season_windows


def _edit(path, fn):
    data = yaml.safe_load(path.read_text())
    fn(data)
    path.write_text(yaml.safe_dump(data, sort_keys=False))


def test_repo_config_loads(cfg):
    assert cfg.pilot.default_ward in cfg.wards
    assert set(cfg.file_hashes) == {"pilot.yaml", "wards.yaml", "phenology.yaml", "product.yaml"}


def test_placeholders_are_flagged_illustrative(cfg):
    assert all(w.illustrative for w in cfg.wards.values())
    assert cfg.phenology.illustrative and cfg.product.illustrative


def test_v0_weights_must_sum_to_one(config_copy):
    _edit(config_copy / "product.yaml", lambda d: d["layer_b_v0"]["phases"]["flowering"].update(weight=0.9))
    with pytest.raises(ValidationError, match="sum to 1"):
        load_config(config_copy)


def test_v0_override_changes_only_its_ward_and_season(config_copy):
    _edit(config_copy / "product.yaml", lambda d: d["layer_b_v0"].update(overrides={
        "ward-a": {"LR": {"flowering": {"trigger": {"mm": 110}, "exit": {"mm": 35}}}}}))
    c = load_config(config_copy)
    assert c.product.layer_b_v0.terms_for("ward-a", "LR")["flowering"].trigger.mm == 110
    assert c.product.layer_b_v0.terms_for("ward-a", "SR")["flowering"].trigger.mm is None
    assert c.product.layer_b_v0.terms_for("ward-b", "LR")["flowering"].trigger.mm is None


def test_v0_override_of_unknown_phase_is_rejected(config_copy):
    _edit(config_copy / "product.yaml", lambda d: d["layer_b_v0"].update(overrides={
        "ward-a": {"LR": {"tasselling": {"weight": 0.1}}}}))
    with pytest.raises(ValidationError, match="unknown phase"):
        load_config(config_copy)


def test_level_needs_exactly_one_of_mm_or_percentile():
    with pytest.raises(ValidationError):
        Level(mm=10, percentile=20)
    with pytest.raises(ValidationError):
        Level()


def test_switching_ward_is_config_only(config_copy):
    _edit(config_copy / "pilot.yaml", lambda d: d["pilot"].update(default_ward="ward-b"))
    assert load_config(config_copy).pilot.default_ward == "ward-b"


def test_unknown_pilot_ward_is_rejected(config_copy):
    _edit(config_copy / "pilot.yaml", lambda d: d["pilot"].update(wards=["ward-a", "ward-z"]))
    with pytest.raises(ValidationError, match="ward-z"):
        load_config(config_copy)


def test_phase_windows_are_contiguous_and_cross_new_year(cfg):
    w = season_windows(cfg.calendar("ward-a", "SR"), 2020)
    for a, b in zip(w, w[1:]):
        assert (b.start - a.end).days == 1
    assert w[0].start.year == 2020 and w[-1].end.year == 2021
    assert sum(x.days for x in w) == sum(p.days for p in cfg.calendar("ward-a", "SR").phases)


# ------------------------------------------------------------------ v1 WRSI terms
def test_wrsi_trigger_must_be_above_exit(config_copy):
    _edit(config_copy / "product.yaml", lambda d: d["layer_b"].update(trigger_wrsi=50, exit_wrsi=60))
    with pytest.raises(ValidationError, match="above exit"):
        load_config(config_copy)


def test_kc_curve_must_span_the_season(config_copy):
    _edit(config_copy / "product.yaml", lambda d: d["layer_b"]["kc"].update(points_pct=[0, 50, 90]))
    with pytest.raises(ValidationError):
        load_config(config_copy)


def test_wrsi_override_applies_to_one_ward_and_season(config_copy):
    _edit(config_copy / "product.yaml", lambda d: d["layer_b"].update(overrides={"ward-b": {"LR": {"trigger_wrsi": 90}}}))
    c = load_config(config_copy)
    assert c.product.layer_b.terms_for("ward-b", "LR")["trigger_wrsi"] == 90
    assert c.product.layer_b.terms_for("ward-a", "LR")["trigger_wrsi"] == 80


def test_target_band_from_return_periods(cfg):
    lo, hi = cfg.product.target.frequency_band
    assert lo == pytest.approx(1 / 7) and hi == pytest.approx(1 / 5)


def test_pilot_scope_is_long_rains_only(cfg):
    assert all(cfg.ward(w).seasons == ["LR"] for w in cfg.pilot.wards)


def test_growing_period_in_dekads(cfg):
    assert cfg.calendar("ward-a", "LR").lgp_dekads == 13
    assert cfg.calendar("ward-b", "LR").lgp_dekads == 18


# ------------------------------------------------------------------ 2c: targets and events per ward
def test_each_ward_has_its_own_target_band(cfg):
    t = cfg.product.target
    assert t.band_for("ward-a") == pytest.approx((1 / 7, 1 / 5))
    assert t.band_for("ward-b") == pytest.approx((1 / 12, 1 / 8))


def test_1984_is_required_at_ward_a_only(cfg):
    e = next(e for e in cfg.product.event_tests if e.year == 1984)
    assert e.required_for == ["ward-a"]


def test_flowering_component_is_off_by_default(cfg):
    assert cfg.product.layer_b.flowering.enabled is False


def test_flowering_exit_must_exceed_trigger(config_copy):
    _edit(config_copy / "product.yaml", lambda d: d["layer_b"]["flowering"].update(trigger=30, exit=20))
    with pytest.raises(ValidationError, match="exit must exceed trigger"):
        load_config(config_copy)


def test_layer_a_threshold_must_beat_climatology(config_copy):
    _edit(config_copy / "product.yaml", lambda d: d["layer_a"].update(trigger_prob_below_normal=0.3))
    with pytest.raises(ValidationError):
        load_config(config_copy)


def test_long_rains_forecast_issued_before_the_season(config_copy):
    _edit(config_copy / "product.yaml", lambda d: d["layer_a"].update(issue_month={"LR": 4}))
    with pytest.raises(ValidationError, match="issued before"):
        load_config(config_copy)


def test_resilience_cap_and_subsidy_terms(cfg):
    assert cfg.product.resilience.discount_cap == 0.15
    assert cfg.product.subsidy.government_share == 0.5
    assert (cfg.product.subsidy.eligible_acres.min, cfg.product.subsidy.eligible_acres.max) == (0.5, 20)
    ids = {p.id for p in cfg.product.resilience.points}
    assert {"certified_seed_verified", "irrigation_full", "irrigation_partial", "sacco_good_standing"} <= ids
