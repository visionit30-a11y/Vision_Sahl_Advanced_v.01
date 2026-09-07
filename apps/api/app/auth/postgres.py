"""PostgreSQL implementation of the session store protocol."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncConnection

from app.auth.sessions import PreAuthState, SessionRecord


class PostgresSessionStore:
    """Persist digests in one caller-owned transaction; no token plaintext crosses this boundary."""

    def __init__(self, connection: AsyncConnection) -> None:
        self.connection = connection

    async def current_time(self) -> datetime:
        return (await self.connection.execute(text("SELECT clock_timestamp()"))).scalar_one()

    @staticmethod
    def _session(row: RowMapping) -> SessionRecord:
        return SessionRecord(
            id=row.id,
            user_id=row.user_id,
            bearer_digest=bytes(row.bearer_digest),
            csrf_digest=bytes(row.csrf_digest),
            security_version=row.security_version,
            created_at=row.created_at,
            authenticated_at=row.authenticated_at,
            last_seen_at=row.last_seen_at,
            idle_expires_at=row.idle_expires_at,
            absolute_expires_at=row.absolute_expires_at,
            revoked_at=row.revoked_at,
            revoked_reason=row.revoked_reason,
        )

    async def save(self, record: SessionRecord) -> None:
        await self.connection.execute(
            text("""
            INSERT INTO auth.sessions
              (id,user_id,bearer_digest,csrf_digest,security_version,created_at,authenticated_at,
               last_seen_at,idle_expires_at,absolute_expires_at,revoked_at,revoked_reason)
            VALUES (:id,:user_id,:bearer_digest,:csrf_digest,:security_version,:created_at,
              :authenticated_at,:last_seen_at,:idle_expires_at,:absolute_expires_at,:revoked_at,
              :revoked_reason)
        """),
            record.__dict__
            if hasattr(record, "__dict__")
            else {name: getattr(record, name) for name in record.__slots__},
        )

    async def get_by_digest(self, digest: bytes) -> SessionRecord | None:
        row = (
            (
                await self.connection.execute(
                    text("""
            SELECT * FROM auth.sessions WHERE bearer_digest=:digest FOR UPDATE
        """),
                    {"digest": digest},
                )
            )
            .mappings()
            .one_or_none()
        )
        return None if row is None else self._session(row)

    async def active_for_user(self, user_id: uuid.UUID) -> list[SessionRecord]:
        await self.connection.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(CAST(:id AS text),0))"),
            {"id": user_id},
        )
        rows = (
            await self.connection.execute(
                text("""
            SELECT * FROM auth.sessions WHERE user_id=:id AND revoked_at IS NULL
            ORDER BY created_at,id FOR UPDATE
        """),
                {"id": user_id},
            )
        ).mappings()
        return [self._session(row) for row in rows]

    async def replace(self, record: SessionRecord) -> None:
        values = {name: getattr(record, name) for name in record.__slots__}
        await self.connection.execute(
            text("""
            UPDATE auth.sessions SET bearer_digest=:bearer_digest,csrf_digest=:csrf_digest,
              last_seen_at=:last_seen_at,idle_expires_at=:idle_expires_at,
              revoked_at=:revoked_at,revoked_reason=:revoked_reason WHERE id=:id
        """),
            values,
        )

    async def save_preauth(self, state: PreAuthState) -> None:
        await self.connection.execute(
            text("""
            INSERT INTO auth.preauth_csrf_states
              (state_digest,csrf_digest,created_at,expires_at,consumed_at)
            VALUES (:state_digest,:csrf_digest,:created_at,:expires_at,:consumed_at)
        """),
            {name: getattr(state, name) for name in state.__slots__},
        )

    async def get_preauth(self, digest: bytes) -> PreAuthState | None:
        row = (
            (
                await self.connection.execute(
                    text("""
            SELECT * FROM auth.preauth_csrf_states WHERE state_digest=:digest FOR UPDATE
        """),
                    {"digest": digest},
                )
            )
            .mappings()
            .one_or_none()
        )
        return (
            None
            if row is None
            else PreAuthState(
                bytes(row.state_digest),
                bytes(row.csrf_digest),
                row.created_at,
                row.expires_at,
                row.consumed_at,
            )
        )

    async def replace_preauth(self, state: PreAuthState) -> None:
        await self.connection.execute(
            text("""
            UPDATE auth.preauth_csrf_states SET consumed_at=:consumed_at
            WHERE state_digest=:state_digest AND consumed_at IS NULL
        """),
            {"state_digest": state.state_digest, "consumed_at": state.consumed_at},
        )
