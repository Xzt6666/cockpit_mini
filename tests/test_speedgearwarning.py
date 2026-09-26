"""Powertrain warnings & interlocks: over-speed, gear shift, reverse camera.

These are the safety-relevant rules: a missed case here means a field
issue, so the tables deliberately probe the exact threshold values.
"""

import pytest

pytestmark = pytest.mark.speedgearwarning


# ---------------------------------------------------------------------------
# Over-speed warning
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "speed, expected_level",
    [
        (0, "none"),
        (119.9, "none"),   # just below the threshold
        (120, "overspeed"),  # exactly at the threshold -> warn
        (180, "overspeed"),
    ],
    ids=["standstill", "just_below", "threshold", "way_over"],
)
def test_speed_warning_threshold(vehicle_state, speed, expected_level):
    vehicle_state.set_signal("vehicle_speed", speed)
    page = vehicle_state.open_hmi_page("home")
    assert page.check_speed_warning() == expected_level


@pytest.mark.smoke
def test_overspeed_chimes_every_check(vehicle_state):
    """Every evaluation above the threshold raises the chime event."""
    vehicle_state.set_signal("vehicle_speed", 130)
    page = vehicle_state.open_hmi_page("home")
    page.check_speed_warning()
    page.check_speed_warning()
    assert vehicle_state.event_count("warning_chime:overspeed") == 2


# ---------------------------------------------------------------------------
# Gear interlock
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "speed, expected",
    [
        (0, True),
        (4.9, True),   # crawling -> still allowed
        (5, False),    # at the threshold -> rejected (draft had >, spec is >=)
        (60, False),
    ],
    ids=["parked", "crawling", "threshold", "moving"],
)
def test_park_lock_while_moving(vehicle_state, speed, expected):
    # Start in D so a successful shift to P is actually observable.
    vehicle_state.set_signal("gear", "D")
    vehicle_state.set_signal("vehicle_speed", speed)
    assert vehicle_state.set_gear("P") is expected
    if expected:
        assert vehicle_state.gear() == "P"
    else:
        # Rejected shifts leave the gear untouched AND leave evidence.
        assert vehicle_state.gear() == "D"
        assert vehicle_state.event_count("gear_shift:P:rejected") == 1


def test_drive_gear_allowed_at_any_speed(vehicle_state):
    """D is always selectable; N too -- only P/R are interlocked."""
    vehicle_state.set_signal("vehicle_speed", 100)
    assert vehicle_state.set_gear("D")
    assert vehicle_state.gear() == "D"


def test_reverse_rejected_while_moving(vehicle_state):
    """Shifting to R at speed would damage the transmission."""
    vehicle_state.set_signal("vehicle_speed", 30)
    assert not vehicle_state.set_gear("R")
    assert vehicle_state.gear() == "P"
    assert vehicle_state.event_count("gear_shift:R:rejected") == 1


def test_invalid_gear_rejected(vehicle_state):
    """Garbage from the shifter (e.g. bus corruption) must be rejected."""
    assert not vehicle_state.set_gear("X")
    with pytest.raises(ValueError, match="invalid gear"):
        vehicle_state.set_signal("gear", "X")


# ---------------------------------------------------------------------------
# Reverse camera
# ---------------------------------------------------------------------------


@pytest.mark.smoke
def test_reverse_camera_only_in_r(vehicle_state):
    camera = vehicle_state.open_hmi_page("camera")
    vehicle_state.set_signal("gear", "D")
    assert not camera.is_widget_visible("reverse_camera")
    vehicle_state.set_signal("vehicle_speed", 0)
    assert vehicle_state.set_gear("R")
    assert camera.is_widget_visible("reverse_camera")


def test_reverse_camera_disappears_after_shift_out(vehicle_state):
    camera = vehicle_state.open_hmi_page("camera")
    vehicle_state.set_signal("gear", "R")
    assert camera.is_widget_visible("reverse_camera")
    vehicle_state.set_signal("gear", "D")
    assert not camera.is_widget_visible("reverse_camera")
