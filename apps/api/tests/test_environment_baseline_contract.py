"""The setup scripts must be able to read the virtual environments we create.

A pyvenv.cfg does not have one agreed shape. Python's own venv module writes
``version``; uv writes ``version_info``. A reader that knows only the first one
returns nothing for a uv environment without failing, which is how a correct
3.14.7 environment was once reported as running "" and rejected. These tests
pin the contract on the actual script, so narrowing it again breaks the suite
rather than a rebuild.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

COMMON_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "_common.ps1"

# The two real shapes, as written by uv 0.12 and by python -m venv.
UV_PYVENV_CFG = """\
home = C:\\Users\\someone\\AppData\\Local\\Programs\\Python\\Python314
implementation = CPython
uv = 0.12.10
version_info = 3.14.7
include-system-site-packages = false
prompt = sahl-api
"""

STDLIB_PYVENV_CFG = """\
home = C:\\Users\\someone\\AppData\\Local\\Programs\\Python\\Python313
include-system-site-packages = false
version = 3.13.1
executable = C:\\Users\\someone\\AppData\\Local\\Programs\\Python\\Python313\\python.exe
"""


def read_declared_version_keys() -> list[str]:
    """The keys scripts/_common.ps1 declares for reading a pyvenv.cfg."""
    source = COMMON_SCRIPT.read_text(encoding="ascii")
    match = re.search(r"\$script:PyvenvVersionKeys\s*=\s*@\((?P<keys>[^)]*)\)", source)
    assert match, "scripts/_common.ps1 no longer declares $script:PyvenvVersionKeys"
    return re.findall(r"'([^']+)'", match.group("keys"))


def read_version_with(keys: list[str], config: str) -> str | None:
    """The lookup scripts/_common.ps1 performs, in the same order it performs it."""
    for key in keys:
        for line in config.splitlines():
            found = re.match(rf"^\s*{re.escape(key)}\s*=\s*(?P<value>\S+)\s*$", line)
            if found:
                return found.group("value")
    return None


def test_the_common_script_is_where_the_tests_expect_it() -> None:
    assert COMMON_SCRIPT.is_file(), f"{COMMON_SCRIPT} is missing"


def test_both_pyvenv_cfg_dialects_are_declared() -> None:
    keys = read_declared_version_keys()

    assert "version_info" in keys, "uv writes version_info; a reader without it sees nothing"
    assert "version" in keys, "python -m venv writes version"


@pytest.mark.parametrize(
    ("config", "expected"),
    [(UV_PYVENV_CFG, "3.14.7"), (STDLIB_PYVENV_CFG, "3.13.1")],
    ids=["uv", "stdlib-venv"],
)
def test_the_declared_keys_read_both_dialects(config: str, expected: str) -> None:
    assert read_version_with(read_declared_version_keys(), config) == expected


def test_a_key_never_matches_a_longer_key_that_starts_with_it() -> None:
    """A short key must not half-match a longer one and return a truncated read."""
    assert read_version_with(["version"], UV_PYVENV_CFG) is None


def test_a_file_without_any_version_key_reads_as_nothing_rather_than_blank() -> None:
    config = "home = C:\\Python\nprompt = x\n"

    assert read_version_with(read_declared_version_keys(), config) is None


@pytest.mark.parametrize(
    ("config", "expected_line"),
    [(UV_PYVENV_CFG, "3.14"), (STDLIB_PYVENV_CFG, "3.13")],
    ids=["uv", "stdlib-venv"],
)
def test_the_baseline_is_compared_on_major_minor(config: str, expected_line: str) -> None:
    """The baseline is a release line; patch levels move under us."""
    version = read_version_with(read_declared_version_keys(), config)
    assert version is not None
    found = re.search(r"(\d+)\.(\d+)", version)
    assert found
    assert f"{found.group(1)}.{found.group(2)}" == expected_line


def test_no_script_still_reads_pyvenv_cfg_with_the_narrow_pattern() -> None:
    """The bug was three copies of ^version\\s*= . There must be none left."""
    offenders = [
        path.name
        for path in sorted(COMMON_SCRIPT.parent.glob("*.ps1"))
        if "'^version\\s*='" in path.read_text(encoding="ascii")
    ]

    assert offenders == []
