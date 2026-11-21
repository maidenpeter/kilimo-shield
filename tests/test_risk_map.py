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
    text = risk_map.story("Frequency", figures, params, "seasons")
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


def fake(key, burn, rate=8.0, offered=True, paid=4, worst=50.0, label="Long rains 2017"):
    return risk_map.WardFigures(key=key, burn_pct=burn, rate_pct=rate, premium_ksh=rate * 600, offered=offered,
                                paid=paid, seasons=20, worst_pct=worst, worst_label=label if worst else "",
                                by_season={"2017 LR": worst})


def test_stories_name_every_tied_ward():
    params = TriggerParams()
    keys = list(WARDS)
    figures = [fake(keys[0], 2.5), fake(keys[1], 2.5), fake(keys[2], 6.0), fake(keys[3], 6.0), fake(keys[4], 2.5)]
    text = risk_map.story("Burn cost", figures, params, "seasons")
    assert text.startswith(f"{risk_map.short(keys[2])} and {risk_map.short(keys[3])} carry the most risk")
    assert f"{risk_map.short(keys[0])}, {risk_map.short(keys[1])} and {risk_map.short(keys[4])} carry the least" in text
    same = [fake(k, 3.0) for k in keys]
    assert risk_map.story("Burn cost", same, params, "seasons").startswith("Every ward has the same burn cost")
    worst = [fake(k, 3.0, worst=7.0) for k in keys]
    assert all(risk_map.short(k) in risk_map.story("Worst season", worst, params, "seasons") for k in keys)


def test_wards_that_never_paid_are_called_that():
    params = TriggerParams()
    keys = list(WARDS)
    figures = [fake(keys[0], 3.0, paid=3), fake(keys[1], 0.0, paid=0, worst=0.0)] + \
        [fake(k, 2.0, paid=2) for k in keys[2:]]
    seasons = risk_map.story("Frequency", figures, params, "short rains")
    assert "was never paid" in seasons and "can cost the same" not in seasons and " in 0" not in seasons
    assert "would never have been paid" in risk_map.story("Burn cost", figures, params, "short rains")


def test_flat_rate_story_respects_the_ceiling_and_burn_costs():
    keys = list(WARDS)
    high = TriggerParams(pricing_mode="flat", premium_rate=0.20)
    blocked = [fake(k, 5.0, rate=20.0, offered=False) for k in keys]
    assert "not offered in any ward" in risk_map.story("Price", blocked, high, "seasons")
    low = TriggerParams(pricing_mode="flat", premium_rate=0.02)
    cheap = [fake(k, 5.0 + i, rate=2.0) for i, k in enumerate(keys)]
    assert "less than every ward's burn cost" in risk_map.story("Price", cheap, low, "seasons")
    mid = TriggerParams(pricing_mode="flat", premium_rate=0.06)
    mixed = [fake(k, b, rate=6.0) for k, b in zip(keys, (5.1, 6.7, 5.9, 5.9, 10.7))]
    text = risk_map.story("Price", mixed, mid, "seasons")
    assert f"{risk_map.short(keys[1])} and {risk_map.short(keys[4])} would pay out more than they collect" in text


def test_replay_draws_the_crosses_and_ranks_by_seasons_paid(setup):
    params, zones, backtests = setup
    figures = risk_map.ward_figures(zones, backtests, ("LR", "SR"), params)
    fig = risk_map.replay_map(figures, params, "kangundo", "seasons")
    assert any(getattr(tr.marker, "symbol", None) == "x-thin" for tr in fig.data)
    paid = [int(row[1].split()[0]) for row in risk_map.ranking("Replay", figures, params, "kangundo")]
    assert paid == sorted(paid, reverse=True)


def test_price_story_when_nothing_or_some_is_offered():
    keys = list(WARDS)
    params = TriggerParams(max_sellable_rate=0.06)
    none = [fake(k, 5.0, rate=8.6 + i, offered=False) for i, k in enumerate(keys)]
    assert "Every ward prices above the 6% ceiling, from 8.6% to 12.6%" in risk_map.story("Price", none, params, "seasons")
    some = [fake(keys[0], 5.0, rate=5.0)] + [fake(k, 5.0, rate=9.0, offered=False) for k in keys[1:]]
    text = risk_map.story("Price", some, params, "seasons")
    assert " and " in text and "would cost" not in text and "in those wards" in text


def test_flat_price_story_uses_both_seasons():
    keys = list(WARDS)
    params = TriggerParams(pricing_mode="flat", premium_rate=0.08)
    # long rains alone would put three wards over 8%; on both seasons only the last one is
    figures = [risk_map.WardFigures(key=k, burn_pct=9.0, rate_pct=8.0, premium_ksh=4_800, offered=True, paid=3,
                                    seasons=10, worst_pct=50.0, worst_label="Long rains 2017", by_season={},
                                    burn_pct_all=b) for k, b in zip(keys, (5.1, 6.7, 5.9, 5.9, 10.7))]
    text = risk_map.story("Price", figures, params, "long rains")
    assert f"{risk_map.short(keys[4])} would pay out more than it collects" in text


def test_replay_story_with_one_ward_a_season():
    keys = list(WARDS)
    figures = [risk_map.WardFigures(key=k, burn_pct=1.0, rate_pct=3.0, premium_ksh=1_800, offered=True, paid=1,
                                    seasons=20, worst_pct=20.0, worst_label="Long rains 2017",
                                    by_season={f"{2015 + i} LR": (20.0 if j == i else 0.0) for i in range(5)})
               for j, k in enumerate(keys)]
    text = risk_map.story("Replay", figures, TriggerParams(), "seasons")
    assert "never saw a widespread drought" in text and "several circles at once" not in text
