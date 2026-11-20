"""Recheck the money rules on many random product settings, not just the defaults."""
from dataclasses import replace

import numpy as np
import pytest

from data import seed_generator as sg
from engine import parametric_engine as pe
from engine import recon_engine as rec

RNG = np.random.default_rng(360)
WEATHER = {key: pe.load_weather(key)[0] for key in pe.WARDS}


def random_params(rng) -> pe.TriggerParams:
    trigger = float(rng.uniform(20, 45))
    return replace(
        pe.TriggerParams(),
        sum_insured=float(rng.choice([30_000, 60_000, 100_000])),
        sm_trigger=trigger, sm_exit=float(rng.uniform(0, trigger - 2)),
        fodder_gate=float(rng.choice([0.0, 0.25, 0.5, 0.75])), ndvi_trigger=float(rng.uniform(10, 50)),
        aggregate_cap_share=float(rng.uniform(0.4, 1.0)),
        rain10_mode=str(rng.choice(["percentile", "fixed"])), rain10_percentile=float(rng.uniform(75, 98)),
        rain10_trigger_mm=float(rng.uniform(100, 300)), heat_temp_c=float(rng.uniform(27, 34)),
        heat_days=int(rng.integers(3, 12)), capacity_mm=float(rng.uniform(60, 200)),
        pricing_mode=str(rng.choice(["target", "flat"])), target_loss_ratio=float(rng.uniform(0.5, 0.7)),
        premium_rate=float(rng.uniform(0.02, 0.2)), subsidy_share=float(rng.uniform(0, 0.7)),
        verifier_accuracy=float(rng.uniform(0.5, 1.0)),
    )


CASES = [(random_params(RNG), str(RNG.choice(list(pe.WARDS)))) for _ in range(30)]


@pytest.mark.parametrize("params,ward", CASES, ids=[f"case{i}" for i in range(len(CASES))])
def test_payout_rules_hold(params, ward):
    s = pe.run_backtest(WEATHER[ward], params)
    eps = 1e-6
    assert len(s) == 20
    assert (s[["payout_a", "payout_b", "payout_c"]] >= -eps).all().all()
    assert (s["payout_a"] <= params.crop_allocation + eps).all()
    assert (s["payout_b"] <= params.fodder_allocation + eps).all()
    assert (s["payout_c"] <= params.health_payout + eps).all()
    assert (s["payout_total"] <= params.aggregate_cap + eps).all()
    assert (s["payout_total"] <= s["payout_uncapped"] + eps).all()
    assert np.allclose(s["payout_total"], s[["payout_a", "payout_b", "payout_c"]].sum(axis=1))
    # where the cap bites, every layer shrinks by the same factor
    capped = s[s["payout_uncapped"] > params.aggregate_cap + eps]
    assert np.allclose(capped["payout_total"], params.aggregate_cap)
    # fodder never pays without a crop payout at the gate
    uncapped_a = s["payout_a"] * (s["payout_uncapped"] / s["payout_total"].where(s["payout_total"] > 0)).fillna(1)
    assert ((s["payout_b"] > eps) <= (uncapped_a >= params.fodder_gate * params.crop_allocation - 1e-3)).all()
    assert ((s["payout_b"] > eps) <= (s["ndvi_pct"] < params.ndvi_trigger)).all()
    # crop pays exactly when the weighted index is under the trigger
    assert ((s["payout_a"] > eps) == (s["sm_weighted"] < params.sm_trigger)).all()

    k = pe.kpis(s, params)
    assert k.burn_cost_pct == pytest.approx(100 * s["payout_total"].mean() / params.sum_insured)
    assert k.premium_ksh == pytest.approx(params.sum_insured * k.premium_rate_pct / 100)
    assert k.farmer_premium_ksh == pytest.approx(k.premium_ksh * (1 - params.subsidy_share))
    if params.pricing_mode == "target" and k.burn_cost_pct > 0:
        assert k.loss_ratio_pct <= 100 * params.target_loss_ratio + 1e-6
        # rounding up to 0.1% never moves the rate by more than 0.1 point
        assert k.premium_rate_pct - k.burn_cost_pct / params.target_loss_ratio < 0.1 + 1e-9
    else:
        assert k.premium_rate_pct == pytest.approx(100 * params.premium_rate if params.pricing_mode == "flat" else 0)
    assert k.offered == (k.premium_rate_pct <= 100 * params.max_sellable_rate + 1e-9)
    b = k.basis
    assert 0 <= b.amber_seasons <= 20
    assert b.mismatches_verified <= b.mismatches_index + b.amber_seasons * (1 - params.verifier_accuracy) + 1e-9


@pytest.mark.parametrize("seed", [1, 7, 2027, 99])
def test_money_is_conserved_in_reconciliation(seed):
    premiums = {"njoro": 5_100.0, "imenti_north": 6_780.0, "kangundo": 5_880.0, "kimilili": 5_940.0}
    data = sg.generate_all(seed=seed, premium_by_ward={**premiums, "bureti": 10_740.0})
    r = rec.reconcile(data.statement, data.members, premiums)
    credited = r.ledger[~r.ledger["match_method"].isin(rec.SUSPENSE_METHODS + (rec.DUPLICATE,))]
    alloc = credited[["to_premium", "to_interest", "to_principal", "to_savings"]].sum(axis=1)
    assert np.allclose(alloc, credited["paid_in_ksh"])
    held = r.ledger[r.ledger["match_method"].isin(rec.SUSPENSE_METHODS + (rec.DUPLICATE,))]
    assert held[["to_premium", "to_interest", "to_principal", "to_savings"]].to_numpy().sum() == 0
    m = r.members
    assert (m["to_premium"] <= m["premium_due"] + 1e-6).all()
    assert (m["to_interest"] <= m["overdue_interest"] + 1e-6).all()
    assert (m["to_principal"] <= m["loan_balance"] + 1e-6).all()
    assert (m["loan_after"] >= -1e-6).all() and (m["interest_after"] >= -1e-6).all()
    # money only reaches savings once premium, interest and principal are all clear
    saved = m[m["to_savings"] > 0]
    assert (saved["to_premium"] >= saved["premium_due"] - 1e-6).all()
    assert (saved["interest_after"] <= 1e-6).all() and (saved["loan_after"] <= 1e-6).all()
    # member totals match the ledger
    assert m["paid_in_ksh"].sum() == pytest.approx(credited["paid_in_ksh"].sum())
    acc = rec.accuracy(r, data.truth)
    assert acc["wrong_member"] == 0 and acc["recall"] >= 0.97
    split = rec.claim_split(m, list(premiums), 25_000, 0.7)
    assert np.allclose(split["to_farmer_b2c_ksh"] + split["to_sacco_loan_ksh"], 25_000)
    assert (split["loan_owed_after_ksh"] >= -1e-6).all()
