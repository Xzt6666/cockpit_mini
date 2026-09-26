"""内存中的"数字座舱域控制器"模拟实现。

真实项目里这一层要通过 ADB / CAN / 以太网去连台架或 HIL 设备。
这里把每一处"硬件行为"都降级成普通的 Python 状态，于是测试套件
在任意一台机器上都能确定性地跑，不需要真车。

四个部分
--------
* :class:`MockCockpit` —— 域控制器本体：上下电状态、车辆信号、
  一份只追加的事件日志（测试可以断言"提示音正好响过一次"）。
* :class:`HmiPage` —— 中控屏的一个页面。小组件的可见性由**实时车辆状态
  推导**出来，而不是写死一张清单，这样页面行为才像真实 HMI
  （车速一上来视频就锁、挂 R 挡才出现倒车影像）。
* :class:`MockVoiceAssistant` / :class:`MockBluetoothModule` —— 两个
  外设的状态机。

车辆信号有两条来路
------------------
``set_signal()`` 是"台架捷径"，直接给信号赋值，适合测纯规则；
``receive_can_frame()`` 走真实链路——信号以 CAN 报文到达、按
``dbc/cockpit.dbc`` 解码、再进入策略层。两条路最终汇入同一套规则，
所以 HMI 的表现和用哪种方式驱动无关。

每个类都提供 ``reset()``，让函数级 fixture 能在用例之间把共享资源
恢复干净，避免用例互相影响。
"""

from __future__ import annotations

from can_bus import CanBus, CanFrame, load_database
from rules import (
    GEARS,
    can_shift_gear,
    is_reverse_camera_active,
    is_video_allowed,
    nomi_wake_response,
    speed_warning_level,
)

#: 首页上始终存在的小组件。
_HOME_WIDGETS: tuple[str, ...] = ("clock", "speed", "media", "nav")

#: 还要额外满足"视频解锁条件"才显示的小组件。
_VIDEO_WIDGETS: frozenset[str] = frozenset({"video", "media_video"})

#: DBC 里的信号名 -> 座舱内部的信号名。
#: 只映射座舱真正会用的信号，其余信号照常解码但被忽略。
_CAN_SIGNAL_MAP: dict[str, str] = {
    "VehicleSpeed": "vehicle_speed",
    "GearPosition": "gear",
}


class MockCockpit:
    """假的座舱域控制器（对应真实项目里的"硬件资源"）。"""

    def __init__(self) -> None:
        self._signals: dict[str, float | str] = {}
        self._events: list[str] = []
        self._powered = False
        # 挂在域控制器下面的子设备。
        self.voice = MockVoiceAssistant()
        self.bluetooth = MockBluetoothModule()
        # 模拟 CAN 总线，由项目自带的 DBC 文件驱动。
        self.can_bus = CanBus(load_database())

    # -- 上下电 -----------------------------------------------------------

    def power_on(self) -> None:
        self._powered = True
        self.log_event("power_on")

    def power_off(self) -> None:
        self._powered = False
        self.log_event("power_off")

    @property
    def is_powered(self) -> bool:
        return self._powered

    # -- 车辆信号 ---------------------------------------------------------

    def set_signal(self, name: str, value: float | str) -> None:
        """写入一个车辆信号，比如 ``vehicle_speed``、``gear``。

        这里做输入校验，模拟"信号本身不可能是负车速、不可能是 P/R/N/D
        以外的挡位"——坏数据应当在入口就被挡住。
        """
        assert self._powered, "座舱未上电"
        if name == "vehicle_speed":
            if not isinstance(value, (int, float)):
                raise TypeError("vehicle_speed 必须是数字")
            if value < 0:
                raise ValueError("vehicle_speed 不能为负")
        elif name == "gear":
            if value not in GEARS:
                raise ValueError(f"非法挡位：{value!r}")
        self._signals[name] = value

    def get_signal(self, name: str) -> float | str:
        """读取车辆信号。

        没收到过的信号返回安全默认值（车速 0、挡位 P），而不是抛 KeyError
        ——真实网关也是这么给默认值的。
        """
        return self._signals.get(name, 0 if name == "vehicle_speed" else "P")

    def speed_kmh(self) -> float:
        return float(self.get_signal("vehicle_speed"))

    def gear(self) -> str:
        return str(self.get_signal("gear"))

    # -- 事件日志 ---------------------------------------------------------

    def log_event(self, event: str) -> None:
        """往只追加的事件日志里记一笔（提示音、状态切换等）。"""
        self._events.append(event)

    def event_count(self, event: str) -> int:
        """某个事件出现了几次。"""
        return self._events.count(event)

    def clear_events(self) -> None:
        self._events.clear()

    # -- 重置 -------------------------------------------------------------

    def reset(self) -> None:
        """把整个控制器恢复到"刚上电"的样子。"""
        self._signals.clear()
        self._events.clear()
        self.voice.reset()
        self.bluetooth.reset()
        self.can_bus.clear_trace()

    # -- HMI --------------------------------------------------------------

    def open_hmi_page(self, page_name: str) -> "HmiPage":
        return HmiPage(self, page_name)

    # -- 由上电信号驱动的动力行为 ------------------------------------------

    def set_gear(self, target_gear: str) -> bool:
        """尝试挂挡，会走挡位互锁规则。

        返回 True 表示挂挡成功。被拒绝时也会记进事件日志，
        这样测试能断言"拒绝的原因"，而不只是一个布尔值。
        """
        allowed, reason = can_shift_gear(target_gear, self.speed_kmh())
        if allowed:
            self.set_signal("gear", target_gear)
        self.log_event(f"gear_shift:{target_gear}:{'ok' if allowed else 'rejected'}")
        return allowed

    # -- CAN 总线 ---------------------------------------------------------

    def receive_can_frame(self, frame: CanFrame) -> dict[str, float | str]:
        """接收一帧 CAN 报文，解码后应用到车辆状态。

        这是台架/HIL 会走的路径：信号先以报文形式到达，按 DBC 解出物理值，
        再进入策略层。返回解码结果，方便测试断言"总线上到底送来了什么"。
        """
        decoded = self.can_bus.receive(frame)
        for dbc_name, signal_name in _CAN_SIGNAL_MAP.items():
            if dbc_name in decoded:
                self.set_signal(signal_name, decoded[dbc_name])
        self.log_event(f"can_rx:{frame.arbitration_id:#x}")
        return decoded

    def broadcast_vehicle_dynamics(self) -> CanFrame:
        """把当前车速和挡位编码成 VehicleDynamics 报文发出去。"""
        return self.can_bus.send(
            "VehicleDynamics",
            {"VehicleSpeed": self.speed_kmh(), "GearPosition": self.gear()},
        )


