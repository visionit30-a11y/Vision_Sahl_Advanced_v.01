"""Store tenant-owned workflow attachment metadata outside object storage."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0024_workflow_documents"
down_revision: str | None = "0023_tenant_admin_guard"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workflow_documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("uploaded_by_membership_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("filename", sa.String(180), nullable=False),
        sa.Column("content_type", sa.String(32), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("object_key", sa.String(120), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("clock_timestamp()"),
        ),
        sa.CheckConstraint(
            "length(btrim(filename)) BETWEEN 1 AND 180",
            name="ck_workflow_documents_filename",
        ),
        sa.CheckConstraint(
            "filename !~ '[[:cntrl:]/\\\\]'", name="ck_workflow_documents_filename_safe"
        ),
        sa.CheckConstraint(
            "content_type IN ('application/pdf','image/png','image/jpeg')",
            name="ck_workflow_documents_type",
        ),
        sa.CheckConstraint("byte_size BETWEEN 1 AND 10485760", name="ck_workflow_documents_size"),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="ck_workflow_documents_hash"),
        sa.CheckConstraint(
            "object_key = tenant_id::text || '/' || replace(id::text, '-', '')",
            name="ck_workflow_documents_object_key_scope",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "request_id"],
            ["app.workflow_requests.tenant_id", "app.workflow_requests.id"],
            ondelete="CASCADE",
            name="fk_workflow_documents_request",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "uploaded_by_membership_id"],
            ["auth.tenant_memberships.tenant_id", "auth.tenant_memberships.id"],
            ondelete="RESTRICT",
            name="fk_workflow_documents_uploader",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_workflow_documents"),
        sa.UniqueConstraint("tenant_id", "object_key", name="uq_workflow_documents_object_key"),
        schema="app",
    )
    op.create_index(
        "ix_workflow_documents_request",
        "workflow_documents",
        ["tenant_id", "request_id", "created_at"],
        schema="app",
    )
    op.execute("ALTER TABLE app.workflow_documents ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE app.workflow_documents FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON app.workflow_documents FOR ALL TO sahl_app "
        "USING (tenant_id = app.current_tenant_id()) "
        "WITH CHECK (tenant_id = app.current_tenant_id())"
    )
    op.execute("ALTER TABLE app.workflow_documents OWNER TO sahl_migrator")
    op.execute("REVOKE ALL ON TABLE app.workflow_documents FROM PUBLIC, sahl_app")
    op.execute("GRANT SELECT, INSERT ON app.workflow_documents TO sahl_app")


def downgrade() -> None:
    op.drop_table("workflow_documents", schema="app")
