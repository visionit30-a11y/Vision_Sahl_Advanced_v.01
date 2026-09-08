"""Closed, typed security event contracts. Database writers prove referenced identities."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import UNIQUE, EnumType, StrEnum, verify
from types import MappingProxyType
from uuid import UUID

from app.authorization.permissions import PERMISSION_CATALOG, PermissionId


class InvalidSecurityAuditEventError(ValueError):
    """A fixed diagnostic that never renders caller-supplied fields or values."""

    def __init__(self) -> None:
        super().__init__("Invalid security audit event.")


class _ClosedAuditEnumType(EnumType):
    # The functional Enum factory is intentionally unavailable to this closed catalogue.
    def __call__(cls, value: object) -> StrEnum:  # type: ignore[override]
        # Enum.__new__ formats unknown values even when _missing_ raises.
        # Resolve this closed catalogue before that formatting path is reached.
        members: Mapping[str, StrEnum] = cls.__members__
        for member in members.values():
            if value is member or (type(value) is str and member.value == value):
                return member
        raise InvalidSecurityAuditEventError()


class _ClosedAuditEnum(StrEnum, metaclass=_ClosedAuditEnumType):
    pass


def _is_catalog_member(value: object, catalog: type[_ClosedAuditEnum]) -> bool:
    # String equality is insufficient: a forged StrEnum can compare equal to a
    # known member while exposing a different, untrusted .value to the writer.
    return type(value) is catalog and any(value is member for member in catalog)


@verify(UNIQUE)
class SecurityEventType(_ClosedAuditEnum):
    LOGIN_SUCCESS = "login_success"
    LOGIN_FAILURE = "login_failure"
    LOGOUT = "logout"
    SESSION_REVOKED = "session_revoked"
    ALL_SESSIONS_REVOKED = "all_sessions_revoked"
    PASSWORD_CHANGED = "password_changed"
    PASSWORD_RESET_REQUESTED = "password_reset_requested"
    PASSWORD_RESET_COMPLETED = "password_reset_completed"
    MEMBERSHIP_DENIED = "membership_denied"
    TENANT_SWITCH = "tenant_switch"
    THROTTLING_TRIGGERED = "throttling_triggered"
    AUTHORIZATION_DENIED = "authorization_denied"
    CSRF_REJECTED = "csrf_rejected"
    ORIGIN_REJECTED = "origin_rejected"
    ROLE_CREATED = "role_created"
    ROLE_UPDATED = "role_updated"
    ROLE_DISABLED = "role_disabled"
    ROLE_PERMISSION_ASSIGNED = "role_permission_assigned"
    ROLE_PERMISSION_REMOVED = "role_permission_removed"
    MEMBERSHIP_ROLE_ASSIGNED = "membership_role_assigned"
    MEMBERSHIP_ROLE_REMOVED = "membership_role_removed"
    SECURITY_EVENTS_PRUNED = "security_events_pruned"


@verify(UNIQUE)
class SecurityEventResult(_ClosedAuditEnum):
    SUCCESS = "success"
    FAILURE = "failure"
    DENIED = "denied"


@verify(UNIQUE)
class SecurityReasonCode(_ClosedAuditEnum):
    INVALID_CREDENTIALS = "invalid_credentials"
    MEMBERSHIP_UNAVAILABLE = "membership_unavailable"
    PERMISSION_DENIED = "permission_denied"
    CSRF_MISSING = "csrf_missing"
    CSRF_INVALID = "csrf_invalid"
    CSRF_STALE = "csrf_stale"
    ORIGIN_DENIED = "origin_denied"
    CSRF_BOOTSTRAP = "csrf_bootstrap"
    CONCURRENT_LIMIT = "concurrent_limit"
    LOGOUT = "logout"
    REVOKE_ALL = "revoke_all"
    PASSWORD_RESET = "password_reset"
    RETENTION_EXPIRED = "retention_expired"
    DEPENDENCY_UNAVAILABLE = "dependency_unavailable"
    LOGIN_USERNAME = "login_username"
    LOGIN_IP = "login_ip"
    LOGIN_IP_USERNAME = "login_ip_username"
    RESET_USERNAME = "reset_username"
    RESET_IP = "reset_ip"


@verify(UNIQUE)
class SubjectKind(_ClosedAuditEnum):
    LOGIN_USERNAME = "login_username"
    LOGIN_IP = "login_ip"
    RESET_USERNAME = "reset_username"
    RESET_IP = "reset_ip"


@dataclass(frozen=True, slots=True)
class SecurityEventPolicy:
    result: SecurityEventResult
    allowed_reasons: frozenset[SecurityReasonCode | None]


def _policy(result: SecurityEventResult, *reasons: SecurityReasonCode) -> SecurityEventPolicy:
    # Existing emitters without a reason remain valid; arbitrary reasons do not.
    return SecurityEventPolicy(result, frozenset((None, *reasons)))


SECURITY_EVENT_POLICIES = MappingProxyType(
    {
        SecurityEventType.LOGIN_SUCCESS: _policy(SecurityEventResult.SUCCESS),
        SecurityEventType.LOGIN_FAILURE: _policy(
            SecurityEventResult.FAILURE,
            SecurityReasonCode.INVALID_CREDENTIALS,
            SecurityReasonCode.DEPENDENCY_UNAVAILABLE,
        ),
        SecurityEventType.LOGOUT: _policy(SecurityEventResult.SUCCESS, SecurityReasonCode.LOGOUT),
        SecurityEventType.SESSION_REVOKED: _policy(
            SecurityEventResult.SUCCESS,
            SecurityReasonCode.CONCURRENT_LIMIT,
            SecurityReasonCode.LOGOUT,
            SecurityReasonCode.REVOKE_ALL,
            SecurityReasonCode.PASSWORD_RESET,
        ),
        SecurityEventType.ALL_SESSIONS_REVOKED: _policy(
            SecurityEventResult.SUCCESS,
            SecurityReasonCode.REVOKE_ALL,
            SecurityReasonCode.PASSWORD_RESET,
        ),
        SecurityEventType.PASSWORD_CHANGED: _policy(
            SecurityEventResult.SUCCESS, SecurityReasonCode.PASSWORD_RESET
        ),
        SecurityEventType.PASSWORD_RESET_REQUESTED: _policy(SecurityEventResult.SUCCESS),
        SecurityEventType.PASSWORD_RESET_COMPLETED: _policy(
            SecurityEventResult.SUCCESS, SecurityReasonCode.PASSWORD_RESET
        ),
        SecurityEventType.MEMBERSHIP_DENIED: _policy(
            SecurityEventResult.DENIED,
            SecurityReasonCode.MEMBERSHIP_UNAVAILABLE,
            SecurityReasonCode.DEPENDENCY_UNAVAILABLE,
        ),
        SecurityEventType.TENANT_SWITCH: _policy(SecurityEventResult.SUCCESS),
        SecurityEventType.THROTTLING_TRIGGERED: _policy(
            SecurityEventResult.DENIED,
            SecurityReasonCode.CSRF_BOOTSTRAP,
            SecurityReasonCode.LOGIN_USERNAME,
            SecurityReasonCode.LOGIN_IP,
            SecurityReasonCode.LOGIN_IP_USERNAME,
            SecurityReasonCode.RESET_USERNAME,
            SecurityReasonCode.RESET_IP,
        ),
        SecurityEventType.AUTHORIZATION_DENIED: _policy(
            SecurityEventResult.DENIED,
            SecurityReasonCode.PERMISSION_DENIED,
            SecurityReasonCode.MEMBERSHIP_UNAVAILABLE,
            SecurityReasonCode.DEPENDENCY_UNAVAILABLE,
        ),
        SecurityEventType.CSRF_REJECTED: _policy(
            SecurityEventResult.DENIED,
            SecurityReasonCode.CSRF_MISSING,
            SecurityReasonCode.CSRF_INVALID,
            SecurityReasonCode.CSRF_STALE,
        ),
        SecurityEventType.ORIGIN_REJECTED: _policy(
            SecurityEventResult.DENIED, SecurityReasonCode.ORIGIN_DENIED
        ),
        SecurityEventType.ROLE_CREATED: _policy(SecurityEventResult.SUCCESS),
        SecurityEventType.ROLE_UPDATED: _policy(SecurityEventResult.SUCCESS),
        SecurityEventType.ROLE_DISABLED: _policy(SecurityEventResult.SUCCESS),
        SecurityEventType.ROLE_PERMISSION_ASSIGNED: _policy(SecurityEventResult.SUCCESS),
        SecurityEventType.ROLE_PERMISSION_REMOVED: _policy(SecurityEventResult.SUCCESS),
        SecurityEventType.MEMBERSHIP_ROLE_ASSIGNED: _policy(SecurityEventResult.SUCCESS),
        SecurityEventType.MEMBERSHIP_ROLE_REMOVED: _policy(SecurityEventResult.SUCCESS),
        SecurityEventType.SECURITY_EVENTS_PRUNED: _policy(
            SecurityEventResult.SUCCESS, SecurityReasonCode.RETENTION_EXPIRED
        ),
    }
)

ROLE_EVENT_TYPES = frozenset(
    {
        SecurityEventType.ROLE_CREATED,
        SecurityEventType.ROLE_UPDATED,
        SecurityEventType.ROLE_DISABLED,
        SecurityEventType.ROLE_PERMISSION_ASSIGNED,
        SecurityEventType.ROLE_PERMISSION_REMOVED,
        SecurityEventType.MEMBERSHIP_ROLE_ASSIGNED,
        SecurityEventType.MEMBERSHIP_ROLE_REMOVED,
    }
)
ROLE_PERMISSION_EVENT_TYPES = frozenset(
    {SecurityEventType.ROLE_PERMISSION_ASSIGNED, SecurityEventType.ROLE_PERMISSION_REMOVED}
)
MEMBERSHIP_ROLE_EVENT_TYPES = frozenset(
    {SecurityEventType.MEMBERSHIP_ROLE_ASSIGNED, SecurityEventType.MEMBERSHIP_ROLE_REMOVED}
)


@dataclass(frozen=True, slots=True, init=False, repr=False)
class SecurityAuditEvent:
    """Internal intent, never proof of ownership; the writer must validate every link.

    IDs and timestamps for the event itself are absent: the writer creates them.
    Subject bytes must originate from approved HMAC processing, not session/reset
    digests. This structural contract cannot establish their cryptographic origin.
    """

    event_type: SecurityEventType
    result: SecurityEventResult
    reason_code: SecurityReasonCode | None
    user_id: UUID | None
    session_id: UUID | None
    membership_id: UUID | None
    role_id: UUID | None
    target_membership_id: UUID | None
    permission_id: PermissionId | None
    subject_digest: bytes | None
    subject_kind: SubjectKind | None
    subject_key_id: int | None
    affected_count: int | None

    def __init__(
        self,
        *,
        event_type: SecurityEventType,
        result: SecurityEventResult,
        reason_code: SecurityReasonCode | None = None,
        user_id: UUID | None = None,
        session_id: UUID | None = None,
        membership_id: UUID | None = None,
        role_id: UUID | None = None,
        target_membership_id: UUID | None = None,
        permission_id: PermissionId | None = None,
        subject_digest: bytes | None = None,
        subject_kind: SubjectKind | None = None,
        subject_key_id: int | None = None,
        affected_count: int | None = None,
        **unknown_fields: object,
    ) -> None:
        if unknown_fields:
            raise InvalidSecurityAuditEventError()
        values = {
            "event_type": event_type,
            "result": result,
            "reason_code": reason_code,
            "user_id": user_id,
            "session_id": session_id,
            "membership_id": membership_id,
            "role_id": role_id,
            "target_membership_id": target_membership_id,
            "permission_id": permission_id,
            "subject_digest": subject_digest,
            "subject_kind": subject_kind,
            "subject_key_id": subject_key_id,
            "affected_count": affected_count,
        }
        for name, value in values.items():
            object.__setattr__(self, name, value)
        self._validate()

    def __repr__(self) -> str:
        return "<SecurityAuditEvent>"

    def _validate(self) -> None:
        if not _is_catalog_member(self.event_type, SecurityEventType):
            raise InvalidSecurityAuditEventError()
        if not _is_catalog_member(self.result, SecurityEventResult):
            raise InvalidSecurityAuditEventError()
        if self.reason_code is not None and not _is_catalog_member(
            self.reason_code, SecurityReasonCode
        ):
            raise InvalidSecurityAuditEventError()
        policy = SECURITY_EVENT_POLICIES[self.event_type]
        if self.result is not policy.result or self.reason_code not in policy.allowed_reasons:
            raise InvalidSecurityAuditEventError()
        identities = (
            self.user_id,
            self.session_id,
            self.membership_id,
            self.role_id,
            self.target_membership_id,
        )
        if any(value is not None and type(value) is not UUID for value in identities):
            raise InvalidSecurityAuditEventError()
        if self.user_id is None and (self.session_id is not None or self.membership_id is not None):
            raise InvalidSecurityAuditEventError()
        if (
            self.event_type is SecurityEventType.TENANT_SWITCH
            or self.event_type in ROLE_EVENT_TYPES
        ) and (self.user_id is None or self.session_id is None or self.membership_id is None):
            raise InvalidSecurityAuditEventError()
        if (self.event_type in ROLE_EVENT_TYPES) != (self.role_id is not None):
            raise InvalidSecurityAuditEventError()
        if (self.event_type in MEMBERSHIP_ROLE_EVENT_TYPES) != (
            self.target_membership_id is not None
        ):
            raise InvalidSecurityAuditEventError()
        if self.permission_id is not None:
            if (
                type(self.permission_id) is not PermissionId
                or self.permission_id not in PERMISSION_CATALOG
                or self.event_type
                not in ROLE_PERMISSION_EVENT_TYPES | {SecurityEventType.AUTHORIZATION_DENIED}
            ):
                raise InvalidSecurityAuditEventError()
        elif self.event_type in ROLE_PERMISSION_EVENT_TYPES:
            raise InvalidSecurityAuditEventError()
        subject = (self.subject_digest, self.subject_kind, self.subject_key_id)
        if any(value is not None for value in subject) and (
            type(self.subject_digest) is not bytes
            or len(self.subject_digest) != 32
            or not _is_catalog_member(self.subject_kind, SubjectKind)
            or type(self.subject_key_id) is not int
            or not 1 <= self.subject_key_id <= 32767
        ):
            raise InvalidSecurityAuditEventError()
        if self.event_type is SecurityEventType.SECURITY_EVENTS_PRUNED:
            if type(self.affected_count) is not int or not 0 <= self.affected_count <= 2**63 - 1:
                raise InvalidSecurityAuditEventError()
            if any(value is not None for value in identities) or any(
                value is not None for value in subject
            ):
                raise InvalidSecurityAuditEventError()
        elif self.affected_count is not None:
            raise InvalidSecurityAuditEventError()
