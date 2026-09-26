"""CAN 编解码测试：位打包、缩放、取值表、拒绝非法输入、端到端。

为什么不能只做"往返测试"
------------------------
"编码后再解码，看结果是否等于输入"这种往返测试是不充分的：
如果编码和解码**错得一模一样**，往返照样会通过。所以这里断言的是
具体的十六进制字节，并且额外用手写的字节反向解码一次——
那才是唯一能证明位布局正确的方式。
"""

import pytest

from can_bus import (
    CanBus,
    CanCodecError,
    CanFrame,
    decode_message,
    encode_message,
    load_database,
)

pytestmark = pytest.mark.can


@pytest.fixture(scope="module")
def database():
    """项目自带的 DBC，每个测试模块只加载一次。"""
    return load_database()


@pytest.fixture
def bus(database):
    """每条用例都拿到一条干净的总线。"""
    return CanBus(database)


# ---------------------------------------------------------------------------
# 位打包：直接断言字节
# ---------------------------------------------------------------------------


@pytest.mark.smoke
def test_vehicle_dynamics_wire_bytes(database):
    """车速 50 km/h、D 挡、车外 -40 度，应该正好编码成这 8 个字节。

    50 ÷ 0.1 = 500 = 0x01F4，小端写进 byte0、byte1 → f4 01
    D 挡的原始值是 3，占 byte2 的低 4 位         → 03
    -40 度按 -40 的偏移反算出原始值 0            → 00
    """
    message = database.message(256)
    data = encode_message(
        message, {"VehicleSpeed": 50.0, "GearPosition": "D", "OutsideTemp": -40.0}
    )
    assert data == bytes.fromhex("f401030000000000")


@pytest.mark.smoke
def test_bluetooth_wire_bytes(database):
    """一个跨字节的信号：PairedCount 从第 4 位起占 8 位，横跨两个字节。

    BtState=2（connected）占 bit0~3，PairedCount=3 占 bit4~11，
    拼起来 byte0 就是 0x32，byte1 是 0x00。
    """
    message = database.message(768)
    data = encode_message(message, {"BtState": "connected", "PairedCount": 3})
    assert data == bytes.fromhex("3200000000000000")


def test_handcrafted_bytes_decode_on_their_own(database):
    """手写的字节必须能独立解出来——完全不借助 encoder。

    即使编码和解码对称地错，这条用例照样会失败。
    """
    decoded = decode_message(database.message(256), bytes.fromhex("f401030000000000"))
    assert decoded["VehicleSpeed"] == pytest.approx(50.0)
    assert decoded["GearPosition"] == "D"
    assert decoded["OutsideTemp"] == -40.0


# ---------------------------------------------------------------------------
# 缩放往返
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "speed", [0, 5, 60, 250], ids=["stop", "threshold", "city", "max"]
)
def test_speed_round_trip(database, speed):
    message = database.message(256)
    data = encode_message(message, {"VehicleSpeed": speed})
    # 一个最小刻度是 0.1 km/h，所以量化误差不会超过半个刻度。
    assert decode_message(message, data)["VehicleSpeed"] == pytest.approx(speed, abs=0.05)


def test_untouched_signals_stay_at_zero(database):
    """只写了车速，其他信号必须保持中立值。"""
    message = database.message(256)
    decoded = decode_message(message, encode_message(message, {"VehicleSpeed": 10}))
    assert decoded["GearPosition"] == "P"    # 原始值 0 → 名字 "P"
    assert decoded["OutsideTemp"] == -40.0   # 原始值 0 加上 -40 的偏移


# ---------------------------------------------------------------------------
# 取值表：名字和数字等价
# ---------------------------------------------------------------------------


@pytest.mark.smoke
@pytest.mark.parametrize("label, raw", [("P", 0), ("R", 1), ("N", 2), ("D", 3)])
def test_gear_label_and_code_are_equivalent(database, label, raw):
    """传 "D" 和传 3 应该得到完全一样的字节。"""
    message = database.message(256)
    by_label = encode_message(message, {"GearPosition": label})
    by_code = encode_message(message, {"GearPosition": raw})
    assert by_label == by_code
    assert decode_message(message, by_label)["GearPosition"] == label


def test_code_without_a_name_decodes_to_a_number(database):
    """原始值 7 在 DBC 范围内，但取值表里没定义，就解成数字。"""
    message = database.message(256)
    data = encode_message(message, {"GearPosition": 7})
    assert decode_message(message, data)["GearPosition"] == 7


# ---------------------------------------------------------------------------
# 非法输入必须被拒绝
# ---------------------------------------------------------------------------


def test_out_of_range_speed_is_rejected(database):
    """超范围时报错而不是钳位——悄悄改成 250 恰好会掩盖真正的缺陷。"""
    with pytest.raises(CanCodecError, match="超出 DBC 定义范围"):
        encode_message(database.message(256), {"VehicleSpeed": 999})


def test_unknown_names_are_rejected(database):
    """取值表里没有的挡位名、DBC 里不存在的信号名，都要报错。"""
    with pytest.raises(CanCodecError, match="取值表里没有"):
        encode_message(database.message(256), {"GearPosition": "X"})
    with pytest.raises(KeyError):
        encode_message(database.message(256), {"NoSuchSignal": 1})


def test_wrong_byte_count_is_rejected(database):
    with pytest.raises(CanCodecError, match="需要 8 字节"):
        decode_message(database.message(256), b"\x00" * 7)


# ---------------------------------------------------------------------------
# 模拟总线
# ---------------------------------------------------------------------------


@pytest.mark.smoke
def test_bus_records_every_frame(bus):
    """总线上发过什么，必须查得到。"""
    assert bus.trace == []
    frame = bus.send("VehicleDynamics", {"VehicleSpeed": 12.5})
    assert bus.trace == [frame]
    assert frame.arbitration_id == 256
    assert frame.dlc == 8
    assert frame.hex().startswith("0x100#")
    bus.clear_trace()
    assert bus.trace == []


# ---------------------------------------------------------------------------
# 端到端：一帧报文驱动中控屏
# ---------------------------------------------------------------------------


@pytest.mark.smoke
def test_a_frame_drives_the_hmi_video_lock(vehicle_state):
    """完整链路：报文 → DBC 解码 → 车辆信号 → 中控屏可见性。"""
    page = vehicle_state.open_hmi_page("home")

    parked = vehicle_state.can_bus.send("VehicleDynamics", {"VehicleSpeed": 0})
    vehicle_state.receive_can_frame(parked)
    assert page.is_widget_visible("video")

    driving = vehicle_state.can_bus.send("VehicleDynamics", {"VehicleSpeed": 60})
    vehicle_state.receive_can_frame(driving)
    assert not page.is_widget_visible("video")


def test_receiving_a_frame_is_logged(vehicle_state):
    """收到报文要留下痕迹，方便事后追溯。"""
    frame = vehicle_state.can_bus.send("VehicleDynamics", {"VehicleSpeed": 10})
    vehicle_state.receive_can_frame(frame)
    assert vehicle_state.event_count("can_rx:0x100") == 1


def test_frame_with_an_undefined_gear_code_is_rejected(vehicle_state):
    """模拟总线数据被破坏：编码 7 在 DBC 范围内，但不在 PRND 里。"""
    message = vehicle_state.can_bus.database.message(256)
    corrupted = CanFrame(256, encode_message(message, {"GearPosition": 7}))
    with pytest.raises(ValueError, match="非法挡位"):
        vehicle_state.receive_can_frame(corrupted)
