"""HMI behaviour: video lock while driving + home-page widgets.

The parametrized table below is the whole point of the fixture design:
``vehicle_state`` guarantees each row starts from a clean standstill
snapshot, so the cases are independent and order-free.
"""

import pytest

from rules import is_video_allowed

pytestmark = pytest.mark.hmi


@pytest.mark.parametrize(
    "speed, expected",
    [
        (0, True),    # standstill
        (4.9, True),  # just below the threshold
        (5, False),   # exactly at the threshold -> locked
        (120, False),  # highway speed -> locked
    ],
    ids=["standstill", "crawling", "threshold", "highway"],
)
def test_video_lock_while_driving(vehicle_state, speed, expected):
    """Pure rule check: video allowed only below the lock speed."""
    vehicle_state.set_signal("vehicle_speed", speed)
    current = vehicle_state.get_signal("vehicle_speed")
    assert is_video_allowed(current) is expected


@pytest.mark.smoke
def test_home_widgets_visible_at_standstill(hmi_home):
    """Core widgets are always on the home page when parked."""
    for widget in ("clock", "speed", "media", "nav"):
        assert hmi_home.is_widget_visible(widget), widget


def test_video_widget_locks_with_speed(hmi_home):
    """HMI level: the *widget* follows the same rule as the pure rule.

    Draft version hard-coded widget visibility; here the page derives it
    from the live speed signal, so UI and policy can never drift apart.
    """
    hmi_home.cockpit.set_signal("vehicle_speed", 0)
    assert hmi_home.is_widget_visible("video")
    hmi_home.cockpit.set_signal("vehicle_speed", 80)
    assert not hmi_home.is_widget_visible("video")


def test_closed_page_hides_everything(hmi_home):
    """A closed page must not render any widget."""
    hmi_home.close()
    assert not hmi_home.is_widget_visible("clock")
    assert not hmi_home.is_widget_visible("video")
