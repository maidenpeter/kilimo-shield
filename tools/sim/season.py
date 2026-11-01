"""SIMULATION / REPLAY of one long-rains season at Ward A (Rongai West), end to end, with fictional members.

    .venv/Scripts/python tools/sim/season.py               # 2008, the real drought in the CHIRPS record
    .venv/Scripts/python tools/sim/season.py --year 2008 --out some/folder

Writes docs/remaining/season-<year>/index.html, season.json and bordereaux/*.zip. Runs in a throwaway database
that is deleted afterwards; never touches var/agroshield.db, never sends an SMS or moves money.
See agroshield_platform/simulate.py.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))          # this checkout's code, even if another copy is installed

from agroshield_platform.simulate import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
