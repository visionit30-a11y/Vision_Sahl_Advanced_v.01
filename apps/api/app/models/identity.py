"""Global user identity and the cross-tenant membership security catalogue."""

from __future__ import annotations

import re
import unicodedata
import uuid
from datetime import datetime
from enum import StrEnum
from typing import NewType

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

UserId = NewType("UserId", uuid.UUID)
MembershipId = NewType("MembershipId", uuid.UUID)

EMAIL_MAX_LENGTH = 254
_ASCII_EMAIL = re.compile(
    r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$"
)


class InvalidEmailAddressError(ValueError):
    """Raised when a login identifier is outside the Phase 2B email contract."""


def new_user_id() -> UserId:
    return UserId(uuid.uuid7())


def new_membership_id() -> MembershipId:
    return MembershipId(uuid.uuid7())


def normalize_email(value: str) -> str:
    """Normalize one ASCII email for identity lookup, without provider-specific rules."""
    normalized = unicodedata.normalize("NFC", value).strip()
    if len(normalized) > EMAIL_MAX_LENGTH or not _ASCII_EMAIL.fullmatch(normalized):
        raise InvalidEmailAddressError("The email address does not meet the identity contract.")
    return normalized.casefold()


class UserStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    ARCHIVED = "archived"


class MembershipStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    LEFT = "left"


USER_STATUS_TRANSITIONS: dict[UserStatus, frozenset[UserStatus]] = {
    UserStatus.PENDING: frozenset({UserStatus.ACTIVE, UserStatus.ARCHIVED}),
    UserStatus.ACTIVE: frozenset({UserStatus.SUSPENDED, UserStatus.ARCHIVED}),
    UserStatus.SUSPENDED: frozenset({UserStatus.ACTIVE, UserStatus.ARCHIVED}),
    UserStatus.ARCHIVED: frozenset(),
}

MEMBERSHIP_STATUS_TRANSITIONS: dict[MembershipStatus, frozenset[MembershipStatus]] = {
    MembershipStatus.PENDING: frozenset(
        {MembershipStatus.ACTIVE, MembershipStatus.SUSPENDED, MembershipStatus.LEFT}
    ),
    MembershipStatus.ACTIVE: frozenset({MembershipStatus.SUSPENDED, MembershipStatus.LEFT}),
    MembershipStatus.SUSPENDED: frozenset({MembershipStatus.ACTIVE, MembershipStatus.LEFT}),
    MembershipStatus.LEFT: frozenset(),
}


class InvalidIdentityStatusTransitionError(ValueError):
    """Raised when an identity-security lifecycle transition is forbidden."""


def assert_user_transition_allowed(current: UserStatus, target: UserStatus) -> None:
    if target not in USER_STATUS_TRANSITIONS[current]:
        raise InvalidIdentityStatusTransitionError(
            f"A user cannot move from {current.value} to {target.value}."
        )


def assert_membership_transition_allowed(
    current: MembershipStatus, target: MembershipStatus
) -> None:
    if target not in MEMBERSHIP_STATUS_TRANSITIONS[current]:
        raise InvalidIdentityStatusTransitionError(
            f"A membership cannot move from {current.value} to {target.value}."
        )


class User(Base):
    """A platform identity that may hold memberships in several tenants."""

    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("security_version > 0", name="security_version_positive"),
        {"schema": "auth"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, default=new_user_id
    )
    email: Mapped[str] = mapped_column(String(EMAIL_MAX_LENGTH), nullable=False)
    normalized_email: Mapped[str] = mapped_column(
        String(EMAIL_MAX_LENGTH), nullable=False, unique=True
    )
    status: Mapped[UserStatus] = mapped_column(
        Enum(
            UserStatus,
            name="user_status",
            schema="auth",
            values_callable=lambda enum: [member.value for member in enum],
        ),
        nullable=False,
        server_default=text("'pending'::auth.user_status"),
    )
    email_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    security_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} status={self.status.value}>"


class TenantMembership(Base):
    """An identity-security association used to prove access before TenantContext exists."""

    __tablename__ = "tenant_memberships"
    __table_args__ = (
        UniqueConstraint("user_id", "tenant_id", name="uq_tenant_memberships_user_tenant"),
        UniqueConstraint("id", "user_id", name="uq_tenant_memberships_id_user"),
        CheckConstraint("version > 0", name="version_positive"),
        CheckConstraint(
            "(status = 'active' AND joined_at IS NOT NULL AND left_at IS NULL) OR "
            "(status IN ('pending', 'suspended') AND left_at IS NULL) OR "
            "(status = 'left' AND left_at IS NOT NULL)",
            name="lifecycle_timestamps",
        ),
        Index("ix_tenant_memberships_user_id_status", "user_id", "status"),
        Index("ix_tenant_memberships_tenant_id_status", "tenant_id", "status"),
        {"schema": "auth"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, default=new_membership_id
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("auth.users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        # Tenant is registered as the default-schema table key in Phase 2A.
        # PostgreSQL resolves that key to public; migration 0005 records the
        # physical cross-schema reference explicitly as public.tenants.id.
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[MembershipStatus] = mapped_column(
        Enum(
            MembershipStatus,
            name="membership_status",
            schema="auth",
            values_callable=lambda enum: [member.value for member in enum],
        ),
        nullable=False,
        server_default=text("'pending'::auth.membership_status"),
    )
    joined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    left_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<TenantMembership id={self.id} user_id={self.user_id} status={self.status.value}>"


class PasswordCredential(Base):
    """One non-reversible Argon2id credential per platform user."""

    __tablename__ = "password_credentials"
    __table_args__ = (
        CheckConstraint("credential_version > 0", name="credential_version_positive"),
        CheckConstraint("password_hash LIKE '$argon2id$%'", name="password_hash_argon2id"),
        {"schema": "auth"},
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("auth.users.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    credential_version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1")
    )
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    def __repr__(self) -> str:
        return (
            f"<PasswordCredential user_id={self.user_id} "
            f"credential_version={self.credential_version}>"
        )
