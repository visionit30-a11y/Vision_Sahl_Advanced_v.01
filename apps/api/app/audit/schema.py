"""SQL constraints generated from the closed runtime audit and permission catalogues."""

from __future__ import annotations

from collections.abc import Iterable

from app.audit.contracts import (
    MEMBERSHIP_ROLE_EVENT_TYPES,
    ROLE_EVENT_TYPES,
    ROLE_PERMISSION_EVENT_TYPES,
    SECURITY_EVENT_POLICIES,
    SecurityEventType,
    SubjectKind,
)
from app.authorization.permissions import PERMISSION_CATALOG


def _values(values: Iterable[str]) -> str:
    return ",".join("'" + value.replace("'", "''") + "'" for value in sorted(values))


_role_events = _values(ROLE_EVENT_TYPES)
_membership_events = _values(MEMBERSHIP_ROLE_EVENT_TYPES)
_permission_events = _values(ROLE_PERMISSION_EVENT_TYPES)
_event_contracts = []
for _event, _policy in SECURITY_EVENT_POLICIES.items():
    _reasons = _values(reason for reason in _policy.allowed_reasons if reason is not None)
    _reason_check = "reason_code IS NULL"
    if _reasons:
        _reason_check = f"(reason_code IS NULL OR reason_code IN ({_reasons}))"
    _event_contracts.append(
        f"(event_type = '{_event}' AND result = '{_policy.result}' AND {_reason_check})"
    )

AUDIT_CHECKS: dict[str, str] = {
    "event_type_allowed": f"event_type IN ({_values(SecurityEventType)})",
    "result_allowed": "result IN ('success','failure','denied')",
    "event_contract": " OR ".join(_event_contracts),
    "event_id_uuid7": (
        "id::text ~ '^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'"
    ),
    "correlation_id_format": (
        "correlation_id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'"
    ),
    "identity_shape": (
        "(user_id IS NOT NULL OR (session_id IS NULL AND membership_id IS NULL)) AND "
        f"(event_type NOT IN ('tenant_switch',{_role_events}) OR "
        "(user_id IS NOT NULL AND session_id IS NOT NULL AND membership_id IS NOT NULL))"
    ),
    "role_shape": f"(event_type IN ({_role_events})) = (role_id IS NOT NULL)",
    "target_membership_shape": (
        f"(event_type IN ({_membership_events})) = (target_membership_id IS NOT NULL)"
    ),
    "permission_catalog": (
        f"permission_id IS NULL OR permission_id IN ({_values(PERMISSION_CATALOG)})"
    ),
    "permission_shape": (
        f"(event_type NOT IN ({_permission_events}) OR permission_id IS NOT NULL) AND "
        f"(permission_id IS NULL OR event_type IN ('authorization_denied',{_permission_events}))"
    ),
    "subject_shape": (
        "(subject_digest IS NULL AND subject_kind IS NULL AND subject_key_id IS NULL) OR "
        "(subject_digest IS NOT NULL AND octet_length(subject_digest) = 32 AND "
        f"subject_kind IS NOT NULL AND subject_kind IN ({_values(SubjectKind)}) AND "
        "subject_key_id IS NOT NULL AND subject_key_id BETWEEN 1 AND 32767)"
    ),
    "affected_count_shape": (
        "(event_type <> 'security_events_pruned' AND affected_count IS NULL) OR "
        "(event_type = 'security_events_pruned' AND affected_count IS NOT NULL AND "
        "affected_count >= 0 AND user_id IS NULL AND session_id IS NULL AND membership_id IS NULL "
        "AND role_id IS NULL AND target_membership_id IS NULL AND subject_digest IS NULL "
        "AND subject_kind IS NULL AND subject_key_id IS NULL)"
    ),
}
