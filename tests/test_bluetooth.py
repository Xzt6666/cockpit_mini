"""蓝牙：配对 → 连接 → 断开，以及异常断开。

模块本身是一个显式状态机，所以用例断言的是**状态转移**
（状态值 + 已配对/已连接字段），而不只是一个布尔值：这样即使以后
重构改了内部实现，只要行为对得上，测试依然有效。
"""

import pytest

pytestmark = pytest.mark.bluetooth

PHONE = "Pixel_8"


def _paired_device(bluetooth_module):
    """小助手：先把一台手机配对好，然后返回模块本身方便链式调用。"""
    bluetooth_module.start_pairing()
    bluetooth_module.complete_pairing(PHONE)
    return bluetooth_module


# ---------------------------------------------------------------------------
# 正常流程
# ---------------------------------------------------------------------------


@pytest.mark.smoke
def test_full_pair_connect_disconnect_cycle(bluetooth_module):
    assert bluetooth_module.state == "off"

    bluetooth_module.start_pairing()
    assert bluetooth_module.state == "pairing"
    bluetooth_module.complete_pairing(PHONE)
    assert PHONE in bluetooth_module.paired_devices
    assert bluetooth_module.state == "off"  # 又回到空闲，但配对记录保留

    bluetooth_module.connect(PHONE)
    assert bluetooth_module.state == "connected"
    assert bluetooth_module.connected_device == PHONE

    bluetooth_module.disconnect()
    assert bluetooth_module.state == "disconnected"
    assert bluetooth_module.connected_device is None
    # 断开之后配对关系还在，这跟真实车机一致。
    assert PHONE in bluetooth_module.paired_devices


def test_connect_second_device_while_connected_fails(bluetooth_module):
    """这个简化版车机同一时刻只支持一路蓝牙连接。"""
    _paired_device(bluetooth_module)
    bluetooth_module.start_pairing()
    bluetooth_module.complete_pairing("iPhone_15")
    bluetooth_module.connect(PHONE)
    with pytest.raises(RuntimeError, match="已经连接了"):
        bluetooth_module.connect("iPhone_15")


# ---------------------------------------------------------------------------
# 异常场景
# ---------------------------------------------------------------------------


def test_connection_lost_out_of_range(bluetooth_module):
    """异常断开：手机走出范围 / 重启 / 开飞行模式。"""
    _paired_device(bluetooth_module)
    bluetooth_module.connect(PHONE)
    bluetooth_module.simulate_connection_lost()
    assert bluetooth_module.state == "connection_lost"
    assert bluetooth_module.connected_device is None
    # 配对关系保留，所以可以重新连上（对应车机的自动重连）。
    bluetooth_module.connect(PHONE)
    assert bluetooth_module.state == "connected"


def test_connect_unpaired_device_fails(bluetooth_module):
    """旁边一台陌生手机不能随便连上你的车机。"""
    with pytest.raises(RuntimeError, match="设备未配对"):
        bluetooth_module.connect("Stranger_Phone")


def test_pairing_while_connected_fails(bluetooth_module):
    _paired_device(bluetooth_module)
    bluetooth_module.connect(PHONE)
    with pytest.raises(RuntimeError, match="不能开始配对"):
        bluetooth_module.start_pairing()


def test_disconnect_and_lost_without_connection_fail(bluetooth_module):
    """没连设备的时候，断开和"模拟异常断开"都应该报错。"""
    with pytest.raises(RuntimeError, match="没有已连接的设备"):
        bluetooth_module.disconnect()
    with pytest.raises(RuntimeError, match="没有已连接的设备"):
        bluetooth_module.simulate_connection_lost()


def test_duplicate_pairing_fails(bluetooth_module):
    _paired_device(bluetooth_module)
    bluetooth_module.start_pairing()
    with pytest.raises(RuntimeError, match="设备已配对过"):
        bluetooth_module.complete_pairing(PHONE)
