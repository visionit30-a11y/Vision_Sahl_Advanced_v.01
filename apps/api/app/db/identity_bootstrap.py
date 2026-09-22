"""Dedicated database boundary for interactive development identity administration."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


@dataclass(frozen=True, slots=True)
class BootstrapTenant:
    id: uuid.UUID
    name: str


@dataclass(frozen=True, slots=True)
class BootstrapResult:
    user_id: uuid.UUID
    membership_id: uuid.UUID
    role_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class PasswordResetSnapshot:
    user_id: uuid.UUID
    credential_version: int
    security_version: int


class IdentityBootstrapDatabase:
    """Use only the dedicated bootstrap capability URL and exact DB functions."""

    def __init__(self, database_url: str) -> None:
        self._engine: AsyncEngine = create_async_engine(database_url)

    async def close(self) -> None:
        await self._engine.dispose()

    async def tenants(self) -> Sequence[BootstrapTenant]:
        async with self._engine.begin() as connection:
            rows = (
                await connection.execute(text("SELECT * FROM auth.bootstrap_tenant_catalog()"))
            ).all()
        return tuple(BootstrapTenant(row.tenant_id, row.tenant_name) for row in rows)

    async def bootstrap_admin(
        self,
        *,
        tenant_id: uuid.UUID,
        email: str,
        normalized_email: str,
        password_hash: str,
        user_id: uuid.UUID,
        membership_id: uuid.UUID,
        role_id: uuid.UUID,
    ) -> BootstrapResult:
        async with self._engine.begin() as connection:
            row = (
                await connection.execute(
                    text(
                        "SELECT * FROM auth.bootstrap_tenant_admin("
                        ":tenant,:email,:normalized,:hash,:user,:membership,:role)"
                    ),
                    {
                        "tenant": tenant_id,
                        "email": email,
                        "normalized": normalized_email,
                        "hash": password_hash,
                        "user": user_id,
                        "membership": membership_id,
                        "role": role_id,
                    },
                )
            ).one()
        return BootstrapResult(row.user_id, row.membership_id, row.role_id)

    async def password_snapshot(self, normalized_email: str) -> PasswordResetSnapshot | None:
        async with self._engine.begin() as connection:
            row = (
                await connection.execute(
                    text("SELECT * FROM auth.admin_password_snapshot(:email)"),
                    {"email": normalized_email},
                )
            ).one_or_none()
        if row is None:
            return None
        return PasswordResetSnapshot(
            row.user_id,
            row.credential_version,
            row.security_version,
        )

    async def reset_password(
        self,
        snapshot: PasswordResetSnapshot,
        password_hash: str,
        *,
        force_password_change: bool,
    ) -> int:
        async with self._engine.begin() as connection:
            revoked = await connection.scalar(
                text(
                    "SELECT auth.admin_apply_password_reset("
                    ":user,:credential,:security,:hash,:force)"
                ),
                {
                    "user": snapshot.user_id,
                    "credential": snapshot.credential_version,
                    "security": snapshot.security_version,
                    "hash": password_hash,
                    "force": force_password_change,
                },
            )
        if not isinstance(revoked, int):
            raise RuntimeError("Password reset returned an invalid result.")
        return revoked
