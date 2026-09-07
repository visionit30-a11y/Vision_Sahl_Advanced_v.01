"""Targeted password primitive and policy tests for G3."""

from __future__ import annotations

import unicodedata
import uuid

import pytest
from argon2 import PasswordHasher, Type, extract_parameters

from app.models.identity import PasswordCredential
from app.security.passwords import PasswordPolicyError, PasswordService, normalize_password

PASSWORD = "valid password 123"


async def test_hash_and_verify_use_exact_argon2id_profile() -> None:
    service = PasswordService()
    password_hash = await service.hash_password(PASSWORD)
    parameters = extract_parameters(password_hash)
    assert password_hash.startswith("$argon2id$")
    assert (parameters.type, parameters.memory_cost, parameters.time_cost) == (Type.ID, 65536, 3)
    assert (parameters.parallelism, parameters.salt_len, parameters.hash_len) == (4, 16, 32)
    assert await service.verify_password(password_hash, PASSWORD) is True
    assert await service.verify_password(password_hash, "wrong password 123") is False


async def test_salts_are_unique_and_malformed_phc_fails_closed() -> None:
    service = PasswordService()
    first, second = await service.hash_password(PASSWORD), await service.hash_password(PASSWORD)
    assert first != second
    assert await service.verify_password("not-a-phc", PASSWORD) is False
    assert service.needs_rehash("not-a-phc") is False


async def test_rehash_only_follows_successful_verification() -> None:
    old = PasswordHasher(time_cost=2, memory_cost=32768, parallelism=2, type=Type.ID).hash(PASSWORD)
    service = PasswordService()
    assert service.needs_rehash(old) is True
    failed = await service.verify_and_rehash(old, "wrong password 123")
    assert failed.verified is False and failed.replacement_hash is None
    succeeded = await service.verify_and_rehash(old, PASSWORD)
    assert succeeded.verified is True and succeeded.replacement_hash is not None
    assert service.needs_rehash(succeeded.replacement_hash) is False


@pytest.mark.parametrize("length", [14, 129])
def test_policy_rejects_outside_15_to_128_code_points(length: int) -> None:
    with pytest.raises(PasswordPolicyError, match="Password length") as failure:
        normalize_password("x" * length)
    assert "x" * length not in str(failure.value)


def test_policy_is_nfc_and_preserves_spaces_and_case() -> None:
    raw = "  Mixed Ca" + "fe\u0301" + " 123 "
    assert normalize_password(raw) == unicodedata.normalize("NFC", raw)
    assert normalize_password(raw).startswith("  M") and normalize_password(raw).endswith(" ")


def test_sensitive_values_are_absent_from_reprs() -> None:
    credential = PasswordCredential(user_id=uuid.uuid4(), password_hash="$argon2id$secret")
    rendered = repr(credential)
    assert "argon2" not in rendered and "secret" not in rendered


def test_hashing_module_has_no_database_dependency() -> None:
    from pathlib import Path

    import app.security.passwords

    module_path = Path(app.security.passwords.__file__ or "")
    source = module_path.read_text(encoding="utf-8")
    assert "sqlalchemy" not in source.casefold()
    assert "transaction" not in source.casefold()
