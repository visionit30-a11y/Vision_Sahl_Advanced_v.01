"""The single, typed catalogue of stable authorization permission identifiers."""

from __future__ import annotations

import re
from collections.abc import Iterable
from enum import UNIQUE, StrEnum, verify

PERMISSION_ID_PATTERN = re.compile(r"^(?:tenant|platform)\.[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")


class InvalidPermissionIdError(ValueError):
    """Raised when a permission identifier violates the published naming contract."""


class InvalidPermissionCatalogError(ValueError):
    """Raised when a permission catalogue contains duplicate identifiers."""


class PermissionId(str):
    """Validated ``<scope>.<resource>.<action>`` permission identifier."""

    def __new__(cls, value: str) -> PermissionId:
        if not isinstance(value, str) or PERMISSION_ID_PATTERN.fullmatch(value) is None:
            raise InvalidPermissionIdError(
                "Permission IDs must use <tenant|platform>.<resource>.<action>."
            )
        return str.__new__(cls, value)


@verify(UNIQUE)
class Permission(StrEnum):
    """Stable permissions belonging to the identity and authorization domain only."""

    TENANT_MEMBERSHIPS_READ = "tenant.memberships.read"
    TENANT_MEMBERSHIPS_MANAGE = "tenant.memberships.manage"
    TENANT_ROLES_READ = "tenant.roles.read"
    TENANT_ROLES_MANAGE = "tenant.roles.manage"
    TENANT_USER_UI_SETTINGS_MANAGE_SELF = "tenant.user_ui_settings.manage_self"
    TENANT_UI_SETTINGS_MANAGE = "tenant.ui_settings.manage"
    PLATFORM_TENANTS_READ = "platform.tenants.read"
    PLATFORM_TENANTS_MANAGE = "platform.tenants.manage"
    PLATFORM_UI_SETTINGS_MANAGE = "platform.ui_settings.manage"


def build_permission_catalog(values: Iterable[str]) -> frozenset[PermissionId]:
    """Validate and freeze a catalogue, rejecting aliases rather than hiding them."""
    materialized = tuple(PermissionId(value) for value in values)
    if len(materialized) != len(set(materialized)):
        raise InvalidPermissionCatalogError("Permission IDs must be unique.")
    return frozenset(materialized)


PERMISSION_CATALOG = build_permission_catalog(permission.value for permission in Permission)
