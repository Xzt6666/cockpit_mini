"""CAN 报文编解码 + 一条模拟总线。

这一层的职责
------------
把"物理值"和"真实字节"互相翻译。左侧是人能看懂的量，右侧是总线上跑的东西：

    {"VehicleSpeed": 50.0}  →  f401030000000000

来龙去脉（以车速 50 km/h 为例）：

    50 km/h ÷ 0.1 = 500        ← 用 DBC 的系数做反算，得到"原始值"
    500 = 0x01F4               ← 原始值写成十六进制
    小端 = 低位字节在前        ← 所以是 f4 01，而不是 01 f4

解码就是反过来：从字节里按位拼出原始值 500，再 × 0.1 得到 50.0。

设计上的两个选择
----------------
* **超出范围就报错，绝不钳位。** 如果测试框架悄悄把 999 km/h 改成
  250 km/h，那它恰好掩盖了自己本该发现的问题。真要模拟"总线上的数据
  被破坏"，就手工构造字节（见 tests/test_can_bus.py）。
* **CanBus 会记录发过的每一帧。** 这样测试能断言"总线上到底跑过什么"，
  而不只是看函数的返回值——证据比结论更可信。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from dbc_parser import Database, Message, Signal, parse_dbc_file

#: 本项目自带的 DBC 文件。
DEFAULT_DBC_PATH = Path(__file__).parent / "dbc" / "cockpit.dbc"


class CanCodecError(ValueError):
    """报文或信号的取值不符合 DBC 定义时抛出。"""


@dataclass(frozen=True)
class CanFrame:
    """一帧经典 CAN：仲裁 ID + 最多 8 字节数据。"""

    arbitration_id: int
    data: bytes

    @property
    def dlc(self) -> int:
        """DLC（数据长度码），就是字节数。"""
        return len(self.data)

    def hex(self) -> str:
        """总线工具那样的显示格式：``0x100#F401030000000000``。"""
        return f"{self.arbitration_id:#05x}#{self.data.hex().upper()}"


# ---------------------------------------------------------------------------
# 位操作：整个编解码就靠这两个函数
# ---------------------------------------------------------------------------


