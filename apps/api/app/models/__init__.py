"""ORM models.

Importing this package registers every model on Base.metadata, which is what
Alembic compares the database against. A model that is not reachable from here
is invisible to autogenerate.
"""

from __future__ import annotations

from app.models.auth_security import PasswordResetToken, SecurityEvent, ThrottleBucket
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

__all__ = [
    "AuthSession",
    "MembershipStatus",
    "PasswordCredential",
    "PasswordResetToken",
    "PreAuthCsrfState",
    "SecurityEvent",
    "Tenant",
    "TenantMembership",
    "ThrottleBucket",
    "User",
    "UserStatus",
]
