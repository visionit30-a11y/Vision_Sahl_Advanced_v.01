"""Pytest quality-gate mode: skipped or expected-failure tests cannot pass a gate."""

from __future__ import annotations

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--strict-security-gates",
        action="store_true",
        help="Fail the quality gate on any skipped, xfailed or xpassed test.",
    )


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    if not session.config.getoption("--strict-security-gates"):
        return
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    if reporter is None:
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
        return
    unsupported = [name for name in ("skipped", "xfailed", "xpassed") if reporter.stats.get(name)]
    if unsupported:
        reporter.write_sep("=", "Blocking quality gate rejected: " + ", ".join(unsupported))
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
