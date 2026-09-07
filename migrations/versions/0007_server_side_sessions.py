"""Add PostgreSQL server-side sessions and pre-auth CSRF states.

Revision ID: 0007_server_side_sessions
Revises: 0006_password_credentials
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_server_side_sessions"
down_revision: str | None = "0006_password_credentials"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("GRANT USAGE ON SCHEMA auth TO sahl_app")
    op.create_table(
        "sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("bearer_digest", postgresql.BYTEA(), nullable=False),
        sa.Column("csrf_digest", postgresql.BYTEA(), nullable=False),
        sa.Column("security_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("authenticated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("idle_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("absolute_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_reason", sa.String(32)),
        sa.CheckConstraint(
            "octet_length(bearer_digest) = 32",
            name=op.f("ck_sessions_bearer_digest_length"),
        ),
        sa.CheckConstraint(
            "octet_length(csrf_digest) = 32",
            name=op.f("ck_sessions_csrf_digest_length"),
        ),
        sa.CheckConstraint(
            "idle_expires_at <= absolute_expires_at",
            name=op.f("ck_sessions_session_expiry_order"),
        ),
        sa.CheckConstraint(
            "(revoked_at IS NULL AND revoked_reason IS NULL) OR "
            "(revoked_at IS NOT NULL AND revoked_reason IN "
            "('logout','revoke_all','concurrent_limit'))",
            name=op.f("ck_sessions_session_revocation_state"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["auth.users.id"],
            name=op.f("fk_sessions_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sessions")),
        sa.UniqueConstraint("bearer_digest", name=op.f("uq_sessions_bearer_digest")),
        schema="auth",
    )
    op.create_index(
        "ix_sessions_user_active",
        "sessions",
        ["user_id", "revoked_at", "created_at"],
        schema="auth",
    )
    op.create_table(
        "preauth_csrf_states",
        sa.Column("state_digest", postgresql.BYTEA(), nullable=False),
        sa.Column("csrf_digest", postgresql.BYTEA(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "octet_length(state_digest) = 32",
            name=op.f("ck_preauth_csrf_states_state_digest_length"),
        ),
        sa.CheckConstraint(
            "octet_length(csrf_digest) = 32",
            name=op.f("ck_preauth_csrf_states_csrf_digest_length"),
        ),
        sa.CheckConstraint(
            "expires_at > created_at",
            name=op.f("ck_preauth_csrf_states_preauth_expiry_order"),
        ),
        sa.PrimaryKeyConstraint("state_digest", name=op.f("pk_preauth_csrf_states")),
        schema="auth",
    )
    for table in ("sessions", "preauth_csrf_states"):
        op.execute(f"REVOKE ALL ON TABLE auth.{table} FROM PUBLIC")
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON TABLE auth.{table} TO sahl_app")


def downgrade() -> None:
    op.execute("REVOKE USAGE ON SCHEMA auth FROM sahl_app")
    op.drop_table("preauth_csrf_states", schema="auth")
    op.drop_index("ix_sessions_user_active", table_name="sessions", schema="auth")
    op.drop_table("sessions", schema="auth")
