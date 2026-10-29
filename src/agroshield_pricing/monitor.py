"""Daily ward monitoring: where the season stands, on the same index the product is priced on.

For one ward, season and planting year, as of a date:

  * observed CHIRPS rain (and PET) up to the last day with data,
  * the ward's daily climatology from every OTHER year for the rest of the season,
  * then the very same season_wrsi() used for pricing.

Each part of the result is only CONFIRMED once observed data covers it:
failed onset at the end of the planting window, the germination dry spell at the
end of its 20-day check, the WRSI payout at the end of the growing period.
Before that the numbers are projections ("if the rest of the season is normal").

Pure: no database, no network. The platform stores each run, audits it and
creates payouts only from confirmed results.
"""
from __future__ import annotations

import hashlib
from datetime import date

import numpy as np
import pandas as pd

from .config import Config
from .wrsi import dekad_end, dekad_label, dekad_start, season_wrsi, to_dekads, window_dekads, wrsi_payout

LEVELS = ("none", "normal", "watch", "alert", "payout")   # increasing concern; "payout" = a confirmed trigger
DRY_SHARE = 0.6        # rain below this share of normal so far is worth a "watch"
STALE_DAYS = 60        # CHIRPS final lags up to ~7 weeks; older than this and there is nothing to say


def climatology_fill(series: pd.Series, through: pd.Timestamp, end: pd.Timestamp, exclude_year: int) -> pd.Series:
    """Observed values up to `through`, then the mean for that day of year over every other year."""
    obs = series.loc[:through]
    hist = series[series.index.year != exclude_year]
    clim = hist.groupby(hist.index.dayofyear).mean()
    future = pd.date_range(through + pd.Timedelta(days=1), end)
    fill = pd.Series(clim.reindex(future.dayofyear).fillna(clim.mean()).to_numpy(), index=future)
    return pd.concat([obs, fill]) if len(future) else obs


def last_observed(series: pd.Series, as_of: date) -> pd.Timestamp | None:
    s = series.loc[:pd.Timestamp(as_of) - pd.Timedelta(days=1)].dropna()
    return s.index.max() if len(s) else None


