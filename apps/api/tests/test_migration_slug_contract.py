"""The slug contract must mean the same thing in the domain and in the schema.

Migration 0002 repeats the contract instead of importing it, because a
migration has to keep meaning what it meant on the day it ran and importing
application code would let a later edit rewrite the past. Duplication is the
right answer there and a drift risk everywhere, so the two copies are compared
here: a change to one that is not made to the other fails the suite rather than
producing a database that accepts what the domain rejects.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.models.tenant import (
    SLUG_FORBIDDEN_SEQUENCE,
    SLUG_MAX_LENGTH,
    SLUG_MIN_LENGTH,
    SLUG_PATTERN,
)

MIGRATION = (
    Path(__file__).resolve().parents[3]
    / "migrations"
    / "versions"
    / "0002_tenant_foundation.py"
)


def migration_constant(name: str) -> str:
    """The literal assigned to a module level constant in the migration."""
    source = MIGRATION.read_text(encoding="utf-8")
    # The name may carry a type annotation, as down_revision does.
    found = re.search(
        rf"^{name}(?::[^=]+)? = r?[\"'](?P<value>.*)[\"']$", source, re.MULTILINE
    )
    assert found, f"{name} is not defined in {MIGRATION.name}"
    return found.group("value")


def migration_number(name: str) -> int:
    source = MIGRATION.read_text(encoding="utf-8")
    found = re.search(rf"^{name}(?::[^=]+)? = (?P<value>\d+)$", source, re.MULTILINE)
    assert found, f"{name} is not defined in {MIGRATION.name}"
    return int(found.group("value"))


def test_the_migration_exists_where_the_test_expects_it() -> None:
    assert MIGRATION.is_file(), f"{MIGRATION} is missing"


def test_the_pattern_matches_the_domain() -> None:
    assert migration_constant("SLUG_PATTERN") == SLUG_PATTERN


def test_the_length_bounds_match_the_domain() -> None:
    assert migration_number("SLUG_MIN_LENGTH") == SLUG_MIN_LENGTH
    assert migration_number("SLUG_MAX_LENGTH") == SLUG_MAX_LENGTH


def test_the_forbidden_sequence_matches_the_domain() -> None:
    assert migration_constant("SLUG_FORBIDDEN_SEQUENCE") == SLUG_FORBIDDEN_SEQUENCE


def test_the_check_constraint_enforces_all_three_rules() -> None:
    """Not just that the constants match, but that the constraint uses them."""
    source = MIGRATION.read_text(encoding="utf-8")

    assert "char_length(slug) BETWEEN" in source
    assert "slug ~ '" in source
    assert "slug !~ '" in source


def test_the_migration_follows_the_baseline() -> None:
    assert migration_constant("down_revision") == "0001_baseline"


def test_the_migration_declares_no_isolation_policy() -> None:
    """RLS is a later, separate decision; tenants is a platform table.

    If a policy appears here, it arrived without the ADR that should have
    accompanied it.
    """
    source = MIGRATION.read_text(encoding="utf-8").upper()

    assert "ROW LEVEL SECURITY" not in source
    assert "CREATE POLICY" not in source
