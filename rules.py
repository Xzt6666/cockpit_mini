"""Pure business rules for the cockpit_mini test framework.

Every function in this module is a *pure* mapping from inputs to
outputs: no mock objects, no I/O, no shared state. That keeps them
trivially unit-testable and mirrors how a real project separates
policy (this module) from mechanism (``cockpit_mock.py``).

All constants are simplified stand-ins for what a real vehicle system
specification would provide.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Domain constants (stand-ins for the system requirement spec)
# ---------------------------------------------------------------------------

#: Center-display video is locked at or above this speed (km/h).
VIDEO_LOCK_SPEED_KMH: float = 5.0

#: Over-speed warning threshold (km/h).
OVERSPEED_WARNING_KMH: float = 120.0

#: Valid PRND gears.
GEARS: tuple[str, ...] = ("P", "R", "N", "D")

#: Supported NOMI wake words (normalized: lowercase, spaces removed).
_WAKE_WORDS: frozenset[str] = frozenset({"hinomi", "你好nomi"})


# ---------------------------------------------------------------------------
# HMI / infotainment rules
# ---------------------------------------------------------------------------

def is_video_allowed(speed_kmh: float) -> bool:
    """Return True when video on the center display is allowed.

    Safety rule: video playback is only allowed when the car is nearly
    standing still (below ``VIDEO_LOCK_SPEED_KMH``).
    """
    return speed_kmh < VIDEO_LOCK_SPEED_KMH


def nomi_wake_response(wake_word: str | None) -> str:
    """Return the NOMI assistant's response to a candidate wake word.

    Matching is case-insensitive and space-insensitive, so ``"HI NOMI"``
    and ``"你好NOMI"`` both wake the assistant -- the production NOMI
    supports both English and Chinese wake phrases.

    ``None`` models the case where the speech-recognition pipeline
    produced no text at all (e.g. empty audio frame) and safely maps to
    ``"none"`` instead of raising ``AttributeError``.
    """
    if not wake_word:
        return "none"
    normalized = wake_word.lower().replace(" ", "")
    return "activated" if normalized in _WAKE_WORDS else "none"


def estimate_eta_hours(distance_km: float, speed_kmh: float) -> float:
    """Estimate travel time in hours for the remaining route.

    Raises:
        ValueError: if ``speed_kmh`` is not positive or ``distance_km``
            is negative -- both are invalid inputs that would silently
            produce nonsense ETAs otherwise.
    """
    if speed_kmh <= 0:
        raise ValueError("speed must be positive")
    if distance_km < 0:
        raise ValueError("distance must not be negative")
    return distance_km / speed_kmh


# ---------------------------------------------------------------------------
# Powertrain / warning rules
# ---------------------------------------------------------------------------

def speed_warning_level(speed_kmh: float) -> str:
    """Classify the over-speed warning level for the current speed.

    Returns ``"overspeed"`` at or above ``OVERSPEED_WARNING_KMH``,
    otherwise ``"none"``.
    """
    return "overspeed" if speed_kmh >= OVERSPEED_WARNING_KMH else "none"


def can_shift_gear(target_gear: str, speed_kmh: float) -> tuple[bool, str]:
    """Gear interlock rule.

    Entering ``P`` (park lock) or ``R`` (reverse) while the vehicle is
    moving would damage the transmission, so both require a speed below
    ``VIDEO_LOCK_SPEED_KMH``. ``N`` and ``D`` may be selected at any
    speed.

    Returns:
        Tuple of ``(allowed, reason)`` so tests can assert on the exact
        rejection cause, not just the boolean.
    """
    if target_gear not in GEARS:
        return False, "invalid target gear"
    if target_gear in ("P", "R") and speed_kmh >= VIDEO_LOCK_SPEED_KMH:
        return (
            False,
            f"shifting to {target_gear} requires speed < {VIDEO_LOCK_SPEED_KMH:g} km/h",
        )
    return True, "ok"


def is_reverse_camera_active(gear: str) -> bool:
    """The reverse camera feeds the center display only in R gear."""
    return gear == "R"
