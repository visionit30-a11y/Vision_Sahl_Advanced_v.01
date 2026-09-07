"""Prove the gate rejects real pytest skip/xfail outcomes in an isolated run."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("def test_ok():\n    assert True\n", 0),
        ("import pytest\ndef test_skipped():\n    pytest.skip('gate regression')\n", 1),
        ("import pytest\n@pytest.mark.xfail\ndef test_expected_failure():\n    assert False\n", 1),
        ("import pytest\n@pytest.mark.xfail\ndef test_unexpected_pass():\n    assert True\n", 1),
        ("import pytest\npytest.skip('collection regression', allow_module_level=True)\n", 1),
    ],
    ids=["pass", "skip", "xfail", "xpass", "collection-skip"],
)
def test_strict_mode_uses_nonzero_exit_for_nonpassing_outcomes(
    tmp_path: Path, body: str, expected: int
) -> None:
    (tmp_path / "test_sample.py").write_text(body, encoding="utf-8")
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(API_ROOT)
    environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "tests.security_gate",
            "--strict-security-gates",
            "--tb=short",
            "-q",
            str(tmp_path),
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == expected, result.stdout + result.stderr
