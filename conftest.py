"""pytest 配置：分层 fixture + 结构化测试报告。

fixture 为什么要分层
--------------------
一句话：**贵的资源用宽作用域，脏的状态用窄作用域。**

* 贵的资源 —— ``cockpit_env`` 是 session 级的，整个测试运行只创建一次
  座舱控制器。它创建成本高，没必要每条用例都重建。
* 脏的状态 —— ``vehicle_state`` 等是函数级的，每条用例都拿到一份重新
  ``reset()`` 过的车辆快照，所以用例之间**不可能互相污染**，也就不存在
  "单独跑能过、一起跑就挂"的偶发失败。

结构化报告
----------
``pytest_runtest_logreport`` 钩子逐条收集用例结果，运行结束时的
``pytest_sessionfinish`` 往 ``reports/`` 目录写两份文件（Markdown + JSON），
把"用例设计 → 自动执行 → 结果分析"这个闭环补上。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from cockpit_mock import MockCockpit

#: 结构化报告的输出目录（不存在会自动创建）。
REPORT_DIR = Path(__file__).parent / "reports"

#: 内存里存放每条用例的结果，由下面的钩子填充。
_RESULTS: list[dict] = []


# ---------------------------------------------------------------------------
# 分层 fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def cockpit_env():
    """session 级：整个测试运行**共用同一个**座舱控制器。"""
    print("\n[env] 座舱上电")
    cockpit = MockCockpit()
    cockpit.power_on()
    yield cockpit  # 这里是贵的资源，只创建一次
    print("\n[env] 座舱下电")
    cockpit.power_off()


@pytest.fixture
def vehicle_state(cockpit_env):
    """函数级：每条用例都拿到一份**干净**的车辆信号快照。"""
    cockpit_env.reset()
    cockpit_env.set_signal("vehicle_speed", 0)
    cockpit_env.set_signal("gear", "P")
    return cockpit_env


@pytest.fixture
def hmi_home(vehicle_state):
    """函数级：打开中控屏首页，用例结束后关闭。"""
    page = vehicle_state.open_hmi_page("home")
    yield page
    page.close()


@pytest.fixture
def voice_assistant(vehicle_state):
    """函数级：一个刚重置过的 NOMI 语音助手。"""
    return vehicle_state.voice


@pytest.fixture
def bluetooth_module(vehicle_state):
    """函数级：一个刚重置过的蓝牙模块。"""
    return vehicle_state.bluetooth


# ---------------------------------------------------------------------------
# 结构化报告钩子
# ---------------------------------------------------------------------------


def pytest_configure(config):
    """自动创建报告目录，并清空内存里的收集器。"""
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    _RESULTS.clear()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_logreport(report):
    """每条用例结束时收集一条记录（setup / call / teardown 三个阶段）。"""
    yield
    if report.when != "call":
        return  # 只有 call 阶段才代表真正的测试结果
    record = {
        "test_id": report.nodeid,
        "test_name": report.head_line or report.nodeid,
        "outcome": report.outcome,  # passed / failed / skipped
        "duration_sec": round(report.duration, 4),
        "failure_reason": None,
    }
    if report.failed:
        # longrepr 里是完整的报错信息，这里只取最后一行
        # （也就是断言失败或异常的那一句），足够定位问题了。
        record["failure_reason"] = str(report.longrepr).strip().splitlines()[-1][:500]
    _RESULTS.append(record)


def _write_markdown_report(records: list[dict], path: Path) -> None:
    """把收集到的结果写成一张人看的 Markdown 表格。"""
    passed = sum(1 for r in records if r["outcome"] == "passed")
    failed = sum(1 for r in records if r["outcome"] == "failed")
    skipped = sum(1 for r in records if r["outcome"] == "skipped")
    total_duration = sum(r["duration_sec"] for r in records)

    lines = [
        "# cockpit_mini 测试报告",
        "",
        f"- 生成时间：{datetime.now(timezone.utc).isoformat()}",
        f"- 总数：{len(records)} | 通过：{passed} | 失败：{failed} | 跳过：{skipped}",
        f"- 总耗时：{total_duration:.3f}s",
        "",
        "| # | 用例 | 结果 | 耗时 | 失败原因 |",
        "|---|------|------|------|----------|",
    ]
    for i, r in enumerate(records, 1):
        reason = r["failure_reason"] or "-"
        lines.append(
            f"| {i} | {r['test_name']} | {r['outcome']} | "
            f"{r['duration_sec']}s | {reason} |"
        )
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def pytest_sessionfinish(session, exitstatus):
    """整个运行结束时写出 Markdown + JSON 两份报告。"""
    if not _RESULTS:
        return
    _write_markdown_report(_RESULTS, REPORT_DIR / "test_report.md")
    (REPORT_DIR / "test_report.json").write_text(
        json.dumps(_RESULTS, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n[report] 结构化报告已写入 {REPORT_DIR}/")
