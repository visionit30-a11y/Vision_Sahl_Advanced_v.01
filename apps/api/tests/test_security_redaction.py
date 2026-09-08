"""G3 closed redaction and final renderer/security boundary tests."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy.exc import DBAPIError

from app.core.config import Settings
from app.core.context import (
    CORRELATION_ID_HEADER,
    bind_request_context,
    clear_request_context,
    get_correlation_id,
    get_internal_correlation_id,
)
from app.core.errors import AppError, _safe_error_details, build_error_payload
from app.core.logging import _safe_log_projection, configure_logging, get_logger
from app.db.session import _engine

MARKERS = (
    "g3-password-canary",
    "g3-password-hash-canary",
    "g3-bearer-canary",
    "g3-reset-token-canary",
    "g3-csrf-token-canary",
    "g3-db-credential-canary",
    "g3-sql-parameter-canary",
    "g3-unknown-key-canary",
)


class SecretPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: str
    count: int

    @field_validator("password")
    @classmethod
    def reject_password(cls, value: str) -> str:
        raise ValueError(value)


@pytest.mark.parametrize("marker", MARKERS)
def test_unknown_nested_values_keys_messages_and_exc_info_are_never_emitted(marker: str) -> None:
    class Poison:
        def __str__(self) -> str:
            pytest.fail("The projection must not stringify arbitrary objects")

        def __repr__(self) -> str:
            pytest.fail("The projection must not repr arbitrary objects")

    projected = _safe_log_projection(
        None,
        "error",
        {
            "event": marker,
            marker: {"nested": [marker]},
            "exc_info": (RuntimeError, RuntimeError(marker), None),
            "exception": marker,
            "stack": marker,
            "body": {marker: [marker]},
            "message": Poison(),
            "correlation_id": marker,
        },
    )
    assert projected == {"event": "diagnostic_event", "level": "error"}


def test_safe_correlation_is_generated_once_and_shared_without_logging_client_id() -> None:
    clear_request_context()
    try:
        bind_request_context("legacy-request-123")
        internal = get_internal_correlation_id()
        assert isinstance(internal, uuid.UUID) and internal.version == 7
        assert get_correlation_id() == "legacy-request-123"
        one = _safe_log_projection(None, "error", {"event": "audit_write_failed"})
        two = _safe_log_projection(None, "error", {"event": "unhandled_exception"})
        assert one["correlation_id"] == two["correlation_id"] == str(internal)
        assert "legacy-request-123" not in repr((one, two))
    finally:
        clear_request_context()
    assert get_internal_correlation_id() is None and get_correlation_id() is None


@pytest.mark.parametrize("header", ["a" * 65, "line\nbreak", "with space", ""])
def test_malformed_correlation_is_replaced(header: str) -> None:
    clear_request_context()
    try:
        bind_request_context(header)
        assert get_correlation_id() != header
        assert len(get_correlation_id() or "") == 32
    finally:
        clear_request_context()


def test_unstructured_error_details_are_discarded() -> None:
    assert _safe_error_details({MARKERS[0]: MARKERS}) is None
    assert _safe_error_details(
        [{"type": MARKERS[0], "loc": ["body", MARKERS[1]], "msg": MARKERS[2], "input": MARKERS}]
    ) == [{"type": "invalid_value", "loc": ["body"]}]
    payload = build_error_payload(MARKERS[0], MARKERS[1], {MARKERS[2]: MARKERS})
    assert payload["error"]["code"] == "internal_error"
    assert payload["error"]["message"] == "Unexpected error."
    assert "details" not in payload["error"]
    assert all(marker not in repr(AppError(marker)) for marker in MARKERS)


async def test_validation_drops_values_validator_text_and_unknown_keys(
    app: FastAPI, client: AsyncClient
) -> None:
    @app.post("/_redaction/validation")
    def validate(payload: SecretPayload) -> None:
        raise AssertionError("Validation must reject the request")

    response = await client.post(
        "/_redaction/validation",
        json={"password": MARKERS[0], "count": MARKERS[1], MARKERS[2]: {MARKERS[3]: MARKERS}},
    )
    assert response.status_code == 422
    details = response.json()["error"]["details"]
    assert {tuple(item["loc"]) for item in details} == {
        ("body", "password"),
        ("body", "count"),
        ("body",),
    }
    assert all(set(item) == {"type", "loc"} for item in details)
    assert all(marker not in response.text for marker in MARKERS)


async def test_malformed_json_never_echoes_body_fragment(app: FastAPI, client: AsyncClient) -> None:
    @app.post("/_redaction/json")
    def validate(payload: SecretPayload) -> None:
        raise AssertionError("Invalid JSON must not execute")

    response = await client.post(
        "/_redaction/json",
        content='{"password":"' + MARKERS[0],
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422
    assert MARKERS[0] not in response.text
    assert response.json()["error"]["details"] == [{"type": "json_invalid", "loc": ["body"]}]


@pytest.mark.parametrize("status_code", [401, 403, 404, 409, 422, 503])
async def test_http_exception_does_not_echo_detail(
    app: FastAPI, client: AsyncClient, status_code: int
) -> None:
    @app.get("/_redaction/http")
    def fail() -> None:
        raise HTTPException(status_code, detail={MARKERS[0]: {"nested": MARKERS}})

    response = await client.get("/_redaction/http")
    assert response.status_code == status_code
    assert all(marker not in response.text for marker in MARKERS)


async def test_app_error_instance_overrides_cannot_inject_public_text(
    app: FastAPI, client: AsyncClient
) -> None:
    @app.get("/_redaction/app")
    def fail() -> None:
        raise AppError(MARKERS[0], code=MARKERS[1], details={"nested": MARKERS})

    response = await client.get("/_redaction/app")
    assert response.status_code == 500
    assert response.json()["error"]["message"] == "Unexpected error."
    assert all(marker not in response.text for marker in MARKERS)


async def test_db_exception_response_and_final_logs_hide_parameters_and_request(
    app: FastAPI, capsys: pytest.CaptureFixture[str]
) -> None:
    configure_logging("DEBUG", "json")

    @app.get("/auth/_redaction/{selector}")
    def fail(selector: str) -> None:
        raise DBAPIError("SELECT " + MARKERS[6], {"data": MARKERS}, RuntimeError(MARKERS[5]), False)

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get(
            "/auth/_redaction/" + MARKERS[0],
            params={"token": MARKERS[1]},
            headers={CORRELATION_ID_HEADER: "external-request", "Cookie": MARKERS[2]},
        )
    assert response.status_code == 500
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers[CORRELATION_ID_HEADER] == "external-request"
    assert response.json()["error"]["correlation_id"] == "external-request"
    output = capsys.readouterr()
    emitted = output.out + output.err
    assert all(marker not in emitted + response.text for marker in MARKERS)
    assert "external-request" not in emitted
    assert '"route": "unmatched"' in emitted
    assert '"error_category": "database"' in emitted
    records = [json.loads(line) for line in emitted.splitlines() if line.startswith("{")]
    correlated = [
        row["correlation_id"]
        for row in records
        if row.get("event") in {"request_completed", "unhandled_exception"}
    ]
    assert len(correlated) == 2 and len(set(correlated)) == 1
    assert get_correlation_id() is None and get_internal_correlation_id() is None


@pytest.mark.parametrize("log_format", ["json", "console"])
def test_actual_structlog_stdlib_and_uvicorn_emission_is_closed(
    capsys: pytest.CaptureFixture[str], log_format: str
) -> None:
    configure_logging("DEBUG", log_format)
    try:
        raise RuntimeError(MARKERS[0])
    except RuntimeError:
        get_logger().exception(MARKERS[1], arbitrary={MARKERS[2]: MARKERS}, stack_info=True)
        for name in ("app.probe", "uvicorn.error", "sqlalchemy.engine", MARKERS[3]):
            logging.getLogger(name).error("params=%s", MARKERS, exc_info=True, stack_info=True)
    captured = capsys.readouterr()
    assert all(marker not in captured.out + captured.err for marker in MARKERS)
    assert "diagnostic_event" in captured.out and "stdlib_diagnostic" in captured.out
    assert "Traceback" not in captured.out + captured.err


def test_config_repr_hides_every_credential_url_and_key() -> None:
    options: dict[str, Any] = {"_env_file": None}
    settings = Settings(
        **options,
        database_url="postgresql://user:" + MARKERS[0] + "@localhost/test",
        migration_database_url="postgresql://user:" + MARKERS[1] + "@localhost/test",
        redis_url="redis://:" + MARKERS[2] + "@localhost/0",
        auth_hmac_key=MARKERS[3],
    )
    assert all(marker not in repr(settings) + str(settings) for marker in MARKERS)
    assert _engine.sync_engine.hide_parameters is True
    assert _engine.sync_engine.echo is False


async def test_parallel_requests_keep_internal_correlation_distinct_and_clear(
    app: FastAPI, client: AsyncClient
) -> None:
    seen: dict[str, uuid.UUID] = {}

    @app.get("/_redaction/context/{identity}")
    async def context(identity: str) -> None:
        before = get_internal_correlation_id()
        assert before is not None
        await asyncio.sleep(0)
        assert before == get_internal_correlation_id()
        seen[identity] = before

    responses = await asyncio.gather(
        *[
            client.get(
                "/_redaction/context/" + str(index), headers={CORRELATION_ID_HEADER: str(index)}
            )
            for index in range(4)
        ]
    )
    assert all(response.status_code == 200 for response in responses)
    assert len(set(seen.values())) == 4
    assert get_correlation_id() is None and get_internal_correlation_id() is None


def test_real_uvicorn_reraise_never_formats_secrets() -> None:
    """Exercise actual server stderr after Starlette re-raises a handled DB exception."""
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", 8011))
        except OSError:
            pytest.fail("Dedicated redaction test port 8011 is occupied; no process was stopped.")
    environment = dict(os.environ, APP_ENV="test", LOG_FORMAT="json", REDIS_ENABLED="false")
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "tests.security_logging_probe:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8011",
        ],
        cwd=Path(__file__).parents[1],
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )
    response: httpx.Response | None = None
    try:
        with httpx.Client(base_url="http://127.0.0.1:8011", timeout=1.0, trust_env=False) as client:
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    pytest.fail("The isolated redaction server exited before readiness")
                try:
                    if client.get("/health").status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                time.sleep(0.1)
            else:
                pytest.fail("The isolated redaction server did not become ready")
            response = client.post(
                "/auth/_redaction_probe/" + MARKERS[0],
                json={"password": MARKERS[1], "nested": {MARKERS[2]: list(MARKERS)}},
                headers={"Cookie": MARKERS[3], "X-CSRF-Token": MARKERS[4]},
            )
            time.sleep(0.1)
    finally:
        if process.poll() is None:
            process.terminate()
        try:
            output, _ = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            output, _ = process.communicate(timeout=5)
    assert response is not None and response.status_code == 500
    assert all(marker not in output + response.text for marker in MARKERS)
    records = [json.loads(line) for line in output.splitlines() if line.startswith("{")]
    assert any(row.get("event") == "unhandled_exception" for row in records)
    assert any(row.get("component") == "uvicorn" and row.get("level") == "error" for row in records)
    assert "Traceback" not in output and "SELECT" not in output


async def test_cancellation_clears_request_context(app: FastAPI) -> None:
    from starlette.requests import Request
    from starlette.responses import Response

    from app.core.middleware import CorrelationIdMiddleware

    async def cancel(_request: Request) -> Response:
        assert get_internal_correlation_id() is not None
        raise asyncio.CancelledError()

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/health",
            "headers": [],
            "query_string": b"",
            "server": ("testserver", 80),
            "scheme": "http",
        }
    )
    with pytest.raises(asyncio.CancelledError):
        await CorrelationIdMiddleware(app).dispatch(request, cancel)
    assert get_correlation_id() is None and get_internal_correlation_id() is None


def test_existing_domain_error_classes_remain_in_the_public_catalog() -> None:
    from app.core.errors import _PUBLIC_MESSAGES

    pending = list(AppError.__subclasses__())
    while pending:
        contract = pending.pop()
        pending.extend(contract.__subclasses__())
        if contract.__module__.startswith("app."):
            assert contract.code in _PUBLIC_MESSAGES
            assert contract.message in _PUBLIC_MESSAGES[contract.code]


async def test_known_route_logs_template_without_request_query(
    client: AsyncClient, capsys: pytest.CaptureFixture[str]
) -> None:
    configure_logging("INFO", "json")
    response = await client.get("/health", params={"password": MARKERS[0]})
    assert response.status_code == 200
    captured = capsys.readouterr()
    records = [json.loads(line) for line in captured.out.splitlines() if line.startswith("{")]
    completed = [row for row in records if row.get("event") == "request_completed"]
    assert len(completed) == 1 and completed[0]["route"] == "/health"
    assert MARKERS[0] not in captured.out + captured.err
