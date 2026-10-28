"""Potential evapotranspiration sources for the WRSI water balance.

Preferred: FEWS NET daily PET (Penman-Monteith from GDAS, 1.0 deg, 2001 onward).
Fallback:  Hargreaves from NASA POWER daily temperature, flagged in every output.
Tests:     a labelled synthetic seasonal PET.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

import numpy as np
import pandas as pd

from ..config import Config, Ward
from ..provenance import Label, Provenance


class PetSource(ABC):
    @abstractmethod
    def daily(self, ward: Ward, start_year: int, end_year: int) -> pd.Series:
        """Daily PET in mm, indexed by date, covering whole calendar years."""

    @abstractmethod
    def provenance(self, ward: Ward) -> Provenance:
        ...


class SyntheticPetSource(PetSource):
    """Smooth seasonal PET (~3.5-5.5 mm/day), for tests and offline demos only."""

    def daily(self, ward: Ward, start_year: int, end_year: int) -> pd.Series:
        days = pd.date_range(f"{start_year}-01-01", f"{end_year}-12-31", freq="D")
        doy = days.dayofyear.to_numpy()
        pet = 4.5 + 0.8 * np.cos(2 * np.pi * (doy - 45) / 365)   # peaks Feb, lowest Jul-Aug
        return pd.Series(np.round(pet, 3), index=days, name="pet_mm")

    def provenance(self, ward: Ward) -> Provenance:
        return Provenance(Label.SYNTHETIC, "agroshield seasonal PET curve",
                          {"caveat": "Generated, not observed. Not for pricing decisions."})


def make_pet_source(cfg: Config, source: str | None = None, allow_download: bool = True,
                    log=print) -> PetSource:
    name = source or cfg.pet.source
    if name == "hargreaves_nasapower":
        from .calibrated import CalibratedPetSource
        from .nasapower import HargreavesNasaPowerSource
        repo = Path(cfg.root).parent
        harg = HargreavesNasaPowerSource(repo / "data" / "raw" / "nasapower", cfg.pet.lapse_rate_c_per_km,
                                         allow_download, log)
        return CalibratedPetSource(harg, repo / cfg.pet.fewsnet_pet_dir, cfg.pet.fewsnet_status)
    if name == "synthetic":
        return SyntheticPetSource()
    raise ValueError(f"unknown PET source {name!r}")
