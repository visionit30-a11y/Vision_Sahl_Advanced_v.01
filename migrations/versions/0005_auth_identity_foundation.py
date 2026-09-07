"""Create the global identity and cross-tenant membership security catalogue.

Revision ID: 0005_auth_identity_foundation
Revises: 0004_runtime_privilege_boundary
Create Date: 2026-09-07
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_auth_identity_foundation"
down_revision: str | None = "0004_runtime_privilege_boundary"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

USER_STATUS_VALUES = ("pending", "active", "suspended", "archived")
MEMBERSHIP_STATUS_VALUES = ("pending", "active", "suspended", "left")


def upgrade() -> None:
    """Create identity tables without opening a runtime data path."""
    op.execute("CREATE SCHEMA auth")
    op.execute("REVOKE ALL ON SCHEMA auth FROM PUBLIC")
    op.execute(
        "ALTER DEFAULT PRIVILEGES FOR ROLE sahl_migrator IN SCHEMA auth "
        "REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC"
    )

    user_status = postgresql.ENUM(
        *USER_STATUS_VALUES, name="user_status", schema="auth"
    )
    membership_status = postgresql.ENUM(
        *MEMBERSHIP_STATUS_VALUES, name="membership_status", schema="auth"
    )
    user_status.create(op.get_bind(), checkfirst=False)
    membership_status.create(op.get_bind(), checkfirst=False)

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("normalized_email", sa.String(length=254), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(
                *USER_STATUS_VALUES,
                name="user_status",
                schema="auth",
                create_type=False,
            ),
            server_default=sa.text("'pending'::auth.user_status"),
            nullable=False,
        ),
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "security_version",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "security_version > 0", name=op.f("ck_users_security_version_positive")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("normalized_email", name=op.f("uq_users_normalized_email")),
        schema="auth",
    )

    op.create_table(
        "tenant_memberships",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(
                *MEMBERSHIP_STATUS_VALUES,
                name="membership_status",
                schema="auth",
                create_type=False,
            ),
            server_default=sa.text("'pending'::auth.membership_status"),
            nullable=False,
        ),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("left_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "version > 0", name=op.f("ck_tenant_memberships_version_positive")
        ),
        sa.CheckConstraint(
            "(status = 'active' AND joined_at IS NOT NULL AND left_at IS NULL) OR "
            "(status IN ('pending', 'suspended') AND left_at IS NULL) OR "
            "(status = 'left' AND left_at IS NOT NULL)",
            name=op.f("ck_tenant_memberships_lifecycle_timestamps"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["public.tenants.id"],
            name=op.f("fk_tenant_memberships_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["auth.users.id"],
            name=op.f("fk_tenant_memberships_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tenant_memberships")),
        sa.UniqueConstraint("id", "user_id", name="uq_tenant_memberships_id_user"),
        sa.UniqueConstraint(
            "user_id", "tenant_id", name="uq_tenant_memberships_user_tenant"
        ),
        schema="auth",
    )
    op.create_index(
        "ix_tenant_memberships_user_id_status",
        "tenant_memberships",
        ["user_id", "status"],
        unique=False,
        schema="auth",
    )
    op.create_index(
        "ix_tenant_memberships_tenant_id_status",
        "tenant_memberships",
        ["tenant_id", "status"],
        unique=False,
        schema="auth",
    )

    op.execute(
        "REVOKE ALL ON TABLE auth.users, auth.tenant_memberships FROM PUBLIC, sahl_app"
    )


def downgrade() -> None:
    """Remove identity objects in dependency order and restore function defaults."""
    op.drop_index(
        "ix_tenant_memberships_tenant_id_status",
        table_name="tenant_memberships",
        schema="auth",
    )
    op.drop_index(
        "ix_tenant_memberships_user_id_status",
        table_name="tenant_memberships",
        schema="auth",
    )
    op.drop_table("tenant_memberships", schema="auth")
    op.drop_table("users", schema="auth")

    membership_status = postgresql.ENUM(
        *MEMBERSHIP_STATUS_VALUES, name="membership_status", schema="auth"
    )
    user_status = postgresql.ENUM(
        *USER_STATUS_VALUES, name="user_status", schema="auth"
    )
    membership_status.drop(op.get_bind(), checkfirst=False)
    user_status.drop(op.get_bind(), checkfirst=False)

    op.execute(
        "ALTER DEFAULT PRIVILEGES FOR ROLE sahl_migrator IN SCHEMA auth "
        "GRANT EXECUTE ON FUNCTIONS TO PUBLIC"
    )
    op.execute("DROP SCHEMA auth RESTRICT")
