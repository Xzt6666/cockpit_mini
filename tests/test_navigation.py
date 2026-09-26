"""Navigation: ETA arithmetic + invalid-input handling.

``pytest.approx`` avoids the classic 0.1 + 0.2 != 0.3 float trap;
``pytest.raises`` asserts the rule *must* reject garbage input.
"""

import pytest

from rules import estimate_eta_hours

pytestmark = pytest.mark.navigation


@pytest.mark.parametrize(
    "dist, speed, expected",
    [
        (100, 100, 1.0),
        (30, 60, 0.5),
        (45, 90, 0.5),
        (7.5, 30, 0.25),
    ],
    ids=["highway", "city", "balanced", "fractional"],
)
def test_eta_normal(dist, speed, expected):
    assert estimate_eta_hours(dist, speed) == pytest.approx(expected)


@pytest.mark.smoke
def test_eta_rejects_zero_speed():
    with pytest.raises(ValueError, match="speed must be positive"):
        estimate_eta_hours(10, 0)


def test_eta_rejects_negative_speed():
    # A reversed GPS fix could produce this; rule must not silently
    # return a negative "time".
    with pytest.raises(ValueError, match="speed must be positive"):
        estimate_eta_hours(10, -5)


def test_eta_rejects_negative_distance():
    with pytest.raises(ValueError, match="distance"):
        estimate_eta_hours(-1, 60)
