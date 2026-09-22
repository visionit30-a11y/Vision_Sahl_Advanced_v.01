"""Add the narrow last-tenant-admin guard boundary.

Revision ID: 0023_tenant_admin_guard
Revises: 0022_password_change_fix
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0023_tenant_admin_guard"
down_revision: str | None = "0022_password_change_fix"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


SIGNATURE = "auth.has_other_active_tenant_admin(uuid,uuid)"


def upgrade() -> None:
    op.execute("""
        CREATE FUNCTION auth.has_other_active_tenant_admin(
          p_membership uuid,p_role uuid
        ) RETURNS boolean
        LANGUAGE sql STABLE STRICT SECURITY DEFINER SET search_path=pg_catalog AS $f$
          SELECT EXISTS(
            SELECT 1
            FROM auth.roles target_role
            JOIN auth.tenant_memberships target_membership
              ON target_membership.tenant_id=target_role.tenant_id
             AND target_membership.id=p_membership
            JOIN auth.membership_roles other_assignment
              ON other_assignment.tenant_id=target_role.tenant_id
             AND other_assignment.role_id=target_role.id
             AND other_assignment.membership_id<>p_membership
            JOIN auth.tenant_memberships other_membership
              ON other_membership.tenant_id=other_assignment.tenant_id
             AND other_membership.id=other_assignment.membership_id
            WHERE target_role.tenant_id=app.current_tenant_id()
              AND target_role.id=p_role
              AND target_role.kind='tenant_admin'::auth.role_kind
              AND target_role.status='active'::auth.role_status
              AND other_membership.status='active'::auth.membership_status
          )
        $f$
    """)
    op.execute(f"ALTER FUNCTION {SIGNATURE} OWNER TO sahl_migrator")
    op.execute(f"REVOKE ALL ON FUNCTION {SIGNATURE} FROM PUBLIC,sahl_app")
    op.execute(f"GRANT EXECUTE ON FUNCTION {SIGNATURE} TO sahl_app")


def downgrade() -> None:
    op.execute(f"DROP FUNCTION {SIGNATURE}")
