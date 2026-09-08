"""Persistence metadata for platform, tenant, and tenant-bound user UI patches."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, SmallInteger, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

SETTINGS_KEYS_CHECK = (
    "settings - ARRAY['theme','buttonPreset','alertPreset','overlayPreset',"
    "'tablePreset','printPreset']::text[] = '{}'::jsonb"
)
def settings_value_checks() -> tuple[CheckConstraint, ...]:
    return (
        CheckConstraint(
        "NOT settings ? 'theme' OR (jsonb_typeof(settings->'theme') = 'string' AND "
        "settings->>'theme' IN ('teal-calm','green-institutional','navy-institutional',"
        "'slate-neutral','sand-warm'))",
        name="settings_theme_value",
        ),
        CheckConstraint(
        "NOT settings ? 'buttonPreset' OR (jsonb_typeof(settings->'buttonPreset') = 'string' "
        "AND settings->>'buttonPreset' IN ('institutional-standard','compact-sharp',"
        "'soft-rounded','outlined-calm','balanced-roomy'))",
        name="settings_button_preset_value",
        ),
        CheckConstraint(
        "NOT settings ? 'alertPreset' OR (jsonb_typeof(settings->'alertPreset') = 'string' "
        "AND settings->>'alertPreset' IN ('tinted-standard','solid-emphatic',"
        "'minimal-inline','dense-compact','bordered-quiet'))",
        name="settings_alert_preset_value",
        ),
        CheckConstraint(
        "NOT settings ? 'overlayPreset' OR (jsonb_typeof(settings->'overlayPreset') = 'string' "
        "AND settings->>'overlayPreset' IN ('institutional-standard','soft-elevated',"
        "'flat-bordered','dim-focused','compact-dense'))",
        name="settings_overlay_preset_value",
        ),
        CheckConstraint(
        "NOT settings ? 'tablePreset' OR (jsonb_typeof(settings->'tablePreset') = 'string' "
        "AND settings->>'tablePreset' IN ('institutional-standard','zebra-scan','full-grid',"
        "'compact-rows','airy-report'))",
        name="settings_table_preset_value",
        ),
        CheckConstraint(
        "NOT settings ? 'printPreset' OR (jsonb_typeof(settings->'printPreset') = 'string' "
        "AND settings->>'printPreset' IN ('institutional-standard','ink-saving',"
        "'high-contrast-print','formal-letterhead','dense-archive'))",
        name="settings_print_preset_value",
        ),
    )


class PlatformUiSettings(Base):
    __tablename__ = "platform_ui_settings"
    __table_args__ = (
        CheckConstraint("id = 1", name="singleton"),
        CheckConstraint("jsonb_typeof(settings) = 'object'", name="settings_object"),
        CheckConstraint(SETTINGS_KEYS_CHECK, name="settings_keys"),
        *settings_value_checks(),
        CheckConstraint("version > 0", name="version_positive"),
        {"schema": "app"},
    )

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, server_default=text("1"))
    settings: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class TenantUiSettings(Base):
    __tablename__ = "tenant_ui_settings"
    __table_args__ = (
        CheckConstraint("jsonb_typeof(settings) = 'object'", name="settings_object"),
        CheckConstraint(SETTINGS_KEYS_CHECK, name="settings_keys"),
        *settings_value_checks(),
        CheckConstraint("version > 0", name="version_positive"),
        {"schema": "app"},
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    settings: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class UserUiSettings(Base):
    __tablename__ = "user_ui_settings"
    __table_args__ = (
        CheckConstraint("jsonb_typeof(settings) = 'object'", name="settings_object"),
        CheckConstraint(SETTINGS_KEYS_CHECK, name="settings_keys"),
        *settings_value_checks(),
        CheckConstraint("version > 0", name="version_positive"),
        {"schema": "app"},
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("auth.users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    settings: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
