"""Expose narrow, session-bound auth HTTP projections.

Revision ID: 0013_auth_http_projections
Revises: 0012_ui_settings_foundation
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0013_auth_http_projections"
down_revision: str | None = "0012_ui_settings_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FUNCTION_SIGNATURES = (
    "auth.session_identity(bytea)",
    "auth.session_memberships(bytea)",
)


def upgrade() -> None:
    # Authentication metadata is an explicit identity-security exception. These
    # projections prove the live bearer digest, active user and security version;
    # they do not accept a user/tenant selector or create a TenantContext.
    op.execute("""
        CREATE FUNCTION auth.session_identity(p_bearer_digest bytea)
        RETURNS TABLE (user_id uuid, email text, security_version integer)
        LANGUAGE sql STABLE STRICT SECURITY DEFINER SET search_path = pg_catalog
        AS $function$
            SELECT u.id, u.email::text, u.security_version
            FROM auth.sessions AS s
            JOIN auth.users AS u ON u.id = s.user_id
            WHERE s.bearer_digest = p_bearer_digest
              AND s.revoked_at IS NULL
              AND s.idle_expires_at > statement_timestamp()
              AND s.absolute_expires_at > statement_timestamp()
              AND u.status = 'active'::auth.user_status
              AND u.security_version = s.security_version
        $function$
    """)
    op.execute("""
        CREATE FUNCTION auth.session_memberships(p_bearer_digest bytea)
        RETURNS TABLE (
            membership_id uuid, tenant_id uuid,
            tenant_name text, membership_version integer
        )
        LANGUAGE sql STABLE STRICT SECURITY DEFINER SET search_path = pg_catalog
        AS $function$
            SELECT m.id, m.tenant_id, t.name_ar::text, m.version
            FROM auth.sessions AS s
            JOIN auth.users AS u ON u.id = s.user_id
            JOIN auth.tenant_memberships AS m ON m.user_id = u.id
            JOIN public.tenants AS t ON t.id = m.tenant_id
            WHERE s.bearer_digest = p_bearer_digest
              AND s.revoked_at IS NULL
              AND s.idle_expires_at > statement_timestamp()
              AND s.absolute_expires_at > statement_timestamp()
              AND u.status = 'active'::auth.user_status
              AND u.security_version = s.security_version
              AND m.status = 'active'::auth.membership_status
              AND t.status = 'active'::public.tenant_status
            ORDER BY m.id
        $function$
    """)
    for signature in FUNCTION_SIGNATURES:
        op.execute(f"ALTER FUNCTION {signature} OWNER TO sahl_migrator")
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO sahl_app")


def downgrade() -> None:
    for signature in reversed(FUNCTION_SIGNATURES):
        op.execute(f"DROP FUNCTION {signature}")
