"""NOMI voice assistant: wake-word boundaries + command gating."""

import pytest

pytestmark = pytest.mark.voice


@pytest.mark.parametrize(
    "wake_word, expected",
    [
        ("Hi NOMI", "activated"),      # standard phrase
        ("hi nomi", "activated"),      # case-insensitive
        ("  HI   NOMI  ", "activated"),  # whitespace-insensitive
        ("你好 NOMI", "activated"),      # Chinese wake phrase
        ("你好NOMI", "activated"),      # Chinese without space
        ("Hey NOMI", "none"),          # near-miss phrase
        ("Hi Nomi!", "none"),          # trailing punctuation is NOT matched
        ("", "none"),                  # empty input
        (None, "none"),                # empty audio frame from the ASR pipe
    ],
    ids=[
        "standard", "lowercase", "extra_spaces",
        "chinese", "chinese_no_space",
        "near_miss", "punctuation", "empty", "none_input",
    ],
)
def test_nomi_wake_word(voice_assistant, wake_word, expected):
    assert voice_assistant.wake(wake_word) == expected


@pytest.mark.smoke
def test_nomi_rejects_are_recorded(voice_assistant):
    """Rejected inputs are logged so UX/analytics can mine them later."""
    voice_assistant.wake("Hey NOMI")
    voice_assistant.wake(None)
    assert voice_assistant.rejected_inputs == ["Hey NOMI", None]


def test_command_requires_awake_assistant(voice_assistant):
    """Commands to a sleeping assistant must fail loudly, not silently."""
    with pytest.raises(RuntimeError, match="not awake"):
        voice_assistant.submit_command("open navigation")


@pytest.mark.smoke
def test_full_wake_and_command_flow(voice_assistant):
    """Happy path: wake, then command, then state is observable."""
    assert voice_assistant.wake("Hi NOMI") == "activated"
    assert voice_assistant.submit_command("open navigation") == "executed:open navigation"
    assert voice_assistant.last_command == "open navigation"
