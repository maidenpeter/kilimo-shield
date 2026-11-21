import pytest

from ui import theme


@pytest.mark.parametrize("value,expected", [
    (0, "KSh 0"), (0.5, "KSh 1"), (2.5, "KSh 3"), (-2.5, "KSh -3"), (999.4, "KSh 999"), (999.5, "KSh 1,000"),
    (5_160, "KSh 5,160"), (13_529.23, "KSh 13,529"),
])
def test_ksh_rounds_half_up(value, expected):
    assert theme.ksh(value) == expected


@pytest.mark.parametrize("value,expected", [
    (950, "KSh 950"), (1_000, "KSh 1.0k"), (13_529.23, "KSh 13.5k"), (999_949, "KSh 999.9k"),
    (999_950, "KSh 1.0m"), (76_500_000, "KSh 76.5m"), (999_950_000, "KSh 1.0bn"), (-1_234_567, "KSh -1.2m"),
])
def test_ksh_short_picks_the_unit_after_rounding(value, expected):
    assert theme.ksh_short(value) == expected
