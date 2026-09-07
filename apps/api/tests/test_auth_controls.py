"""G6 service contracts without replacing PostgreSQL integration proofs."""

from __future__ import annotations

import base64

import pytest

from app.auth.controls import (
    POLICIES,
    PasswordResetService,
    ResetRequest,
    ThrottleDecision,
    ThrottleScope,
    ThrottleService,
    new_reset_token,
    sensitive_key_digest,
    token_digest,
)
from app.core.config import AuthHmacKeyMissingError
from app.security.passwords import PasswordService


class RecordingThrottleStore:
    def __init__(self, *, failure: Exception | None = None) -> None:
        self.calls: list[tuple[object, ...]] = []
        self.failure = failure

    async def consume(self, *values: object) -> ThrottleDecision:
        self.calls.append(values)
        if self.failure:
            raise self.failure
        return ThrottleDecision(True, 1, 60)


class RecordingResetStore:
    def __init__(self, *, exists: bool = True) -> None:
        self.exists = exists
        self.request_digest: bytes | None = None
        self.completed: tuple[bytes, str] | None = None

    async def request(self, email: str, digest: bytes, *args: object) -> bool:
        self.request_digest = digest
        return self.exists

    async def complete(self, digest: bytes, password_hash: str, *args: object) -> bool:
        self.completed = (digest, password_hash)
        return True


def test_throttle_policy_is_the_approved_fixed_window_contract() -> None:
    assert POLICIES == {
        ThrottleScope.LOGIN_USERNAME: (10, 900),
        ThrottleScope.LOGIN_IP: (30, 60),
        ThrottleScope.LOGIN_IP_USERNAME: (5, 900),
        ThrottleScope.RESET_USERNAME: (3, 3600),
        ThrottleScope.RESET_IP: (20, 3600),
        ThrottleScope.CSRF_IP: (30, 60),
    }


async def test_sensitive_throttle_keys_are_hmaced_and_purpose_separated() -> None:
    secret = b"k" * 32
    raw = "person@example.test"
    username = sensitive_key_digest(secret, ThrottleScope.LOGIN_USERNAME, raw)
    combined = sensitive_key_digest(secret, ThrottleScope.LOGIN_IP_USERNAME, raw)
    assert len(username) == 32 and username != combined and raw.encode() not in username
    store = RecordingThrottleStore()
    await ThrottleService(store, secret).consume(ThrottleScope.LOGIN_USERNAME, raw)
    assert store.calls[0][1] == username
    assert raw not in repr(store.calls)


async def test_postgres_throttle_failure_propagates_and_has_no_fallback() -> None:
    store = RecordingThrottleStore(failure=ConnectionError("database unavailable"))
    with pytest.raises(ConnectionError, match="unavailable"):
        await ThrottleService(store, b"k" * 32).consume(ThrottleScope.LOGIN_IP, "192.0.2.1")
    assert len(store.calls) == 1


def test_throttle_rejects_short_hmac_key() -> None:
    with pytest.raises(ValueError, match="256 bits"):
        ThrottleService(RecordingThrottleStore(), b"short")


async def test_reset_request_is_generic_and_delivery_token_is_private() -> None:
    existing = await PasswordResetService(
        RecordingResetStore(exists=True), PasswordService()
    ).request("known@example.test", "correlation")
    missing = await PasswordResetService(
        RecordingResetStore(exists=False), PasswordService()
    ).request("missing@example.test", "correlation")
    assert existing.accepted is True and missing.accepted is True
    assert existing.delivery_token is not None and missing.delivery_token is None
    assert "delivery_token" not in repr(existing) and existing.delivery_token not in repr(existing)


def test_reset_token_has_256_bits_and_digest_only_representation() -> None:
    token = new_reset_token()
    decoded = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
    assert len(decoded) == 32 and len(token_digest(token)) == 32
    assert token.encode() not in token_digest(token)
    assert token not in repr(ResetRequest(delivery_token=token))


async def test_reset_hashes_before_atomic_database_completion() -> None:
    store = RecordingResetStore()
    service = PasswordResetService(store, PasswordService())
    token = new_reset_token()
    assert await service.complete(token, "new password value 123", "correlation") is True
    assert store.completed is not None
    digest, password_hash = store.completed
    assert digest == token_digest(token) and password_hash.startswith("$argon2id$")
    assert token not in repr(store.completed) and "new password value 123" not in repr(
        store.completed
    )


def test_missing_auth_hmac_secret_fails_closed() -> None:
    from tests.test_config import IsolatedSettings

    with pytest.raises(AuthHmacKeyMissingError, match="no insecure fallback"):
        _ = IsolatedSettings(auth_hmac_key=None).required_auth_hmac_key
    assert IsolatedSettings(auth_hmac_key="x" * 32).required_auth_hmac_key == b"x" * 32
