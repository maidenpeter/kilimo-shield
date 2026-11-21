import pandas as pd
import pytest

from engine import whatsapp_simulator as wa
from engine.unit_economics import PilotInputs, pilot_economics


@pytest.mark.parametrize("vci,expected", [(34.9, "RED"), (35.0, "AMBER"), (36.5, "AMBER"), (40.0, "AMBER"),
                                          (40.1, "GREEN")])
def test_zones(vci, expected):
    assert wa.zone(vci) == expected


def test_network_has_fifteen_masked_verifiers():
    net = wa.verifier_network("njoro")
    assert len(net) == 15
    assert set(net["role"]) == {"Lead farmer", "Agro-vet"}
    assert net["phone_masked"].str.contains(r"\*\*\*").all()


def test_amber_reading_runs_the_full_loop():
    machine = wa.AmberZoneMachine("njoro", 36.5)
    assert machine.state == wa.State.AMBER_HOLD
    message = machine.send_bounties()
    assert "KSh 100" in message and "VCI 36.5%" in message
    assert machine.state == wa.State.VERIFYING
    subs = wa.simulate_submissions("njoro", 36.5)
    assert len(subs) == 12
    machine.receive(subs)
    final = machine.decide()
    share = wa.consensus(subs)
    assert final == (wa.State.RED_UNLOCKED if share >= 0.6 else wa.State.RELEASED)
    assert machine.airtime_cost == 100 * int(subs["inside_ward"].sum())
    assert len(machine.log) == 4


def test_low_amber_vci_unlocks_and_high_amber_vci_is_less_likely_to():
    low = wa.AmberZoneMachine("kangundo", 35.5)
    assert low.run() == wa.State.RED_UNLOCKED
    shares = [wa.consensus(wa.simulate_submissions(k, 39.5)) for k in ("njoro", "kangundo", "kimilili")]
    assert min(shares) < wa.consensus(wa.simulate_submissions("kangundo", 35.5))


def test_red_and_green_skip_verification():
    assert wa.AmberZoneMachine("njoro", 20).state == wa.State.RED_AUTOMATIC
    assert wa.AmberZoneMachine("njoro", 60).state == wa.State.GREEN
    with pytest.raises(ValueError):
        wa.AmberZoneMachine("njoro", 60).send_bounties()


def test_photos_outside_the_ward_do_not_count():
    subs = pd.DataFrame({"inside_ward": [True, True, False], "confirms_stress": [True, False, True]})
    assert wa.consensus(subs) == 0.5


def test_submissions_are_deterministic():
    pd.testing.assert_frame_equal(wa.simulate_submissions("bureti", 37.0), wa.simulate_submissions("bureti", 37.0))


def test_pilot_economics_defaults():
    e = pilot_economics(PilotInputs())
    assert e.gross_premium_season == pytest.approx(15_000 * 60_000 * 0.06)
    assert e.platform_fee_season == pytest.approx(e.gross_premium_season * 0.10)
    assert e.saas_revenue_season == pytest.approx(15_000 * 10 * 6)
    assert e.platform_revenue_season == pytest.approx(e.platform_fee_season + e.saas_revenue_season)
    assert e.resilience_discount_season == pytest.approx(0.05 * e.gross_premium_season)
    assert e.platform_contribution_year == pytest.approx(
        2 * (e.platform_revenue_season - e.verification_cost_season - e.resilience_discount_season))
    # fee plus both net premiums is the whole gross premium, no more
    assert e.platform_fee_season + e.insurer_retained_premium_season + e.reinsurer_ceded_premium_season ==         pytest.approx(e.gross_premium_season)
    assert e.insurer_retained_premium_season == pytest.approx(0.3 * 0.9 * e.gross_premium_season)
    assert e.loss_ratio == pytest.approx(0.03 / 0.06)
