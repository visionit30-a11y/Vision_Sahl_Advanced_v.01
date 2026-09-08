"""Authentication throttles, reset tokens, and append-only security events."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import BYTEA, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.audit.contracts import SecurityEventType
from app.audit.schema import AUDIT_CHECKS
from app.db.base import Base

EVENT_TYPES = tuple(event.value for event in SecurityEventType)


class ThrottleBucket(Base):
    __tablename__ = "throttle_buckets"
    __table_args__ = (
        CheckConstraint("octet_length(key_digest)=32", name="key_digest_length"),
        CheckConstraint("request_count>0", name="request_count_positive"),
        {"schema": "auth"},
    )
    scope: Mapped[str] = mapped_column(String(40), primary_key=True)
    key_digest: Mapped[bytes] = mapped_column(BYTEA, primary_key=True)
    window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    key_id: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    request_count: Mapped[int] = mapped_column(Integer, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"
    __table_args__ = (
        CheckConstraint("octet_length(token_digest)=32", name="token_digest_length"),
        UniqueConstraint("token_digest", name="uq_password_reset_tokens_digest"),
        Index("ix_password_reset_tokens_user_open", "user_id", "consumed_at", "revoked_at"),
        {"schema": "auth"},
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("auth.users.id", ondelete="CASCADE"), nullable=False
    )
    token_digest: Mapped[bytes] = mapped_column(BYTEA, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    def __repr__(self) -> str:
        return f"<PasswordResetToken id={self.id} user_id={self.user_id}>"


class SecurityEvent(Base):
    __tablename__ = "security_events"
    __table_args__ = (
        *(CheckConstraint(expression, name=name) for name, expression in AUDIT_CHECKS.items()),
        {"schema": "auth"},
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid7)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    result: Mapped[str] = mapped_column(String(16), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(40))
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    session_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    membership_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    subject_digest: Mapped[bytes | None] = mapped_column(BYTEA)
    role_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    target_membership_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    permission_id: Mapped[str | None] = mapped_column(String(120))
    subject_kind: Mapped[str | None] = mapped_column(String(32))
    subject_key_id: Mapped[int | None] = mapped_column(SmallInteger)
    affected_count: Mapped[int | None] = mapped_column(BigInteger)
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    def __repr__(self) -> str:
        return "<SecurityEvent>"
