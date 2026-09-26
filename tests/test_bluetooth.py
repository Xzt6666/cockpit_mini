"""Bluetooth: pairing -> connect -> disconnect, plus abnormal drops.

The module is an explicit state machine; tests assert on *transitions*
(state + paired/connected fields), not just booleans, so a refactor
that keeps behaviour but renames internals still gets caught.
"""

import pytest

pytestmark = pytest.mark.bluetooth

PHONE = "Pixel_8"


def _paired_device(bluetooth_module):
    """Helper: pair one phone, returning the module for chaining."""
    bluetooth_module.start_pairing()
    bluetooth_module.complete_pairing(PHONE)
    return bluetooth_module


# ---------------------------------------------------------------------------
# Normal flow
# ---------------------------------------------------------------------------


@pytest.mark.smoke
def test_full_pair_connect_disconnect_cycle(bluetooth_module):
    assert bluetooth_module.state == "off"

    bluetooth_module.start_pairing()
    assert bluetooth_module.state == "pairing"
    bluetooth_module.complete_pairing(PHONE)
    assert PHONE in bluetooth_module.paired_devices
    assert bluetooth_module.state == "off"  # idle again, bond persists

    bluetooth_module.connect(PHONE)
    assert bluetooth_module.state == "connected"
    assert bluetooth_module.connected_device == PHONE

    bluetooth_module.disconnect()
    assert bluetooth_module.state == "disconnected"
    assert bluetooth_module.connected_device is None
    # The pairing bond survives a disconnect (real-world behaviour).
    assert PHONE in bluetooth_module.paired_devices


def test_connect_second_device_while_connected_fails(bluetooth_module):
    """Only one HFP/A2DP sink at a time on this simplified head unit."""
    _paired_device(bluetooth_module)
    bluetooth_module.start_pairing()
    bluetooth_module.complete_pairing("iPhone_15")
    bluetooth_module.connect(PHONE)
    with pytest.raises(RuntimeError, match="already connected"):
        bluetooth_module.connect("iPhone_15")


# ---------------------------------------------------------------------------
# Abnormal scenarios
# ---------------------------------------------------------------------------


def test_connection_lost_out_of_range(bluetooth_module):
    """Abnormal drop: phone walks out of range / reboots."""
    _paired_device(bluetooth_module)
    bluetooth_module.connect(PHONE)
    bluetooth_module.simulate_connection_lost()
    assert bluetooth_module.state == "connection_lost"
    assert bluetooth_module.connected_device is None
    # Bond is kept; auto-reconnect is allowed from connection_lost.
    bluetooth_module.connect(PHONE)
    assert bluetooth_module.state == "connected"


def test_connect_unpaired_device_fails(bluetooth_module):
    """A random nearby phone must not be able to hijack the cabin."""
    with pytest.raises(RuntimeError, match="not paired"):
        bluetooth_module.connect("Stranger_Phone")


def test_pairing_while_connected_fails(bluetooth_module):
    _paired_device(bluetooth_module)
    bluetooth_module.connect(PHONE)
    with pytest.raises(RuntimeError, match="cannot pair while"):
        bluetooth_module.start_pairing()


def test_disconnect_without_device_fails(bluetooth_module):
    with pytest.raises(RuntimeError, match="no device connected"):
        bluetooth_module.disconnect()


def test_simulate_lost_without_connection_fails(bluetooth_module):
    with pytest.raises(RuntimeError, match="no device connected"):
        bluetooth_module.simulate_connection_lost()


def test_duplicate_pairing_fails(bluetooth_module):
    _paired_device(bluetooth_module)
    bluetooth_module.start_pairing()
    with pytest.raises(RuntimeError, match="already paired"):
        bluetooth_module.complete_pairing(PHONE)
