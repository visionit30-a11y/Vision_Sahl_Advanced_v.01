"""ORM models.

Importing this package registers every model on Base.metadata, which is what
Alembic compares the database against. A model that is not reachable from here
is invisible to autogenerate.
"""

from __future__ import annotations

from app.models.auth_security import PasswordResetToken, SecurityEvent, ThrottleBucket
from app.models.authorization import MembershipRole, Role, RolePermission, RoleStatus
from app.models.identity import (
    AuthSession,
    MembershipStatus,
    PasswordCredential,
    PreAuthCsrfState,
    TenantMembership,
    User,
    UserStatus,
)
from app.models.tenant import Tenant
from app.models.ui_settings import PlatformUiSettings, TenantUiSettings, UserUiSettings

__all__ = [
    "AuthSession",
    "MembershipRole",
    "MembershipStatus",
    "PasswordCredential",
    "PasswordResetToken",
    "PlatformUiSettings",
    "PreAuthCsrfState",
    "Role",
    "RolePermission",
    "RoleStatus",
    "SecurityEvent",
    "Tenant",
    "TenantMembership",
    "TenantUiSettings",
    "ThrottleBucket",
    "User",
    "UserStatus",
    "UserUiSettings",
]
