"""EXPERIMENTAL early advance on Layer B (product.yaml layer_b.advance).

At a check day after the start of season the end-of-season WRSI is projected
(observed CHIRPS so far, CHIRPS-GEFS 15 days, climatology after). Below the
threshold an advance of `advance_share` x sum insured is paid. At the end of the
season the advance is deducted from the Layer B payout and never clawed back, so

    farmer receives = max(advance, final Layer B payout)       if the advance fired
                      final Layer B payout                     otherwise
    extra cost      = max(0, advance - final payout)           (false alarms cost the full advance)

Only the extra cost is priced on top of Layer B. Pure functions: the research
script feeds them the projections (research/advance.py).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .burn import burn_cost
from .config import Config, SumInsured
from .premium import gross_premium


def outcomes(projected: pd.Series, final_share: pd.Series, threshold: float, advance_share: float) -> pd.DataFrame:
    """Per season: did the advance fire, what the farmer receives and the extra cost (shares of sum insured)."""
    fired = projected < threshold
    adv = np.where(fired, advance_share, 0.0)
    extra = np.where(fired, np.maximum(0.0, advance_share - final_share), 0.0)
    return pd.DataFrame({"projected_wrsi": projected, "final_share": final_share, "fired": fired,
                         "advance_share": adv, "farmer_receives_share": np.maximum(adv, final_share),
                         "deducted_at_end_share": np.minimum(adv, final_share), "extra_share": extra,
                         "event": final_share > 0})


def verify(fired: np.ndarray, event: np.ndarray) -> dict:
    fired, event = np.asarray(fired, bool), np.asarray(event, bool)
    hits, misses = int((fired & event).sum()), int((~fired & event).sum())
    false_alarms, quiet = int((fired & ~event).sum()), int((~fired & ~event).sum())
    return {"seasons": int(len(fired)), "fired": int(fired.sum()), "events": int(event.sum()),
            "hits": hits, "misses": misses, "false_alarms": false_alarms, "correct_quiet": quiet,
            "hit_rate": hits / (hits + misses) if hits + misses else None,
            "false_alarm_ratio": false_alarms / (hits + false_alarms) if hits + false_alarms else None,
            "peirce": _peirce(hits, misses, false_alarms, quiet)}


def _peirce(h: int, m: int, f: int, q: int) -> float | None:
    """Hit rate minus false-alarm rate (Peirce / Hanssen-Kuipers skill score)."""
    if not (h + m) or not (f + q):
        return None
    return h / (h + m) - f / (f + q)


def choose_threshold(projected: pd.Series, event: pd.Series, grid: list[float], prefer: float) -> float:
    """Best Peirce score on these seasons; ties go to the threshold nearest `prefer`, then the lower one."""
    def key(t: float):
        s = verify((projected < t).to_numpy(), event.to_numpy())["peirce"]
        return (-(s if s is not None else -1.0), abs(t - prefer), t)
    return min(grid, key=key)


def leave_one_out(projected: pd.Series, final_share: pd.Series, grid: list[float], prefer: float,
                  advance_share: float) -> dict:
    """Each season in turn is held out; the threshold is chosen on the others and tested on it."""
    event = final_share > 0
    rows = []
    for y in projected.index:
        keep = projected.index != y
        t = choose_threshold(projected[keep], event[keep], grid, prefer)
        o = outcomes(projected[[y]], final_share[[y]], t, advance_share).iloc[0]
        rows.append({"year": int(y), "threshold": float(t), "fired": bool(o["fired"]), "event": bool(o["event"]),
                     "extra_share": float(o["extra_share"])})
    df = pd.DataFrame(rows).set_index("year")
    chosen = df["threshold"].value_counts().sort_index()
    return {"out_of_sample": verify(df["fired"].to_numpy(), df["event"].to_numpy()),
            "thresholds_chosen": {f"{k:g}": int(v) for k, v in chosen.items()},
            "folds_choosing_configured": int((df["threshold"] == prefer).sum()),
            "expected_extra_share": float(df["extra_share"].mean()),
            "history": df.reset_index().to_dict(orient="records")}


def price_extra(extra_share: pd.Series, cfg: Config) -> dict:
    """Burn cost and gross premium of the net extra cost, per sum-insured option (same loadings as Layer B)."""
    si = cfg.product.sum_insured
    b = burn_cost(extra_share)
    p = gross_premium(b, extra_share.to_numpy(), cfg.product.premium, SumInsured(**si.model_dump()))
    return {"expected_extra_share": b["expected_loss"], "gross_rate": p["gross_rate"],
            "per_acre": [{"sum_insured_kes_per_acre": o["sum_insured_kes_per_acre"],
                          "expected_extra_kes": o["expected_loss_kes"], "gross_kes": o["gross_premium_kes"]}
                         for o in p["per_acre"]]}
