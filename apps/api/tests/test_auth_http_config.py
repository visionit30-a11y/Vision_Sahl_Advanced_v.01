"""The browser-test HTTP exception never changes production origin policy."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from tests.test_config import IsolatedSettings


def test_browser_test_origin_is_not_enabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AUTH_LOCAL_HTTP_ORIGIN", raising=False)
    settings = IsolatedSettings()
    assert settings.auth_local_http_origin is None
    assert settings.auth_origin_list == settings.cors_origin_list
    assert "http://localhost:5187" not in settings.auth_origin_list
    assert settings.api_port == 8010
    assert "http://localhost:5173" in settings.cors_origin_list


@pytest.mark.parametrize("environment", ["development", "test"])
def test_exact_approved_origin_requires_local_environment(environment: str) -> None:
    settings = IsolatedSettings.model_validate(
        {
            "app_env": environment,
            "auth_local_http_origin": "http://localhost:5187",
        }
    )
    assert settings.auth_origin_list[-1] == "http://localhost:5187"
    assert "http://localhost:5187" not in settings.cors_origin_list


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_protected_environments_reject_local_http_exception(environment: str) -> None:
    with pytest.raises(ValidationError, match="restricted"):
        IsolatedSettings.model_validate(
            {
                "app_env": environment,
                "auth_local_http_origin": "http://localhost:5187",
            }
        )


@pytest.mark.parametrize(
    "origin",
    [
        "http://127.0.0.1:5187",
        "http://localhost:5188",
        "http://localhost:5187/",
        "http://evil.test:5187",
        "http://localhost:5187.evil.test",
        "*",
    ],
)
def test_unapproved_http_origins_are_rejected(origin: str) -> None:
    with pytest.raises(ValidationError, match="restricted"):
        IsolatedSettings(auth_local_http_origin=origin)


def test_explicit_browser_origin_is_not_duplicated() -> None:
    settings = IsolatedSettings(
        cors_origins="http://localhost:5187",
        auth_local_http_origin="http://localhost:5187",
    )
    assert settings.auth_origin_list == ["http://localhost:5187"]


def test_development_origin_is_explicit_and_not_available_to_test_or_production() -> None:
    settings = IsolatedSettings(
        app_env="development", auth_local_http_origin="http://localhost:5173"
    )
    assert settings.auth_local_http_origin == "http://localhost:5173"
    for environment in ("test", "staging", "production"):
        with pytest.raises(ValidationError, match="restricted"):
            IsolatedSettings.model_validate(
                {"app_env": environment, "auth_local_http_origin": "http://localhost:5173"}
            )
