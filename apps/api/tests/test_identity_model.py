"""Domain contracts for global users and cross-tenant memberships."""

from __future__ import annotations

import uuid

import pytest

from app.models.identity import (
    MEMBERSHIP_STATUS_TRANSITIONS,
    USER_STATUS_TRANSITIONS,
    InvalidEmailAddressError,
    InvalidIdentityStatusTransitionError,
    MembershipStatus,
    TenantMembership,
    User,
    UserStatus,
    assert_membership_transition_allowed,
    assert_user_transition_allowed,
    new_membership_id,
    new_user_id,
    normalize_email,
)


def test_identity_ids_are_distinct_uuid_version_7_values() -> None:
    values = [new_user_id(), new_membership_id(), new_user_id(), new_membership_id()]

    assert all(isinstance(value, uuid.UUID) and value.version == 7 for value in values)
    assert len(set(values)) == len(values)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (" Person@Example.COM ", "person@example.com"),
        ("first.last+tag@example.co.uk", "first.last+tag@example.co.uk"),
    ],
)
def test_email_normalization_is_explicit_and_provider_neutral(raw: str, expected: str) -> None:
    assert normalize_email(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["", "plain-address", "name@localhost", "name@exa_mple.com", "مستخدم@example.com"],
)
def test_email_normalization_rejects_values_outside_the_ascii_contract(raw: str) -> None:
    with pytest.raises(InvalidEmailAddressError):
        normalize_email(raw)


def test_user_lifecycle_is_complete_and_archived_is_final() -> None:
    assert set(USER_STATUS_TRANSITIONS) == set(UserStatus)
    assert USER_STATUS_TRANSITIONS[UserStatus.ARCHIVED] == frozenset()
    assert_user_transition_allowed(UserStatus.PENDING, UserStatus.ACTIVE)
    assert_user_transition_allowed(UserStatus.ACTIVE, UserStatus.SUSPENDED)
    assert_user_transition_allowed(UserStatus.SUSPENDED, UserStatus.ACTIVE)
    with pytest.raises(InvalidIdentityStatusTransitionError):
        assert_user_transition_allowed(UserStatus.ARCHIVED, UserStatus.ACTIVE)


def test_membership_lifecycle_is_complete_and_left_is_final() -> None:
    assert set(MEMBERSHIP_STATUS_TRANSITIONS) == set(MembershipStatus)
    assert MEMBERSHIP_STATUS_TRANSITIONS[MembershipStatus.LEFT] == frozenset()
    assert_membership_transition_allowed(MembershipStatus.PENDING, MembershipStatus.ACTIVE)
    assert_membership_transition_allowed(MembershipStatus.ACTIVE, MembershipStatus.SUSPENDED)
    assert_membership_transition_allowed(MembershipStatus.SUSPENDED, MembershipStatus.ACTIVE)
    with pytest.raises(InvalidIdentityStatusTransitionError):
        assert_membership_transition_allowed(MembershipStatus.LEFT, MembershipStatus.ACTIVE)


def test_users_are_global_and_memberships_carry_the_tenant_reference() -> None:
    assert "tenant_id" not in User.__table__.columns
    assert "tenant_id" in TenantMembership.__table__.columns
    assert "role" not in TenantMembership.__table__.columns
    assert "permissions" not in TenantMembership.__table__.columns
