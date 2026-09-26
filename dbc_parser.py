"""极简 DBC（CAN 报文定义文件）解析器。

DBC 是什么
----------
它是汽车行业用来描述 CAN 总线上"有哪些报文、每个报文里有哪些信号"的
纯文本文件，一般由 Vector CANdb++ 这类工具生成。可以把它理解成一份
总线的"数据字典"：光看 8 个字节的原始数据谁也读不懂，有了 DBC 才知道
哪几位是车速、哪几位是挡位。

本项目只实现最常用的 5 类语句，其余语句（CM_ / BA_ / NS_ / BS_ ...）
一律跳过，所以真实工具导出的 DBC 也能加载：

    VERSION "..."                    文件版本
    BU_: DCU HMI VCU                 网络上有哪些节点（ECU）
    BO_ 256 VehicleDynamics: 8 DCU   一条报文：ID 256、8 字节、由 DCU 发送
     SG_ VehicleSpeed : ...          报文里的一个信号
    VAL_ 256 GearPosition 0 "P" ...  取值表：把数字翻译成人看得懂的名字

怎么读一条 SG_ 语句
-------------------
    SG_ 信号名 : 起始位|长度@字节序符号 (系数,偏移) [最小值|最大值] "单位" 接收者

    例：SG_ VehicleSpeed : 0|16@1+ (0.1,0) [0|250] "km/h" HMI,VCU

    起始位 = 0      从第 0 位开始（小端时这一位是"最低位"）
    长度   = 16     占 16 位，也就是 2 个字节
    字节序 = 1      小端（Intel）
    符号   = +      无符号
    系数   = 0.1    物理值 = 原始值 × 0.1
    偏移   = 0      物理值 = 原始值 × 0.1 + 0
    单位   = km/h
    接收者 = HMI,VCU  哪些节点会读这个信号

于是"原始值 500"读出来就是 50.0 km/h。这个"系数 + 偏移"的换算，
是 DBC 里最重要也最实用的概念。

本项目的简化点（面试时可以主动说明）
------------------------------------
* **只支持小端（Intel，@1）字节序。** 大端（Motorola，@0）信号的位
  布局是"锯齿轮廓"：在一个字节内从高位往低位走，跨到下一个字节时
  要跳到那个字节的最高位。理解成本高、本项目用不到，因此不做——
  遇到 @0 会直接报错，而不是悄悄算错。
* **不支持多路复用信号（M / m0）。** 本项目没有这类信号。
* **VAL_ 必须写在其对应的 BO_ 之后。** 真实文件里两者顺序不定。
* **不解析注释（CM_）、属性（BA_）等语句**，直接跳过。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


class DbcParseError(ValueError):
    """DBC 里某一行"看得出想表达什么、但格式不对"时抛出。"""


@dataclass
class Signal:
    """一个信号（SG_）：占哪些位、怎么缩放、数字怎么翻译成名字。"""

    name: str
    start_bit: int      # 起始位号（小端时是最低位）
    length: int         # 占多少位
    factor: float       # 缩放系数
    offset: float       # 偏移量
    minimum: float      # 物理值下限
    maximum: float      # 物理值上限
    unit: str = ""
    value_table: dict[int, str] = field(default_factory=dict)  # 原始值 -> 名字

    @property
    def highest_bit(self) -> int:
        """信号占用的最高位号。小端时它就是最高有效位。"""
        return self.start_bit + self.length - 1

    def bits(self) -> list[int]:
        """信号覆盖的位号，最高位在前。

        小端信号从起始位往上连续占用，所以直接就是一段连续位号。
        返回"最高位在前"是为了让编解码两边都只用一个移位循环。
        """
        return list(range(self.highest_bit, self.start_bit - 1, -1))

    def to_physical(self, raw: int) -> float:
        """原始值 → 物理值：``raw × factor + offset``。"""
        return raw * self.factor + self.offset

    def name_of(self, raw: int) -> str | None:
        """查取值表：原始值对应的名字，没定义就返回 None。"""
        return self.value_table.get(raw)

    def raw_of(self, name: str) -> int | None:
        """反查取值表：名字对应的原始值，没定义就返回 None。"""
        for raw, label in self.value_table.items():
            if label == name:
                return raw
        return None


@dataclass
class Message:
    """一条报文（BO_）以及它下面挂的信号。"""

    frame_id: int       # CAN 仲裁 ID
    name: str
    length: int         # 字节数（DLC）
    signals: dict[str, Signal] = field(default_factory=dict)

    def signal(self, name: str) -> Signal:
        """按名字取出一个信号。"""
        if name not in self.signals:
            raise KeyError(
                f"报文 {self.name} 里没有信号 {name!r}，"
                f"已有的是 {sorted(self.signals)}"
            )
        return self.signals[name]


@dataclass
class Database:
    """一整份解析好的 DBC 文件。"""

    version: str = ""
    nodes: list[str] = field(default_factory=list)
    messages: dict[int, Message] = field(default_factory=dict)

    def message(self, frame_id: int) -> Message:
        """按 CAN ID 找报文。"""
        if frame_id not in self.messages:
            raise KeyError(
                f"没有 ID 为 {frame_id:#x} 的报文，"
                f"已有的是 {[hex(i) for i in self.messages]}"
            )
        return self.messages[frame_id]

    def message_by_name(self, name: str) -> Message:
        """按名字找报文。报文很少，直接遍历就行，不需要建索引。"""
        for message in self.messages.values():
            if message.name == name:
                return message
        raise KeyError(
            f"没有叫 {name!r} 的报文，"
            f"已有的是 {sorted(m.name for m in self.messages.values())}"
        )


# ---------------------------------------------------------------------------
# 语句的正则。每组括号就是一个字段，后面按下标取用。
# ---------------------------------------------------------------------------

_BO_RE = re.compile(r"^BO_\s+(\d+)\s+(\w+)\s*:\s*(\d+)\s+(\w+)\s*$")

_SG_RE = re.compile(
    r"^SG_\s+(\w+)\s*:\s*(\d+)\|(\d+)@([01])([+-])"      # 名字 起始位|长度@字节序符号
    r"\s*\(\s*([-\d.eE+]+)\s*,\s*([-\d.eE+]+)\s*\)"      # (系数,偏移)
    r"\s*\[\s*([-\d.eE+]+)\s*\|\s*([-\d.eE+]+)\s*\]"     # [最小值|最大值]
    r'\s*"([^"]*)"'                                       # "单位"
    r"\s*(.*)$"                                           # 接收者（本项目忽略）
)

_VAL_RE = re.compile(r"^VAL_\s+(\d+)\s+(\w+)\s+(.*);\s*$")
_VAL_PAIR_RE = re.compile(r'(-?\d+)\s+"([^"]*)"')


def parse_dbc(text: str) -> Database:
    """把 DBC 文本解析成 :class:`Database`。

    只认 VERSION / BU_ / BO_ / SG_ / VAL_，其他行直接跳过。

    但有一条例外：**"看起来是 BO_ 或 SG_、格式却不对"的行会直接报错**。
    因为静默跳过一条写坏的信号，会让数据库看起来一切正常、实际解出来的
    物理值是错的——这比当场失败危险得多。
    """
    database = Database()
    current: Message | None = None

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue

        # 用第一个词判断这行是什么语句。这样不会把 BO_TX_BU_ 误当成 BO_。
        keyword = line.split(maxsplit=1)[0]

        if keyword == "VERSION":
            database.version = line.split('"')[1] if '"' in line else ""
        elif keyword == "BU_:":
            database.nodes = line.partition(":")[2].split()
        elif keyword == "BO_":
            match = _BO_RE.match(line)
            if not match:
                raise DbcParseError(f"BO_ 语句格式不对：{line!r}")
            current = Message(int(match[1]), match[2], int(match[3]))
            database.messages[current.frame_id] = current
        elif keyword == "SG_":
            if current is None:
                raise DbcParseError(f"SG_ 出现在任何 BO_ 之前：{line!r}")
            match = _SG_RE.match(line)
            if not match:
                raise DbcParseError(f"SG_ 语句格式不对：{line!r}")
            if match[4] != "1":
                raise DbcParseError(f"本项目只支持小端（@1）信号：{line!r}")
            current.signals[match[1]] = Signal(
                name=match[1],
                start_bit=int(match[2]),
                length=int(match[3]),
                factor=float(match[6]),
                offset=float(match[7]),
                minimum=float(match[8]),
                maximum=float(match[9]),
                unit=match[10],
            )
        elif keyword == "VAL_":
            match = _VAL_RE.match(line)
            if not match:
                raise DbcParseError(f"VAL_ 语句格式不对：{line!r}")
            table = {int(raw): label for raw, label in _VAL_PAIR_RE.findall(match[3])}
            database.message(int(match[1])).signal(match[2]).value_table = table
        # 其余语句（CM_ / BS_ / BA_ / NS_ ...）本项目不关心，直接跳过。

    return database


def parse_dbc_file(path: str | Path) -> Database:
    """按 UTF-8 读取并解析 DBC 文件。"""
    return parse_dbc(Path(path).read_text(encoding="utf-8"))


__all__ = [
    "DbcParseError",
    "Database",
    "Message",
    "Signal",
    "parse_dbc",
    "parse_dbc_file",
]
