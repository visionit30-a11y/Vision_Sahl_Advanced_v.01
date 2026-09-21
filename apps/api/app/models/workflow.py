"""Tenant-owned persistence metadata for shared workflow and approvals."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
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

from app.db.base import Base


class WorkflowRequest(Base):
    __tablename__ = "workflow_requests"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_workflow_requests_tenant_id"),
        CheckConstraint("request_type ~ '^[a-z][a-z0-9_]{0,62}$'", name="type"),
        CheckConstraint("length(btrim(title)) BETWEEN 1 AND 160", name="title"),
        CheckConstraint("length(description) BETWEEN 1 AND 2000", name="description"),
        CheckConstraint(
            "status IN ('draft','pending','approved','rejected','returned')", name="status"
        ),
        CheckConstraint("version > 0", name="version"),
        CheckConstraint("requester_membership_id <> approver_membership_id", name="separation"),
        Index(
            "ix_workflow_requests_requester", "tenant_id", "requester_membership_id", "updated_at"
        ),
        Index("ix_workflow_requests_status", "tenant_id", "status", "updated_at"),
        ForeignKeyConstraint(
            ["tenant_id", "requester_membership_id"],
            ["auth.tenant_memberships.tenant_id", "auth.tenant_memberships.id"],
            name="fk_workflow_requests_requester",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "approver_membership_id"],
            ["auth.tenant_memberships.tenant_id", "auth.tenant_memberships.id"],
            name="fk_workflow_requests_approver",
            ondelete="RESTRICT",
        ),
        {"schema": "app"},
    )
    id: Mapped[uuid.UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("tenants.id", name="fk_workflow_requests_tenant", ondelete="CASCADE"),
        nullable=False,
    )
    requester_membership_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True), nullable=False
    )
    approver_membership_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True), nullable=False
    )
    request_type: Mapped[str] = mapped_column(String(63), nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(String(2000), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'draft'"))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WorkflowApprovalTask(Base):
    __tablename__ = "workflow_approval_tasks"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_workflow_tasks_tenant_id"),
        CheckConstraint(
            "status IN ('pending','approved','rejected','returned','cancelled')", name="status"
        ),
        CheckConstraint("version > 0", name="version"),
        ForeignKeyConstraint(
            ["tenant_id", "request_id"],
            ["app.workflow_requests.tenant_id", "app.workflow_requests.id"],
            name="fk_workflow_tasks_request",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "assignee_membership_id"],
            ["auth.tenant_memberships.tenant_id", "auth.tenant_memberships.id"],
            name="fk_workflow_tasks_assignee",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_workflow_tasks_inbox", "tenant_id", "assignee_membership_id", "status", "created_at"
        ),
        {"schema": "app"},
    )
    id: Mapped[uuid.UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(PostgresUUID(as_uuid=True), nullable=False)
    request_id: Mapped[uuid.UUID] = mapped_column(PostgresUUID(as_uuid=True), nullable=False)
    assignee_membership_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'pending'")
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    decision_note: Mapped[str | None] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WorkflowEvent(Base):
    __tablename__ = "workflow_events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('created','updated','submitted','resubmitted',"
            "'approved','rejected','returned')",
            name="type",
        ),
        CheckConstraint(
            "to_status IN ('draft','pending','approved','rejected','returned')", name="to_status"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "request_id"],
            ["app.workflow_requests.tenant_id", "app.workflow_requests.id"],
            name="fk_workflow_events_request",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "actor_membership_id"],
            ["auth.tenant_memberships.tenant_id", "auth.tenant_memberships.id"],
            name="fk_workflow_events_actor",
            ondelete="RESTRICT",
        ),
        Index("ix_workflow_events_history", "tenant_id", "request_id", "created_at", "id"),
        {"schema": "app"},
    )
    id: Mapped[uuid.UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(PostgresUUID(as_uuid=True), nullable=False)
    request_id: Mapped[uuid.UUID] = mapped_column(PostgresUUID(as_uuid=True), nullable=False)
    actor_membership_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(16), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(16))
    to_status: Mapped[str] = mapped_column(String(16), nullable=False)
    note: Mapped[str | None] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
