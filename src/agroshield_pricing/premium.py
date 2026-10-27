"""Gross premium build-up from the burn cost.

    pure premium = expected loss + risk margin
    gross        = pure / (1 - sum of loadings)    (loadings are shares of gross)

All rates are shares of sum insured. Every input comes from product.yaml.
Subsidy and the Resilience discount are applied later, to the farmer share only.
"""
from __future__ import annotations

import numpy as np

from .config import Premium, SumInsured


def risk_margin(burn: dict, losses, method: str, factor: float, percentile: float | None) -> float:
    if method == "std_dev":
        return factor * burn["std_dev"]
    if method == "tail":
        tail = float(np.quantile(losses, percentile / 100))
        return factor * max(0.0, tail - burn["expected_loss"])
    raise ValueError(f"unknown risk margin method {method!r}")


def gross_premium(burn: dict, losses, premium: Premium, sum_insured: SumInsured) -> dict:
    rm_cfg = premium.risk_margin
    el = burn["expected_loss"]
    rm = risk_margin(burn, losses, rm_cfg.method, rm_cfg.factor, rm_cfg.percentile)
    pure = el + rm
    load_total = sum(premium.loadings.values())
    gross = pure / (1 - load_total)
    loadings = {k: gross * v for k, v in premium.loadings.items()}

    def kes(rate: float, si: float) -> float:
        return round(rate * si, 2)

    per_option = []
    for si in sum_insured.options_kes_per_acre:
        per_option.append({
            "sum_insured_kes_per_acre": si,
            "expected_loss_kes": kes(el, si),
            "risk_margin_kes": kes(rm, si),
            "loadings_kes": {k: kes(v, si) for k, v in loadings.items()},
            "gross_premium_kes": kes(gross, si),
        })
    return {
        "expected_loss_rate": el,
        "risk_margin_rate": rm,
        "risk_margin_method": rm_cfg.model_dump(exclude_none=True),
        "pure_premium_rate": pure,
        "loadings_share_of_gross": dict(premium.loadings),
        "loadings_rate": loadings,
        "gross_rate": gross,
        "loss_ratio_at_gross": el / gross if gross else None,
        "per_acre": per_option,
        "default_sum_insured_kes_per_acre": sum_insured.default_kes_per_acre,
    }
