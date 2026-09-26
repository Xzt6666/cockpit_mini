"""HMI 行为：行车时锁视频 + 首页小组件。

下面这张参数化表格就是 fixture 设计的价值所在：``vehicle_state``
保证每一行都从"干净的停车状态"开始，所以这些用例彼此独立、与执行顺序无关。
"""

import pytest

from rules import is_video_allowed

pytestmark = pytest.mark.hmi


@pytest.mark.parametrize(
    "speed, expected",
    [
        (0, True),     # 停着
        (4.9, True),   # 比阈值低一点点
        (5, False),    # 正好卡在阈值上 —— 锁定
        (120, False),  # 高速
    ],
    ids=["standstill", "crawling", "threshold", "highway"],
)
def test_video_lock_while_driving(vehicle_state, speed, expected):
    """纯规则：只有低于锁定车速才允许放视频。"""
    vehicle_state.set_signal("vehicle_speed", speed)
    assert is_video_allowed(vehicle_state.get_signal("vehicle_speed")) is expected


@pytest.mark.smoke
def test_home_widgets_visible_at_standstill(hmi_home):
    """停车时首页上的核心组件应该都在。"""
    for widget in ("clock", "speed", "media", "nav"):
        assert hmi_home.is_widget_visible(widget), widget


def test_video_widget_locks_with_speed(hmi_home):
    """页面层：小组件必须跟着同一条规则走。

    初版是把可见性写死成一张清单；现在改成由实时车速推导，
    这样界面和规则就不可能出现"两套说法"。
    """
    hmi_home.cockpit.set_signal("vehicle_speed", 0)
    assert hmi_home.is_widget_visible("video")
    hmi_home.cockpit.set_signal("vehicle_speed", 80)
    assert not hmi_home.is_widget_visible("video")


def test_closed_page_hides_everything(hmi_home):
    """页面关掉之后，任何组件都不该再显示。"""
    hmi_home.close()
    assert not hmi_home.is_widget_visible("clock")
    assert not hmi_home.is_widget_visible("video")
