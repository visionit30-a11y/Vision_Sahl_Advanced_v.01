"""Required context and the application-layer access contract."""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import cast

import pytest
from structlog.contextvars import bound_contextvars

from app.db import tenant_transaction as transaction_module
from app.models.tenant import new_tenant_id
from app.tenancy.context import InvalidTenantIdError, TenantContext, TenantContextRequiredError

APP = Path(__file__).resolve().parents[1] / "app"


@pytest.mark.parametrize("value", [None, "untrusted-id", object()])
async def test_a_transaction_rejects_missing_context_before_any_session(
    monkeypatch: pytest.MonkeyPatch, value: object
) -> None:
    def forbidden_session() -> None:
        pytest.fail("Missing context must fail before acquiring a database session.")

    monkeypatch.setattr(transaction_module, "_session_factory", forbidden_session)
    with (
        bound_contextvars(tenant_id="logging-is-not-a-trusted-context"),
        pytest.raises(TenantContextRequiredError),
    ):
        async with transaction_module.tenant_transaction(cast(TenantContext, value)):
            pytest.fail("The service body must not execute without trusted context.")


def test_the_only_context_setter_is_a_literal_with_a_bound_transaction_local_value() -> None:
    statement = transaction_module._TENANT_CONTEXT_SQL
    assert statement.text == "SELECT set_config('app.tenant_id', :tenant_id, true)"
    assert statement.compile().params == {"tenant_id": None}
    setter_file = APP / "db" / "tenant_transaction.py"
    offenders = [
        str(path.relative_to(APP))
        for path in APP.rglob("*.py")
        if path != setter_file and "set_config" in path.read_text(encoding="utf-8")
    ]
    assert offenders == [], "Context setters belong only to the tenant transaction boundary."


def test_services_and_http_cannot_import_or_construct_a_raw_database_session() -> None:
    forbidden_constructors = {
        "create_engine",
        "create_async_engine",
        "async_sessionmaker",
        "sessionmaker",
        "AsyncSession",
        "Session",
    }
    allowed_session_imports = {
        "main.py": {"dispose_engine"},
        "services/health_service.py": {"check_connection"},
    }
    violations: list[str] = []
    for path in APP.rglob("*.py"):
        relative = path.relative_to(APP).as_posix()
        if relative.startswith("db/"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        constructor_names = set(forbidden_constructors)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name in forbidden_constructors:
                        constructor_names.add(alias.asname or alias.name)
                if node.module == "app.db.session":
                    allowed = allowed_session_imports.get(relative, set())
                    if any(alias.name not in allowed for alias in node.names):
                        violations.append(relative)
                if node.module == "app.db" and any(alias.name == "session" for alias in node.names):
                    violations.append(relative)
            elif isinstance(node, ast.Import):
                if any(alias.name in {"app.db.session", "psycopg"} for alias in node.names):
                    violations.append(relative)
            elif isinstance(node, ast.Call):
                name = (
                    node.func.id
                    if isinstance(node.func, ast.Name)
                    else getattr(node.func, "attr", "")
                )
                if name in constructor_names:
                    violations.append(relative)
    assert violations == [], "Tenant services must obtain sessions through tenant_transaction."
    session_source = (APP / "db" / "session.py").read_text(encoding="utf-8")
    assert "def get_session(" not in session_source
    assert "SessionFactory" not in session_source


def test_session_level_tenant_set_statements_are_forbidden() -> None:
    migrations = APP.parents[2] / "migrations"
    statement = re.compile(
        r"\bSET\s+(?:(?:SESSION|LOCAL)\s+)?(?:app\.tenant_id|\"app\.tenant_id\")\s*(?:=|TO\b)",
        re.IGNORECASE,
    )
    violations = [
        str(path)
        for root in (APP, migrations)
        for path in root.rglob("*.py")
        if statement.search(path.read_text(encoding="utf-8"))
    ]
    assert violations == [], "Tenant context must be transaction-local and parameterized."


async def test_invalid_context_is_rejected_before_acquiring_a_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = TenantContext(new_tenant_id())
    object.__setattr__(context, "tenant_id", "not-a-uuid")

    def forbidden_session() -> None:
        pytest.fail("Invalid identity must fail before acquiring a database session.")

    monkeypatch.setattr(transaction_module, "_session_factory", forbidden_session)
    with pytest.raises(InvalidTenantIdError):
        async with transaction_module.tenant_transaction(context):
            pytest.fail("Invalid identity must never execute the service body.")
