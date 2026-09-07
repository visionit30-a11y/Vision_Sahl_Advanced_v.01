"""Tenant foundation.

Creates the app schema and the tenants table. Nothing here is tenant owned:
tenants is a platform table, declared as such rather than by omission
(FR-MT-07), and the tenant isolation policy is not what governs it. Row level
security arrives in a later migration and is a separate decision.

The slug constraint repeats the contract in app/models/tenant.py word for word
rather than importing it. A migration has to keep meaning what it meant on the
day it ran, and importing application code would let a later edit rewrite the
past. A test compares the two so the duplication cannot drift.

Revision ID: 0002_tenant_foundation
Revises: 0001_baseline
Create Date: 2026-09-06
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_tenant_foundation"
down_revision: str | None = "0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SLUG_MIN_LENGTH = 3
SLUG_MAX_LENGTH = 63
SLUG_PATTERN = r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$"
SLUG_FORBIDDEN_SEQUENCE = "--"

SLUG_CHECK = (
    f"char_length(slug) BETWEEN {SLUG_MIN_LENGTH} AND {SLUG_MAX_LENGTH} "
    f"AND slug ~ '{SLUG_PATTERN}' "
    f"AND slug !~ '{SLUG_FORBIDDEN_SEQUENCE}'"
)

TENANT_STATUS_VALUES = ("pending", "active", "suspended", "archived")


def upgrade() -> None:
    """Create the app schema, the status type and the tenants table."""
    # The schema the isolation helper will live in. Created here so that
    # migration owns it, like everything else.
    op.execute("CREATE SCHEMA IF NOT EXISTS app")

    tenant_status = postgresql.ENUM(*TENANT_STATUS_VALUES, name="tenant_status")
    tenant_status.create(op.get_bind(), checkfirst=False)

    op.create_table(
        "tenants",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("slug", sa.String(length=SLUG_MAX_LENGTH), nullable=False),
        sa.Column("name_ar", sa.String(length=200), nullable=False),
        sa.Column("name_en", sa.String(length=200), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(*TENANT_STATUS_VALUES, name="tenant_status", create_type=False),
            server_default=sa.text("'pending'::tenant_status"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tenants")),
        sa.UniqueConstraint("slug", name=op.f("uq_tenants_slug")),
        sa.CheckConstraint(SLUG_CHECK, name=op.f("ck_tenants_slug_shape")),
    )


def downgrade() -> None:
    """Undo in the reverse order, so nothing is dropped before its dependents."""
    op.drop_table("tenants")

    tenant_status = postgresql.ENUM(*TENANT_STATUS_VALUES, name="tenant_status")
    tenant_status.drop(op.get_bind(), checkfirst=False)

    # The schema is dropped only if this migration left it empty; a later
    # migration's objects must not disappear because this one was reversed.
    op.execute("DROP SCHEMA IF EXISTS app RESTRICT")
