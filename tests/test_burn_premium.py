import numpy as np
import pandas as pd
import pytest

from agroshield_pricing.burn import burn_cost, exceedance_curve
from agroshield_pricing.config import Premium, SumInsured
from agroshield_pricing.premium import gross_premium


def _losses():
    # 20 seasons: 16 with no payout, then 0.1, 0.2, 0.4, 1.0
    return pd.Series([0.0] * 16 + [0.1, 0.2, 0.4, 1.0], index=range(2000, 2020))


def test_burn_cost_statistics():
    x = _losses()
    b = burn_cost(x)
    assert b["seasons"] == 20
    assert b["payout_seasons"] == 4
    assert b["payout_frequency"] == pytest.approx(0.2)
    assert b["expected_loss"] == pytest.approx(1.7 / 20)
    assert b["std_dev"] == pytest.approx(np.std(x, ddof=1))
    assert b["loss_1_in_10"] == pytest.approx(np.quantile(x, 0.90))
    assert b["loss_1_in_20"] == pytest.approx(np.quantile(x, 0.95))
    assert b["max_loss"] == 1.0
    assert b["worst_seasons"][0] == {"year": 2019, "payout_frac": 1.0}


def test_burn_cost_meaningful_frequency_ignores_token_payouts():
    b = burn_cost(_losses(), meaningful=0.15)
    assert b["meaningful_payout_frequency"] == pytest.approx(3 / 20)


def test_burn_cost_needs_history():
    with pytest.raises(ValueError):
        burn_cost(pd.Series([0.1], index=[2000]))


def test_exceedance_curve_is_descending():
    pts = exceedance_curve(_losses())
    losses = [p["loss"] for p in pts]
    assert losses == sorted(losses, reverse=True)
    assert pts[0]["exceedance"] < pts[-1]["exceedance"]


def _premium(method="std_dev", factor=0.25, percentile=None, loadings=None):
    return Premium(risk_margin={"method": method, "factor": factor, "percentile": percentile},
                   loadings=loadings or {"expense": 0.10, "platform": 0.10})


SI = SumInsured(options_kes_per_acre=[10000], default_kes_per_acre=10000)


def test_gross_premium_build_up():
    x = _losses()
    b = burn_cost(x)
    g = gross_premium(b, x.to_numpy(), _premium(), SI)
    el, rm = b["expected_loss"], 0.25 * b["std_dev"]
    assert g["pure_premium_rate"] == pytest.approx(el + rm)
    assert g["gross_rate"] == pytest.approx((el + rm) / 0.8)
    # loadings are shares of gross, so they add back up to gross
    assert g["pure_premium_rate"] + sum(g["loadings_rate"].values()) == pytest.approx(g["gross_rate"])
    assert g["per_acre"][0]["gross_premium_kes"] == pytest.approx(round(g["gross_rate"] * 10000, 2))


def test_gross_premium_tail_risk_margin():
    x = _losses()
    b = burn_cost(x)
    g = gross_premium(b, x.to_numpy(), _premium("tail", 0.5, 95), SI)
    assert g["risk_margin_rate"] == pytest.approx(0.5 * (np.quantile(x, 0.95) - b["expected_loss"]))


def test_loadings_must_leave_room_for_risk():
    with pytest.raises(ValueError):
        _premium(loadings={"expense": 0.6, "margin": 0.4})
