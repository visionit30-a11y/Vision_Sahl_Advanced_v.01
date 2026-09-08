"""Internal password authentication composition; no HTTP or alternative identity path."""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.audit.contracts import (
    SecurityAuditEvent,
    SecurityEventResult,
    SecurityEventType,
    SecurityReasonCode,
)
from app.audit.writer import SecurityEventWriter
from app.auth.controls import PostgresThrottleStore, ThrottleScope, ThrottleService
from app.auth.postgres import PostgresSessionStore
from app.auth.sessions import IssuedSession, SessionService, token_digest
from app.models.identity import InvalidEmailAddressError, normalize_email
from app.security.passwords import PasswordService


class PasswordAuthenticationUnavailableError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("Password authentication is unavailable.")


@dataclass(frozen=True, slots=True)
class _CredentialSnapshot:
    user_id: uuid.UUID
    password_hash: str = field(repr=False)
    credential_version: int
    security_version: int

    @classmethod
    def from_row(cls, row: RowMapping) -> _CredentialSnapshot:
        return cls(row.user_id, row.password_hash, row.credential_version, row.security_version)


class PasswordAuthenticationService:
    """Reuse Argon2id, throttling and session services with short DB transactions.

    Snapshot reads finish before Argon2 work; narrow DB functions recheck and lock
    the current credential/user/session before a mutation. No bearer leaves the
    existing IssuedSession contract and no authentication HTTP endpoint is added.
    """

    def __init__(
        self,
        engine: AsyncEngine,
        passwords: PasswordService,
        hmac_key: bytes,
        *,
        hmac_key_id: int = 1,
    ) -> None:
        if len(hmac_key) < 32:
            raise ValueError("Throttle HMAC key must contain at least 256 bits.")
        self._engine = engine
        self._passwords = passwords
        self._hmac_key = hmac_key
        self._hmac_key_id = hmac_key_id
        self._dummy_hash: str | None = None

    async def _dummy(self) -> str:
        # This is only Argon2 workload for a missing identity, never an authority cache.
        # Every initial request initializes it before lookup, regardless of identity.
        if self._dummy_hash is None:
            self._dummy_hash = await self._passwords.hash_password(secrets.token_urlsafe(32))
        return self._dummy_hash

    async def login(self, identifier: str, password: str, client_ip: str) -> IssuedSession | None:
        try:
            return await self._login(identifier, password, client_ip)
        except SQLAlchemyError:
            raise PasswordAuthenticationUnavailableError() from None

    async def _login(self, identifier: str, password: str, client_ip: str) -> IssuedSession | None:
        dummy = await self._dummy()
        try:
            normalized = normalize_email(identifier)
        except InvalidEmailAddressError:
            normalized = None
        username = normalized if normalized is not None else identifier
        # Quotas must commit even when credential verification later fails.
        async with self._engine.begin() as connection:
            throttle = ThrottleService(
                PostgresThrottleStore(connection), self._hmac_key, key_id=self._hmac_key_id
            )
            decisions = [
                await throttle.consume(ThrottleScope.LOGIN_USERNAME, username),
                await throttle.consume(ThrottleScope.LOGIN_IP, client_ip),
                await throttle.consume(
                    ThrottleScope.LOGIN_IP_USERNAME, client_ip + "\0" + username
                ),
            ]
            allowed = all(decision.allowed for decision in decisions)
            if not allowed:
                await SecurityEventWriter(connection).write(
                    SecurityAuditEvent(
                        event_type=SecurityEventType.LOGIN_FAILURE,
                        result=SecurityEventResult.FAILURE,
                        reason_code=SecurityReasonCode.INVALID_CREDENTIALS,
                    )
                )
        if not allowed:
            return None
        async with self._engine.begin() as connection:
            row = (
                (
                    await connection.execute(
                        text("SELECT * FROM auth.password_authentication_snapshot(:email)"),
                        {"email": normalized},
                    )
                )
                .mappings()
                .one_or_none()
            )
            snapshot = None if row is None else _CredentialSnapshot.from_row(row)
        verified = await self._passwords.verify_password(
            dummy if snapshot is None else snapshot.password_hash, password
        )
        async with self._engine.begin() as connection:
            writer = SecurityEventWriter(connection)
            current = False
            if verified and snapshot is not None:
                current = bool(
                    await connection.scalar(
                        text("SELECT auth.confirm_password_authentication(:id,:cv,:sv,:hash)"),
                        {
                            "id": snapshot.user_id,
                            "cv": snapshot.credential_version,
                            "sv": snapshot.security_version,
                            "hash": snapshot.password_hash,
                        },
                    )
                )
            if not current or snapshot is None:
                await writer.write(
                    SecurityAuditEvent(
                        event_type=SecurityEventType.LOGIN_FAILURE,
                        result=SecurityEventResult.FAILURE,
                        reason_code=SecurityReasonCode.INVALID_CREDENTIALS,
                    )
                )
                return None
            issued = await SessionService(PostgresSessionStore(connection)).issue(
                snapshot.user_id, snapshot.security_version
            )
            await writer.write(
                SecurityAuditEvent(
                    event_type=SecurityEventType.LOGIN_SUCCESS,
                    result=SecurityEventResult.SUCCESS,
                    user_id=issued.record.user_id,
                    session_id=issued.record.id,
                )
            )
            return issued

    async def change_password(self, bearer: str, old_password: str, new_password: str) -> bool:
        try:
            return await self._change_password(bearer, old_password, new_password)
        except SQLAlchemyError:
            raise PasswordAuthenticationUnavailableError() from None

    async def _change_password(self, bearer: str, old_password: str, new_password: str) -> bool:
        dummy = await self._dummy()
        try:
            digest = token_digest(bearer)
        except UnicodeEncodeError:
            return False
        async with self._engine.begin() as connection:
            row = (
                (
                    await connection.execute(
                        text("SELECT * FROM auth.password_change_snapshot(:digest)"),
                        {"digest": digest},
                    )
                )
                .mappings()
                .one_or_none()
            )
            snapshot = None if row is None else _CredentialSnapshot.from_row(row)
        verified = await self._passwords.verify_password(
            dummy if snapshot is None else snapshot.password_hash, old_password
        )
        if not verified or snapshot is None:
            return False
        replacement = await self._passwords.hash_password(new_password)
        async with self._engine.begin() as connection:
            # The function writes mandatory audit rows through append_security_event
            # in this same transaction, including when called directly through SQL.
            changed = (
                await connection.execute(
                    text("SELECT * FROM auth.apply_password_change(:digest,:cv,:sv,:old,:new)"),
                    {
                        "digest": digest,
                        "cv": snapshot.credential_version,
                        "sv": snapshot.security_version,
                        "old": snapshot.password_hash,
                        "new": replacement,
                    },
                )
            ).one_or_none()
            return changed is not None
