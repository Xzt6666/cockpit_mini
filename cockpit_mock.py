"""In-memory mock of a digital cockpit domain controller.

In a real project this layer would talk to a test bench or HIL rig over
ADB / CAN / Ethernet. Here every "hardware" behaviour is reduced to
plain Python state so the test suite can run repeatably on any machine
with no vehicle attached.

Design notes
------------
* ``MockCockpit`` models the domain controller itself: power state,
  vehicle signals, and an append-only event log that tests can assert
  against (e.g. "a warning chime was issued exactly once").
* ``HmiPage`` models one screen of the center display. Visibility is
  now *derived from the current vehicle state* instead of a hard-coded
  widget tuple, so the page behaves like the real HMI (video locks with
  speed, reverse camera appears only in R gear).
* ``MockVoiceAssistant`` and ``MockBluetoothModule`` model two soft
  peripherals behind simple, explicit state machines.

All classes expose a ``reset()`` so function-scoped fixtures can return
the shared session resource to a clean state between tests.
"""

from __future__ import annotations

from rules import (
    GEARS,
    can_shift_gear,
    is_reverse_camera_active,
    is_video_allowed,
    nomi_wake_response,
    speed_warning_level,
)

#: Widgets always present on the home page of the center display.
_HOME_WIDGETS: tuple[str, ...] = ("clock", "speed", "media", "nav")

#: Widgets that additionally require the video-unlock condition.
_VIDEO_WIDGETS: frozenset[str] = frozenset({"video", "media_video"})


class MockCockpit:
    """Fake cockpit domain controller (session-scoped hardware)."""

    def __init__(self) -> None:
        self._signals: dict[str, float | str] = {}
        self._events: list[str] = []
        self._powered = False
        # Sub-devices that hang off the domain controller.
        self.voice = MockVoiceAssistant()
        self.bluetooth = MockBluetoothModule()

    # -- power ------------------------------------------------------------

    def power_on(self) -> None:
        self._powered = True
        self.log_event("power_on")

    def power_off(self) -> None:
        self._powered = False
        self.log_event("power_off")

    @property
    def is_powered(self) -> bool:
        return self._powered

    # -- signals ----------------------------------------------------------

    def set_signal(self, name: str, value: float | str) -> None:
        """Write a vehicle signal (e.g. ``vehicle_speed``, ``gear``)."""
        assert self._powered, "cockpit is not powered on"
        if name == "vehicle_speed":
            if not isinstance(value, (int, float)):
                raise TypeError("vehicle_speed must be numeric")
            if value < 0:
                raise ValueError("vehicle_speed must not be negative")
        elif name == "gear":
            if value not in GEARS:
                raise ValueError(f"invalid gear: {value!r}")
        self._signals[name] = value

    def get_signal(self, name: str) -> float | str:
        # Default missing signals to a safe standstill state instead of
        # raising KeyError -- matches how a real gateway exposes defaults.
        return self._signals.get(name, 0 if name == "vehicle_speed" else "P")

    def speed_kmh(self) -> float:
        return float(self.get_signal("vehicle_speed"))

    def gear(self) -> str:
        return str(self.get_signal("gear"))

    # -- event log --------------------------------------------------------

    def log_event(self, event: str) -> None:
        """Append to the append-only event log (chimes, state changes...)."""
        self._events.append(event)

    def event_count(self, event: str) -> int:
        return self._events.count(event)

    def clear_events(self) -> None:
        self._events.clear()

    # -- reset ------------------------------------------------------------

    def reset(self) -> None:
        """Return the whole controller to the just-powered-on state."""
        self._signals.clear()
        self._events.clear()
        self.voice.reset()
        self.bluetooth.reset()

    # -- HMI --------------------------------------------------------------

    def open_hmi_page(self, page_name: str) -> "HmiPage":
        return HmiPage(self, page_name)

    # -- powertrain behaviours driven by signals --------------------------

    def set_gear(self, target_gear: str) -> bool:
        """Attempt a gear shift, honouring the interlock rule.

        Returns True when the shift happened; the rejection is recorded
        in the event log so tests can assert on the *reason*.
        """
        allowed, reason = can_shift_gear(target_gear, self.speed_kmh())
        if allowed:
            self.set_signal("gear", target_gear)
        self.log_event(f"gear_shift:{target_gear}:{'ok' if allowed else 'rejected'}")
        return allowed


class HmiPage:
    """One page of the center display, bound to live vehicle state."""

    def __init__(self, cockpit: MockCockpit, name: str) -> None:
        self.cockpit = cockpit
        self.name = name
        self.opened = True

    def is_widget_visible(self, widget: str) -> bool:
        """Visibility derived from page + live vehicle signals.

        Draft version hard-coded the widget tuple; the real HMI locks
        video widgets with speed and shows the reverse camera in R gear.
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

    # -- behaviour triggered by signals -----------------------------------

    def check_speed_warning(self) -> str:
        """Re-evaluate the over-speed rule and chime on transitions."""
        level = speed_warning_level(self.cockpit.speed_kmh())
        if level == "overspeed":
            self.cockpit.log_event("warning_chime:overspeed")
        return level


class MockVoiceAssistant:
    """Mock of the NOMI voice assistant (simple state machine)."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.active = False
        self.last_command: str | None = None
        self.rejected_inputs: list[str | None] = []

    def wake(self, wake_word: str | None) -> str:
        """Feed a candidate wake word and update internal state."""
        response = nomi_wake_response(wake_word)
        if response == "activated":
            self.active = True
        else:
            self.rejected_inputs.append(wake_word)
        return response

    def submit_command(self, command: str) -> str:
        """Submit a voice command; requires the assistant to be awake."""
        if not self.active:
            raise RuntimeError("voice assistant is not awake")
        self.last_command = command
        return f"executed:{command}"


class MockBluetoothModule:
    """Mock of the in-car Bluetooth module (explicit state machine).

    States: ``off -> pairing -> connected -> disconnected`` with
    ``connection_lost`` modelling an abnormal drop (walk-out-of-range,
    phone reboot...).
    """

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.state = "off"
        self.paired_devices: list[str] = []
        self.connected_device: str | None = None

    # -- pairing ----------------------------------------------------------

    def start_pairing(self) -> None:
        if self.state == "connected":
            raise RuntimeError("cannot pair while a device is connected")
        self.state = "pairing"

    def complete_pairing(self, device_name: str) -> None:
        if self.state != "pairing":
            raise RuntimeError("no pairing session in progress")
        if device_name in self.paired_devices:
            raise RuntimeError(f"device already paired: {device_name}")
        self.paired_devices.append(device_name)
        self.state = "off"

    # -- connection -------------------------------------------------------

    def connect(self, device_name: str) -> None:
        if device_name not in self.paired_devices:
            raise RuntimeError(f"device not paired: {device_name}")
        if self.connected_device is not None:
            raise RuntimeError(f"already connected to {self.connected_device}")
        self.connected_device = device_name
        self.state = "connected"

    def disconnect(self) -> None:
        """Graceful disconnect initiated by the user."""
        if self.connected_device is None:
            raise RuntimeError("no device connected")
        self.connected_device = None
        self.state = "disconnected"

    def simulate_connection_lost(self) -> None:
        """Abnormal drop: phone out of range, reboot, airplane mode..."""
        if self.connected_device is None:
            raise RuntimeError("no device connected")
        self.connected_device = None
        self.state = "connection_lost"
