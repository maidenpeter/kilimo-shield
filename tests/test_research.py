"""Checks on the research 3b helpers (verification maths and the GeoTIFF reader)."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "research"))

import skill  # noqa: E402
from early_trigger import _packbits  # noqa: E402


def test_leave_one_out_tercile_excludes_the_season_itself():
    x = pd.Series([10.0, 20, 30, 40, 50, 60], index=range(2000, 2006))
    below = skill.loo_lower_tercile(x)
    # 2000 (10 mm) is below the lower tercile of the other five years; 2005 (60 mm) is not.
    assert below[2000] and not below[2005]
    # With itself excluded, 20 mm is compared with 10, 30, 40, 50, 60 (P33 = 30): below.
    assert below[2001]


def test_roc_area_perfect_random_and_inverted():
    event = np.array([1, 1, 0, 0, 0, 0], bool)
    assert skill.roc_auc(np.array([0.9, 0.8, 0.3, 0.2, 0.1, 0.4]), event) == 1.0
    assert skill.roc_auc(np.array([0.1, 0.2, 0.8, 0.9, 0.7, 0.6]), event) == 0.0
    assert skill.roc_auc(np.full(6, 0.5), event) == 0.5
    assert skill.roc_auc(np.ones(3), np.ones(3, bool)) is None


def test_correlation_interval_contains_r_and_narrows_with_n():
    rng = np.random.default_rng(0)
    x = rng.normal(size=200)
    y = 0.5 * x + rng.normal(size=200)
    big = skill.corr_ci(x, y)
    small = skill.corr_ci(x[:30], y[:30])
    assert big["ci95"][0] < big["r"] < big["ci95"][1]
    assert (big["ci95"][1] - big["ci95"][0]) < (small["ci95"][1] - small["ci95"][0])


def test_threshold_scores():
    p = pd.Series([0.6, 0.5, 0.2, 0.5, 0.1], index=range(5))
    b = pd.Series([True, True, False, False, False], index=range(5))
    row = next(r for r in skill.scores(p, b)["by_threshold"] if r["threshold"] == 0.45)
    assert row["triggers"] == 3 and row["hit_rate"] == 1.0
    assert row["false_alarm_rate"] == pytest.approx(1 / 3) and row["false_alarm_ratio"] == pytest.approx(1 / 3)


def test_packbits_decoder():
    # TIFF 6.0 PackBits example: header -3 repeats the next byte 4 times; 2 copies 3 literal bytes.
    assert _packbits(bytes([0xFD, 0xAA, 0x02, 0x80, 0x00, 0x2A])) == bytes([0xAA] * 4 + [0x80, 0x00, 0x2A])
    assert _packbits(bytes([0x80, 0x01, 0x05])) == bytes([0x05])   # -128 is a no-op
