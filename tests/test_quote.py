from dataclasses import replace
from datetime import date

import pytest

from engine import parametric_engine as pe
from engine import quote as qt

P = pe.TriggerParams()
WEATHER = {key: pe.load_weather(key)[0] for key in pe.WARDS}
ZONES = pe.zone_pricing(P).set_index("ward_key")


def make(ward="njoro", season="LR", acres=2.0, cows=2, practices=None, params=P, offered=True):
    return qt.quote(WEATHER[ward], params, ward_key=ward, season=season, acres=acres, cows=cows,
                    practices=practices, ward_offered=offered)


@pytest.mark.parametrize("ward", [k for k in pe.WARDS if ZONES.loc[k, "offered"] == "Yes"])
def test_standard_farm_matches_zone_pricing(ward):
    q = make(ward)
    assert q.sum_insured == 60_000
    assert q.cover == {"crop": 30_000, "fodder": 20_000, "vet": 10_000}
    assert q.premium_rate * 100 == pytest.approx(ZONES.loc[ward, "premium_rate_pct"])
    assert q.gross_premium == pytest.approx(ZONES.loc[ward, "premium_ksh"])
    assert q.seasonal_cap == pytest.approx(50_000)


def test_ward_not_offered_gets_no_quote():
    with pytest.raises(qt.QuoteError, match="not offered"):
        make("bureti", offered=False)


@pytest.mark.parametrize("acres,cows", [(0, 0), (0.25, 0), (21, 2), (2, 21), (-1, 2)])
def test_impossible_farms_are_refused(acres, cows):
    with pytest.raises(qt.QuoteError):
        make(acres=acres, cows=cows)


@pytest.mark.parametrize("acres,cows", [(0.5, 0), (1, 0), (0, 1), (3, 5), (20, 20), (7.5, 1)])
def test_money_adds_up(acres, cows):
    q = make(acres=acres, cows=cows, practices={"certified_seed": True, "sacco_good_standing": True},
             params=replace(P, subsidy_share=0.5))
    assert q.sum_insured == acres * 15_000 + cows * 15_000
    assert q.gross_premium == round(q.sum_insured * q.premium_rate)
    assert q.government_share + q.farmer_share == q.gross_premium
    assert q.farmer_share - q.discount == q.farmer_pays
    # the insurer always receives the full gross premium
    assert q.farmer_pays + q.government_share + q.discount == q.gross_premium
    assert q.per_day_checkoff == pytest.approx(q.farmer_pays / 90)
    # target pricing: the farm's own loss ratio never exceeds the target
    assert q.burn_cost_rate / q.premium_rate <= P.target_loss_ratio + 1e-9


def test_subsidy_only_inside_the_acre_band():
    with_subsidy = replace(P, subsidy_share=0.5)
    inside = make(acres=2, params=with_subsidy)
    assert inside.subsidy_eligible and inside.government_share == round(inside.gross_premium * 0.5)
    dairy_only = make(acres=0, cows=3, params=with_subsidy)
    assert not dairy_only.subsidy_eligible and dairy_only.government_share == 0
    assert make(acres=2).government_share == 0  # default: no subsidy agreed


def test_resilience_points_cap_and_groups():
    points, counted = qt.resilience({"irrigation_full": True, "irrigation_partial": True})
    assert points == 3 and len(counted) == 1  # only the better irrigation item counts
    everything = {item.id: True for item in qt.RESILIENCE_ITEMS}
    points, _ = qt.resilience(everything)
    assert points == 5 + 4 + 3 + 3 + 2
    q = make(practices=everything)
    assert q.discount_rate == qt.DISCOUNT_CAP  # 17 points, capped at 15%
    assert q.discount == round(q.farmer_share * 0.15)
    assert q.discount_exceeds_fee  # 15% of the farmer's share is more than the 10% platform fee
    with pytest.raises(qt.QuoteError):
        qt.resilience({"bribe": True})


def test_discount_never_touches_the_risk_price():
    plain = make()
    discounted = make(practices={"certified_seed": True})
    assert discounted.gross_premium == plain.gross_premium
    assert discounted.premium_rate == plain.premium_rate
    assert discounted.farmer_pays < plain.farmer_pays


def test_dates_follow_the_14_day_rule():
    lr = make(season="LR")
    assert (lr.enrolment_closes, lr.cover_starts) == (date(2027, 2, 15), date(2027, 3, 1))
    sr = make(season="SR")
    assert (sr.enrolment_closes, sr.cover_starts) == (date(2027, 9, 17), date(2027, 10, 1))


def test_history_matches_the_backtest():
    q = make(season="SR")
    seasons = pe.run_backtest(WEATHER["njoro"], qt.farm_params(P, 2, 2))
    sr = seasons[seasons["season"] == "SR"].reset_index(drop=True)
    assert list(q.history["payout_total"]) == pytest.approx(list(sr["payout_total"]))
    assert len(q.history) == 10


def test_quote_id_is_stable_and_specific():
    assert make().quote_id == make().quote_id
    assert make().quote_id != make(acres=3).quote_id
    assert make().quote_id.startswith("SS360-Q-")


def test_quote_text():
    text = qt.quote_text(make(practices={"certified_seed": True}))
    assert "ILLUSTRATIVE" in text and "Partner insurer (to be named)" in text
    assert "15 February 2027" in text and "Farmer pays" in text
    assert "—" not in text
