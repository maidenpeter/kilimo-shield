"""Research 3b(e): where in semi-arid eastern Kenya is October-December the main maize season?

CHIRPS v2.0 monthly over 37-39.5E, 3.5-0.5S (Machakos, Makueni, Kitui), 1981-2016:
the years available as uncompressed CHC Africa BIL files (see research/fetch_data.py).
For each 0.05-degree cell:
  MAM and OND mean totals, OND share of the two, OND coefficient of variation,
  and how often each season reaches MAIZE_MIN_MM (a rough floor for a maize crop).
A cell is a short-rains candidate when OND is wetter than MAM on average AND OND
reaches MAIZE_MIN_MM in at least RELIABLE_SHARE of years. Report only: candidates
are not added to the pilot config.

No county boundary data is used; places are named by the nearest town (approx.).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
NPZ = REPO / "data" / "raw" / "research" / "chirps_monthly_eastern_kenya.npz"
MAIZE_MIN_MM = 250
RELIABLE_SHARE = 0.6
TOWNS = {  # approximate coordinates (lat, lon), for orientation only
    "Machakos": (-1.52, 37.26), "Tala": (-1.27, 37.32), "Mwala": (-1.35, 37.45), "Wote (Makueni)": (-1.78, 37.63),
    "Mbooni": (-1.62, 37.45), "Emali": (-2.08, 37.47), "Kathonzweni": (-1.98, 37.74), "Kibwezi": (-2.41, 37.97),
    "Mtito Andei": (-2.69, 38.17), "Kitui": (-1.37, 38.01), "Mwingi": (-0.93, 38.06), "Mutomo": (-1.85, 38.21),
    "Ikutha": (-2.07, 38.18), "Kyuso": (-0.56, 38.21), "Mutitu": (-1.20, 38.60),
}


def nearest_town(lat: float, lon: float) -> str:
    name, (tl, tn) = min(TOWNS.items(), key=lambda kv: (kv[1][0] - lat) ** 2 + (kv[1][1] - lon) ** 2)
    km = 111 * np.hypot(tl - lat, (tn - lon) * np.cos(np.radians(lat)))
    return f"{name} ({km:.0f} km)"


def load() -> dict:
    if not NPZ.exists():
        raise FileNotFoundError(f"{NPZ} missing; run research/fetch_data.py eastern-bil")
    d = np.load(NPZ)
    p = d["precip"].astype(float)          # [year, month, lat, lon], mm/month
    p[p < 0] = np.nan                      # nodata
    return {"p": p, "years": d["years"], "months": list(d["months"]), "lat": d["lat"], "lon": d["lon"]}


def scan() -> dict:
    d = load()
    p, months, y, x, yrs = d["p"], d["months"], d["lat"], d["lon"], d["years"]
    pick = lambda ms: [months.index(m) for m in ms]  # noqa: E731
    mam = p[:, pick([3, 4, 5])].sum(axis=1)        # [year, lat, lon]
    ond = p[:, pick([10, 11, 12])].sum(axis=1)
    mam_mean, ond_mean = mam.mean(axis=0), ond.mean(axis=0)
    ond_share = ond_mean / (ond_mean + mam_mean)
    ond_cv = ond.std(axis=0, ddof=1) / ond_mean
    ond_ok = (ond >= MAIZE_MIN_MM).mean(axis=0)
    mam_ok = (mam >= MAIZE_MIN_MM).mean(axis=0)
    candidate = (ond_mean > mam_mean) & (ond_ok >= RELIABLE_SHARE)

    cells = []
    for j, lat in enumerate(y):
        for i, lon in enumerate(x):
            if np.isnan(ond_mean[j, i]):
                continue
            cells.append({"lat": float(lat), "lon": float(lon), "mam_mm": float(mam_mean[j, i]), "ond_mm": float(ond_mean[j, i]),
                          "ond_share": float(ond_share[j, i]), "ond_cv": float(ond_cv[j, i]),
                          "ond_reliable": float(ond_ok[j, i]), "mam_reliable": float(mam_ok[j, i]),
                          "candidate": bool(candidate[j, i])})
    cand = [c for c in cells if c["candidate"]]
    # Group candidates by nearest town for a readable summary.
    groups: dict[str, list[dict]] = {}
    for c in cand:
        groups.setdefault(nearest_town(c["lat"], c["lon"]).split(" (")[0], []).append(c)
    summary = sorted(({"near": k, "cells": len(v), "area_km2": round(len(v) * 5.55 ** 2),
                       "ond_mm": float(np.mean([c["ond_mm"] for c in v])), "mam_mm": float(np.mean([c["mam_mm"] for c in v])),
                       "ond_reliable": float(np.mean([c["ond_reliable"] for c in v])),
                       "ond_cv": float(np.mean([c["ond_cv"] for c in v])),
                       "best": max(v, key=lambda c: (c["ond_reliable"], c["ond_mm"]))} for k, v in groups.items()),
                     key=lambda g: (-g["ond_reliable"], -g["cells"]))
    return {"years": [int(yrs.min()), int(yrs.max())], "grid": {"lon": [float(x.min()), float(x.max())],
            "lat": [float(y.min()), float(y.max())], "cells": len(cells)},
            "rule": {"maize_min_mm": MAIZE_MIN_MM, "reliable_share": RELIABLE_SHARE},
            "ond_main_cells": int(sum(c["ond_mm"] > c["mam_mm"] for c in cells)),
            "candidate_cells": len(cand), "by_town": summary, "cells": cells}


if __name__ == "__main__":
    r = scan()
    print({k: v for k, v in r.items() if k not in ("cells", "by_town")})
    for g in r["by_town"][:12]:
        print(f"  near {g['near']:<16} {g['cells']:>4} cells  OND {g['ond_mm']:.0f} mm vs MAM {g['mam_mm']:.0f} mm, "
              f"OND >= {MAIZE_MIN_MM} mm in {g['ond_reliable']:.0%} of years, CV {g['ond_cv']:.2f}")
