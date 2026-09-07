# ruff: noqa: E501
"""Add the tenant-owned RBAC persistence foundation.

Revision ID: 0010_tenant_rbac_foundation
Revises: 0009_auth_security_controls
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010_tenant_rbac_foundation"
down_revision: str | None = "0009_auth_security_controls"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLE_STATUS_VALUES = ("active", "inactive")
TABLES = ("roles", "role_permissions", "membership_roles")


def upgrade() -> None:
    role_status = postgresql.ENUM(*ROLE_STATUS_VALUES, name="role_status", schema="auth")
    role_status.create(op.get_bind(), checkfirst=False)
    op.create_unique_constraint(
        "uq_tenant_memberships_tenant_id", "tenant_memberships", ["tenant_id", "id"], schema="auth"
    )
    op.create_table(
        "roles",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("key", sa.String(63), nullable=False),
        sa.Column("display_name", sa.String(120), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(
                *ROLE_STATUS_VALUES, name="role_status", schema="auth", create_type=False
            ),
            server_default=sa.text("'active'::auth.role_status"),
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
        sa.CheckConstraint("key ~ '^[a-z][a-z0-9_]{0,62}$'", name=op.f("ck_roles_key_format")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["public.tenants.id"],
            name=op.f("fk_roles_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_roles")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_roles_tenant_id"),
        sa.UniqueConstraint("tenant_id", "key", name="uq_roles_tenant_key"),
        schema="auth",
    )
    op.create_table(
        "role_permissions",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("permission_id", sa.String(128), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "permission_id ~ '^tenant\\.[a-z][a-z0-9_]*\\.[a-z][a-z0-9_]*$'",
            name=op.f("ck_role_permissions_permission_id_format"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "role_id"],
            ["auth.roles.tenant_id", "auth.roles.id"],
            name="fk_role_permissions_tenant_role",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "tenant_id", "role_id", "permission_id", name=op.f("pk_role_permissions")
        ),
        schema="auth",
    )
    op.create_table(
        "membership_roles",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("membership_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "membership_id"],
            ["auth.tenant_memberships.tenant_id", "auth.tenant_memberships.id"],
            name="fk_membership_roles_tenant_membership",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "role_id"],
            ["auth.roles.tenant_id", "auth.roles.id"],
            name="fk_membership_roles_tenant_role",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "tenant_id", "membership_id", "role_id", name=op.f("pk_membership_roles")
        ),
        schema="auth",
    )
    for table in TABLES:
        op.execute(f"ALTER TABLE auth.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE auth.{table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON auth.{table} FOR ALL TO sahl_app USING (tenant_id = app.current_tenant_id()) WITH CHECK (tenant_id = app.current_tenant_id())"
        )
        op.execute(f"REVOKE ALL ON TABLE auth.{table} FROM PUBLIC, sahl_app")
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE auth.{table} TO sahl_app")


def downgrade() -> None:
    op.drop_table("membership_roles", schema="auth")
    op.drop_table("role_permissions", schema="auth")
    op.drop_table("roles", schema="auth")
    op.drop_constraint(
        "uq_tenant_memberships_tenant_id", "tenant_memberships", schema="auth", type_="unique"
    )
    role_status = postgresql.ENUM(*ROLE_STATUS_VALUES, name="role_status", schema="auth")
    role_status.drop(op.get_bind(), checkfirst=False)
