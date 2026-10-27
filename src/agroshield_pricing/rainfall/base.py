"""Rainfall source interface.

A source returns a daily rainfall series for a ward. The pricing engine only
sees this interface, so CHIRPS, synthetic data, TAHMO stations or a future
calculating-agent feed are interchangeable.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd

from ..config import Ward
from ..provenance import Provenance


class RainfallSource(ABC):
    @abstractmethod
    def daily(self, ward: Ward, start_year: int, end_year: int) -> pd.Series:
        """Daily rainfall in mm, indexed by date, covering whole calendar years."""

    @abstractmethod
    def provenance(self, ward: Ward) -> Provenance:
        """Where the series for this ward came from."""


def validate_series(s: pd.Series, start_year: int, end_year: int, what: str) -> pd.Series:
    """Check a daily series is complete and physically plausible."""
    expected = pd.date_range(f"{start_year}-01-01", f"{end_year}-12-31", freq="D")
    s = s.sort_index()
    missing = expected.difference(s.index)
    if len(missing):
        raise ValueError(f"{what}: {len(missing)} missing days, first {missing[0].date()}")
    s = s.loc[expected]
    if s.isna().any():
        raise ValueError(f"{what}: {int(s.isna().sum())} NaN days")
    if (s < 0).any() or (s > 500).any():
        raise ValueError(f"{what}: values outside 0-500 mm/day")
    s.name = "rain_mm"
    return s
