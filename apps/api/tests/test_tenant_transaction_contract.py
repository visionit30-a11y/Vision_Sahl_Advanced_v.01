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


MAINTENANCE_RUNNER = "maintenance/security_audit_retention.py"


def _imported_module(relative: str, node: ast.ImportFrom) -> str:
    if not node.level:
        return node.module or ""
    package = ["app", *Path(relative).parent.parts]
    parent = package[: len(package) - node.level + 1]
    return ".".join([*parent, *(node.module or "").split(".")]).rstrip(".")


def _database_boundary_violations(relative: str, source: str) -> list[str]:
    tree = ast.parse(source)
    violations: list[str] = []
    # Maintenance is an explicitly invoked standalone capability, never an
    # application service. Namespace imports must not make its connector reachable.
    if relative != MAINTENANCE_RUNNER:
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                module = _imported_module(relative, node)
                modules = [module, *(f"{module}.{alias.name}" for alias in node.names)]
            if any(
                module == "app.maintenance" or module.startswith("app.maintenance.")
                for module in modules
            ):
                violations.append("maintenance-import")
    if relative.startswith("db/"):
        return violations

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
    constructor_names = set(forbidden_constructors)
    standalone_engine_imported = False
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name in forbidden_constructors:
                    constructor_names.add(alias.asname or alias.name)
                if (
                    node.module == "sqlalchemy"
                    and alias.name == "create_engine"
                    and alias.asname is None
                ):
                    standalone_engine_imported = True
            if node.module == "app.db.session":
                allowed = allowed_session_imports.get(relative, set())
                if any(alias.name not in allowed for alias in node.names):
                    violations.append("session-import")
            if node.module == "app.db" and any(alias.name == "session" for alias in node.names):
                violations.append("session-import")
            if node.module == "psycopg" or (node.module or "").startswith("psycopg."):
                violations.append("driver-import")
        elif isinstance(node, ast.Import):
            if any(alias.name in {"app.db.session", "psycopg"} for alias in node.names):
                violations.append("session-or-driver-import")
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = (
                node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", "")
            )
            if name in constructor_names:
                # G4's separately authorized runner constructs one synchronous
                # NullPool engine with its maintenance URL; no application session
                # factory, async constructor, or other maintenance file is exempt.
                approved_maintenance_engine = (
                    relative == MAINTENANCE_RUNNER
                    and standalone_engine_imported
                    and isinstance(node.func, ast.Name)
                    and name == "create_engine"
                )
                if not approved_maintenance_engine:
                    violations.append("session-constructor")
    return violations


def test_services_and_http_cannot_import_or_construct_a_raw_database_session() -> None:
    violations = {
        path.relative_to(APP).as_posix(): result
        for path in APP.rglob("*.py")
        if (
            result := _database_boundary_violations(
                path.relative_to(APP).as_posix(), path.read_text(encoding="utf-8")
            )
        )
    }
    assert violations == {}, "Tenant services must obtain sessions through tenant_transaction."
    session_source = (APP / "db" / "session.py").read_text(encoding="utf-8")
    assert "def get_session(" not in session_source
    assert "SessionFactory" not in session_source


def test_only_the_approved_standalone_runner_can_construct_its_sync_engine() -> None:
    source = "from sqlalchemy import create_engine\ncreate_engine(maintenance_url)"
    assert _database_boundary_violations(MAINTENANCE_RUNNER, source) == []


@pytest.mark.parametrize(
    "relative", ["services/roles.py", "api/dependencies.py", "maintenance/other.py"]
)
def test_maintenance_classification_does_not_allow_other_raw_connectors(relative: str) -> None:
    source = "from sqlalchemy import create_engine\ncreate_engine(url)"
    assert _database_boundary_violations(relative, source) == ["session-constructor"]


@pytest.mark.parametrize(
    "constructor",
    ["Session", "AsyncSession", "sessionmaker", "async_sessionmaker", "create_async_engine"],
)
def test_maintenance_runner_still_cannot_create_application_sessions(constructor: str) -> None:
    source = f"from sqlalchemy import {constructor} as forbidden\nforbidden()"
    assert _database_boundary_violations(MAINTENANCE_RUNNER, source) == ["session-constructor"]


@pytest.mark.parametrize(
    "statement",
    [
        "import psycopg",
        "from psycopg import connect",
        "import app.db.session",
        "from app.db.session import _session_factory",
        "from app.db import session",
    ],
)
def test_maintenance_runner_keeps_driver_and_application_session_import_guards(
    statement: str,
) -> None:
    assert _database_boundary_violations(MAINTENANCE_RUNNER, statement)


@pytest.mark.parametrize(
    "statement",
    [
        "import app.maintenance",
        "import app.maintenance.security_audit_retention as runner",
        "from app import maintenance",
        "from app.maintenance import security_audit_retention",
        "from app.maintenance.security_audit_retention import main",
        "from ..maintenance import security_audit_retention",
    ],
)
def test_application_services_cannot_reach_the_standalone_maintenance_runner(
    statement: str,
) -> None:
    assert "maintenance-import" in _database_boundary_violations("services/roles.py", statement)


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
