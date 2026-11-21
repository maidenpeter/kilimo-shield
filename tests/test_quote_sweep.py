"""Random farms, random product settings: the quote's money rules must hold every time."""
from dataclasses import replace
from decimal import Decimal

import numpy as np
import pytest

from engine import parametric_engine as pe
from engine import quote as qt

RNG = np.random.default_rng(2027)
WEATHER = {key: pe.load_weather(key)[0] for key in pe.WARDS}


def random_case(rng):
    params = replace(
        pe.TriggerParams(),
        sm_trigger=float(rng.uniform(22, 40)), ndvi_trigger=float(rng.uniform(10, 45)),
        fodder_gate=float(rng.choice([0.0, 0.5, 0.75])), aggregate_cap_share=float(rng.uniform(0.5, 1.0)),
        pricing_mode=str(rng.choice(["target", "flat"])), target_loss_ratio=float(rng.uniform(0.5, 0.7)),
        premium_rate=float(rng.uniform(0.03, 0.15)), subsidy_share=float(rng.choice([0.0, 0.3, 0.5, 0.7])),
    )
    acres = float(rng.choice([0, 0.5, 1, 2, 3.5, 7.25, 12, 20]))
    cows = int(rng.choice([0, 1, 2, 3, 8, 20]))
    if acres < 0.5 and cows == 0:
        cows = 1
    practices = {item.id: bool(rng.random() < 0.4) for item in qt.RESILIENCE_ITEMS}
    return params, str(rng.choice(list(pe.WARDS))), str(rng.choice(["LR", "SR"])), acres, cows, practices


CASES = [random_case(RNG) for _ in range(60)]


@pytest.mark.parametrize("params,ward,season,acres,cows,practices", CASES, ids=[f"q{i}" for i in range(len(CASES))])
def test_quote_money_rules(params, ward, season, acres, cows, practices):
    try:
        q = qt.quote(WEATHER[ward], params, ward_key=ward, season=season, acres=acres, cows=cows, practices=practices)
    except qt.FarmAboveCeiling as err:
        assert err.rate > params.max_sellable_rate
        return
    assert q.sum_insured == acres * 15_000 + cows * 15_000
    assert q.seasonal_cap == pytest.approx(q.sum_insured * params.aggregate_cap_share)
    assert 0 <= q.farmer_pays <= q.farmer_share <= q.gross_premium
    assert q.government_share + q.farmer_share == q.gross_premium
    assert q.farmer_pays + q.government_share + q.discount == q.gross_premium
    assert q.government_share == (qt.money(Decimal(q.gross_premium) * Decimal(repr(params.subsidy_share)))
                                  if 0.5 <= acres <= 20 else 0)
    points, _ = qt.resilience(practices)
    assert q.discount_rate == min(0.15, points * 0.01)
    assert (q.history["payout_total"] <= q.seasonal_cap + 1e-6).all()
    assert len(q.history) == 10 and set(q.history["season"]) == {season}
    if params.pricing_mode == "target":
        assert q.premium_rate * 1000 == pytest.approx(round(q.premium_rate * 1000))  # whole tenths of a percent
        assert q.burn_cost_rate <= q.premium_rate * params.target_loss_ratio + 1e-12
    else:
        assert q.premium_rate == params.premium_rate
