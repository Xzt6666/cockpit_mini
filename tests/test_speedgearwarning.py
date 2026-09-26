"""动力告警与互锁：超速提醒、挡位互锁、倒车影像。

这三块是安全相关的规则——漏掉一个边界就是一次现场问题，所以下面
的参数化表格特意把阈值本身（4.9 / 5、119.9 / 120）一条条测过去。
"""

import pytest

pytestmark = pytest.mark.speedgearwarning


# ---------------------------------------------------------------------------
# 超速提醒
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "speed, expected_level",
    [
        (0, "none"),          # 停着
        (119.9, "none"),      # 差一点点到阈值
        (120, "overspeed"),   # 正好卡在阈值上 → 提醒
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
    """每评估一次超速就响一声，次数要能数得出来。"""
    vehicle_state.set_signal("vehicle_speed", 130)
    page = vehicle_state.open_hmi_page("home")
    page.check_speed_warning()
    page.check_speed_warning()
    assert vehicle_state.event_count("warning_chime:overspeed") == 2


# ---------------------------------------------------------------------------
# 挡位互锁
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "speed, expected",
    [
        (0, True),
        (4.9, True),    # 龟速，仍然允许挂 P
        (5, False),     # 正好卡在阈值上 → 拒绝
        (60, False),
    ],
    ids=["parked", "crawling", "threshold", "moving"],
)
def test_park_lock_while_moving(vehicle_state, speed, expected):
    # 先挂到 D，这样"成功挂上 P"才是可观察的。
    vehicle_state.set_signal("gear", "D")
    vehicle_state.set_signal("vehicle_speed", speed)
    assert vehicle_state.set_gear("P") is expected
    if expected:
        assert vehicle_state.gear() == "P"
    else:
        # 被拒绝的挂挡：挡位不能变，而且必须留下证据。
        assert vehicle_state.gear() == "D"
        assert vehicle_state.event_count("gear_shift:P:rejected") == 1


def test_drive_gear_allowed_at_any_speed(vehicle_state):
    """D 和 N 任何车速都能挂，只有 P/R 受互锁限制。"""
    vehicle_state.set_signal("vehicle_speed", 100)
    assert vehicle_state.set_gear("D")
    assert vehicle_state.gear() == "D"


def test_reverse_rejected_while_moving(vehicle_state):
    """车还在动就挂 R，会打坏变速箱，必须拒绝。"""
    vehicle_state.set_signal("vehicle_speed", 30)
    assert not vehicle_state.set_gear("R")
    assert vehicle_state.gear() == "P"
    assert vehicle_state.event_count("gear_shift:R:rejected") == 1


def test_invalid_gear_rejected(vehicle_state):
    """换挡杆传来的垃圾数据（比如总线被干扰）必须被挡在入口。"""
    assert not vehicle_state.set_gear("X")
    with pytest.raises(ValueError, match="非法挡位"):
        vehicle_state.set_signal("gear", "X")


# ---------------------------------------------------------------------------
# 倒车影像
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
    """挂出 R 挡之后，倒车影像必须立刻消失。"""
    camera = vehicle_state.open_hmi_page("camera")
    vehicle_state.set_signal("gear", "R")
    assert camera.is_widget_visible("reverse_camera")
    vehicle_state.set_signal("gear", "D")
    assert not camera.is_widget_visible("reverse_camera")
