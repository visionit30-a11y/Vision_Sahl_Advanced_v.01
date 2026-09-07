"""Add Argon2id password credentials.

Revision ID: 0006_password_credentials
Revises: 0005_auth_identity_foundation
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_password_credentials"
down_revision: str | None = "0005_auth_identity_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "password_credentials",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column(
            "credential_version",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column(
            "changed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "credential_version > 0",
            name=op.f("ck_password_credentials_credential_version_positive"),
        ),
        sa.CheckConstraint(
            "password_hash LIKE '$argon2id$%'",
            name=op.f("ck_password_credentials_password_hash_argon2id"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["auth.users.id"],
            name=op.f("fk_password_credentials_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_password_credentials")),
        schema="auth",
    )
    op.execute("REVOKE ALL ON TABLE auth.password_credentials FROM PUBLIC")
    op.execute("REVOKE ALL ON TABLE auth.password_credentials FROM sahl_app")


def downgrade() -> None:
    op.drop_table("password_credentials", schema="auth")
