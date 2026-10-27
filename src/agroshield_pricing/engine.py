"""Run the full Layer B pricing and backtest for one ward, season by season.

Long rains and short rains are priced separately: each has its own phenology,
its own resolved triggers and its own burn cost, because rainfall reliability
(and later forecast skill) differs between them.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from .backtest import backtest_yields, rainfall_season_stats
from .burn import burn_cost, exceedance_curve
from .config import Config
from .index import effective_daily, phase_rainfall, resolve_terms, season_payouts
from .phenology import season_windows, season_years
from .premium import gross_premium
from .provenance import Label, Provenance
from .rainfall import RainfallSource
from .yields import synthetic_yields


@dataclass
class SeasonResult:
    season: str
    summary: dict                      # JSON-ready results
    phase_rain: pd.DataFrame           # years x phases, mm (index terms)
    payouts: pd.DataFrame              # per-phase fractions + payout_frac
    yields: pd.Series
    climatology: pd.Series             # mean daily rainfall by day of year
    windows_example: list = field(default_factory=list)


@dataclass
class WardResult:
    ward_id: str
    summary: dict
    seasons: dict[str, SeasonResult]


def price_ward(cfg: Config, ward_id: str, source: RainfallSource) -> WardResult:
    ward = cfg.ward(ward_id)
    hist = cfg.rainfall.history
    lb = cfg.product.layer_b
    rain = source.daily(ward, hist.start_year, hist.end_year)
    rain_eff = effective_daily(rain, lb.daily_min_mm, lb.daily_cap_mm)
    climatology = rain.groupby(rain.index.dayofyear).mean()

    seasons = {}
    for season in ward.seasons:
        cal = cfg.calendar(ward_id, season)
        years = season_years(cal, hist.start_year, hist.end_year, rain.index.max())
        terms = lb.terms_for(ward_id, season)
        all_phase_rain = phase_rainfall(rain_eff, cal, years)
        phase_rain = all_phase_rain[list(terms)]
        resolved = resolve_terms(terms, phase_rain, (lb.calibration.start_year, lb.calibration.end_year))
        payouts = season_payouts(phase_rain, resolved)
        burn = burn_cost(payouts["payout_frac"], cfg.product.backtest.meaningful_payout)
        premium = gross_premium(burn, payouts["payout_frac"].to_numpy(), cfg.product.premium,
                                cfg.product.sum_insured)
        # Yields use rainfall without the index's daily cap (runoff still wets nothing,
        # but the crop model has its own water accounting).
        yld = synthetic_yields(effective_daily(rain, lb.daily_min_mm, 1e9), cal, years,
                               cfg.product.synthetic_yield, ward_id, season)
        bt = backtest_yields(payouts["payout_frac"], yld, cfg.product.backtest.bad_yield_threshold,
                             cfg.product.backtest.meaningful_payout)
        windows = season_windows(cal, years[-1])
        summary = {
            "season": season,
            "season_label": "Long rains" if season == "LR" else "Short rains",
            "years": [int(y) for y in years],
            "calendar": {
                "planting_date": cal.planting_date,
                "planting_window": cal.planting_window.model_dump(),
                "phases": [{"name": p.name, "days": p.days, "insured": p.name in terms} for p in cal.phases],
                "example_year": int(years[-1]),
                "example_windows": [{"phase": w.phase, "start": str(w.start.date()), "end": str(w.end.date())}
                                    for w in windows],
            },
            "terms": {p: r.to_dict() for p, r in resolved.items()},
            "rainfall_by_phase": rainfall_season_stats(phase_rain),
            "trigger_sensitivity": trigger_sensitivity(cfg, terms, phase_rain),
            "burn_cost": burn,
            "exceedance": exceedance_curve(payouts["payout_frac"]),
            "premium": premium,
            "backtest": {**bt, "yield_provenance": Provenance(
                Label.SYNTHETIC, "FAO-33 water-stress model on the same rainfall",
                {"caveat": "Correlates with the index by construction; tests the machinery only."}).to_dict()},
            "history": [
                {"year": int(y), **{f"rain_{p}": round(float(phase_rain.loc[y, p]), 1) for p in terms},
                 **{c: round(float(payouts.loc[y, c]), 4) for c in payouts.columns},
                 "yield_t_per_ha": float(yld.loc[y])}
                for y in years
            ],
        }
        seasons[season] = SeasonResult(season, summary, phase_rain, payouts, yld, climatology, windows)

    summary = {
        "ward": ward.model_dump(),
        "rainfall_provenance": source.provenance(ward).to_dict(),
        "rainfall_annual_mean_mm": float(rain.groupby(rain.index.year).sum().mean()),
        "index_version": lb.version,
        "daily_min_mm": lb.daily_min_mm,
        "daily_cap_mm": lb.daily_cap_mm,
        "calibration": lb.calibration.model_dump(),
        "seasons": {s: r.summary for s, r in seasons.items()},
        "provenance": provenance_block(cfg, ward_id, source),
    }
    return WardResult(ward_id, summary, seasons)


SENSITIVITY_PERCENTILES = (5, 10, 15, 20, 25)


def trigger_sensitivity(cfg: Config, terms: dict, phase_rain: pd.DataFrame) -> list[dict]:
    """Re-price with every phase trigger moved to another percentile, exits unchanged.

    Shows the underwriter how payout frequency and price move with the trigger,
    which is the main lever once real yields are available to judge basis risk.
    """
    lb = cfg.product.layer_b
    calib = (lb.calibration.start_year, lb.calibration.end_year)
    rows = []
    for pct in SENSITIVITY_PERCENTILES:
        alt = {p: t.model_copy(update={"trigger": t.trigger.model_copy(update={"mm": None, "percentile": pct})})
               for p, t in terms.items()}
        try:
            resolved = resolve_terms(alt, phase_rain, calib)
        except ValueError:
            continue  # trigger would sit at or below the exit for some phase
        pay = season_payouts(phase_rain, resolved)["payout_frac"]
        burn = burn_cost(pay)
        prem = gross_premium(burn, pay.to_numpy(), cfg.product.premium, cfg.product.sum_insured)
        rows.append({"trigger_percentile": pct, "payout_frequency": burn["payout_frequency"],
                     "expected_loss": burn["expected_loss"], "loss_1_in_10": burn["loss_1_in_10"],
                     "gross_rate": prem["gross_rate"]})
    return rows


def provenance_block(cfg: Config, ward_id: str, source: RainfallSource) -> list[dict]:
    """Every input that shaped the numbers, with its REAL/SYNTHETIC/ILLUSTRATIVE label."""
    ward = cfg.ward(ward_id)
    ill = lambda flag: Label.ILLUSTRATIVE if flag else Label.REAL  # noqa: E731
    items = [
        ("Rainfall", source.provenance(ward)),
        ("Ward location", Provenance(ill(ward.illustrative), "config/wards.yaml",
                                     {"note": "Placeholder location, not a real ward boundary."
                                      if ward.illustrative else "Agreed pilot ward."})),
        ("Phenology calendar", Provenance(ill(cfg.phenology.illustrative), "config/phenology.yaml",
                                          {"note": "Pending agronomist sign-off."})),
        ("Trigger and exit levels", Provenance(ill(cfg.product.illustrative), "config/product.yaml",
                                               {"note": "Percentile placeholders, not filed terms."})),
        ("Loadings and margins", Provenance(ill(cfg.product.illustrative), "config/product.yaml",
                                            {"note": "Pending underwriter agreement."})),
        ("Sum insured options", Provenance(ill(cfg.product.illustrative), "config/product.yaml",
                                           {"note": "Pending SACCO input-cost data."})),
        ("Yields", Provenance(Label.SYNTHETIC, "FAO-33 water-stress model",
                              {"note": "No real ward yield data yet."})),
    ]
    return [{"input": name, **p.to_dict()} for name, p in items]
