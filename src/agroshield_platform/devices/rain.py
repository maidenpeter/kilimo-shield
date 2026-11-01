"""Rain gauges: daily totals, a check against CHIRPS satellite rainfall, and the TAHMO adapter (blocked).

Gauge readings are for spotting basis risk and broken gauges, never for triggers. A point gauge and a satellite
pixel average differ a lot from day to day, so the check compares 10-day totals (dekads) and flags only large gaps.
All thresholds are DRAFT defaults, to be tuned once a season of gauge data is in.

    dekad check (when the ward's CHIRPS file covers the dekad and the gauge reported every day of it)
        wetter than satellite   gauge - CHIRPS > 30 mm and gauge > 3 x CHIRPS
        drier than satellite    CHIRPS - gauge > 30 mm and gauge < CHIRPS / 3 ("possible blocked funnel" at 0 mm)
    day check (always): a day above twice the wettest CHIRPS day on record for that ward and calendar month
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Device, DeviceReading

NAIROBI = timezone(timedelta(hours=3))
DEKAD_GAP_MM = 30.0          # DRAFT
DEKAD_RATIO = 3.0            # DRAFT
DAY_FACTOR = 2.0             # DRAFT


def daily_totals(s: Session, device: Device, start: date, end: date) -> dict[date, float]:
    """Gauge rainfall per Nairobi calendar day (the interval is credited to the day it ended in)."""
    lo = datetime.combine(start, datetime.min.time(), NAIROBI).astimezone(timezone.utc)
    hi = datetime.combine(end + timedelta(days=1), datetime.min.time(), NAIROBI).astimezone(timezone.utc)
    out: dict[date, float] = {}
    rows = s.execute(select(DeviceReading.observed_at, DeviceReading.value).where(
        DeviceReading.device_id == device.id, DeviceReading.metric == "rain_mm",
        DeviceReading.observed_at >= lo, DeviceReading.observed_at < hi))
    for at, mm in rows:
        at = at if at.tzinfo else at.replace(tzinfo=timezone.utc)
        d = at.astimezone(NAIROBI).date()
        out[d] = round(out.get(d, 0.0) + mm, 3)
    return out


def reporting_days(s: Session, device: Device, start: date, end: date) -> set[date]:
    """Days on which the gauge sent at least one reading (a day with no tips still counts as reported)."""
    lo = datetime.combine(start, datetime.min.time(), NAIROBI).astimezone(timezone.utc)
    hi = datetime.combine(end + timedelta(days=1), datetime.min.time(), NAIROBI).astimezone(timezone.utc)
    rows = s.scalars(select(DeviceReading.observed_at).where(
        DeviceReading.device_id == device.id, DeviceReading.metric == "interval_min",
        DeviceReading.observed_at >= lo, DeviceReading.observed_at < hi))
    return {(a if a.tzinfo else a.replace(tzinfo=timezone.utc)).astimezone(NAIROBI).date() for a in rows}


class RainSource(Protocol):
    """Daily rainfall for a place: the ward's CHIRPS series, or a TAHMO station."""
    name: str

    def daily(self, key: str, start: date, end: date) -> dict[date, float]: ...


class ChirpsFiles:
    """The ward CHIRPS daily files already in the repo (data/raw/chirps/<ward>.csv: date, rain_mm)."""
    name = "CHIRPS"

    def __init__(self, folder: Path):
        self.folder = Path(folder)

    def available(self, ward_id: str) -> bool:
        return (self.folder / f"{ward_id}.csv").exists()

    def series(self, ward_id: str) -> dict[date, float]:
        return _load(str(self.folder / f"{ward_id}.csv"))

    def daily(self, key: str, start: date, end: date) -> dict[date, float]:
        return {d: v for d, v in self.series(key).items() if start <= d <= end} if self.available(key) else {}

    def wettest_day_by_month(self, ward_id: str) -> dict[int, float]:
        out: dict[int, float] = {}
        for d, v in self.series(ward_id).items():
            out[d.month] = max(out.get(d.month, 0.0), v)
        return out

    def last_day(self, ward_id: str) -> date | None:
        return max(self.series(ward_id)) if self.available(ward_id) else None


