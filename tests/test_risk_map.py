import json

import pytest

from engine.parametric_engine import WARDS, TriggerParams, kpis, load_weather, run_backtest, zone_pricing
from ui import risk_map, theme


@pytest.fixture(scope="module")
def setup():
    params = TriggerParams()
    backtests = {key: run_backtest(load_weather(key)[0], params) for key in WARDS}
    return params, zone_pricing(params), backtests


def test_county_outlines_cover_kenya():
    geo = json.loads(risk_map.GEO_PATH.read_text(encoding="utf-8"))
    names = {f["properties"]["name"] for f in geo["features"]}
    assert len(names) == 47
    assert {ward.county for ward in WARDS.values()} <= names
    for c in risk_map.counties():
        xs = [x for x in c["x"] if x is not None]
        ys = [y for y in c["y"] if y is not None]
        # every county sits inside the drawn window (Turkana's Ilemi Triangle reaches 5.4 N)
        assert risk_map.X_RANGE[0] < min(xs) and max(xs) < risk_map.X_RANGE[1], c["name"]
        assert risk_map.Y_RANGE[0] < min(ys) and max(ys) < risk_map.Y_RANGE[1], c["name"]


def test_ward_figures_match_the_engine(setup):
    params, zones, backtests = setup
    zone = zones.set_index("ward_key")
    for season_keys in (("LR", "SR"), ("LR",), ("SR",)):
        for w in risk_map.ward_figures(zones, backtests, season_keys, params):
            seasons = backtests[w.key][backtests[w.key]["season"].isin(season_keys)]
            k = kpis(seasons, params)
            assert w.burn_pct == pytest.approx(k.burn_cost_pct)
            assert w.paid == k.seasons_paying and w.seasons == k.seasons
            assert w.rate_pct == zone.loc[w.key, "premium_rate_pct"]  # the price always uses both seasons
            assert w.offered == (zone.loc[w.key, "offered"] == "Yes")
            assert w.worst_pct == pytest.approx(100 * seasons["payout_total"].max() / params.sum_insured)
            assert set(w.by_season) == set(seasons["label"])


def test_every_view_draws_and_tells_its_story(setup):
    params, zones, backtests = setup
    figures = risk_map.ward_figures(zones, backtests, ("LR", "SR"), params)
    for view in risk_map.VIEWS:
        fig = risk_map.replay_map(figures, params, "kangundo", "seasons") if view == "Replay" else \
            risk_map.static_map(view, figures, params, "kangundo", "seasons")
        assert len(fig.data) > 47
        text = risk_map.story(view, figures, params, "seasons")
        assert text and "—" not in text
    replay = risk_map.replay_map(figures, params, "kangundo", "seasons")
    assert [f.name for f in replay.frames] == list(figures[0].by_season)
    assert len(replay.frames) == 20


def test_story_names_ties_and_the_blocked_ward(setup):
    params, zones, backtests = setup
    figures = risk_map.ward_figures(zones, backtests, ("LR", "SR"), params)
    most = max(w.paid for w in figures)
    text = risk_map.story("Seasons paid", figures, params, "seasons")
    for w in figures:
        if w.paid == most:
            assert risk_map.short(w.key) in text.split(" would have been paid")[0]
    price = risk_map.story("Price", figures, params, "seasons")
    for w in figures:
        if not w.offered:
            assert risk_map.short(w.key) in price and theme.pct(w.rate_pct, 1) in price


def test_flat_rate_story_shows_the_spread(setup):
    _, zones_target, _ = setup
    params = TriggerParams(pricing_mode="flat", premium_rate=0.06)
    backtests = {key: run_backtest(load_weather(key)[0], params) for key in WARDS}
    figures = risk_map.ward_figures(zone_pricing(params), backtests, ("LR", "SR"), params)
    assert "6.0%" in risk_map.story("Price", figures, params, "seasons")


def test_colour_ramp_ends_and_clamps():
    assert risk_map.colour(0) == risk_map.RAMP[0]
    assert risk_map.colour(1) == risk_map.RAMP[-1]
    assert risk_map.colour(-3) == risk_map.RAMP[0] and risk_map.colour(9) == risk_map.RAMP[-1]


@pytest.mark.parametrize("value,decimals,expected", [
    (82.5, 0, "83%"), (17.85, 1, "17.9%"), (0.125, 2, "0.13%"), (-0.04, 1, "0.0%"), (float("nan"), 1, "n/a"),
])
def test_percentages_round_half_up(value, decimals, expected):
    assert theme.pct(value, decimals) == expected