class HmiPage:
    """中控屏的一个页面，绑定在实时车辆状态上。"""

    def __init__(self, cockpit: MockCockpit, name: str) -> None:
        self.cockpit = cockpit
        self.name = name
        self.opened = True

    def is_widget_visible(self, widget: str) -> bool:
        """小组件是否可见——由"当前页面 + 实时信号"共同决定。

        初版是写死一张清单；真实 HMI 会随车速锁视频、挂 R 挡才出倒车影像。
        """
        if not self.opened:
            return False
        if self.name == "home":
            if widget in _HOME_WIDGETS:
                return True
            if widget in _VIDEO_WIDGETS:
                return is_video_allowed(self.cockpit.speed_kmh())
        if self.name == "camera" and widget == "reverse_camera":
            return is_reverse_camera_active(self.cockpit.gear())
        return False

    def close(self) -> None:
        self.opened = False

    # -- 由信号触发的行为 --------------------------------------------------

    def check_speed_warning(self) -> str:
        """重新评估超速规则，超速时响一声提示音。"""
        level = speed_warning_level(self.cockpit.speed_kmh())
        if level == "overspeed":
            self.cockpit.log_event("warning_chime:overspeed")
        return level


class MockVoiceAssistant:
    """NOMI 语音助手的模拟实现（一个简单的状态机）。"""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.active = False
        self.last_command: str | None = None
        self.rejected_inputs: list[str | None] = []

    def wake(self, wake_word: str | None) -> str:
        """喂一个候选唤醒词，并更新内部状态。"""
        response = nomi_wake_response(wake_word)
        if response == "activated":
            self.active = True
        else:
            # 被拒绝的输入也记下来，方便后续分析唤醒失败率。
            self.rejected_inputs.append(wake_word)
        return response

    def submit_command(self, command: str) -> str:
        """提交一条语音指令；要求助手已经处于唤醒状态。"""
        if not self.active:
            raise RuntimeError("语音助手未被唤醒")
        self.last_command = command
        return f"executed:{command}"


class MockBluetoothModule:
    """车载蓝牙模块的模拟实现（一个显式的状态机）。

    状态流转：``off -> pairing -> connected -> disconnected``，
    另外用 ``connection_lost`` 表示异常断开（手机走出范围、重启、
    开飞行模式等）。
    """

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.state = "off"
        self.paired_devices: list[str] = []
        self.connected_device: str | None = None

    # -- 配对 -------------------------------------------------------------

    def start_pairing(self) -> None:
        if self.state == "connected":
            raise RuntimeError("已有设备连接时不能开始配对")
        self.state = "pairing"

    def complete_pairing(self, device_name: str) -> None:
        if self.state != "pairing":
            raise RuntimeError("当前没有正在进行的配对")
        if device_name in self.paired_devices:
            raise RuntimeError(f"设备已配对过：{device_name}")
        self.paired_devices.append(device_name)
        self.state = "off"  # 配对完成后回到空闲，配对记录保留

    # -- 连接 -------------------------------------------------------------

    def connect(self, device_name: str) -> None:
        if device_name not in self.paired_devices:
            raise RuntimeError(f"设备未配对：{device_name}")
        if self.connected_device is not None:
            raise RuntimeError(f"已经连接了 {self.connected_device}")
        self.connected_device = device_name
        self.state = "connected"

    def disconnect(self) -> None:
        """用户在车机上主动断开。"""
        if self.connected_device is None:
            raise RuntimeError("没有已连接的设备")
        self.connected_device = None
        self.state = "disconnected"

    def simulate_connection_lost(self) -> None:
        """模拟异常断开：手机走出范围、重启、开飞行模式等。"""
        if self.connected_device is None:
            raise RuntimeError("没有已连接的设备")
        self.connected_device = None
        self.state = "connection_lost"
