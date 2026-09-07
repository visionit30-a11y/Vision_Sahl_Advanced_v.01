"""The database tests must never be filtered out of a quality gate.

The "db" marker exists so a developer can run `pytest -m "not db"` for a fast
loop. That is a convenience, not a mode the project ships in: the tests it hides
are the ones that prove ownership and, later, isolation. Excluding them from
03-test.ps1 or from CI would leave a green suite that proves nothing about the
thing this phase exists to establish, so the exclusion is checked for here
rather than left to review.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]

GATE_FILES = [
    REPOSITORY_ROOT / "scripts" / "03-test.ps1",
    REPOSITORY_ROOT / ".github" / "workflows" / "ci.yml",
]


@pytest.mark.parametrize("path", GATE_FILES, ids=lambda p: p.name)
def test_the_gate_file_exists(path: Path) -> None:
    assert path.is_file(), f"{path} is missing"


@pytest.mark.parametrize("path", GATE_FILES, ids=lambda p: p.name)
def test_no_quality_gate_excludes_the_database_tests(path: Path) -> None:
    content = path.read_text(encoding="utf-8")

    assert "not db" not in content, (
        f"{path.name} filters out the database tests. They are blocking: a run "
        "without them proves nothing about schema ownership or isolation."
    )


@pytest.mark.parametrize("path", GATE_FILES, ids=lambda p: p.name)
def test_security_proofs_and_cleanup_are_blocking_in_both_gates(path: Path) -> None:
    content = path.read_text(encoding="utf-8")
    assert "--strict-security-gates" in content
    assert "tests.db.verify_clean_database" in content
    assert "continue-on-error:" not in content


def test_ci_uses_the_real_postgresql_17_service_and_separate_roles() -> None:
    content = GATE_FILES[1].read_text(encoding="utf-8")
    assert "image: postgres:17" in content
    assert "DATABASE_URL: postgresql+psycopg://sahl_app:" in content
    assert "MIGRATION_DATABASE_URL: postgresql+psycopg://sahl_migrator:" in content
    assert "if: always()" in content


def test_probe_is_never_registered_in_a_production_migration() -> None:
    for path in (REPOSITORY_ROOT / "migrations" / "versions").glob("*.py"):
        assert "tenant_scoped_probe" not in path.read_text(encoding="utf-8"), str(path)
