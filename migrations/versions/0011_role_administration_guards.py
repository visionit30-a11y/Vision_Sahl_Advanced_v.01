"""Add optimistic role versions and a narrow active-membership guard.

Revision ID: 0011_role_administration_guards
Revises: 0010_tenant_rbac_foundation
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_role_administration_guards"
down_revision: str | None = "0010_tenant_rbac_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FUNCTION_SIGNATURE = "auth.is_active_membership_in_tenant(uuid,uuid)"


def upgrade() -> None:
    op.add_column(
        "roles",
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        schema="auth",
    )
    op.create_check_constraint("version_positive", "roles", "version > 0", schema="auth")
    op.execute(
        """
        CREATE FUNCTION auth.is_active_membership_in_tenant(
            p_membership_id uuid, p_tenant_id uuid
        ) RETURNS boolean
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $function$
            SELECT EXISTS (
                SELECT 1
                FROM auth.tenant_memberships AS membership
                JOIN auth.users AS user_record ON user_record.id = membership.user_id
                JOIN public.tenants AS tenant_record ON tenant_record.id = membership.tenant_id
                WHERE membership.id = p_membership_id
                  AND membership.tenant_id = p_tenant_id
                  AND membership.status = 'active'::auth.membership_status
                  AND user_record.status = 'active'::auth.user_status
                  AND tenant_record.status = 'active'::public.tenant_status
            )
        $function$
        """
    )
    op.execute(f"ALTER FUNCTION {FUNCTION_SIGNATURE} OWNER TO sahl_migrator")
    op.execute(f"REVOKE ALL ON FUNCTION {FUNCTION_SIGNATURE} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {FUNCTION_SIGNATURE} TO sahl_app")


def downgrade() -> None:
    op.execute(f"DROP FUNCTION {FUNCTION_SIGNATURE}")
    op.drop_constraint("version_positive", "roles", schema="auth", type_="check")
    op.drop_column("roles", "version", schema="auth")
