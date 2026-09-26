"""Test configuration: layered fixtures + structured result reporting.

Layering principle (interview answer)
-------------------------------------
* Expensive resources go WIDE: the ``cockpit_env`` session fixture powers
  the mocked domain controller once per run.
* Dirty state goes NARROW: every test receives a freshly reset vehicle
  signal snapshot via the function-scoped fixtures, so no test can
  pollute another ("用例之间互相影响、偶发失败" from the self-check
  table is prevented by ``reset()`` in the narrow fixtures).

Structured results
------------------
``pytest_runtest_logreport`` collects per-test records; at session end
``pytest_sessionfinish`` writes a human-readable Markdown report and a
machine-readable JSON report into ``reports/``, closing the loop
"用例设计 -> 自动执行 -> 结果分析".
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from cockpit_mock import MockCockpit

#: Directory where structured reports are written (auto-created).
REPORT_DIR = Path(__file__).parent / "reports"

#: In-memory collector for per-test results (filled by the logreport hook).
_RESULTS: list[dict] = []


# ---------------------------------------------------------------------------
# Layered fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def cockpit_env():
    """Session level: the whole test run shares ONE cockpit controller."""
    print("\n[env] power on cockpit")
    cockpit = MockCockpit()
    cockpit.power_on()
    yield cockpit  # expensive resource, created once
    print("\n[env] power off cockpit")
    cockpit.power_off()


@pytest.fixture
def vehicle_state(cockpit_env):
    """Function level: every test gets a CLEAN vehicle signal snapshot."""
    cockpit_env.reset()
    cockpit_env.set_signal("vehicle_speed", 0)
    cockpit_env.set_signal("gear", "P")
    return cockpit_env


@pytest.fixture
def hmi_home(vehicle_state):
    """Function level: open the center-display home page, close after."""
    page = vehicle_state.open_hmi_page("home")
    yield page
    page.close()


@pytest.fixture
def voice_assistant(vehicle_state):
    """Function level: a freshly reset NOMI voice assistant."""
    return vehicle_state.voice


@pytest.fixture
def bluetooth_module(vehicle_state):
    """Function level: a freshly reset Bluetooth module."""
    return vehicle_state.bluetooth


# ---------------------------------------------------------------------------
# Structured reporting hooks
# ---------------------------------------------------------------------------


def pytest_configure(config):
    """Auto-create the report directory and reset the in-memory collector."""
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    del config  # nothing config-specific needed; reports use module state
    _RESULTS.clear()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_logreport(report):
    """Collect one record per finished test (setup/call/teardown)."""
    outcome = yield
    if report.when != "call":
        return  # only the call phase carries the real verdict
    item = report.head_line or report.nodeid
    record = {
        "test_id": report.nodeid,
        "test_name": item,
        "markers": sorted(getattr(report, "keywords", {})),
        "outcome": report.outcome,  # passed / failed / skipped
        "duration_sec": round(report.duration, 4),
        "failure_reason": None,
    }
    if report.failed:
        # Longrepr holds the full crash info; keep the last line (the
        # assertion / exception summary) plus the location for analysis.
        longrepr = str(report.longrepr)
        record["failure_reason"] = longrepr.strip().splitlines()[-1][:500]
    _RESULTS.append(record)


def _write_markdown_report(records: list[dict], path: Path) -> None:
    passed = sum(1 for r in records if r["outcome"] == "passed")
    failed = sum(1 for r in records if r["outcome"] == "failed")
    skipped = sum(1 for r in records if r["outcome"] == "skipped")
    total_duration = sum(r["duration_sec"] for r in records)

    lines = [
        "# cockpit_mini Test Report",
        "",
        f"- Generated: {datetime.now(timezone.utc).isoformat()}",
        f"- Total: {len(records)} | Passed: {passed} | "
        f"Failed: {failed} | Skipped: {skipped}",
        f"- Total duration: {total_duration:.3f}s",
        "",
        "| # | Test case | Outcome | Duration | Failure reason |",
        "|---|-----------|---------|----------|----------------|",
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
    """Write Markdown + JSON structured reports at the end of the run."""
    del session, exitstatus  # reports are generated regardless of verdict
    if not _RESULTS:
        return
    _write_markdown_report(_RESULTS, REPORT_DIR / "test_report.md")
    (REPORT_DIR / "test_report.json").write_text(
        json.dumps(_RESULTS, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n[report] structured results written to {REPORT_DIR}/")
