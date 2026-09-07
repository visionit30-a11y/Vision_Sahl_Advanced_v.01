"""Add trusted membership selection and the narrow bootstrap resolver.

Revision ID: 0008_trusted_membership
Revises: 0007_server_side_sessions
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008_trusted_membership"
down_revision: str | None = "0007_server_side_sessions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FUNCTION_SIGNATURE = "auth.resolve_active_membership(uuid, uuid, integer, integer)"


def upgrade() -> None:
    op.add_column(
        "sessions",
        sa.Column("selected_membership_id", postgresql.UUID(as_uuid=True)),
        schema="auth",
    )
    op.add_column(
        "sessions",
        sa.Column("selected_membership_version", sa.Integer()),
        schema="auth",
    )
    op.create_check_constraint(
        "selected_membership_pair",
        "sessions",
        "(selected_membership_id IS NULL) = (selected_membership_version IS NULL)",
        schema="auth",
    )
    op.create_check_constraint(
        "selected_membership_version_positive",
        "sessions",
        "selected_membership_version IS NULL OR selected_membership_version > 0",
        schema="auth",
    )
    op.create_foreign_key(
        "fk_sessions_selected_membership_id_tenant_memberships",
        "sessions",
        "tenant_memberships",
        ["selected_membership_id", "user_id"],
        ["id", "user_id"],
        source_schema="auth",
        referent_schema="auth",
        ondelete="RESTRICT",
    )
    op.execute("""
        CREATE FUNCTION auth.resolve_active_membership(
            p_user_id uuid, p_membership_id uuid,
            p_membership_version integer, p_security_version integer
        ) RETURNS TABLE (tenant_id uuid, membership_id uuid, membership_version integer)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $function$
            SELECT m.tenant_id, m.id, m.version
            FROM auth.users AS u
            JOIN auth.tenant_memberships AS m ON m.user_id = u.id
            JOIN public.tenants AS t ON t.id = m.tenant_id
            WHERE u.id = p_user_id
              AND u.status = 'active'::auth.user_status
              AND u.security_version = p_security_version
              AND m.id = p_membership_id
              AND m.status = 'active'::auth.membership_status
              AND (p_membership_version IS NULL OR m.version = p_membership_version)
              AND t.status = 'active'::public.tenant_status
        $function$
    """)
    op.execute(f"ALTER FUNCTION {FUNCTION_SIGNATURE} OWNER TO sahl_migrator")
    op.execute(f"REVOKE ALL ON FUNCTION {FUNCTION_SIGNATURE} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {FUNCTION_SIGNATURE} TO sahl_app")


def downgrade() -> None:
    op.execute(f"DROP FUNCTION {FUNCTION_SIGNATURE}")
    op.drop_constraint(
        "fk_sessions_selected_membership_id_tenant_memberships",
        "sessions",
        schema="auth",
        type_="foreignkey",
    )
    op.execute(
        "ALTER TABLE auth.sessions DROP CONSTRAINT IF EXISTS "
        "ck_sessions_selected_membership_version_positive"
    )
    op.execute(
        "ALTER TABLE auth.sessions DROP CONSTRAINT IF EXISTS ck_sessions_selected_membership_pair"
    )
    op.drop_column("sessions", "selected_membership_version", schema="auth")
    op.drop_column("sessions", "selected_membership_id", schema="auth")