@lru_cache(maxsize=8)
def _load(path: str) -> dict[date, float]:
    with open(path, newline="", encoding="utf-8") as f:
        return {date.fromisoformat(r["date"]): float(r["rain_mm"]) for r in csv.DictReader(f) if r.get("rain_mm")}


class TahmoBlocked(RuntimeError):
    pass


TAHMO_BLOCKED = (
    "TAHMO station data needs credentials that AgroShield does not have: a TAHMO API username and password (or "
    "token) under a data-sharing agreement with TAHMO, and the codes of the stations nearest each pilot ward. Per the "
    "brief, nobody has signed up or contacted TAHMO. Set TAHMO_API_USER and TAHMO_API_PASSWORD and list station codes "
    "in the device settings once the agreement exists.")


class TahmoAdapter:
    """BLOCKED STUB. The interface the TAHMO connection will fill: daily rainfall per station, for the same check
    the CHIRPS files feed. It makes no network call; with or without credentials it raises TahmoBlocked."""
    name = "TAHMO"

    def __init__(self, user: str | None = None, password: str | None = None):
        self.user, self.password = user, password

    def daily(self, key: str, start: date, end: date) -> dict[date, float]:
        raise TahmoBlocked(TAHMO_BLOCKED)


@dataclass
class Flag:
    start: date
    end: date
    kind: str            # wetter_than_satellite | drier_than_satellite | possible_blocked_funnel | unusually_heavy_day
    gauge_mm: float
    satellite_mm: float | None
    text: str


def dekads(start: date, end: date):
    """(first day, last day) of each dekad (1-10, 11-20, 21-end of month) wholly inside start..end."""
    d = start
    while d <= end:
        first = date(d.year, d.month, 1 if d.day <= 10 else 11 if d.day <= 20 else 21)
        if first.day < 21:
            last = first + timedelta(days=9)
        else:
            last = (first.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        if first >= start and last <= end:
            yield first, last
        d = last + timedelta(days=1)


def check_against_chirps(ward_id: str, gauge: dict[date, float], reported: set[date], chirps: ChirpsFiles,
                         start: date, end: date) -> list[Flag]:
    """Flags for a gauge's daily totals in start..end (see the module notes). Empty when CHIRPS has no ward file."""
    if not chirps.available(ward_id):
        return []
    sat = chirps.series(ward_id)
    flags: list[Flag] = []
    for first, last in dekads(start, end):
        days = [first + timedelta(days=i) for i in range((last - first).days + 1)]
        if not all(d in sat for d in days) or not all(d in reported for d in days):
            continue
        g, c = round(sum(gauge.get(d, 0.0) for d in days), 1), round(sum(sat[d] for d in days), 1)
        if g - c > DEKAD_GAP_MM and g > DEKAD_RATIO * c:
            flags.append(Flag(first, last, "wetter_than_satellite", g, c,
                              f"Gauge {g:.0f} mm, satellite {c:.0f} mm: much wetter than the satellite estimate."))
        elif c - g > DEKAD_GAP_MM and g < c / DEKAD_RATIO:
            kind = "possible_blocked_funnel" if g == 0 else "drier_than_satellite"
            flags.append(Flag(first, last, kind, g, c,
                              f"Gauge {g:.0f} mm, satellite {c:.0f} mm: " +
                              ("no rain recorded. Check the funnel is not blocked." if g == 0
                               else "much drier than the satellite estimate.")))
    wettest = chirps.wettest_day_by_month(ward_id)
    for d, g in sorted(gauge.items()):
        if start <= d <= end and wettest.get(d.month) and g > DAY_FACTOR * wettest[d.month]:
            flags.append(Flag(d, d, "unusually_heavy_day", round(g, 1), round(wettest[d.month], 1),
                              f"{g:.0f} mm in one day: more than twice the wettest satellite day on record for "
                              f"this ward in {d:%B} ({wettest[d.month]:.0f} mm). Check the gauge."))
    return flags
