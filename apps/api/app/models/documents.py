"""Tenant-owned metadata for objects stored outside PostgreSQL."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
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


class WorkflowDocument(Base):
    __tablename__ = "workflow_documents"
    __table_args__ = (
        UniqueConstraint("tenant_id", "object_key", name="uq_workflow_documents_object_key"),
        CheckConstraint("length(btrim(filename)) BETWEEN 1 AND 180", name="filename"),
        CheckConstraint("filename !~ '[[:cntrl:]/\\\\]'", name="filename_safe"),
        CheckConstraint(
            "content_type IN ('application/pdf','image/png','image/jpeg')", name="type"
        ),
        CheckConstraint("byte_size BETWEEN 1 AND 10485760", name="size"),
        CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="hash"),
        CheckConstraint(
            "object_key = tenant_id::text || '/' || replace(id::text, '-', '')",
            name="object_key_scope",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "request_id"],
            ["app.workflow_requests.tenant_id", "app.workflow_requests.id"],
            name="fk_workflow_documents_request",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "uploaded_by_membership_id"],
            ["auth.tenant_memberships.tenant_id", "auth.tenant_memberships.id"],
            name="fk_workflow_documents_uploader",
            ondelete="RESTRICT",
        ),
        Index("ix_workflow_documents_request", "tenant_id", "request_id", "created_at"),
        {"schema": "app"},
    )
    id: Mapped[uuid.UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(PostgresUUID(as_uuid=True), nullable=False)
    request_id: Mapped[uuid.UUID] = mapped_column(PostgresUUID(as_uuid=True), nullable=False)
    uploaded_by_membership_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True), nullable=False
    )
    filename: Mapped[str] = mapped_column(String(180), nullable=False)
    content_type: Mapped[str] = mapped_column(String(32), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    object_key: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp()
    )
