"""Hargreaves calibrated against FEWS NET PET where the two overlap (2001 onward).

When data/raw/fewsnet_pet/<ward>.csv (date, pet_mm) exists:
  * FEWS NET Penman-Monteith PET is used for every day it covers;
  * earlier days use Hargreaves x a monthly ratio (FEWS NET mean / Hargreaves mean
    for that calendar month over the overlap), so 1981-2000 is consistent with
    the later record;
  * the bias of raw Hargreaves against FEWS NET is reported.
When the file is absent, Hargreaves passes through unchanged and the calibration
is reported as pending.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..config import Ward
from ..provenance import Provenance
from . import PetSource


class CalibratedPetSource(PetSource):
    def __init__(self, base: PetSource, fews_dir: str | Path, status: str = ""):
        self.base = base
        self.fews_dir = Path(fews_dir)
        self.status = status
        self.calibration: dict[str, dict] = {}

    def _fews(self, ward: Ward) -> pd.Series | None:
        path = self.fews_dir / f"{ward.id}.csv"
        if not path.exists():
            return None
        return pd.read_csv(path, parse_dates=["date"]).set_index("date")["pet_mm"].astype(float)

    def daily(self, ward: Ward, start_year: int, end_year: int) -> pd.Series:
        harg = self.base.daily(ward, start_year, end_year)
        fews = self._fews(ward)
        if fews is None:
            self.calibration[ward.id] = {"available": False, "reason": self.status or "No FEWS NET PET file."}
            return harg
        both = pd.concat({"h": harg, "f": fews}, axis=1, join="inner").dropna()
        if len(both) < 365:
            self.calibration[ward.id] = {"available": False,
                                         "reason": f"only {len(both)} overlapping days with FEWS NET PET"}
            return harg
        monthly = both.groupby(both.index.month).mean()
        ratio = (monthly["f"] / monthly["h"]).to_dict()
        out = harg * harg.index.month.map(ratio).to_numpy()
        covered = fews.index.intersection(harg.index)
        out.loc[covered] = fews.loc[covered]
        diff = both["h"] - both["f"]
        self.calibration[ward.id] = {
            "available": True,
            "overlap": [str(both.index.min().date()), str(both.index.max().date())],
            "hargreaves_mean_mm_per_day": float(both["h"].mean()),
            "fewsnet_mean_mm_per_day": float(both["f"].mean()),
            "mean_bias_mm_per_day": float(diff.mean()),
            "bias_pct": float(100 * diff.mean() / both["f"].mean()),
            "monthly_ratio_fews_over_hargreaves": {int(m): round(float(r), 4) for m, r in ratio.items()},
            "fewsnet_from": str(covered.min().date()),
        }
        out.name = "pet_mm"
        return out

    def provenance(self, ward: Ward) -> Provenance:
        base = self.base.provenance(ward)
        cal = self.calibration.get(ward.id, {"available": False, "reason": self.status})
        if cal.get("available"):
            src = f"FEWS NET PET from {cal['fewsnet_from']}; calibrated Hargreaves before"
            note = f"Raw Hargreaves bias vs FEWS NET: {cal['bias_pct']:+.1f}%."
        else:
            src, note = base.source, base.details.get("note", "")
        return Provenance(base.label, src, {**base.details, "note": note, "calibration": cal})