def _get_bit(data: bytes, position: int) -> int:
    """读出第 position 位（0 或 1）。

    位号 → 字节号 = position // 8，字节内第几位 = position % 8。
    """
    return (data[position // 8] >> (position % 8)) & 1


def _put_bit(buffer: bytearray, position: int, value: int) -> None:
    """把第 position 位写成 value（0 或 1）。"""
    byte_index, bit_index = divmod(position, 8)
    if value:
        buffer[byte_index] |= 1 << bit_index          # 置 1：按位或
    else:
        buffer[byte_index] &= ~(1 << bit_index) & 0xFF  # 清 0：按位与取反


# ---------------------------------------------------------------------------
# 缩放：物理值 <-> 原始值
# ---------------------------------------------------------------------------


def physical_to_raw(signal: Signal, value: float | str) -> int:
    """物理值 → 原始整数。

    传字符串时会先查信号的 VAL_ 取值表，所以
    ``{"GearPosition": "D"}`` 和 ``{"GearPosition": 3}`` 是一回事。

    下面三种情况会报错，而不是悄悄糊弄过去：

    1. 字符串不在取值表里（比如挡位写了 "X"）
    2. 数值超出 DBC 定义的 [最小值|最大值]
    3. 换算出的原始值装不进信号的位宽
    """
    if isinstance(value, str):
        raw = signal.raw_of(value)
        if raw is None:
            raise CanCodecError(
                f"{signal.name}: 取值表里没有 {value!r}，"
                f"可选的是 {sorted(signal.value_table.values())}"
            )
        return raw

    if not signal.minimum <= value <= signal.maximum:
        raise CanCodecError(
            f"{signal.name}: {value} {signal.unit} 超出 DBC 定义范围 "
            f"[{signal.minimum:g}|{signal.maximum:g}]"
        )

    raw = round((value - signal.offset) / signal.factor)
    limit = (1 << signal.length) - 1
    if not 0 <= raw <= limit:
        raise CanCodecError(
            f"{signal.name}: 原始值 {raw} 装不进 {signal.length} 位（上限 {limit}）"
        )
    return raw


def raw_to_physical(signal: Signal, raw: int) -> float:
    """原始整数 → 物理值。"""
    return signal.to_physical(raw)


# ---------------------------------------------------------------------------
# 报文级编解码
# ---------------------------------------------------------------------------


def _check_length(message: Message, data: bytes) -> None:
    """检查字节数是否和 DBC 声明的一致。"""
    if len(data) != message.length:
        raise CanCodecError(
            f"报文 {message.name} 需要 {message.length} 字节，实际给了 {len(data)} 字节"
        )


def decode_raw(message: Message, signal: Signal, data: bytes) -> int:
    """从报文字节里取出某个信号的原始整数。

    做法：按位号从高位到低位，每读一位就把已有结果左移一位、再把这一位拼上。
    循环结束时 raw 就是该信号的原始值。
    """
    _check_length(message, data)
    raw = 0
    for position in signal.bits():
        raw = (raw << 1) | _get_bit(data, position)
    return raw


def decode_message(message: Message, data: bytes) -> dict[str, float | str]:
    """把整条报文解成 ``{信号名: 物理值或名字}``。

    信号在 DBC 里配了 VAL_ 取值表时返回名字（挡位 3 → ``"D"``），
    否则返回物理值（车速 500 → ``50.0``）。
    """
    _check_length(message, data)
    decoded: dict[str, float | str] = {}
    for name, signal in message.signals.items():
        raw = decode_raw(message, signal, data)
        label = signal.name_of(raw)
        decoded[name] = label if label is not None else signal.to_physical(raw)
    return decoded


def encode_message(message: Message, values: dict[str, float | str]) -> bytes:
    """把 ``{信号名: 值}`` 打包成报文字节。

    没提到的信号保持 0。信号名不存在时，``Message.signal()`` 会抛 KeyError。
    """
    buffer = bytearray(message.length)
    for name, value in values.items():
        signal = message.signal(name)
        raw = physical_to_raw(signal, value)
        # bits() 是"最高位在前"，所以第一个位号要放 raw 的最高位。
        for index, position in enumerate(signal.bits()):
            shift = signal.length - 1 - index
            _put_bit(buffer, position, (raw >> shift) & 1)
    return bytes(buffer)


# ---------------------------------------------------------------------------
# 模拟总线
# ---------------------------------------------------------------------------


@dataclass
class CanBus:
    """一条模拟 CAN 总线。

    和 MockCockpit 的事件日志一个思路：保留一份只追加的收发明细，
    测试就能断言"证据"，而不只是断言函数的返回值。
    """

    database: Database
    trace: list[CanFrame] = field(default_factory=list)

    def send(self, message_name: str, values: dict[str, float | str]) -> CanFrame:
        """按报文名编码出一帧，并记录到总线上。"""
        message = self.database.message_by_name(message_name)
        frame = CanFrame(message.frame_id, encode_message(message, values))
        self.trace.append(frame)
        return frame

    def receive(self, frame: CanFrame) -> dict[str, float | str]:
        """把收到的一帧解成命名信号。"""
        message = self.database.message(frame.arbitration_id)
        return decode_message(message, frame.data)

    def clear_trace(self) -> None:
        self.trace.clear()


def load_database(path: str | Path = DEFAULT_DBC_PATH) -> Database:
    """加载 DBC 文件。

    每次都重新解析。文件只有几十行，解析开销可以忽略，
    换来的是"改了 .dbc 立刻生效"，不用操心缓存失效。
    """
    return parse_dbc_file(Path(path))


__all__ = [
    "CanBus",
    "CanCodecError",
    "CanFrame",
    "decode_message",
    "decode_raw",
    "encode_message",
    "load_database",
    "physical_to_raw",
    "raw_to_physical",
]
