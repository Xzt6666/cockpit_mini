"""座舱的业务规则（纯函数，不依赖任何 Mock）。

这个模块里每个函数都是从"输入"到"输出"的纯映射：不碰 Mock 对象、
不做 I/O、不存任何状态。好处是它们可以被极简单地单元测试——给一个
值，断言一个结果，不需要任何准备和清理。

这也正是真实项目的分层方式：**策略**（本模块）和**机制**
（``cockpit_mock.py``）分开。规则改了只动这里，硬件模型改了只动那边。

模块里的常量都是"系统需求规格"的替身。真实项目里这些阈值来自需求文档，
这里写成常量方便在测试里引用和讨论边界值。
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# 领域常量（系统需求规格的替身）
# ---------------------------------------------------------------------------

#: 车速达到或超过这个值（km/h）就锁定中控屏视频。
VIDEO_LOCK_SPEED_KMH: float = 5.0

#: 超速提示的阈值（km/h）。
OVERSPEED_WARNING_KMH: float = 120.0

#: 合法的 PRND 挡位。
GEARS: tuple[str, ...] = ("P", "R", "N", "D")

#: 支持的 NOMI 唤醒词（已归一化：转小写、去空格）。
_WAKE_WORDS: frozenset[str] = frozenset({"hinomi", "你好nomi"})


# ---------------------------------------------------------------------------
# HMI / 车机娱乐规则
# ---------------------------------------------------------------------------


def is_video_allowed(speed_kmh: float) -> bool:
    """车速是否允许在中控屏放视频。

    安全规则：只有车几乎停住（低于 ``VIDEO_LOCK_SPEED_KMH``）才允许放视频。
    """
    return speed_kmh < VIDEO_LOCK_SPEED_KMH


def nomi_wake_response(wake_word: str | None) -> str:
    """NOMI 语音助手对一个候选唤醒词的回应。

    匹配时忽略大小写和空格，所以 ``"HI NOMI"`` 和 ``"你好NOMI"`` 都能唤醒
    ——真实的 NOMI 同时支持中英文唤醒词。

    传入 ``None`` 表示语音识别那一环压根没产出文本（比如空音频帧），
    这时安全地返回 ``"none"``，而不是抛 AttributeError。
    """
    if not wake_word:
        return "none"
    normalized = wake_word.lower().replace(" ", "")
    return "activated" if normalized in _WAKE_WORDS else "none"


def estimate_eta_hours(distance_km: float, speed_kmh: float) -> float:
    """估算剩余路程需要多少小时。

    抛出：
        ValueError：速度为 0 或负数、距离为负数时。这两种输入如果不拦住，
            会悄悄算出一个毫无意义的预计到达时间。
    """
    if speed_kmh <= 0:
        raise ValueError("速度必须为正数")
    if distance_km < 0:
        raise ValueError("距离不能为负数")
    return distance_km / speed_kmh


# ---------------------------------------------------------------------------
# 动力 / 告警规则
# ---------------------------------------------------------------------------


def speed_warning_level(speed_kmh: float) -> str:
    """判断当前车速对应的超速告警等级。

    达到或超过 ``OVERSPEED_WARNING_KMH`` 返回 ``"overspeed"``，否则 ``"none"``。
    """
    return "overspeed" if speed_kmh >= OVERSPEED_WARNING_KMH else "none"


def can_shift_gear(target_gear: str, speed_kmh: float) -> tuple[bool, str]:
    """挡位互锁规则。

    车还在动的时候挂 P（驻车锁）或 R（倒挡）会打坏变速箱，所以这两个挡位
    都要求车速低于 ``VIDEO_LOCK_SPEED_KMH``。N 和 D 任何车速都能挂。

    返回：
        ``(是否允许, 原因)``。返回原因是为了让测试能断言"被拒绝的具体理由"，
        而不只是断言一个 True/False。
    """
    if target_gear not in GEARS:
        return False, "目标挡位非法"
    if target_gear in ("P", "R") and speed_kmh >= VIDEO_LOCK_SPEED_KMH:
        return (
            False,
            f"挂 {target_gear} 挡要求车速低于 {VIDEO_LOCK_SPEED_KMH:g} km/h",
        )
    return True, "ok"


def is_reverse_camera_active(gear: str) -> bool:
    """倒车影像只在 R 挡时才送到中控屏。"""
    return gear == "R"
