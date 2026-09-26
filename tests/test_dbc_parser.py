"""DBC 解析器测试：语句解析、位布局、缩放、取值表、非法输入。

核心要求：**解析器遇到读不懂的语句必须报错，不能装作没看见。**
一份"能加载、位布局却错了"的数据库，会让每一条下游断言都建立在
错误的前提上——静默跳过比直接失败危险得多。
"""

import pytest

from can_bus import DEFAULT_DBC_PATH
from dbc_parser import DbcParseError, parse_dbc, parse_dbc_file

pytestmark = pytest.mark.dbc

#: 一份最小的、格式正确的报文，用作各种"坏输入"测试的底板。
_VALID = (
    "BO_ 256 Probe: 8 DCU\n"
    ' SG_ ProbeSignal : 0|8@1+ (1,0) [0|255] "" HMI'
)


@pytest.fixture(scope="module")
def database():
    """项目自带的 DBC，每个测试模块只解析一次。"""
    return parse_dbc_file(DEFAULT_DBC_PATH)


@pytest.mark.smoke
def test_loads_the_shipped_database(database):
    """项目自带的 DBC 要能正常加载，内容符合预期。"""
    assert database.version == "cockpit_mini 1.0"
    assert database.nodes == ["DCU", "HMI", "VCU"]
    assert sorted(m.name for m in database.messages.values()) == [
        "BluetoothStatus",
        "VehicleDynamics",
    ]


def test_signal_layout_and_scaling(database):
    """一条 SG_ 语句里的每个字段都要被正确读出来。"""
    speed = database.message(256).signal("VehicleSpeed")
    assert (speed.start_bit, speed.length) == (0, 16)
    assert (speed.factor, speed.offset) == (0.1, 0)
    assert (speed.minimum, speed.maximum) == (0, 250)
    assert speed.unit == "km/h"
    # 缩放：原始值 500 × 0.1 = 50.0 km/h
    assert speed.to_physical(500) == pytest.approx(50.0)


def test_bits_are_listed_most_significant_first(database):
    """小端信号占一段连续的位号，最高位是 起始位 + 位数 - 1。"""
    assert database.message(256).signal("VehicleSpeed").bits() == list(range(15, -1, -1))
    # 跨字节的例子：GearPosition 只占 byte2 的低 4 位。
    assert database.message(256).signal("GearPosition").bits() == [19, 18, 17, 16]


def test_offset_shifts_the_physical_value(database):
    """OutsideTemp 的偏移是 -40：原始值 0 对应的就是 -40 摄氏度。"""
    temp = database.message(256).signal("OutsideTemp")
    assert (temp.factor, temp.offset) == (1, -40)
    assert temp.to_physical(0) == -40
    assert temp.to_physical(125) == 85


@pytest.mark.smoke
def test_value_table(database):
    """取值表把原始值翻译成名字，两个方向都要能查。"""
    gear = database.message(256).signal("GearPosition")
    assert gear.value_table == {0: "P", 1: "R", 2: "N", 3: "D"}
    assert gear.name_of(3) == "D"
    assert gear.raw_of("D") == 3
    # 在 DBC 范围内、但取值表里没定义的编码不算错误，只是没有名字。
    assert gear.name_of(7) is None
    assert gear.raw_of("X") is None


def test_message_lookup_by_id_and_by_name(database):
    by_id = database.message(256)
    assert (by_id.name, by_id.length) == ("VehicleDynamics", 8)
    assert database.message_by_name("VehicleDynamics") is by_id


def test_unknown_message_or_signal_raises(database):
    with pytest.raises(KeyError):
        database.message(0x999)
    with pytest.raises(KeyError):
        database.message(256).signal("NoSuchSignal")


def test_unmodelled_statements_are_ignored():
    """真实工具导出的 DBC 里还有一大堆我们不关心的语句，要能照样加载。"""
    text = (
        'VERSION ""\n'
        "NS_ :\n"                        # NS_ 是一段裸关键字清单，没有数据
        "\tCM_\n"
        "\tBA_DEF_\n"
        "BS_:\n"
        'BA_DEF_ BO_ "GenMsgCycleTime" INT 0 65535;\n'
        'CM_ BO_ 256 "这条注释会被忽略";\n'
        "BU_: A B\n" + _VALID + "\n"
    )
    parsed = parse_dbc(text)
    assert len(parsed.messages) == 1
    assert parsed.nodes == ["A", "B"]
    assert parsed.message(256).signal("ProbeSignal").length == 8


@pytest.mark.parametrize(
    "statement",
    [
        "BO_ 256 NoColon 8 DCU",                      # BO_ 少了冒号
        'SG_ NoSign : 0|8@1 (1,0) [0|255] "" HMI',    # 少了符号位 +/-
        'SG_ NoUnit : 0|8@1+ (1,0) [0|255] HMI',      # 单位忘了加引号
    ],
    ids=["message_without_colon", "signal_without_sign", "signal_with_unquoted_unit"],
)
def test_malformed_statement_is_rejected(statement):
    with pytest.raises(DbcParseError):
        parse_dbc(f"{_VALID}\n{statement}\n")


def test_big_endian_signal_is_rejected():
    """本项目不支持大端（@0）字节序，遇到必须明确报错，不能算错。"""
    text = _VALID + '\n SG_ BigEndian : 7|8@0+ (1,0) [0|255] "" HMI\n'
    with pytest.raises(DbcParseError, match="小端"):
        parse_dbc(text)
