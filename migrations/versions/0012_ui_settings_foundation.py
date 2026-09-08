# ruff: noqa: E501
"""Add validated platform, tenant, and user UI settings patches.

Revision ID: 0012_ui_settings_foundation
Revises: 0011_role_administration_guards
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012_ui_settings_foundation"
down_revision: str | None = "0011_role_administration_guards"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_TABLES = ("tenant_ui_settings", "user_ui_settings")
KEYS_CHECK = (
    "settings - ARRAY['theme','buttonPreset','alertPreset','overlayPreset',"
    "'tablePreset','printPreset']::text[] = '{}'::jsonb"
)
VALUE_CHECKS = (
    ("settings_theme_value", "NOT settings ? 'theme' OR (jsonb_typeof(settings->'theme') = 'string' AND settings->>'theme' IN ('teal-calm','green-institutional','navy-institutional','slate-neutral','sand-warm'))"),
    ("settings_button_preset_value", "NOT settings ? 'buttonPreset' OR (jsonb_typeof(settings->'buttonPreset') = 'string' AND settings->>'buttonPreset' IN ('institutional-standard','compact-sharp','soft-rounded','outlined-calm','balanced-roomy'))"),
    ("settings_alert_preset_value", "NOT settings ? 'alertPreset' OR (jsonb_typeof(settings->'alertPreset') = 'string' AND settings->>'alertPreset' IN ('tinted-standard','solid-emphatic','minimal-inline','dense-compact','bordered-quiet'))"),
    ("settings_overlay_preset_value", "NOT settings ? 'overlayPreset' OR (jsonb_typeof(settings->'overlayPreset') = 'string' AND settings->>'overlayPreset' IN ('institutional-standard','soft-elevated','flat-bordered','dim-focused','compact-dense'))"),
    ("settings_table_preset_value", "NOT settings ? 'tablePreset' OR (jsonb_typeof(settings->'tablePreset') = 'string' AND settings->>'tablePreset' IN ('institutional-standard','zebra-scan','full-grid','compact-rows','airy-report'))"),
    ("settings_print_preset_value", "NOT settings ? 'printPreset' OR (jsonb_typeof(settings->'printPreset') = 'string' AND settings->>'printPreset' IN ('institutional-standard','ink-saving','high-contrast-print','formal-letterhead','dense-archive'))"),
)


def settings_columns() -> list[sa.Column[object]]:
    return [
        sa.Column(
            "settings",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    ]


def settings_checks(table: str) -> list[sa.CheckConstraint]:
    return [
        sa.CheckConstraint("jsonb_typeof(settings) = 'object'", name=op.f(f"ck_{table}_settings_object")),
        sa.CheckConstraint(KEYS_CHECK, name=op.f(f"ck_{table}_settings_keys")),
        *(sa.CheckConstraint(expression, name=op.f(f"ck_{table}_{name}")) for name, expression in VALUE_CHECKS),
        sa.CheckConstraint("version > 0", name=op.f(f"ck_{table}_version_positive")),
    ]


def upgrade() -> None:
    op.create_table(
        "platform_ui_settings",
        sa.Column("id", sa.SmallInteger(), server_default=sa.text("1"), nullable=False),
        *settings_columns(),
        sa.CheckConstraint("id = 1", name=op.f("ck_platform_ui_settings_singleton")),
        *settings_checks("platform_ui_settings"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_platform_ui_settings")),
        schema="app",
    )
    op.create_table(
        "tenant_ui_settings",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        *settings_columns(),
        *settings_checks("tenant_ui_settings"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["public.tenants.id"], ondelete="CASCADE", name=op.f("fk_tenant_ui_settings_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("tenant_id", name=op.f("pk_tenant_ui_settings")),
        schema="app",
    )
    op.create_table(
        "user_ui_settings",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        *settings_columns(),
        *settings_checks("user_ui_settings"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["public.tenants.id"], ondelete="CASCADE", name=op.f("fk_user_ui_settings_tenant_id_tenants")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["auth.users.id"], ondelete="CASCADE", name=op.f("fk_user_ui_settings_user_id_users")
        ),
        sa.PrimaryKeyConstraint("tenant_id", "user_id", name=op.f("pk_user_ui_settings")),
        schema="app",
    )
    for table in TENANT_TABLES:
        op.execute(f"ALTER TABLE app.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE app.{table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON app.{table} FOR ALL TO sahl_app USING (tenant_id = app.current_tenant_id()) WITH CHECK (tenant_id = app.current_tenant_id())"
        )
        op.execute(f"REVOKE ALL ON TABLE app.{table} FROM PUBLIC, sahl_app")
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE app.{table} TO sahl_app")
    op.execute("REVOKE ALL ON TABLE app.platform_ui_settings FROM PUBLIC, sahl_app")
    op.execute("GRANT SELECT ON TABLE app.platform_ui_settings TO sahl_app")


def downgrade() -> None:
    op.drop_table("user_ui_settings", schema="app")
    op.drop_table("tenant_ui_settings", schema="app")
    op.drop_table("platform_ui_settings", schema="app")