def ward_status(cfg: Config, ward_id: str, season: str, year: int, as_of: date, rain: pd.Series,
                pet: pd.Series) -> dict:
    """The monitoring result for one ward and season, as of a date (data up to the day before)."""
    ward, cal, lb = cfg.ward(ward_id), cfg.calendar(ward_id, season), cfg.product.layer_b
    terms = lb.terms_for(ward_id, season)
    trig, exit_ = terms["trigger_wrsi"], terms["exit_wrsi"]
    n = cal.lgp_dekads
    t0, t1 = window_dekads(cal.planting_window, year)
    window_start, window_end = dekad_start(t0), dekad_end(t1)
    latest_end = dekad_end(t1 + lb.germination_dry_spell.restart_search_extra_dekads + n + 1)
    through = last_observed(rain, as_of)
    base = {"ward_id": ward_id, "season": season, "year": year, "as_of": str(as_of),
            "data_through": str(through.date()) if through is not None else None,
            "index_version": lb.version, "trigger_wrsi": trig, "exit_wrsi": exit_,
            "window": [str(window_start.date()), str(window_end.date())],
            "config_sha256": dict(cfg.file_hashes)}
    if pd.Timestamp(as_of) <= window_start:
        return {**base, "phase": "before_season", "level": "none", "confirmed": [], "projected_share": 0.0,
                "inputs_sha256": None}
    if through is None or (pd.Timestamp(as_of) - through).days > STALE_DAYS:
        return {**base, "phase": "data_unavailable", "level": "none", "confirmed": [], "projected_share": 0.0,
                "inputs_sha256": None}

    end = max(latest_end, through)
    r = climatology_fill(rain, through, end, year)
    p = climatology_fill(pet.reindex(pd.date_range(pet.index.min(), end)), min(through, pet.dropna().index.max()),
                         end, year)
    used = rain.loc[pd.Timestamp(year - 1, 10, 1):through]
    inputs_sha = hashlib.sha256(used.round(3).to_csv(lineterminator="\n").encode()).hexdigest()
    s = season_wrsi(r, to_dekads(r), to_dekads(p), cal, year, lb, ward.soil_whc_mm)

    # Rain since the planting window opened, against normal for the same days.
    span = pd.date_range(window_start, min(through, latest_end))
    obs_mm = float(rain.reindex(span).fillna(0).sum()) if len(span) else 0.0
    hist = rain[rain.index.year != year]
    clim = hist.groupby(hist.index.dayofyear).mean()
    normal_mm = float(clim.reindex(span.dayofyear).sum()) if len(span) else 0.0

    confirmed, events = [], {}
    failed_confirmed = s.failed_onset and through >= window_end
    if failed_confirmed:
        confirmed.append("failed_onset")
        events["failed_onset"] = {"share": terms["failed_onset_payout"], "window_rain_mm": s.window_rain_mm,
                                  "threshold_mm": lb.failed_onset.window_rain_below_mm}
    if s.germination_failed and s.germination_window and pd.Timestamp(s.germination_window[1]) <= through:
        confirmed.append("germination_dry_spell")
        events["germination_dry_spell"] = {"voucher_kes_per_acre": lb.germination_dry_spell.replant_cost_kes_per_acre,
                                           "rain_mm": s.germination_rain_mm, "window": s.germination_window,
                                           "threshold_mm": lb.germination_dry_spell.rain_below_mm}
    sos_seen = s.sos is not None and dekad_end(s.planting_rain_dekad if s.planting_rain_dekad is not None else s.sos) <= through
    season_end = dekad_end(s.sos + n - 1) if s.sos is not None else None
    complete = failed_confirmed or (season_end is not None and through >= season_end)
    share = wrsi_payout(s, trig, exit_) if not s.failed_onset else terms["failed_onset_payout"]
    if complete and not s.failed_onset:
        confirmed.append("wrsi_final")
        events["wrsi_final"] = {"wrsi": s.wrsi, "share": share}

    if complete:
        phase = "complete"
        level = "payout" if share > 0 or "germination_dry_spell" in confirmed else "normal"
    elif "germination_dry_spell" in confirmed:
        phase, level = "in_season", "payout"
    elif not sos_seen:
        phase = "waiting_for_rains"
        level = "alert" if s.failed_onset else ("watch" if normal_mm and obs_mm < DRY_SHARE * normal_mm and
                                                 through >= window_start + pd.Timedelta(days=20) else "none")
    else:
        phase = "in_season"
        level = "alert" if s.wrsi is not None and s.wrsi < trig else \
            "watch" if s.wrsi is not None and s.wrsi < trig + cfg.monitoring.watch_margin_wrsi else "normal"
        if level == "normal" and normal_mm and obs_mm < DRY_SHARE * normal_mm:
            level = "watch"          # well below normal rain, even if stored soil water still carries the crop

    return {**base, "phase": phase, "level": level, "confirmed": confirmed, "events": events,
            "projected_wrsi": s.wrsi, "projected_share": round(float(share), 6), "failed_onset_projected": s.failed_onset,
            "sos": dekad_label(s.sos) if s.sos is not None else None, "sos_date": str(dekad_start(s.sos).date()) if s.sos is not None else None,
            "sos_observed": bool(sos_seen), "sos_rule": s.sos_rule,
            "season_end": str(season_end.date()) if season_end is not None else None,
            "days_into_season": int((through - dekad_start(s.sos)).days) if sos_seen else None,
            "rain_since_window_mm": round(obs_mm, 1), "normal_since_window_mm": round(normal_mm, 1),
            "rain_pct_of_normal": round(100 * obs_mm / normal_mm) if normal_mm > 0 else None,
            "window_rain_mm": s.window_rain_mm, "inputs_sha256": inputs_sha,
            "dekads_observed": int(np.sum(to_dekads(rain.loc[window_start:through]).index >= t0)) if through >= window_start else 0}
