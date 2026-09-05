"""Baseline revision.

Phase 0 creates no domain table on purpose. This revision exists so that the
migration chain starts from an explicit, reversible point and every later
schema change is an incremental migration (SRS section 10).

Revision ID: 0001_baseline
Revises:
Create Date: 2026-09-05
"""

from __future__ import annotations

from collections.abc import Sequence

revision: str = "0001_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """No schema object is created in Phase 0."""


def downgrade() -> None:
    """Nothing to undo."""
