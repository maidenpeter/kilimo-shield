"""FAO-56 Hargreaves reference evapotranspiration.

    ET0 = 0.0023 * (Tmean + 17.8) * sqrt(Tmax - Tmin) * Ra        (FAO-56 eq. 52)

with Ra the extraterrestrial radiation (FAO-56 eq. 21) expressed as mm/day of
evaporation (x 0.408). Hargreaves needs only temperature, so it is the fallback
when Penman-Monteith PET (FEWS NET GDAS) is unavailable. It tends to overstate
PET in humid conditions; every output using it says so.
"""
from __future__ import annotations

import numpy as np

GSC = 0.0820  # solar constant, MJ m-2 min-1


def extraterrestrial_radiation(lat_deg: float, doy) -> np.ndarray:
    """Ra in MJ m-2 day-1 for latitude (degrees) and day of year (1-366)."""
    j = np.asarray(doy, dtype=float)
    phi = np.radians(lat_deg)
    dr = 1 + 0.033 * np.cos(2 * np.pi * j / 365)
    delta = 0.409 * np.sin(2 * np.pi * j / 365 - 1.39)
    ws = np.arccos(np.clip(-np.tan(phi) * np.tan(delta), -1, 1))
    return (24 * 60 / np.pi) * GSC * dr * (ws * np.sin(phi) * np.sin(delta)
                                           + np.cos(phi) * np.cos(delta) * np.sin(ws))


def hargreaves_et0(tmax, tmin, lat_deg: float, doy) -> np.ndarray:
    """Daily ET0 in mm from max/min air temperature (deg C)."""
    tmax, tmin = np.asarray(tmax, float), np.asarray(tmin, float)
    ra_mm = 0.408 * extraterrestrial_radiation(lat_deg, doy)
    tmean = (tmax + tmin) / 2
    return 0.0023 * (tmean + 17.8) * np.sqrt(np.clip(tmax - tmin, 0, None)) * ra_mm
