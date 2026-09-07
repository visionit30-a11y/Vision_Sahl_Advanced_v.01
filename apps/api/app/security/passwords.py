"""Argon2id password policy, hashing, verification, and rehash decisions."""

from __future__ import annotations

import asyncio
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError

MIN_PASSWORD_CODE_POINTS = 15
MAX_PASSWORD_CODE_POINTS = 128
ARGON2_MEMORY_COST_KIB = 65_536
ARGON2_TIME_COST = 3
ARGON2_PARALLELISM = 4
ARGON2_SALT_LENGTH = 16
ARGON2_HASH_LENGTH = 32


class PasswordPolicyError(ValueError):
    """Raised without echoing a password when it violates the contract."""


def normalize_password(password: str) -> str:
    """Apply NFC only; preserve spaces, case, and leading/trailing characters."""
    normalized = unicodedata.normalize("NFC", password)
    if not MIN_PASSWORD_CODE_POINTS <= len(normalized) <= MAX_PASSWORD_CODE_POINTS:
        raise PasswordPolicyError(
            f"Password length must be {MIN_PASSWORD_CODE_POINTS} to "
            f"{MAX_PASSWORD_CODE_POINTS} Unicode code points."
        )
    return normalized


@dataclass(frozen=True, slots=True)
class PasswordVerification:
    verified: bool
    replacement_hash: str | None = field(default=None, repr=False)


class PasswordService:
    """Run memory-hard work off the event loop with bounded concurrency."""

    __slots__ = ("_hasher", "_semaphore")

    def __init__(self, *, max_concurrency: int = 2) -> None:
        if max_concurrency < 1:
            raise ValueError("Password hashing concurrency must be positive.")
        self._hasher = PasswordHasher(
            time_cost=ARGON2_TIME_COST,
            memory_cost=ARGON2_MEMORY_COST_KIB,
            parallelism=ARGON2_PARALLELISM,
            hash_len=ARGON2_HASH_LENGTH,
            salt_len=ARGON2_SALT_LENGTH,
            type=Type.ID,
        )
        self._semaphore = asyncio.Semaphore(max_concurrency)

    async def _run(self, function: Callable[..., Any], *args: Any) -> Any:
        async with self._semaphore:
            return await asyncio.to_thread(function, *args)

    async def hash_password(self, password: str) -> str:
        return str(await self._run(self._hasher.hash, normalize_password(password)))

    async def verify_password(self, password_hash: str, password: str) -> bool:
        try:
            normalized = normalize_password(password)
            return bool(await self._run(self._hasher.verify, password_hash, normalized))
        except PasswordPolicyError, InvalidHashError, VerificationError:
            return False

    def needs_rehash(self, password_hash: str) -> bool:
        try:
            return self._hasher.check_needs_rehash(password_hash)
        except InvalidHashError:
            return False

    async def verify_and_rehash(self, password_hash: str, password: str) -> PasswordVerification:
        try:
            normalized = normalize_password(password)
            verified = bool(await self._run(self._hasher.verify, password_hash, normalized))
        except PasswordPolicyError, InvalidHashError, VerificationError:
            return PasswordVerification(verified=False)
        replacement = (
            str(await self._run(self._hasher.hash, normalized))
            if self.needs_rehash(password_hash)
            else None
        )
        return PasswordVerification(verified=verified, replacement_hash=replacement)
