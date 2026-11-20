"""Pilot unit economics for the platform (calculating agent and SACCO reconciliation SaaS). ILLUSTRATIVE.

The platform never carries insurance risk: premium belongs to the partner insurer, which keeps a share and cedes
the rest to the treaty reinsurer. The platform earns a calculating-agent fee out of gross premium (borne by insurer
and reinsurer in proportion to their shares) and a per-member reconciliation fee from the SACCO. So gross premium =
platform fee + insurer's net premium + reinsurer's net premium, exactly.
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
    amber_checks_per_season: int = 3         # ward verifications expected per season (an assumption)
    photos_per_check: int = 12
    bounty_ksh: float = 100.0


@dataclass(frozen=True)
class PilotEconomics:
    gross_premium_season: float
    expected_claims_season: float
    platform_fee_season: float
    saas_revenue_season: float
    platform_revenue_season: float           # fee plus SACCO fee
    verification_cost_season: float          # airtime bounties the platform pays
    platform_contribution_season: float      # revenue less airtime
    platform_contribution_year: float
    insurer_retained_premium_season: float   # insurer's share of premium, net of its share of the platform fee
    reinsurer_ceded_premium_season: float    # reinsurer's share, net of its share of the platform fee
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
    contribution = fee + saas_season - verification
    retained = 1.0 - inputs.reinsurer_share
    net = gwp - fee
    return PilotEconomics(
        gross_premium_season=gwp, expected_claims_season=claims, platform_fee_season=fee,
        saas_revenue_season=saas_season, platform_revenue_season=fee + saas_season,
        verification_cost_season=verification, platform_contribution_season=contribution,
        platform_contribution_year=contribution * SEASONS_PER_YEAR,
        insurer_retained_premium_season=net * retained, reinsurer_ceded_premium_season=net * inputs.reinsurer_share,
        insurer_expected_claims_season=claims * retained, reinsurer_expected_claims_season=claims * inputs.reinsurer_share,
        loss_ratio=claims / gwp if gwp else 0.0,
    )
