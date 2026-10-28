"""Run Layer B pricing for one ward, season by season.

v1 (WRSI, the priced index) and v0 (superseded per-phase percentile index) are
both computed on the same rainfall so the report can show them side by side.
Only v1 drives the premium.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy import stats

from .burn import burn_cost, exceedance_curve
from .config import Config
from .index import effective_daily, phase_rainfall, resolve_terms, season_payouts
from .pet import PetSource
from .phenology import season_years as v0_season_years
from .premium import gross_premium
from .provenance import Label, Provenance
from .rainfall import RainfallSource
from .validation import compare_fewsnet, load_fewsnet_wrsi, real_yield_backtest
from .wrsi import (SeasonWRSI, dekad_label, dekad_start, season_wrsi, season_years, to_dekads,
                   wrsi_payout)


@dataclass
class SeasonResult:
    season: str
    summary: dict                                # JSON-ready results
    v1: pd.DataFrame                             # per year: sos, wrsi, payout
    v0: pd.DataFrame                             # per year: v0 payout
    traces: dict[int, pd.DataFrame] = field(default_factory=dict)  # water balance by year


@dataclass
class WardResult:
    ward_id: str
    summary: dict
    seasons: dict[str, SeasonResult]
    rain_daily: pd.Series
    pet_daily: pd.Series


def _price(payout: pd.Series, cfg: Config) -> tuple[dict, dict]:
    burn = burn_cost(payout, cfg.product.backtest.meaningful_payout)
    prem = gross_premium(burn, payout.to_numpy(), cfg.product.premium, cfg.product.sum_insured)
    return burn, prem


def _v1_table(results: list[SeasonWRSI], terms: dict) -> pd.DataFrame:
    rows = []
    for s in results:
        rows.append({
            "year": s.year,
            "sos": dekad_label(s.sos) if s.sos is not None else None,
            "sos_date": str(dekad_start(s.sos).date()) if s.sos is not None else None,
            "failed_onset": s.failed_onset,
            "wrsi": s.wrsi,
            "season_rain_mm": round(float(s.trace["rain"].sum()), 1) if s.trace is not None else None,
            "water_requirement_mm": round(float(s.trace["wr"].sum()), 1) if s.trace is not None else None,
            "payout": wrsi_payout(s, terms["failed_onset_payout"], terms["trigger_wrsi"], terms["exit_wrsi"]),
        })
    return pd.DataFrame(rows).set_index("year")


def _day_extreme(dates: pd.Series, pick) -> str | None:
    """Earliest/latest start by calendar day, e.g. '11 Mar (1981)'."""
    d = dates.dropna()
    if d.empty:
        return None
    iso = pick(d, key=lambda s: s[5:])
    ts = pd.Timestamp(iso)
    return f"{ts.day} {ts:%b} ({ts.year})"


def _in_band(freq: float, band: tuple[float, float]) -> bool:
    return band[0] - 1e-9 <= freq <= band[1] + 1e-9


def _v0(cfg: Config, ward_id: str, season: str, rain: pd.Series) -> tuple[pd.DataFrame, dict]:
    """The superseded per-phase index, priced the same way for comparison."""
    lb0 = cfg.product.layer_b_v0
    cal = cfg.calendar(ward_id, season)
    years = v0_season_years(cal, cfg.rainfall.history.start_year, cfg.rainfall.history.end_year, rain.index.max())
    terms = lb0.terms_for(ward_id, season)
    phase_rain = phase_rainfall(effective_daily(rain, lb0.daily_min_mm, lb0.daily_cap_mm), cal, years)[list(terms)]
    resolved = resolve_terms(terms, phase_rain, (lb0.calibration.start_year, lb0.calibration.end_year))
    pay = season_payouts(phase_rain, resolved)
    return pay, {"version": lb0.version, "terms": {p: r.to_dict() for p, r in resolved.items()}}


def price_ward(cfg: Config, ward_id: str, rain_source: RainfallSource, pet_source: PetSource) -> WardResult:
    ward = cfg.ward(ward_id)
    hist = cfg.rainfall.history
    lb = cfg.product.layer_b
    band = cfg.product.target.frequency_band
    rain = rain_source.daily(ward, hist.start_year, hist.end_year)
    pet = pet_source.daily(ward, hist.start_year, hist.end_year)
    rain_dk, pet_dk = to_dekads(rain), to_dekads(pet)

    seasons = {}
    for season in ward.seasons:
        cal = cfg.calendar(ward_id, season)
        years = season_years(cal, hist.start_year, hist.end_year, int(rain_dk.index.max()))
        terms = lb.terms_for(ward_id, season)

        def run(whc: float) -> list[SeasonWRSI]:
            return [season_wrsi(rain_dk, pet_dk, cal, y, lb, whc) for y in years]

        results = run(ward.soil_whc_mm)
        v1 = _v1_table(results, terms)
        burn, prem = _price(v1["payout"], cfg)

        # Trigger sensitivity, in WRSI points (exit and failed-onset payout unchanged).
        sens = []
        for trig in lb.sensitivity_triggers:
            pay = pd.Series([wrsi_payout(s, terms["failed_onset_payout"], trig, terms["exit_wrsi"]) for s in results],
                            index=years)
            b, p = _price(pay, cfg)
            sens.append({"trigger_wrsi": trig, "payout_frequency": b["payout_frequency"],
                         "return_period_years": (1 / b["payout_frequency"]) if b["payout_frequency"] else None,
                         "expected_loss": b["expected_loss"], "loss_1_in_10": b["loss_1_in_10"],
                         "gross_rate": p["gross_rate"], "in_target_band": _in_band(b["payout_frequency"], band),
                         "is_current": trig == terms["trigger_wrsi"]})

        # Placeholder soil: how much does the water holding capacity move things?
        whc_sens = []
        for whc in lb.sensitivity_whc_mm:
            alt = _v1_table(run(whc), terms)
            b, p = _price(alt["payout"], cfg)
            whc_sens.append({"whc_mm": whc, "is_current": whc == ward.soil_whc_mm,
                             "median_wrsi": float(alt["wrsi"].median()), "payout_frequency": b["payout_frequency"],
                             "expected_loss": b["expected_loss"], "gross_rate": p["gross_rate"],
                             "event_payouts": {str(e.year): float(alt.loc[e.year, "payout"])
                                               for e in cfg.product.event_tests
                                               if e.season == season and e.year in alt.index}})

        # v0 on the same rainfall, for the side-by-side comparison.
        v0_pay, v0_info = _v0(cfg, ward_id, season, rain)
        v0_burn, v0_prem = _price(v0_pay["payout_frac"], cfg)
        common = v1.index.intersection(v0_pay.index)
        both = pd.DataFrame({"v1": v1.loc[common, "payout"], "v0": v0_pay.loc[common, "payout_frac"]})
        rho = stats.spearmanr(both["v1"], both["v0"])[0] if both["v1"].nunique() > 1 and both["v0"].nunique() > 1 else None

        def metrics(b, p, pays):
            return {"payout_frequency": b["payout_frequency"], "expected_loss": b["expected_loss"],
                    "loss_1_in_10": b["loss_1_in_10"], "loss_1_in_20": b["loss_1_in_20"],
                    "gross_rate": p["gross_rate"],
                    "event_payouts": {str(e.year): float(pays.get(e.year, np.nan))
                                      for e in cfg.product.event_tests if e.season == season}}

        events = []
        for e in cfg.product.event_tests:
            if e.season != season or e.year not in v1.index:
                continue
            row = v1.loc[e.year]
            events.append({"year": e.year, "note": e.note, "min_payout": e.min_payout,
                           "wrsi": row["wrsi"], "failed_onset": bool(row["failed_onset"]), "sos": row["sos"],
                           "payout": float(row["payout"]), "passed": bool(row["payout"] >= e.min_payout),
                           "v0_payout": float(v0_pay["payout_frac"].get(e.year, np.nan))})

        order = v1.assign(_k=v1["wrsi"].fillna(-1)).sort_values(["_k"]).head(10)
        worst = [{"rank": i + 1, "year": int(y), "sos": r["sos"], "failed_onset": bool(r["failed_onset"]),
                  "wrsi": r["wrsi"], "payout": float(r["payout"]),
                  "v0_payout": float(v0_pay["payout_frac"].get(y, np.nan))}
                 for i, (y, r) in enumerate(order.iterrows())]

        fews = compare_fewsnet(v1["wrsi"], load_fewsnet_wrsi(cfg, ward_id, season),
                               cfg.validation.large_gap_wrsi, cfg.validation.fewsnet_status)
        basis = real_yield_backtest(cfg, ward_id, season, v1["payout"])

        keep = {e["year"] for e in events} | {w["year"] for w in worst[:1]}
        traces = {s.year: s.trace for s in results if s.year in keep and s.trace is not None}
        summary = {
            "season": season,
            "season_label": "Long rains" if season == "LR" else "Short rains",
            "years": [int(y) for y in years],
            "calendar": {"planting_window": cal.planting_window.model_dump(), "variety": cal.variety,
                         "lgp_days": cal.lgp_days, "lgp_dekads": cal.lgp_dekads},
            "terms": {**terms, "version": lb.version, "soil_whc_mm": ward.soil_whc_mm,
                      "depletion_fraction": lb.depletion_fraction, "spinup_dekads": lb.spinup_dekads,
                      "onset": lb.onset.model_dump(), "kc": lb.kc.model_dump()},
            "onset_stats": {"failed_onsets": int(v1["failed_onset"].sum()),
                            "failed_onset_years": [int(y) for y in v1.index[v1["failed_onset"]]],
                            # Compare by calendar day (MM-DD), not whole date, so years do not dominate.
                            "earliest": _day_extreme(v1["sos_date"], min),
                            "latest": _day_extreme(v1["sos_date"], max)},
            "wrsi_stats": {"median": float(v1["wrsi"].median()), "min": float(v1["wrsi"].min()),
                           "below_trigger": int((v1["wrsi"] < terms["trigger_wrsi"]).sum()),
                           "at_or_below_exit": int((v1["wrsi"] <= terms["exit_wrsi"]).sum())},
            "burn_cost": burn,
            "exceedance": exceedance_curve(v1["payout"]),
            "premium": prem,
            "target": {"return_period_years": list(cfg.product.target.payout_return_period_years),
                       "frequency_band": list(band), "payout_frequency": burn["payout_frequency"],
                       "in_band": _in_band(burn["payout_frequency"], band),
                       "triggers_in_band": [r["trigger_wrsi"] for r in sens if r["in_target_band"]]},
            "trigger_sensitivity": sens,
            "whc_sensitivity": whc_sens,
            "event_tests": events,
            "worst_seasons": worst,
            "fewsnet_validation": fews,
            "basis_risk": basis,
            "v0": {**v0_info, **metrics(v0_burn, v0_prem, v0_pay["payout_frac"])},
            "v1_metrics": metrics(burn, prem, v1["payout"]),
            "comparison": {"seasons": len(common), "spearman_payouts": None if rho is None else float(rho),
                           "both_pay": int(((both["v1"] > 0) & (both["v0"] > 0)).sum()),
                           "only_v1_pays": int(((both["v1"] > 0) & (both["v0"] == 0)).sum()),
                           "only_v0_pays": int(((both["v1"] == 0) & (both["v0"] > 0)).sum())},
            "history": [
                {"year": int(y), "sos": r["sos"], "failed_onset": bool(r["failed_onset"]),
                 "wrsi": r["wrsi"], "season_rain_mm": r["season_rain_mm"],
                 "water_requirement_mm": r["water_requirement_mm"], "payout": float(r["payout"]),
                 "v0_payout": float(v0_pay["payout_frac"].get(y, np.nan))}
                for y, r in v1.iterrows()
            ],
        }
        seasons[season] = SeasonResult(season, summary, v1, v0_pay, traces)

    summary = {
        "ward": ward.model_dump(),
        "rainfall_provenance": rain_source.provenance(ward).to_dict(),
        "pet_provenance": pet_source.provenance(ward).to_dict(),
        "rainfall_annual_mean_mm": float(rain.groupby(rain.index.year).sum().mean()),
        "pet_annual_mean_mm": float(pet.groupby(pet.index.year).sum().mean()),
        "index_version": lb.version,
        "seasons": {s: r.summary for s, r in seasons.items()},
        "provenance": provenance_block(cfg, ward_id, rain_source, pet_source, seasons),
    }
    return WardResult(ward_id, summary, seasons, rain, pet)


def provenance_block(cfg: Config, ward_id: str, rain_source: RainfallSource, pet_source: PetSource,
                     seasons: dict) -> list[dict]:
    """Every input that shaped the numbers, with its label."""
    ward = cfg.ward(ward_id)
    ill = lambda flag: Label.ILLUSTRATIVE if flag else Label.REAL  # noqa: E731
    fews_ok = any(r.summary["fewsnet_validation"]["available"] for r in seasons.values())
    yields_ok = any(r.summary["basis_risk"]["available"] for r in seasons.values())
    items = [
        ("Rainfall", rain_source.provenance(ward)),
        ("PET", pet_source.provenance(ward)),
        ("Ward location", Provenance(ill(ward.illustrative), "config/wards.yaml",
                                     {"note": "Placeholder location, not a real ward boundary."})),
        ("Soil water holding capacity", Provenance(ill(ward.soil_illustrative), "config/wards.yaml",
                                                   {"note": f"{ward.soil_whc_mm:g} mm placeholder until ward soil data."})),
        ("Crop calendar and LGP", Provenance(ill(cfg.phenology.illustrative), "config/phenology.yaml",
                                             {"note": "Planting window and growing period pending agronomist sign-off."})),
        ("WRSI trigger, exit, failed-onset payout", Provenance(ill(cfg.product.illustrative), "config/product.yaml",
                                                               {"note": "Placeholders, not filed terms."})),
        ("Target payout frequency", Provenance(Label.ILLUSTRATIVE, "config/product.yaml",
                                               {"note": "1 season in 5-7; underwriter to confirm."})),
        ("Loadings and margins", Provenance(ill(cfg.product.illustrative), "config/product.yaml",
                                            {"note": "Pending underwriter agreement."})),
        ("Sum insured options", Provenance(ill(cfg.product.illustrative), "config/product.yaml",
                                           {"note": "Pending SACCO input-cost data."})),
        ("FEWS NET WRSI (validation)", Provenance(Label.REAL if fews_ok else Label.PENDING,
                                                  "USGS FEWS NET CHIRPS Croplands WRSI",
                                                  {"note": "Compared below." if fews_ok else cfg.validation.fewsnet_status})),
        ("Yields (basis risk)", Provenance(Label.REAL if yields_ok else Label.PENDING, "ward yield history",
                                           {"note": "Backtest below." if yields_ok else
                                            "No real ward yields; basis risk not measurable."})),
    ]
    return [{"input": name, **p.to_dict()} for name, p in items]
