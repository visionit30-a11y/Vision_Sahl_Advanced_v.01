"""Internal persistence boundary for versioned UI-setting patches."""

from __future__ import annotations

import uuid

from sqlalchemy import text

from app.db.session import _engine
from app.db.tenant_transaction import tenant_transaction
from app.tenancy.context import TenantContext
from app.ui_settings.contracts import StoredUiSettingsPatch, UiSettingsPatch


class UiSettingsRepository:
    """Own every SQL operation; platform state is deliberately read-only."""

    async def read_platform(self) -> StoredUiSettingsPatch | None:
        async with _engine.connect() as connection:
            row = (
                await connection.execute(
                    text("SELECT settings,version FROM app.platform_ui_settings WHERE id=1")
                )
            ).one_or_none()
        return self._record(row)

    async def read_tenant(self, context: TenantContext) -> StoredUiSettingsPatch | None:
        async with tenant_transaction(context) as transaction:
            row = (
                await transaction.execute(
                    text(
                        "SELECT settings,version FROM app.tenant_ui_settings "
                        "WHERE tenant_id=:tenant_id"
                    ),
                    {"tenant_id": context.tenant_id},
                )
            ).one_or_none()
        return self._record(row)

    async def read_user(
        self, context: TenantContext, user_id: uuid.UUID
    ) -> StoredUiSettingsPatch | None:
        async with tenant_transaction(context) as transaction:
            row = (
                await transaction.execute(
                    text(
                        "SELECT settings,version FROM app.user_ui_settings "
                        "WHERE tenant_id=:tenant_id AND user_id=:user_id"
                    ),
                    {"tenant_id": context.tenant_id, "user_id": user_id},
                )
            ).one_or_none()
        return self._record(row)

    async def put_tenant(
        self, context: TenantContext, patch: UiSettingsPatch, expected_version: int | None
    ) -> StoredUiSettingsPatch | None:
        async with tenant_transaction(context) as transaction:
            if expected_version is None:
                row = (
                    await transaction.execute(
                        text(
                            "INSERT INTO app.tenant_ui_settings(tenant_id,settings) "
                            "VALUES (:tenant_id,CAST(:settings AS jsonb)) ON CONFLICT DO NOTHING "
                            "RETURNING settings,version"
                        ),
                        {"tenant_id": context.tenant_id, "settings": patch.model_dump_json()},
                    )
                ).one_or_none()
            else:
                row = (
                    await transaction.execute(
                        text(
                            "UPDATE app.tenant_ui_settings SET settings=CAST(:settings AS jsonb),"
                            "version=version+1,updated_at=clock_timestamp() "
                            "WHERE tenant_id=:tenant_id AND version=:version "
                            "RETURNING settings,version"
                        ),
                        {
                            "tenant_id": context.tenant_id,
                            "settings": patch.model_dump_json(),
                            "version": expected_version,
                        },
                    )
                ).one_or_none()
        return self._record(row)

    async def put_user(
        self,
        context: TenantContext,
        user_id: uuid.UUID,
        patch: UiSettingsPatch,
        expected_version: int | None,
    ) -> StoredUiSettingsPatch | None:
        async with tenant_transaction(context) as transaction:
            if expected_version is None:
                row = (
                    await transaction.execute(
                        text(
                            "INSERT INTO app.user_ui_settings(tenant_id,user_id,settings) "
                            "VALUES (:tenant_id,:user_id,CAST(:settings AS jsonb)) "
                            "ON CONFLICT DO NOTHING "
                            "RETURNING settings,version"
                        ),
                        {
                            "tenant_id": context.tenant_id,
                            "user_id": user_id,
                            "settings": patch.model_dump_json(),
                        },
                    )
                ).one_or_none()
            else:
                row = (
                    await transaction.execute(
                        text(
                            "UPDATE app.user_ui_settings SET settings=CAST(:settings AS jsonb),"
                            "version=version+1,updated_at=clock_timestamp() "
                            "WHERE tenant_id=:tenant_id AND user_id=:user_id AND version=:version "
                            "RETURNING settings,version"
                        ),
                        {
                            "tenant_id": context.tenant_id,
                            "user_id": user_id,
                            "settings": patch.model_dump_json(),
                            "version": expected_version,
                        },
                    )
                ).one_or_none()
        return self._record(row)

    async def delete_tenant(self, context: TenantContext, expected_version: int) -> bool:
        async with tenant_transaction(context) as transaction:
            row = (
                await transaction.execute(
                    text(
                        "DELETE FROM app.tenant_ui_settings WHERE tenant_id=:tenant_id "
                        "AND version=:version RETURNING 1"
                    ),
                    {"tenant_id": context.tenant_id, "version": expected_version},
                )
            ).scalar_one_or_none()
        return row == 1

    async def delete_user(
        self, context: TenantContext, user_id: uuid.UUID, expected_version: int
    ) -> bool:
        async with tenant_transaction(context) as transaction:
            row = (
                await transaction.execute(
                    text(
                        "DELETE FROM app.user_ui_settings WHERE tenant_id=:tenant_id "
                        "AND user_id=:user_id "
                        "AND version=:version RETURNING 1"
                    ),
                    {
                        "tenant_id": context.tenant_id,
                        "user_id": user_id,
                        "version": expected_version,
                    },
                )
            ).scalar_one_or_none()
        return row == 1

    @staticmethod
    def _record(row: object) -> StoredUiSettingsPatch | None:
        if row is None:
            return None
        return StoredUiSettingsPatch(UiSettingsPatch.model_validate(row.settings), row.version)  # type: ignore[attr-defined]


ui_settings_repository = UiSettingsRepository()
