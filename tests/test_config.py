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


def test_weights_must_sum_to_one(config_copy):
    _edit(config_copy / "product.yaml", lambda d: d["layer_b"]["phases"]["flowering"].update(weight=0.9))
    with pytest.raises(ValidationError, match="sum to 1"):
        load_config(config_copy)


def test_override_changes_only_its_ward_and_season(config_copy):
    _edit(config_copy / "product.yaml", lambda d: d["layer_b"].update(overrides={
        "ward-a": {"LR": {"flowering": {"trigger": {"mm": 110}, "exit": {"mm": 35}}}}}))
    c = load_config(config_copy)
    assert c.product.layer_b.terms_for("ward-a", "LR")["flowering"].trigger.mm == 110
    assert c.product.layer_b.terms_for("ward-a", "SR")["flowering"].trigger.mm is None
    assert c.product.layer_b.terms_for("ward-b", "LR")["flowering"].trigger.mm is None


def test_override_of_unknown_phase_is_rejected(config_copy):
    _edit(config_copy / "product.yaml", lambda d: d["layer_b"].update(overrides={
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
