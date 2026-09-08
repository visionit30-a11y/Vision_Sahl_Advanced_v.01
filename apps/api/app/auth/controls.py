"""PostgreSQL-backed throttling, password-reset, and security-event services."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.audit.writer import SecurityEventWriter as SecurityEventWriter
from app.security.passwords import PasswordService

RESET_TOKEN_BYTES = 32


class ThrottleScope(StrEnum):
    LOGIN_USERNAME = "login_username"
    LOGIN_IP = "login_ip"
    LOGIN_IP_USERNAME = "login_ip_username"
    RESET_USERNAME = "reset_username"
    RESET_IP = "reset_ip"
    CSRF_IP = "csrf_ip"


POLICIES = {
    ThrottleScope.LOGIN_USERNAME: (10, 900),
    ThrottleScope.LOGIN_IP: (30, 60),
    ThrottleScope.LOGIN_IP_USERNAME: (5, 900),
    ThrottleScope.RESET_USERNAME: (3, 3600),
    ThrottleScope.RESET_IP: (20, 3600),
    ThrottleScope.CSRF_IP: (30, 60),
}


def sensitive_key_digest(key: bytes, purpose: ThrottleScope, value: str) -> bytes:
    return hmac.new(key, purpose.value.encode() + b"\0" + value.encode(), hashlib.sha256).digest()


def token_digest(token: str) -> bytes:
    return hashlib.sha256(token.encode("ascii")).digest()


def new_reset_token() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(RESET_TOKEN_BYTES)).rstrip(b"=").decode()


@dataclass(frozen=True, slots=True)
class ThrottleDecision:
    allowed: bool
    request_count: int
    retry_after_seconds: int


class ThrottleStore(Protocol):
    async def consume(
        self, scope: ThrottleScope, key_digest: bytes, key_id: int, limit: int, window_seconds: int
    ) -> ThrottleDecision: ...


class PostgresThrottleStore:
    def __init__(self, connection: AsyncConnection) -> None:
        self.connection = connection

    async def consume(
        self, scope: ThrottleScope, key_digest: bytes, key_id: int, limit: int, window_seconds: int
    ) -> ThrottleDecision:
        row = (
            await self.connection.execute(
                text(
                    """SELECT * FROM auth.consume_throttle(
                    CAST(:scope AS text),CAST(:key AS bytea),CAST(:key_id AS smallint),
                    CAST(:limit AS integer),CAST(:window AS integer)
                    )"""
                ),
                {
                    "scope": scope.value,
                    "key": key_digest,
                    "key_id": key_id,
                    "limit": limit,
                    "window": window_seconds,
                },
            )
        ).one()
        return ThrottleDecision(row.allowed, row.request_count, row.retry_after_seconds)


class ThrottleService:
    def __init__(self, store: ThrottleStore, key: bytes, *, key_id: int = 1) -> None:
        if len(key) < 32:
            raise ValueError("Throttle HMAC key must contain at least 256 bits.")
        self.store = store
        self.key = key
        self.key_id = key_id

    async def consume(self, scope: ThrottleScope, value: str) -> ThrottleDecision:
        limit, window = POLICIES[scope]
        return await self.store.consume(
            scope, sensitive_key_digest(self.key, scope, value), self.key_id, limit, window
        )


@dataclass(frozen=True, slots=True)
class ResetRequest:
    accepted: bool = True
    delivery_token: str | None = field(default=None, repr=False)


class ResetStore(Protocol):
    async def request(
        self,
        email: str,
        digest: bytes,
        token_id: uuid.UUID,
        event_id: uuid.UUID,
        correlation_id: str,
    ) -> bool: ...
    async def complete(
        self, digest: bytes, password_hash: str, event_id: uuid.UUID, correlation_id: str
    ) -> bool: ...


class PostgresResetStore:
    def __init__(self, connection: AsyncConnection) -> None:
        self.connection = connection

    async def request(
        self,
        email: str,
        digest: bytes,
        token_id: uuid.UUID,
        event_id: uuid.UUID,
        correlation_id: str,
    ) -> bool:
        return bool(
            await self.connection.scalar(
                text(
                    "SELECT auth.request_password_reset(:email,:digest,:token,:event,:correlation)"
                ),
                {
                    "email": email,
                    "digest": digest,
                    "token": token_id,
                    "event": event_id,
                    "correlation": correlation_id,
                },
            )
        )

    async def complete(
        self, digest: bytes, password_hash: str, event_id: uuid.UUID, correlation_id: str
    ) -> bool:
        return bool(
            await self.connection.scalar(
                text("SELECT auth.complete_password_reset(:digest,:hash,:event,:correlation)"),
                {
                    "digest": digest,
                    "hash": password_hash,
                    "event": event_id,
                    "correlation": correlation_id,
                },
            )
        )


class PasswordResetService:
    def __init__(self, store: ResetStore, passwords: PasswordService) -> None:
        self.store = store
        self.passwords = passwords

    async def request(self, normalized_email: str, correlation_id: str) -> ResetRequest:
        token = new_reset_token()
        exists = await self.store.request(
            normalized_email, token_digest(token), uuid.uuid7(), uuid.uuid7(), correlation_id
        )
        return ResetRequest(delivery_token=token if exists else None)

    async def complete(self, token: str, new_password: str, correlation_id: str) -> bool:
        password_hash = await self.passwords.hash_password(new_password)
        return await self.store.complete(
            token_digest(token), password_hash, uuid.uuid7(), correlation_id
        )
