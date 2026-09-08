"""Closed audit contracts reject free text, inconsistent links and secret-bearing input."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, fields
from typing import Any
from uuid import uuid7

import pytest

from app.audit.contracts import (
    MEMBERSHIP_ROLE_EVENT_TYPES,
    ROLE_EVENT_TYPES,
    ROLE_PERMISSION_EVENT_TYPES,
    SECURITY_EVENT_POLICIES,
    InvalidSecurityAuditEventError,
    SecurityAuditEvent,
    SecurityEventResult,
    SecurityEventType,
    SecurityReasonCode,
    SubjectKind,
)
from app.authorization.permissions import Permission, PermissionId


class Unrenderable:
    def __repr__(self) -> str:
        raise AssertionError("Untrusted input must never be rendered.")

    def __str__(self) -> str:
        raise AssertionError("Untrusted input must never be converted to text.")


def _event(
    event_type: SecurityEventType = SecurityEventType.LOGIN_FAILURE, **changes: Any
) -> SecurityAuditEvent:
    kwargs: dict[str, Any] = {
        "event_type": event_type,
        "result": SECURITY_EVENT_POLICIES[event_type].result,
    }
    if event_type in ROLE_EVENT_TYPES or event_type is SecurityEventType.TENANT_SWITCH:
        kwargs.update(user_id=uuid7(), session_id=uuid7(), membership_id=uuid7())
    if event_type in ROLE_EVENT_TYPES:
        kwargs["role_id"] = uuid7()
    if event_type in MEMBERSHIP_ROLE_EVENT_TYPES:
        kwargs["target_membership_id"] = uuid7()
    if event_type in ROLE_PERMISSION_EVENT_TYPES:
        kwargs["permission_id"] = PermissionId(Permission.TENANT_ROLES_MANAGE.value)
    if event_type is SecurityEventType.SECURITY_EVENTS_PRUNED:
        kwargs["affected_count"] = 0
    kwargs.update(changes)
    return SecurityAuditEvent(**kwargs)


def _reject(**changes: Any) -> None:
    with pytest.raises(InvalidSecurityAuditEventError) as caught:
        _event(**changes)
    assert str(caught.value) == "Invalid security audit event."
    assert repr(caught.value) == "InvalidSecurityAuditEventError('Invalid security audit event.')"


def test_catalog_is_complete_unique_and_immutable() -> None:
    assert len(SecurityEventType) == 22
    assert len(SecurityReasonCode) == 19
    assert set(SECURITY_EVENT_POLICIES) == set(SecurityEventType)
    with pytest.raises(TypeError):
        SECURITY_EVENT_POLICIES[SecurityEventType.LOGIN_SUCCESS] = (  # type: ignore[index]
            SECURITY_EVENT_POLICIES[SecurityEventType.LOGIN_FAILURE]
        )
    policy = SECURITY_EVENT_POLICIES[SecurityEventType.LOGIN_SUCCESS]
    with pytest.raises(FrozenInstanceError):
        policy.result = SecurityEventResult.DENIED  # type: ignore[misc]
    assert all(
        type(policy.allowed_reasons) is frozenset for policy in SECURITY_EVENT_POLICIES.values()
    )


@pytest.mark.parametrize("event_type", list(SecurityEventType))
def test_each_event_has_a_closed_result_and_reason_mapping(event_type: SecurityEventType) -> None:
    policy = SECURITY_EVENT_POLICIES[event_type]
    assert _event(event_type).reason_code is None
    for result in SecurityEventResult:
        if result is not policy.result:
            _reject(event_type=event_type, result=result)
    for reason in SecurityReasonCode:
        if reason in policy.allowed_reasons:
            assert _event(event_type, reason_code=reason).reason_code is reason
        else:
            _reject(event_type=event_type, reason_code=reason)


@pytest.mark.parametrize(
    "enum_type", [SecurityEventType, SecurityEventResult, SecurityReasonCode, SubjectKind]
)
def test_enum_constructor_does_not_echo_unknown_values(enum_type: Any) -> None:
    for value in ("canary-untrusted-خفي", Unrenderable()):
        with pytest.raises(InvalidSecurityAuditEventError) as caught:
            enum_type(value)
        assert str(caught.value) == "Invalid security audit event."
        assert "canary" not in repr(caught.value)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("event_type", SecurityEventType.LOGIN_FAILURE.value),
        ("result", SecurityEventResult.FAILURE.value),
        ("reason_code", SecurityReasonCode.INVALID_CREDENTIALS.value),
        ("event_type", "canary-free-event"),
        ("reason_code", "canary-free-reason-\nخفي"),
        ("result", Unrenderable()),
        ("reason_code", Unrenderable()),
    ],
)
def test_raw_event_result_reason_strings_and_objects_are_rejected(
    field: str, value: object
) -> None:
    kwargs: dict[str, Any] = {
        "event_type": SecurityEventType.LOGIN_FAILURE,
        "result": SecurityEventResult.FAILURE,
    }
    kwargs[field] = value
    with pytest.raises(InvalidSecurityAuditEventError) as caught:
        SecurityAuditEvent(**kwargs)
    assert str(caught.value) == "Invalid security audit event."


@pytest.mark.parametrize(
    "field",
    [
        "password",
        "password_hash",
        "session_bearer",
        "reset_token",
        "csrf_token",
        "database_credentials",
        "metadata",
        "correlation_id",
        "id",
        "created_at",
        "tenant_id",
        "canary-arbitrary-extra-key-خفي",
    ],
)
def test_unknown_fields_are_rejected_without_echoing_the_key_or_value(field: str) -> None:
    _reject(**{field: Unrenderable()})


@pytest.mark.parametrize(
    "field", ["user_id", "session_id", "membership_id", "role_id", "target_membership_id"]
)
def test_identity_fields_require_uuid_objects_without_coercion(field: str) -> None:
    for value in (str(uuid7()), 1, True, Unrenderable()):
        _reject(**{field: value})


def test_session_or_membership_requires_a_user() -> None:
    _reject(session_id=uuid7())
    _reject(membership_id=uuid7())
    assert _event(user_id=uuid7(), session_id=uuid7(), membership_id=uuid7()).user_id is not None


@pytest.mark.parametrize("event_type", [SecurityEventType.TENANT_SWITCH, *ROLE_EVENT_TYPES])
def test_tenant_switch_and_role_events_require_actor_links(event_type: SecurityEventType) -> None:
    for field in ("user_id", "session_id", "membership_id"):
        _reject(event_type=event_type, **{field: None})


def test_role_targets_belong_only_to_their_closed_event_types() -> None:
    _reject(role_id=uuid7())
    _reject(target_membership_id=uuid7())
    for event_type in ROLE_EVENT_TYPES:
        _reject(event_type=event_type, role_id=None)
    for event_type in MEMBERSHIP_ROLE_EVENT_TYPES:
        _reject(event_type=event_type, target_membership_id=None)
    _reject(event_type=SecurityEventType.ROLE_UPDATED, target_membership_id=uuid7())


def test_permissions_are_typed_catalog_members_and_scoped_to_relevant_events() -> None:
    permission = PermissionId(Permission.TENANT_ROLES_MANAGE.value)
    assert _event(SecurityEventType.AUTHORIZATION_DENIED, permission_id=permission).permission_id
    for value in (
        str(permission),
        Permission.TENANT_ROLES_MANAGE,
        PermissionId("tenant.unknown_resource.unknown_action"),
        Unrenderable(),
    ):
        _reject(event_type=SecurityEventType.AUTHORIZATION_DENIED, permission_id=value)
    _reject(permission_id=permission)
    for event_type in ROLE_PERMISSION_EVENT_TYPES:
        _reject(event_type=event_type, permission_id=None)


@pytest.mark.parametrize("kind", list(SubjectKind))
def test_subject_digest_requires_closed_purpose_and_key_identifier(kind: SubjectKind) -> None:
    event = _event(subject_digest=b"a" * 32, subject_kind=kind, subject_key_id=1)
    assert event.subject_digest == b"a" * 32
    assert event.subject_kind is kind
    assert event.subject_key_id == 1
    for field in ("subject_digest", "subject_kind", "subject_key_id"):
        values: dict[str, Any] = {
            "subject_digest": b"a" * 32,
            "subject_kind": kind,
            "subject_key_id": 1,
        }
        values[field] = None
        _reject(**values)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("subject_digest", b"a" * 31),
        ("subject_digest", b"a" * 33),
        ("subject_digest", "a" * 32),
        ("subject_digest", bytearray(b"a" * 32)),
        ("subject_kind", SubjectKind.LOGIN_USERNAME.value),
        ("subject_kind", "canary-ip-value"),
        ("subject_key_id", True),
        ("subject_key_id", 1.0),
        ("subject_key_id", "1"),
        ("subject_key_id", 0),
        ("subject_key_id", 32768),
        ("subject_digest", Unrenderable()),
        ("subject_key_id", Unrenderable()),
    ],
)
def test_subject_triad_uses_strict_scalar_types_and_lengths(field: str, value: object) -> None:
    values: dict[str, Any] = {
        "subject_digest": b"a" * 32,
        "subject_kind": SubjectKind.LOGIN_USERNAME,
        "subject_key_id": 1,
    }
    values[field] = value
    _reject(**values)


def test_maintenance_count_is_reserved_bounded_and_disallows_identity_or_subject_fields() -> None:
    for count in (0, 100, 2**63 - 1):
        assert (
            _event(SecurityEventType.SECURITY_EVENTS_PRUNED, affected_count=count).affected_count
            == count
        )
    for invalid_count in (None, -1, True, 1.0, "1", 2**63, Unrenderable()):
        _reject(event_type=SecurityEventType.SECURITY_EVENTS_PRUNED, affected_count=invalid_count)
    _reject(affected_count=0)
    _reject(event_type=SecurityEventType.SECURITY_EVENTS_PRUNED, user_id=uuid7())
    _reject(
        event_type=SecurityEventType.SECURITY_EVENTS_PRUNED,
        subject_digest=b"a" * 32,
        subject_kind=SubjectKind.LOGIN_IP,
        subject_key_id=1,
    )


def test_event_is_frozen_closed_and_has_no_field_rendering() -> None:
    event = _event(
        user_id=uuid7(),
        subject_digest=b"a" * 32,
        subject_kind=SubjectKind.LOGIN_IP,
        subject_key_id=1,
    )
    assert repr(event) == str(event) == "<SecurityAuditEvent>"
    assert not hasattr(event, "__dict__")
    with pytest.raises(FrozenInstanceError):
        event.user_id = uuid7()  # type: ignore[misc]
    assert {field.name for field in fields(event)} == {
        "event_type",
        "result",
        "reason_code",
        "user_id",
        "session_id",
        "membership_id",
        "role_id",
        "target_membership_id",
        "permission_id",
        "subject_digest",
        "subject_kind",
        "subject_key_id",
        "affected_count",
    }
    invalid_event = object.__new__(SecurityAuditEvent)
    object.__setattr__(invalid_event, "user_id", Unrenderable())
    assert repr(invalid_event) == "<SecurityAuditEvent>"


@pytest.mark.parametrize(
    ("field", "member"),
    [
        ("event_type", SecurityEventType.LOGIN_FAILURE),
        ("result", SecurityEventResult.FAILURE),
        ("reason_code", SecurityReasonCode.INVALID_CREDENTIALS),
        ("subject_kind", SubjectKind.LOGIN_IP),
    ],
)
@pytest.mark.parametrize("uses_known_string", [False, True])
def test_forged_enum_instances_are_rejected_without_exposing_values(
    field: str, member: Any, uses_known_string: bool
) -> None:
    canary = "canary-forged-audit-enum"
    forged = str.__new__(type(member), member.value if uses_known_string else canary)
    forged._name_ = "FORGED"
    forged._value_ = Unrenderable()
    values: dict[str, Any] = {
        "event_type": SecurityEventType.LOGIN_FAILURE,
        "result": SecurityEventResult.FAILURE,
        "reason_code": SecurityReasonCode.INVALID_CREDENTIALS,
        "subject_digest": b"a" * 32,
        "subject_kind": SubjectKind.LOGIN_IP,
        "subject_key_id": 1,
    }
    event = SecurityAuditEvent(**values)
    values[field] = forged
    with pytest.raises(InvalidSecurityAuditEventError) as caught:
        SecurityAuditEvent(**values)
    assert str(caught.value) == "Invalid security audit event."
    assert canary not in repr(caught.value)
    object.__setattr__(event, field, forged)
    with pytest.raises(InvalidSecurityAuditEventError) as caught:
        event._validate()
    assert str(caught.value) == "Invalid security audit event."
    assert canary not in repr(caught.value) + repr(event)
