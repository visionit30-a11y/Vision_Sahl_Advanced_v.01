"""Add tenant-isolated notifications, preferences, and task due dates."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0019_activity_center"
down_revision: str | None = "0018_workflow_approvals"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("notifications", "notification_preferences")


def upgrade() -> None:
    op.add_column(
        "workflow_approval_tasks",
        sa.Column(
            "due_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp() + interval '48 hours'"),
            nullable=False,
        ),
        schema="app",
    )
    op.create_index(
        "ix_workflow_tasks_due",
        "workflow_approval_tasks",
        ["tenant_id", "assignee_membership_id", "status", "due_at"],
        schema="app",
    )
    op.create_table(
        "notifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("recipient_membership_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("title_snapshot", sa.String(160), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('request_submitted','approval_requested','request_returned',"
            "'request_rejected','request_approved','task_overdue')",
            name="ck_notifications_kind",
        ),
        sa.CheckConstraint(
            "length(title_snapshot) BETWEEN 1 AND 160", name="ck_notifications_title"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["public.tenants.id"], ondelete="CASCADE", name="fk_notifications_tenant"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "recipient_membership_id"],
            ["auth.tenant_memberships.tenant_id", "auth.tenant_memberships.id"],
            ondelete="CASCADE",
            name="fk_notifications_recipient",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "request_id"],
            ["app.workflow_requests.tenant_id", "app.workflow_requests.id"],
            ondelete="CASCADE",
            name="fk_notifications_request",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_notifications"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_notifications_tenant_id"),
        schema="app",
    )
    op.create_index(
        "ix_notifications_recipient",
        "notifications",
        ["tenant_id", "recipient_membership_id", "read_at", "created_at"],
        schema="app",
    )
    op.create_table(
        "notification_preferences",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("membership_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("approval_requested", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("request_approved", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("request_rejected", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("request_returned", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("overdue_tasks", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.CheckConstraint("version > 0", name="ck_notification_preferences_version"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["public.tenants.id"],
            ondelete="CASCADE",
            name="fk_notification_preferences_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "membership_id"],
            ["auth.tenant_memberships.tenant_id", "auth.tenant_memberships.id"],
            ondelete="CASCADE",
            name="fk_notification_preferences_membership",
        ),
        sa.PrimaryKeyConstraint("tenant_id", "membership_id", name="pk_notification_preferences"),
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
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON app.{table} TO sahl_app")


def downgrade() -> None:
    op.drop_table("notification_preferences", schema="app")
    op.drop_table("notifications", schema="app")
    op.drop_index("ix_workflow_tasks_due", table_name="workflow_approval_tasks", schema="app")
    op.drop_column("workflow_approval_tasks", "due_at", schema="app")
