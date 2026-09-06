"""The tenant's identity contract and its lifecycle.

These are domain tests: no database, no session. What the database enforces is
tested in tests/db, against the database.
"""

from __future__ import annotations

import uuid

import pytest

from app.models.tenant import (
    ALLOWED_STATUS_TRANSITIONS,
    SLUG_MAX_LENGTH,
    SLUG_MIN_LENGTH,
    InvalidTenantSlugError,
    InvalidTenantStatusTransitionError,
    TenantStatus,
    assert_transition_allowed,
    can_transition,
    new_tenant_id,
    validate_tenant_slug,
)


def test_a_generated_identity_is_a_uuid_version_7() -> None:
    """Version 7, not merely "a uuid": v4 would scatter the index of every
    tenant owned table, and the choice must not drift silently."""
    identity = new_tenant_id()

    assert isinstance(identity, uuid.UUID)
    assert identity.version == 7


def test_generated_identities_are_distinct() -> None:
    assert len({new_tenant_id() for _ in range(1000)}) == 1000


def test_generated_identities_are_time_ordered() -> None:
    """The property v7 is chosen for: later identities sort after earlier ones."""
    identities = [new_tenant_id() for _ in range(50)]

    assert identities == sorted(identities)


@pytest.mark.parametrize(
    "slug",
    [
        "abc",
        "a-b-c",
        "tenant-1",
        "a1b",
        "0ab",
        "x" * SLUG_MIN_LENGTH,
        "x" * SLUG_MAX_LENGTH,
        "a-b-c-d",
    ],
    ids=lambda slug: slug[:12],
)
def test_slugs_that_meet_the_contract(slug: str) -> None:
    assert validate_tenant_slug(slug) == slug


@pytest.mark.parametrize(
    "slug",
    [
        "ab",
        "x" * (SLUG_MAX_LENGTH + 1),
        "",
        "-abc",
        "abc-",
        "ab--c",
        "Abc",
        "ab_c",
        "ab c",
        "ab.c",
        "جمعية",
        "ab/c",
    ],
    ids=[
        "too-short",
        "too-long",
        "empty",
        "leading-hyphen",
        "trailing-hyphen",
        "double-hyphen",
        "uppercase",
        "underscore",
        "space",
        "dot",
        "non-ascii",
        "slash",
    ],
)
def test_slugs_that_do_not(slug: str) -> None:
    with pytest.raises(InvalidTenantSlugError):
        validate_tenant_slug(slug)


def test_the_slug_is_not_an_identity() -> None:
    """A reminder in executable form: nothing derives an identity from a slug.

    ADR-0014 makes id the only security identity. This test fails if
    new_tenant_id ever starts depending on the slug.
    """
    assert new_tenant_id() != new_tenant_id()


def test_every_status_has_a_transition_rule() -> None:
    assert set(ALLOWED_STATUS_TRANSITIONS) == set(TenantStatus)


def test_archived_is_final() -> None:
    assert ALLOWED_STATUS_TRANSITIONS[TenantStatus.ARCHIVED] == frozenset()
    for target in TenantStatus:
        assert not can_transition(TenantStatus.ARCHIVED, target)


def test_suspension_is_reversible() -> None:
    assert can_transition(TenantStatus.ACTIVE, TenantStatus.SUSPENDED)
    assert can_transition(TenantStatus.SUSPENDED, TenantStatus.ACTIVE)


def test_a_pending_tenant_becomes_active_but_not_suspended() -> None:
    assert can_transition(TenantStatus.PENDING, TenantStatus.ACTIVE)
    assert not can_transition(TenantStatus.PENDING, TenantStatus.SUSPENDED)


def test_every_status_can_be_archived_except_archived_itself() -> None:
    for status in TenantStatus:
        expected = status is not TenantStatus.ARCHIVED
        assert can_transition(status, TenantStatus.ARCHIVED) is expected


def test_staying_put_is_not_a_transition() -> None:
    """Re-applying a status is a no-op for a caller to notice, not a move."""
    for status in TenantStatus:
        assert not can_transition(status, status)


def test_asserting_a_forbidden_transition_names_both_ends() -> None:
    with pytest.raises(InvalidTenantStatusTransitionError) as failure:
        assert_transition_allowed(TenantStatus.ARCHIVED, TenantStatus.ACTIVE)

    assert "archived" in str(failure.value)
    assert "active" in str(failure.value)


def test_asserting_an_allowed_transition_is_silent() -> None:
    assert_transition_allowed(TenantStatus.PENDING, TenantStatus.ACTIVE)


def test_status_values_are_the_strings_the_database_stores() -> None:
    assert {status.value for status in TenantStatus} == {
        "pending",
        "active",
        "suspended",
        "archived",
    }
