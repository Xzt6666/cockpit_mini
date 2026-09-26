"""NOMI 语音助手：唤醒词的边界 + 指令门控。

唤醒词这类需求，真正的难点全在"边界"上：差一个字母、多一个标点，
到底算不算唤醒？这张表格就是把这些边界一个个钉死。
"""

import pytest

pytestmark = pytest.mark.voice


@pytest.mark.parametrize(
    "wake_word, expected",
    [
        ("Hi NOMI", "activated"),        # 标准说法
        ("  HI   NOMI  ", "activated"),  # 大小写、空格都不敏感
        ("你好 NOMI", "activated"),       # 中文唤醒词
        ("Hey NOMI", "none"),            # 相似但不是唤醒词
        ("Hi Nomi!", "none"),            # 多了标点就不算匹配
        (None, "none"),                  # 语音识别压根没产出文本
    ],
    ids=["standard", "case_and_space", "chinese", "near_miss", "punctuation", "no_text"],
)
def test_nomi_wake_word(voice_assistant, wake_word, expected):
    assert voice_assistant.wake(wake_word) == expected


@pytest.mark.smoke
def test_nomi_rejects_are_recorded(voice_assistant):
    """被拒绝的输入也要记下来，方便之后分析唤醒失败率。"""
    voice_assistant.wake("Hey NOMI")
    voice_assistant.wake(None)
    assert voice_assistant.rejected_inputs == ["Hey NOMI", None]


def test_command_requires_awake_assistant(voice_assistant):
    """对没唤醒的助手下指令必须明确报错，不能悄悄吞掉。"""
    with pytest.raises(RuntimeError, match="未被唤醒"):
        voice_assistant.submit_command("打开导航")


@pytest.mark.smoke
def test_full_wake_and_command_flow(voice_assistant):
    """正常路径：先唤醒，再下指令，状态可观察。"""
    assert voice_assistant.wake("Hi NOMI") == "activated"
    assert voice_assistant.submit_command("打开导航") == "executed:打开导航"
    assert voice_assistant.last_command == "打开导航"
