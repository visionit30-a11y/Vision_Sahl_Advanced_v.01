"""Logging and error redaction guards touched by password credentials."""

from app.core.errors import _safe_error_details
from app.core.logging import MASK, _redact_sensitive


def test_nested_passwords_and_hashes_are_redacted() -> None:
    value = {"body": {"password": "plain", "items": [{"password_hash": "$argon2id$secret"}]}}
    redacted = _redact_sensitive(None, "info", value)
    assert redacted == {"body": {"password": MASK, "items": [{"password_hash": MASK}]}}
    assert "plain" not in repr(redacted) and "secret" not in repr(redacted)


def test_validation_input_and_context_are_redacted() -> None:
    details = _safe_error_details([{"input": "plain", "ctx": {"error": "plain"}}])
    assert details == [{"input": MASK, "ctx": MASK}]


def test_g6_identity_and_network_selectors_are_redacted() -> None:
    raw = {
        "email": "person@example.test",
        "normalized_email": "person@example.test",
        "ip": "192.0.2.1",
        "ip_address": "192.0.2.2",
        "subject_key": "private selector",
    }
    assert set(_redact_sensitive(None, "info", raw).values()) == {MASK}
