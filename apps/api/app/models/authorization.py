"""Tenant-owned RBAC persistence contracts without authorization decisions."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from enum import StrEnum
from typing import NewType

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.authorization.permissions import PermissionId
from app.db.base import Base

RoleId = NewType("RoleId", uuid.UUID)
ROLE_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


class InvalidRoleKeyError(ValueError):
    """Raised when a stable role key violates the domain contract."""


class RoleKey(str):
    """Stable machine key; display names never participate in authorization."""

    def __new__(cls, value: str) -> RoleKey:
        if not isinstance(value, str) or ROLE_KEY_PATTERN.fullmatch(value) is None:
            raise InvalidRoleKeyError("Role keys must be 1-63 lowercase ASCII characters.")
        return str.__new__(cls, value)


class RoleStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"


def new_role_id() -> RoleId:
    return RoleId(uuid.uuid7())


class Role(Base):
    """A tenant-owned bundle whose name is presentation data only."""

    __tablename__ = "roles"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_roles_tenant_id"),
        UniqueConstraint("tenant_id", "key", name="uq_roles_tenant_key"),
        CheckConstraint("key ~ '^[a-z][a-z0-9_]{0,62}$'", name="key_format"),
        CheckConstraint("version > 0", name="version_positive"),
        {"schema": "auth"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, default=new_role_id
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False
    )
    key: Mapped[str] = mapped_column(String(63), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[RoleStatus] = mapped_column(
        Enum(
            RoleStatus,
            name="role_status",
            schema="auth",
            values_callable=lambda enum: [member.value for member in enum],
        ),
        nullable=False,
        server_default=text("'active'::auth.role_status"),
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<Role id={self.id} tenant_id={self.tenant_id} status={self.status.value}>"


class RolePermission(Base):
    """One catalogued tenant permission assigned to a role in the same tenant."""

    __tablename__ = "role_permissions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "role_id"],
            ["auth.roles.tenant_id", "auth.roles.id"],
            name="fk_role_permissions_tenant_role",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "permission_id ~ '^tenant\\.[a-z][a-z0-9_]*\\.[a-z][a-z0-9_]*$'",
            name="permission_id_format",
        ),
        {"schema": "auth"},
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True)
    role_id: Mapped[uuid.UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True)
    permission_id: Mapped[PermissionId] = mapped_column(String(128), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MembershipRole(Base):
    """A tenant membership-to-role assignment constrained to one tenant."""

    __tablename__ = "membership_roles"
    __table_args__ = (
        Index("ix_membership_roles_tenant_role", "tenant_id", "role_id"),
        ForeignKeyConstraint(
            ["tenant_id", "membership_id"],
            ["auth.tenant_memberships.tenant_id", "auth.tenant_memberships.id"],
            name="fk_membership_roles_tenant_membership",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "role_id"],
            ["auth.roles.tenant_id", "auth.roles.id"],
            name="fk_membership_roles_tenant_role",
            ondelete="CASCADE",
        ),
        {"schema": "auth"},
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True)
    membership_id: Mapped[uuid.UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True)
    role_id: Mapped[uuid.UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
