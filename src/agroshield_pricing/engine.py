"""Run Layer B pricing for one ward, season by season.

The product's season payout, per acre, at sum insured SI:
    failed onset        failed_onset.payout x SI                (and nothing else)
    otherwise           WRSI share x SI
                        + replanting cost (KES)        if the germination dry spell fired
                        + flowering share x SI         only if the EXPERIMENTAL component is enabled
    capped at SI.
Because the replanting payout is a fixed KES amount, the product is priced per
sum-insured option in KES, not as one rate.

v0 (superseded per-phase percentile index) is computed on the same rainfall for
side-by-side comparison only.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy import stats

from .burn import burn_cost, exceedance_curve
from .config import Config, SumInsured
from .index import effective_daily, phase_rainfall, resolve_terms, season_payouts
from .layer_a import run_layer_a
from .pet import PetSource
from .phenology import season_years as v0_season_years
from .premium import gross_premium
from .provenance import Label, Provenance
from .rainfall import RainfallSource
from .validation import compare_fewsnet, load_fewsnet_wrsi, real_yield_backtest
from .wrsi import (SeasonWRSI, dekad_label, dekad_start, flowering_payout, season_wrsi, season_years,
                   to_dekads, wrsi_payout)


@dataclass
class SeasonResult:
    season: str
    summary: dict                                # JSON-ready results
    table: pd.DataFrame                          # per year: components and product payout (default SI)
    v0: pd.DataFrame                             # per year: v0 payout
    traces: dict[int, pd.DataFrame] = field(default_factory=dict)  # water balance by year


@dataclass
class WardResult:
    ward_id: str
    summary: dict
    seasons: dict[str, SeasonResult]
    rain_daily: pd.Series
    pet_daily: pd.Series


# ------------------------------------------------------------------ components
def component_table(results: list[SeasonWRSI], terms: dict, cfg: Config) -> pd.DataFrame:
    lb = cfg.product.layer_b
    rows = []
    for s in results:
        rows.append({
            "year": s.year,
            "sos": dekad_label(s.sos) if s.sos is not None else None,
            "sos_date": str(dekad_start(s.sos).date()) if s.sos is not None else None,
            "sos_rule": s.sos_rule,
            "window_rain_mm": s.window_rain_mm,
            "failed_onset": s.failed_onset,
            "planting_rain": dekad_label(s.planting_rain_dekad) if s.planting_rain_dekad is not None else None,
            "germination_failed": s.germination_failed,
            "germination_rain_mm": s.germination_rain_mm,
            "germination_window": s.germination_window,
            "wrsi": s.wrsi,
            "season_rain_mm": round(float(s.trace["rain"].sum()), 1) if s.trace is not None else None,
            "water_requirement_mm": round(float(s.trace["wr"].sum()), 1) if s.trace is not None else None,
            "wrsi_share": wrsi_payout(s, terms["trigger_wrsi"], terms["exit_wrsi"]),
            "failed_onset_share": terms["failed_onset_payout"] if s.failed_onset else 0.0,
            "replant_kes": lb.germination_dry_spell.replant_cost_kes_per_acre if s.germination_failed else 0.0,
            "flowering_share": flowering_payout(s.flowering, lb.flowering),
            "flowering_dry_spell_days": s.flowering["longest_dry_spell_days"] if s.flowering else None,
            "flowering_deficit_pct": s.flowering["rainfall_deficit_pct"] if s.flowering else None,
            "flowering_window": (s.flowering["start"], s.flowering["end"]) if s.flowering else None,
        })
    return pd.DataFrame(rows).set_index("year")


def product_kes(table: pd.DataFrame, si: float, with_flowering: bool) -> pd.Series:
    share = table["failed_onset_share"] + table["wrsi_share"]
    if with_flowering:
        share = share + table["flowering_share"]
    return np.minimum(si, share * si + table["replant_kes"]).rename("payout_kes")


def price_product(table: pd.DataFrame, cfg: Config, with_flowering: bool) -> dict:
    """Burn cost and gross premium for every sum-insured option, priced in KES."""
    si_cfg, prem_cfg = cfg.product.sum_insured, cfg.product.premium
    out = {"per_acre": []}
    for si in si_cfg.options_kes_per_acre:
        share = product_kes(table, si, with_flowering) / si
        b = burn_cost(share, cfg.product.backtest.meaningful_payout)
        p = gross_premium(b, share.to_numpy(), prem_cfg, SumInsured(options_kes_per_acre=[si], default_kes_per_acre=si))
        out["per_acre"].append({**p["per_acre"][0], "gross_rate": p["gross_rate"]})
        if si == si_cfg.default_kes_per_acre:
            out["burn"], out["premium"] = b, {**p, "per_acre": None}
            out["payout_share"] = share
    out["premium"]["per_acre"] = out["per_acre"]
    out["premium"]["default_sum_insured_kes_per_acre"] = si_cfg.default_kes_per_acre
    return out


def component_breakdown(table: pd.DataFrame, cfg: Config) -> list[dict]:
    """Each component on its own, at the default sum insured (before the SI cap)."""
    si = cfg.product.sum_insured.default_kes_per_acre
    parts = {
        "WRSI": table["wrsi_share"] * si,
        "Failed onset (catastrophe only)": table["failed_onset_share"] * si,
        "Germination replanting (seed voucher)": table["replant_kes"],
    }
    if cfg.product.layer_b.flowering.enabled:   # dropped from v1; only shown if re-enabled
        parts["Flowering dry spell (EXPERIMENTAL)"] = table["flowering_share"] * si
    rows = []
    for name, kes in parts.items():
        share = kes / si
        b = burn_cost(share)
        p = gross_premium(b, share.to_numpy(), cfg.product.premium, cfg.product.sum_insured)
        rows.append({"component": name, "seasons_paying": int((kes > 0).sum()),
                     "payout_frequency": b["payout_frequency"], "expected_loss_kes": float(kes.mean()),
                     "gross_kes_alone": round(p["gross_rate"] * si, 2), "in_product": True})
    return rows


def _day_extreme(dates: pd.Series, pick) -> str | None:
    """Earliest/latest start by calendar day, e.g. '11 Mar (1981)'."""
    d = dates.dropna()
    if d.empty:
        return None
    ts = pd.Timestamp(pick(d, key=lambda s: s[5:]))
    return f"{ts.day} {ts:%b} ({ts.year})"


def frequencies(table: pd.DataFrame, share: pd.Series) -> dict:
    """Payout frequencies: main (WRSI + failed onset), replanting, and any payout (combined)."""
    main = (table["wrsi_share"] > 0) | table["failed_onset"]
    return {"main": float(main.mean()), "replanting": float(table["germination_failed"].mean()),
            "combined": float((share > 0).mean())}


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


def _targets(cfg: Config, ward_id: str, fq: dict, sens: list[dict]) -> dict:
    t = cfg.product.target
    band = t.band_for(ward_id)
    out = {"main": {"label": "WRSI and failed onset", "return_period_years": list(t.periods_for(ward_id)),
                    "frequency_band": list(band), "frequency": fq["main"], "in_band": _in_band(fq["main"], band),
                    "triggers_in_band": [r["trigger_wrsi"] for r in sens if r["in_target_band"]]},
           "combined": {"label": "Any payout (for farmer communication)", "frequency": fq["combined"],
                        "about_one_in": (1 / fq["combined"]) if fq["combined"] else None}}
    if t.replant_band:
        out["replanting"] = {"label": "Replanting seed voucher", "return_period_years": list(t.replant_return_period_years),
                             "frequency_band": list(t.replant_band), "frequency": fq["replanting"],
                             "in_band": _in_band(fq["replanting"], t.replant_band)}
    return out


# Levels used only to show the non-configured flowering metric beside the configured one.
ALT_FLOWERING_LEVELS = {"rainfall_deficit": {"trigger": 40.0, "exit": 80.0},
                        "longest_dry_spell": {"trigger": 12.0, "exit": 25.0}}


def _metrics(b: dict, p: dict, pays: pd.Series, events) -> dict:
    return {"payout_frequency": b["payout_frequency"], "expected_loss": b["expected_loss"],
            "loss_1_in_10": b["loss_1_in_10"], "loss_1_in_20": b["loss_1_in_20"], "gross_rate": p["gross_rate"],
            "event_payouts": {str(e.year): float(pays.get(e.year, np.nan)) for e in events}}


def _flowering_comparison(cfg: Config, table: pd.DataFrame, results: list[SeasonWRSI], years: list[int],
                          events) -> dict:
    """WRSI-only vs WRSI + flowering, with the other flowering metric beside it."""
    lb = cfg.product.layer_b
    fl_on = lb.flowering.enabled
    off, on = price_product(table, cfg, False), price_product(table, cfg, True)
    # The other flowering metric on the same seasons, so the choice of metric is visible.
    other = "rainfall_deficit" if lb.flowering.metric == "longest_dry_spell" else "longest_dry_spell"
    alt_fl = lb.flowering.model_copy(update={"metric": other, **ALT_FLOWERING_LEVELS[other]})
    alt_share = pd.Series([flowering_payout(s.flowering, alt_fl) for s in results], index=years)
    alt_on = price_product(table.assign(flowering_share=alt_share), cfg, True)
    return {
        "enabled_in_product": fl_on, "terms": lb.flowering.model_dump(),
        "alternative": {"metric": other, "trigger": alt_fl.trigger, "exit": alt_fl.exit,
                        "seasons_paying": int((alt_share > 0).sum()),
                        "with_flowering": _metrics(alt_on["burn"], alt_on["premium"], alt_on["payout_share"], events)},
        "wrsi_only": _metrics(off["burn"], off["premium"], off["payout_share"], events),
        "with_flowering": _metrics(on["burn"], on["premium"], on["payout_share"], events),
        "seasons_flowering_pays": [
            {"year": int(y), "dry_spell_days": r["flowering_dry_spell_days"], "deficit_pct": r["flowering_deficit_pct"],
             "window": r["flowering_window"], "flowering_share": float(r["flowering_share"]),
             "wrsi": r["wrsi"], "wrsi_share": float(r["wrsi_share"])}
            for y, r in table.iterrows() if r["flowering_share"] > 0],
    }


# ------------------------------------------------------------------ one ward
def price_ward(cfg: Config, ward_id: str, rain_source: RainfallSource, pet_source: PetSource) -> WardResult:
    ward = cfg.ward(ward_id)
    hist = cfg.rainfall.history
    lb = cfg.product.layer_b
    band = cfg.product.target.band_for(ward_id)
    si = cfg.product.sum_insured.default_kes_per_acre
    rain = rain_source.daily(ward, hist.start_year, hist.end_year)
    pet = pet_source.daily(ward, hist.start_year, hist.end_year)
    rain_dk, pet_dk = to_dekads(rain), to_dekads(pet)
    fl_on = lb.flowering.enabled

    seasons = {}
    for season in ward.seasons:
        cal = cfg.calendar(ward_id, season)
        events = [e for e in cfg.product.event_tests if e.season == season]
        years = season_years(cal, hist.start_year, hist.end_year, int(rain_dk.index.max()),
                             lb.germination_dry_spell.restart_search_extra_dekads)
        terms = lb.terms_for(ward_id, season)

        def run(whc: float) -> list[SeasonWRSI]:
            return [season_wrsi(rain, rain_dk, pet_dk, cal, y, lb, whc) for y in years]

        results = run(ward.soil_whc_mm)
        table = component_table(results, terms, cfg)
        priced = price_product(table, cfg, fl_on)
        burn, prem, share = priced["burn"], priced["premium"], priced["payout_share"]
        table["payout_share"] = share
        table["payout_kes"] = share * si

        # Trigger sensitivity in WRSI points (other components unchanged).
        sens = []
        for trig in lb.sensitivity_triggers:
            alt = component_table(results, {**terms, "trigger_wrsi": trig}, cfg)
            pr = price_product(alt, cfg, fl_on)
            b = pr["burn"]
            fq = frequencies(alt, pr["payout_share"])
            sens.append({"trigger_wrsi": trig, "main_frequency": fq["main"], "payout_frequency": fq["combined"],
                         "return_period_years": (1 / fq["main"]) if fq["main"] else None,
                         "expected_loss": b["expected_loss"], "loss_1_in_10": b["loss_1_in_10"],
                         "gross_rate": pr["premium"]["gross_rate"], "in_target_band": _in_band(fq["main"], band),
                         "is_current": trig == terms["trigger_wrsi"]})

        # Placeholder soil: how much does the water holding capacity move things?
        whc_sens = []
        for whc in lb.sensitivity_whc_mm:
            alt = component_table(run(whc), terms, cfg)
            pr = price_product(alt, cfg, fl_on)
            whc_sens.append({"whc_mm": whc, "is_current": whc == ward.soil_whc_mm,
                             "median_wrsi": float(alt["wrsi"].median()),
                             "payout_frequency": pr["burn"]["payout_frequency"],
                             "expected_loss": pr["burn"]["expected_loss"], "gross_rate": pr["premium"]["gross_rate"],
                             "event_payouts": {str(e.year): float(pr["payout_share"].get(e.year, np.nan)) for e in events}})

        # Flowering was dropped from v1 (CHIRPS dry spells are unreliable): compared
        # only if someone re-enables it.
        flowering_cmp = _flowering_comparison(cfg, table, results, years, events) if fl_on else None

        # Every season where an early-season trigger fired, with the rain that caused it.
        early = []
        for y, r in table.iterrows():
            if r["failed_onset"]:
                early.append({"year": int(y), "trigger": "Failed onset", "payout_kes": float(r["failed_onset_share"] * si),
                              "cause": f"{r['window_rain_mm']:.0f} mm over the planting window "
                                       f"({cal.planting_window.start} to {cal.planting_window.end}), below "
                                       f"{lb.failed_onset.window_rain_below_mm:g} mm"})
            elif r["germination_failed"]:
                g0, g1 = r["germination_window"]
                early.append({"year": int(y), "trigger": "Germination dry spell", "payout_kes": float(r["replant_kes"]),
                              "cause": f"planting rain {r['planting_rain']}, then {r['germination_rain_mm']:.0f} mm "
                                       f"from {g0} to {g1}, below {lb.germination_dry_spell.rain_below_mm:g} mm; "
                                       f"season restarted {r['sos']}"})

        # v0 on the same rainfall, for the side-by-side comparison.
        v0_pay, v0_info = _v0(cfg, ward_id, season, rain)
        b0 = burn_cost(v0_pay["payout_frac"], cfg.product.backtest.meaningful_payout)
        p0 = gross_premium(b0, v0_pay["payout_frac"].to_numpy(), cfg.product.premium, cfg.product.sum_insured)
        common = table.index.intersection(v0_pay.index)
        both = pd.DataFrame({"v1": share.loc[common], "v0": v0_pay.loc[common, "payout_frac"]})
        rho = stats.spearmanr(both["v1"], both["v0"])[0] if both["v1"].nunique() > 1 and both["v0"].nunique() > 1 else None

        event_rows = []
        for e in events:
            if e.year not in table.index:
                continue
            r = table.loc[e.year]
            required = ward_id in e.required_for
            event_rows.append({"year": e.year, "note": e.note, "min_payout": e.min_payout, "required": required,
                               "wrsi": r["wrsi"], "failed_onset": bool(r["failed_onset"]), "sos": r["sos"],
                               "payout": float(share[e.year]),
                               "passed": bool(share[e.year] >= e.min_payout) if required else None,
                               "v0_payout": float(v0_pay["payout_frac"].get(e.year, np.nan))})

        order = table.assign(_k=table["wrsi"].fillna(-1)).sort_values(["_k"]).head(10)
        worst = [{"rank": i + 1, "year": int(y), "sos": r["sos"], "failed_onset": bool(r["failed_onset"]),
                  "germination_failed": bool(r["germination_failed"]), "wrsi": r["wrsi"],
                  "payout": float(r["payout_share"]), "v0_payout": float(v0_pay["payout_frac"].get(y, np.nan))}
                 for i, (y, r) in enumerate(order.iterrows())]

        fews = compare_fewsnet(table["wrsi"], load_fewsnet_wrsi(cfg, ward_id, season),
                               cfg.validation.large_gap_wrsi, cfg.validation.fewsnet_status)
        basis = real_yield_backtest(cfg, ward_id, season, share)
        if ward_id in cfg.product.layer_a.offered_wards:
            layer_a = run_layer_a(cfg, ward_id, season, rain, share)
        else:
            layer_a = {"available": False, "offered": False,
                       "reason": "Layer A is not offered at this ward (decision 2026-10-28): a dry March-May here "
                                 "rarely becomes a crop failure. Its forecast skill is still measured in research 3b."}
        default_b = next(o for o in prem["per_acre"] if o["sum_insured_kes_per_acre"] == si)
        combined = {"sum_insured_kes_per_acre": si, "layer_b_gross_kes": default_b["gross_premium_kes"],
                    "layer_a_gross_kes": layer_a.get("gross_kes"),
                    "total_gross_kes": round(default_b["gross_premium_kes"] + (layer_a.get("gross_kes") or 0), 2)}

        keep = {e["year"] for e in event_rows} | {w["year"] for w in worst[:1] if w["wrsi"] is not None}
        traces = {s.year: s.trace for s in results if s.year in keep and s.trace is not None}
        summary = {
            "season": season,
            "season_label": "Long rains" if season == "LR" else "Short rains",
            "years": [int(y) for y in years],
            "calendar": {"planting_window": cal.planting_window.model_dump(), "planting_rain_from": cal.planting_rain_start,
                         "variety": cal.variety,
                         "lgp_days": cal.lgp_days, "lgp_dekads": cal.lgp_dekads},
            "terms": {**terms, "version": lb.version, "soil_whc_mm": ward.soil_whc_mm,
                      "depletion_fraction": lb.depletion_fraction, "spinup_dekads": lb.spinup_dekads,
                      "planting_rain_mm": lb.planting_rain_mm, "failed_onset": lb.failed_onset.model_dump(),
                      "germination_dry_spell": lb.germination_dry_spell.model_dump(), "kc": lb.kc.model_dump()},
            "onset_stats": {"failed_onsets": int(table["failed_onset"].sum()),
                            "germination_failures": int(table["germination_failed"].sum()),
                            "lowest_window_rain": [{"year": int(y), "mm": float(v)} for y, v in
                                                   table["window_rain_mm"].nsmallest(3).items()],
                            "earliest": _day_extreme(table["sos_date"], min),
                            "latest": _day_extreme(table["sos_date"], max)},
            "early_season_triggers": early,
            "wrsi_stats": {"median": float(table["wrsi"].median()), "min": float(table["wrsi"].min()),
                           "below_trigger": int((table["wrsi"] < terms["trigger_wrsi"]).sum()),
                           "at_or_below_exit": int((table["wrsi"] <= terms["exit_wrsi"]).sum())},
            "burn_cost": burn,
            "exceedance": exceedance_curve(share),
            "premium": prem,
            "components": component_breakdown(table, cfg),
            "target": _targets(cfg, ward_id, frequencies(table, share), sens),
            "trigger_sensitivity": sens,
            "whc_sensitivity": whc_sens,
            "flowering": flowering_cmp,
            "event_tests": event_rows,
            "worst_seasons": worst,
            "fewsnet_validation": fews,
            "basis_risk": basis,
            "layer_a": layer_a,
            "combined_gross_per_acre": combined,
            "v0": {**v0_info, **_metrics(b0, p0, v0_pay["payout_frac"], events)},
            "v1_metrics": _metrics(burn, prem, share, events),
            "comparison": {"seasons": len(common), "spearman_payouts": None if rho is None else float(rho),
                           "both_pay": int(((both["v1"] > 0) & (both["v0"] > 0)).sum()),
                           "only_v1_pays": int(((both["v1"] > 0) & (both["v0"] == 0)).sum()),
                           "only_v0_pays": int(((both["v1"] == 0) & (both["v0"] > 0)).sum())},
            "history": [
                {"year": int(y), "sos": r["sos"], "sos_rule": r["sos_rule"], "window_rain_mm": r["window_rain_mm"],
                 "failed_onset": bool(r["failed_onset"]), "germination_failed": bool(r["germination_failed"]),
                 "wrsi": r["wrsi"], "season_rain_mm": r["season_rain_mm"],
                 "water_requirement_mm": r["water_requirement_mm"], "wrsi_share": float(r["wrsi_share"]),
                 "replant_kes": float(r["replant_kes"]), "flowering_dry_spell_days": r["flowering_dry_spell_days"],
                 "flowering_share": float(r["flowering_share"]), "payout": float(r["payout_share"]),
                 "payout_kes": float(r["payout_kes"]), "v0_payout": float(v0_pay["payout_frac"].get(y, np.nan))}
                for y, r in table.iterrows()
            ],
        }
        seasons[season] = SeasonResult(season, summary, table, v0_pay, traces)

    calibration = getattr(pet_source, "calibration", {}).get(ward_id)
    summary = {
        "ward": ward.model_dump(),
        "rainfall_provenance": rain_source.provenance(ward).to_dict(),
        "pet_provenance": pet_source.provenance(ward).to_dict(),
        "pet_calibration": calibration or {"available": False, "reason": "PET source has no calibration step."},
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
        ("WRSI trigger and exit", Provenance(ill(cfg.product.illustrative), "config/product.yaml",
                                             {"note": "Placeholders, not filed terms."})),
        ("Failed-onset and germination triggers", Provenance(ill(cfg.product.illustrative), "config/product.yaml",
                                                             {"note": "Rain thresholds and replanting cost are placeholders."})),
        ("Flowering component", Provenance(Label.ILLUSTRATIVE, "config/product.yaml",
                                           {"note": "EXPERIMENTAL; " + ("in the product." if cfg.product.layer_b.flowering.enabled
                                                                        else "off, shown for comparison only.")})),
        ("Seasonal forecast (Layer A)", Provenance(Label.SYNTHETIC, "agroshield synthetic tercile forecast",
                                                   {"note": "Generated from observed rainfall at the skill measured from C3S SEAS5.1 hindcasts (research 3b)."})),
        ("Layer A trigger and voucher value", Provenance(ill(cfg.product.illustrative), "config/product.yaml",
                                                         {"note": "Probability threshold and voucher KES per acre are placeholders."})),
        ("Target payout frequency", Provenance(Label.ILLUSTRATIVE, "config/product.yaml",
                                               {"note": "1 season in {:g}-{:g}; underwriter to confirm.".format(
                                                   *sorted(cfg.product.target.periods_for(ward_id)))})),
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
