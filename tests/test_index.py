import numpy as np
import pandas as pd
import pytest

from agroshield_pricing.config import Level, PhaseTerms
from agroshield_pricing.index import (effective_daily, payout_fraction, phase_rainfall, resolve_terms,
                                      season_payouts)


# ---------------------------------------------------------------- payout function
@pytest.mark.parametrize("rain, expected", [
    (150, 0.0),    # well above trigger
    (100, 0.0),    # exactly at trigger pays nothing
    (75, 0.5),     # halfway between trigger and exit
    (60, 0.8),
    (50, 1.0),     # exactly at exit pays in full
    (0, 1.0),      # below exit stays at full payout
])
def test_payout_fraction_is_linear_between_trigger_and_exit(rain, expected):
    assert payout_fraction(rain, trigger_mm=100, exit_mm=50) == pytest.approx(expected)


def test_payout_fraction_vectorised():
    out = payout_fraction(np.array([120, 90, 40]), 100, 50)
    assert np.allclose(out, [0.0, 0.2, 1.0])


@pytest.mark.parametrize("trigger, exit_", [(50, 50), (40, 50)])
def test_trigger_must_be_above_exit(trigger, exit_):
    with pytest.raises(ValueError):
        payout_fraction(30, trigger, exit_)


def test_payout_is_monotone_in_rainfall():
    rain = np.linspace(0, 200, 401)
    f = payout_fraction(rain, 120, 30)
    assert np.all(np.diff(f) <= 1e-12)


# ---------------------------------------------------------------- daily clipping
def test_effective_daily_drops_drizzle_and_caps_storms():
    s = pd.Series([0.5, 1.0, 30.0, 120.0])
    assert effective_daily(s, 1.0, 60.0).tolist() == [0.0, 1.0, 30.0, 60.0]


# ---------------------------------------------------------------- season payout
def _resolved(**phases):
    terms = {p: PhaseTerms(weight=w, trigger=Level(mm=t), exit=Level(mm=e)) for p, (w, t, e) in phases.items()}
    dummy = pd.DataFrame({p: [0.0] * 12 for p in phases}, index=range(2000, 2012))
    return resolve_terms(terms, dummy, (2000, 2011))


def test_season_payout_is_weighted_sum_of_phases():
    resolved = _resolved(germination=(0.3, 100, 50), flowering=(0.7, 80, 20))
    rain = pd.DataFrame({"germination": [75.0, 200.0, 0.0], "flowering": [200.0, 50.0, 0.0]},
                        index=[2001, 2002, 2003])
    out = season_payouts(rain, resolved)
    assert out.loc[2001, "payout_frac"] == pytest.approx(0.3 * 0.5)   # germination half
    assert out.loc[2002, "payout_frac"] == pytest.approx(0.7 * 0.5)   # flowering half
    assert out.loc[2003, "payout_frac"] == pytest.approx(1.0)         # total failure pays sum insured


def test_resolve_percentile_levels_from_history():
    hist = pd.DataFrame({"flowering": np.arange(1.0, 41.0)}, index=range(1981, 2021))
    terms = {"flowering": PhaseTerms(weight=1.0, trigger=Level(percentile=50), exit=Level(percentile=0))}
    r = resolve_terms(terms, hist, (1981, 2020))["flowering"]
    assert r.trigger_mm == pytest.approx(20.5)
    assert r.exit_mm == pytest.approx(1.0)
    assert r.trigger_basis == "P50 of 1981-2020"


def test_resolve_refuses_too_few_calibration_seasons():
    hist = pd.DataFrame({"flowering": np.arange(5.0)}, index=range(2000, 2005))
    terms = {"flowering": PhaseTerms(weight=1.0, trigger=Level(percentile=50), exit=Level(percentile=0))}
    with pytest.raises(ValueError, match="calibration seasons"):
        resolve_terms(terms, hist, (2000, 2004))


def test_phase_rainfall_sums_each_window(cfg):
    cal = cfg.calendar("ward-a", "LR")
    days = pd.date_range("2010-01-01", "2010-12-31")
    rain = pd.Series(1.0, index=days)                       # 1 mm every day
    totals = phase_rainfall(rain, cal, [2010])
    for phase in cal.phases:
        assert totals.loc[2010, phase.name] == pytest.approx(phase.days)
