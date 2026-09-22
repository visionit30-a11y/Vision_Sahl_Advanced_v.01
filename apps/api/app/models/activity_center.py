"""Tenant-owned notification center and user preference persistence."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_notifications_tenant_id"),
        CheckConstraint(
            "kind IN ('request_submitted','approval_requested','request_returned',"
            "'request_rejected','request_approved','task_overdue')",
            name="kind",
        ),
        CheckConstraint("length(title_snapshot) BETWEEN 1 AND 160", name="title"),
        ForeignKeyConstraint(
            ["tenant_id", "recipient_membership_id"],
            ["auth.tenant_memberships.tenant_id", "auth.tenant_memberships.id"],
            name="fk_notifications_recipient",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "request_id"],
            ["app.workflow_requests.tenant_id", "app.workflow_requests.id"],
            name="fk_notifications_request",
            ondelete="CASCADE",
        ),
        Index(
            "ix_notifications_recipient",
            "tenant_id",
            "recipient_membership_id",
            "read_at",
            "created_at",
        ),
        {"schema": "app"},
    )
    id: Mapped[uuid.UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("tenants.id", name="fk_notifications_tenant", ondelete="CASCADE"),
        nullable=False,
    )
    recipient_membership_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True), nullable=False
    )
    request_id: Mapped[uuid.UUID] = mapped_column(PostgresUUID(as_uuid=True), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    title_snapshot: Mapped[str] = mapped_column(String(160), nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class NotificationPreference(Base):
    __tablename__ = "notification_preferences"
    __table_args__ = (
        CheckConstraint("version > 0", name="version"),
        ForeignKeyConstraint(
            ["tenant_id", "membership_id"],
            ["auth.tenant_memberships.tenant_id", "auth.tenant_memberships.id"],
            name="fk_notification_preferences_membership",
            ondelete="CASCADE",
        ),
        {"schema": "app"},
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("tenants.id", name="fk_notification_preferences_tenant", ondelete="CASCADE"),
        primary_key=True,
    )
    membership_id: Mapped[uuid.UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True)
    approval_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    request_approved: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    request_rejected: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    request_returned: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    overdue_tasks: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
