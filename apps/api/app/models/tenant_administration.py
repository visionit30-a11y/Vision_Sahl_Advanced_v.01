"""Tenant-scoped append-only access administration history."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TenantAccessEvent(Base):
    """Human-facing access history; application grants never permit mutation."""

    __tablename__ = "tenant_access_events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('user_invited','membership_activated','membership_suspended',"
            "'tenant_admin_bootstrapped','password_admin_reset','role_created',"
            "'role_updated','role_disabled','permission_assigned','permission_removed',"
            "'role_assigned','role_removed')",
            name="type",
        ),
        Index("ix_access_events_tenant_created", "tenant_id", "created_at", "id"),
        {"schema": "app"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, default=uuid.uuid7
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    actor_membership_id: Mapped[uuid.UUID | None] = mapped_column(PostgresUUID(as_uuid=True))
    target_membership_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True), nullable=False
    )
    role_id: Mapped[uuid.UUID | None] = mapped_column(PostgresUUID(as_uuid=True))
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("clock_timestamp()")
    )
