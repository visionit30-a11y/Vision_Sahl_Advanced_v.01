"""The official local server uses a Psycopg-compatible loop only on Windows."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app import local_server


def test_local_server_refuses_nondevelopment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(local_server, "get_settings", lambda: SimpleNamespace(app_env="production"))

    with pytest.raises(RuntimeError, match="APP_ENV=development"):
        local_server.main()


def test_windows_local_server_uses_selector_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = Mock()
    runner.__enter__ = Mock(return_value=runner)
    runner.__exit__ = Mock(return_value=False)
    server = Mock()
    operation = object()
    server.serve.return_value = operation

    monkeypatch.setattr(
        local_server, "get_settings", lambda: SimpleNamespace(app_env="development")
    )
    monkeypatch.setattr(local_server.uvicorn, "Config", Mock(return_value=object()))
    monkeypatch.setattr(local_server.uvicorn, "Server", Mock(return_value=server))
    monkeypatch.setattr(local_server.platform, "system", lambda: "Windows")
    runner_factory = Mock(return_value=runner)
    monkeypatch.setattr(local_server.asyncio, "Runner", runner_factory)

    local_server.main()

    factory = runner_factory.call_args.kwargs["loop_factory"]
    loop = factory()
    try:
        assert isinstance(loop, local_server.asyncio.SelectorEventLoop)
    finally:
        loop.close()
    runner.run.assert_called_once_with(operation)
