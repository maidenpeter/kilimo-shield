"""Pilot unit economics for the platform (calculating agent and SACCO reconciliation SaaS). ILLUSTRATIVE.

The platform never carries insurance risk: premium belongs to the partner insurer, which keeps a share and cedes
the rest to the treaty reinsurer. The platform earns a calculating-agent fee on gross premium and a per-member
reconciliation fee from the SACCO.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

SEASONS_PER_YEAR = 2
MONTHS_PER_YEAR = 12


@dataclass(frozen=True)
class PilotInputs:
    farms: int = 15_000
    avg_sum_insured: float = 60_000.0
    premium_rate: float = 0.06               # per season
    agent_fee_rate: float = 0.10             # platform calculating-agent fee, share of gross premium
    saas_fee_member_month: float = 10.0      # SACCO reconciliation fee, KSh per member per month
    burn_cost_rate: float = 0.03             # expected payouts per season, share of sum insured (from the backtest)
    reinsurer_share: float = 0.70            # quota share ceded to the treaty reinsurer
    amber_checks_per_season: int = 3         # ward verifications expected per season
    photos_per_check: int = 12
    bounty_ksh: float = 100.0


@dataclass(frozen=True)
class PilotEconomics:
    gross_premium_season: float
    expected_claims_season: float
    platform_fee_season: float
    saas_revenue_season: float
    verification_cost_season: float
    founder_revenue_season: float
    founder_revenue_year: float
    insurer_retained_premium_season: float
    reinsurer_ceded_premium_season: float
    insurer_expected_claims_season: float
    reinsurer_expected_claims_season: float
    loss_ratio: float

    def as_dict(self) -> dict:
        return asdict(self)


def pilot_economics(inputs: PilotInputs = PilotInputs()) -> PilotEconomics:
    sum_insured = inputs.farms * inputs.avg_sum_insured
    gwp = sum_insured * inputs.premium_rate
    claims = sum_insured * inputs.burn_cost_rate
    fee = gwp * inputs.agent_fee_rate
    saas_season = inputs.farms * inputs.saas_fee_member_month * MONTHS_PER_YEAR / SEASONS_PER_YEAR
    verification = inputs.amber_checks_per_season * inputs.photos_per_check * inputs.bounty_ksh
    founder_season = fee + saas_season - verification
    retained = 1.0 - inputs.reinsurer_share
    return PilotEconomics(
        gross_premium_season=gwp, expected_claims_season=claims, platform_fee_season=fee,
        saas_revenue_season=saas_season, verification_cost_season=verification,
        founder_revenue_season=founder_season, founder_revenue_year=founder_season * SEASONS_PER_YEAR,
        insurer_retained_premium_season=gwp * retained, reinsurer_ceded_premium_season=gwp * inputs.reinsurer_share,
        insurer_expected_claims_season=claims * retained, reinsurer_expected_claims_season=claims * inputs.reinsurer_share,
        loss_ratio=claims / gwp if gwp else 0.0,
    )
