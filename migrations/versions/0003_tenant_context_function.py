"""Transaction-local tenant identity reader.

The setting carries no authority by itself: the service transaction boundary
supplies a validated tenant identity, while this function only reads it. Missing,
empty and malformed values return NULL. No table lookup, default identity or
security-definer privilege is involved.

Revision ID: 0003_tenant_context_function
Revises: 0002_tenant_foundation
Create Date: 2026-09-07
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0003_tenant_context_function"
down_revision: str | None = "0002_tenant_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Install the reader in the existing, migration-owned app schema."""
    op.execute(
        """
        CREATE FUNCTION app.current_tenant_id()
        RETURNS uuid
        LANGUAGE plpgsql
        STABLE
        SECURITY INVOKER
        AS $function$
        BEGIN
            RETURN NULLIF(
                pg_catalog.current_setting('app.tenant_id', true), ''
            )::pg_catalog.uuid;
        EXCEPTION
            WHEN invalid_text_representation THEN
                RETURN NULL;
        END;
        $function$
        """
    )
    # PostgreSQL grants function execution to PUBLIC by default. The runtime
    # only needs to resolve this schema and call this function; not create in it.
    op.execute("REVOKE ALL ON FUNCTION app.current_tenant_id() FROM PUBLIC")
    op.execute("GRANT USAGE ON SCHEMA app TO sahl_app")
    op.execute("GRANT EXECUTE ON FUNCTION app.current_tenant_id() TO sahl_app")


def downgrade() -> None:
    """Remove this function and the schema access introduced with it."""
    op.execute("DROP FUNCTION app.current_tenant_id()")
    op.execute("REVOKE USAGE ON SCHEMA app FROM sahl_app")
