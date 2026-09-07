"""Remove speculative runtime access to platform and future tables.

Revision ID: 0004_runtime_privilege_boundary
Revises: 0003_tenant_context_function
Create Date: 2026-09-07

The platform tenants table has no runtime consumer and stays outside tenant RLS.
Future tenant-owned tables receive explicit grants in their own migrations.
This revision creates no table, policy, type, sequence or function.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0004_runtime_privilege_boundary"
down_revision: str | None = "0003_tenant_context_function"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("REVOKE ALL ON TABLE public.tenants FROM sahl_app, PUBLIC")
    op.execute(
        "ALTER DEFAULT PRIVILEGES FOR ROLE sahl_migrator IN SCHEMA public "
        "REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM sahl_app"
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES FOR ROLE sahl_migrator IN SCHEMA public "
        "REVOKE USAGE, SELECT ON SEQUENCES FROM sahl_app"
    )


def downgrade() -> None:
    """Restore the recorded pre-Group-4 privilege contract, never create RLS."""
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.tenants TO sahl_app"
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES FOR ROLE sahl_migrator IN SCHEMA public "
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO sahl_app"
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES FOR ROLE sahl_migrator IN SCHEMA public "
        "GRANT USAGE, SELECT ON SEQUENCES TO sahl_app"
    )
