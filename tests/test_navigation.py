"""导航：ETA 计算 + 非法输入处理。

两个 pytest 的常用技巧在这里各出现一次：
``pytest.approx`` 绕开"浮点数不能直接比相等"的坑（0.1 + 0.2 != 0.3）；
``pytest.raises`` 断言规则**必须**拒绝垃圾输入。
"""

import pytest

from rules import estimate_eta_hours

pytestmark = pytest.mark.navigation


@pytest.mark.parametrize(
    "distance, speed, expected",
    [
        (100, 100, 1.0),   # 高速，整一小时
        (30, 60, 0.5),     # 市区，半小时
        (7.5, 30, 0.25),   # 带小数的距离
    ],
    ids=["highway", "city", "fractional"],
)
def test_eta_normal(distance, speed, expected):
    assert estimate_eta_hours(distance, speed) == pytest.approx(expected)


@pytest.mark.smoke
@pytest.mark.parametrize(
    "distance, speed, message",
    [
        (10, 0, "速度必须为正数"),
        (10, -5, "速度必须为正数"),   # GPS 定位翻转可能产生负速度
        (-1, 60, "距离不能为负数"),
    ],
    ids=["zero_speed", "negative_speed", "negative_distance"],
)
def test_eta_rejects_invalid_input(distance, speed, message):
    with pytest.raises(ValueError, match=message):
        estimate_eta_hours(distance, speed)
