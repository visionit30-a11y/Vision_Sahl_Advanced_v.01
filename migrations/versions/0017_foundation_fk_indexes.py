"""Index the three reviewed referencing keys; preserve all policies and grants."""

from alembic import op

revision = "0017_foundation_fk_indexes"
down_revision = "0016_security_audit_retention"
branch_labels = None
depends_on = None

INDEXES = (
    ("app", "user_ui_settings", "ix_user_ui_settings_user_id", ["user_id"]),
    (
        "auth",
        "membership_roles",
        "ix_membership_roles_tenant_role",
        ["tenant_id", "role_id"],
    ),
    (
        "auth",
        "sessions",
        "ix_sessions_selected_membership_user",
        ["selected_membership_id", "user_id"],
    ),
)


def upgrade() -> None:
    for schema, table, name, columns in INDEXES:
        op.create_index(name, table, columns, schema=schema)


def downgrade() -> None:
    for schema, table, name, _ in reversed(INDEXES):
        op.drop_index(name, table_name=table, schema=schema)
