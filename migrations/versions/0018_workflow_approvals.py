"""Add tenant-isolated shared workflow requests, approvals, and history."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0018_workflow_approvals"
down_revision: str | None = "0017_foundation_fk_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("workflow_requests", "workflow_approval_tasks", "workflow_events")
OLD_AUDIT_PERMISSIONS = (
    "'platform.tenants.manage','platform.tenants.read','platform.ui_settings.manage',"
    "'tenant.memberships.manage','tenant.memberships.read','tenant.roles.manage',"
    "'tenant.roles.read','tenant.ui_settings.manage','tenant.user_ui_settings.manage_self'"
)
NEW_AUDIT_PERMISSIONS = OLD_AUDIT_PERMISSIONS + (
    ",'tenant.workflow_approvals.decide','tenant.workflow_requests.create',"
    "'tenant.workflow_requests.read'"
)


def _replace_audit_permissions(previous: str, current: str) -> None:
    escaped_previous = previous.replace("'", "''")
    escaped_current = current.replace("'", "''")
    op.execute(
        f"""
        DO $migration$
        DECLARE definition text;
        BEGIN
            SELECT pg_get_functiondef('auth.validate_security_event_insert()'::regprocedure)
              INTO definition;
            IF strpos(definition, '{escaped_previous}') = 0 THEN
                RAISE EXCEPTION USING ERRCODE='55000', MESSAGE='audit_permission_catalog_mismatch';
            END IF;
            definition := replace(definition, '{escaped_previous}', '{escaped_current}');
            EXECUTE definition;
        END
        $migration$
        """
    )
    op.execute(
        "ALTER FUNCTION auth.validate_security_event_insert() OWNER TO sahl_migrator"
    )


def upgrade() -> None:
    _replace_audit_permissions(OLD_AUDIT_PERMISSIONS, NEW_AUDIT_PERMISSIONS)
    op.create_table(
        "workflow_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "requester_membership_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column(
            "approver_membership_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("request_type", sa.String(63), nullable=False),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("description", sa.String(2000), nullable=False),
        sa.Column("status", sa.String(16), server_default="draft", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "request_type ~ '^[a-z][a-z0-9_]{0,62}$'", name="ck_workflow_requests_type"
        ),
        sa.CheckConstraint(
            "length(btrim(title)) BETWEEN 1 AND 160", name="ck_workflow_requests_title"
        ),
        sa.CheckConstraint(
            "length(description) BETWEEN 1 AND 2000",
            name="ck_workflow_requests_description",
        ),
        sa.CheckConstraint(
            "status IN ('draft','pending','approved','rejected','returned')",
            name="ck_workflow_requests_status",
        ),
        sa.CheckConstraint("version > 0", name="ck_workflow_requests_version"),
        sa.CheckConstraint(
            "requester_membership_id <> approver_membership_id",
            name="ck_workflow_requests_separation",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["public.tenants.id"],
            ondelete="CASCADE",
            name="fk_workflow_requests_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "requester_membership_id"],
            ["auth.tenant_memberships.tenant_id", "auth.tenant_memberships.id"],
            ondelete="RESTRICT",
            name="fk_workflow_requests_requester",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "approver_membership_id"],
            ["auth.tenant_memberships.tenant_id", "auth.tenant_memberships.id"],
            ondelete="RESTRICT",
            name="fk_workflow_requests_approver",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_workflow_requests"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_workflow_requests_tenant_id"),
        schema="app",
    )
    op.create_index(
        "ix_workflow_requests_requester",
        "workflow_requests",
        ["tenant_id", "requester_membership_id", "updated_at"],
        schema="app",
    )
    op.create_index(
        "ix_workflow_requests_status",
        "workflow_requests",
        ["tenant_id", "status", "updated_at"],
        schema="app",
    )

    op.create_table(
        "workflow_approval_tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "assignee_membership_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("status", sa.String(16), server_default="pending", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("decision_note", sa.String(1000), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending','approved','rejected','returned','cancelled')",
            name="ck_workflow_approval_tasks_status",
        ),
        sa.CheckConstraint("version > 0", name="ck_workflow_approval_tasks_version"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "request_id"],
            ["app.workflow_requests.tenant_id", "app.workflow_requests.id"],
            ondelete="CASCADE",
            name="fk_workflow_tasks_request",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "assignee_membership_id"],
            ["auth.tenant_memberships.tenant_id", "auth.tenant_memberships.id"],
            ondelete="RESTRICT",
            name="fk_workflow_tasks_assignee",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_workflow_approval_tasks"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_workflow_tasks_tenant_id"),
        schema="app",
    )
    op.create_index(
        "ix_workflow_tasks_inbox",
        "workflow_approval_tasks",
        ["tenant_id", "assignee_membership_id", "status", "created_at"],
        schema="app",
    )

    op.create_table(
        "workflow_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_membership_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(16), nullable=False),
        sa.Column("from_status", sa.String(16), nullable=True),
        sa.Column("to_status", sa.String(16), nullable=False),
        sa.Column("note", sa.String(1000), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "event_type IN ('created','updated','submitted','resubmitted','approved','rejected','returned')",
            name="ck_workflow_events_type",
        ),
        sa.CheckConstraint(
            "to_status IN ('draft','pending','approved','rejected','returned')",
            name="ck_workflow_events_to_status",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "request_id"],
            ["app.workflow_requests.tenant_id", "app.workflow_requests.id"],
            ondelete="CASCADE",
            name="fk_workflow_events_request",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "actor_membership_id"],
            ["auth.tenant_memberships.tenant_id", "auth.tenant_memberships.id"],
            ondelete="RESTRICT",
            name="fk_workflow_events_actor",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_workflow_events"),
        schema="app",
    )
    op.create_index(
        "ix_workflow_events_history",
        "workflow_events",
        ["tenant_id", "request_id", "created_at", "id"],
        schema="app",
    )

    for table in TABLES:
        op.execute(f"ALTER TABLE app.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE app.{table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON app.{table} FOR ALL TO sahl_app "
            "USING (tenant_id = app.current_tenant_id()) "
            "WITH CHECK (tenant_id = app.current_tenant_id())"
        )
        op.execute(f"ALTER TABLE app.{table} OWNER TO sahl_migrator")
        op.execute(f"REVOKE ALL ON TABLE app.{table} FROM PUBLIC, sahl_app")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON app.workflow_requests, app.workflow_approval_tasks TO sahl_app"
    )
    op.execute("GRANT SELECT, INSERT ON app.workflow_events TO sahl_app")
    op.execute("""
        CREATE FUNCTION auth.workflow_approvers()
        RETURNS TABLE(membership_id uuid, display_name text)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog
        AS $function$
            SELECT membership.id, users.email::text
            FROM auth.tenant_memberships AS membership
            JOIN auth.users AS users ON users.id=membership.user_id
            JOIN public.tenants AS tenant ON tenant.id=membership.tenant_id
            WHERE membership.tenant_id=app.current_tenant_id()
              AND membership.status='active'::auth.membership_status
              AND users.status='active'::auth.user_status
              AND tenant.status='active'::public.tenant_status
            ORDER BY users.email,membership.id
        $function$
    """)
    op.execute("ALTER FUNCTION auth.workflow_approvers() OWNER TO sahl_migrator")
    op.execute("REVOKE ALL ON FUNCTION auth.workflow_approvers() FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION auth.workflow_approvers() TO sahl_app")


def downgrade() -> None:
    op.execute("DROP FUNCTION auth.workflow_approvers()")
    op.drop_table("workflow_events", schema="app")
    op.drop_table("workflow_approval_tasks", schema="app")
    op.drop_table("workflow_requests", schema="app")
    _replace_audit_permissions(NEW_AUDIT_PERMISSIONS, OLD_AUDIT_PERMISSIONS)
