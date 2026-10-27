"""Turn a ward's phenology calendar into dated phase windows for a given year."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .config import SeasonCalendar


@dataclass(frozen=True)
class PhaseWindow:
    phase: str
    start: pd.Timestamp   # first day, inclusive
    end: pd.Timestamp     # last day, inclusive

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1


def season_windows(cal: SeasonCalendar, year: int) -> list[PhaseWindow]:
    """Back-to-back phase windows starting on the planting date in `year`."""
    month, day = cal.planting_month_day
    start = pd.Timestamp(year=year, month=month, day=day)
    windows = []
    for phase in cal.phases:
        end = start + pd.Timedelta(days=phase.days - 1)
        windows.append(PhaseWindow(phase.name, start, end))
        start = end + pd.Timedelta(days=1)
    return windows


def season_years(cal: SeasonCalendar, first_year: int, last_year: int,
                 data_end: pd.Timestamp) -> list[int]:
    """Planting years whose whole season falls inside the data."""
    return [y for y in range(first_year, last_year + 1)
            if season_windows(cal, y)[-1].end <= data_end]
