"""Typed permission catalogue and anti-scattering contracts for Phase 2C G2."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.authorization.permissions import (
    PERMISSION_CATALOG,
    InvalidPermissionCatalogError,
    InvalidPermissionIdError,
    Permission,
    PermissionId,
    build_permission_catalog,
)
from app.models.authorization import InvalidRoleKeyError, RoleKey, RoleStatus, new_role_id

APP_ROOT = Path(__file__).resolve().parents[1] / "app"
CATALOG_FILE = APP_ROOT / "authorization" / "permissions.py"
SERVICE_FILE = APP_ROOT / "authorization" / "service.py"
RBAC_MODEL_FILE = APP_ROOT / "models" / "authorization.py"


def test_catalog_is_complete_typed_and_unique() -> None:
    expected = frozenset(PermissionId(permission.value) for permission in Permission)
    assert expected == PERMISSION_CATALOG
    assert len(PERMISSION_CATALOG) == len(Permission)
    assert all(type(value) is PermissionId for value in PERMISSION_CATALOG)


def test_duplicate_permission_is_rejected() -> None:
    with pytest.raises(InvalidPermissionCatalogError):
        build_permission_catalog(["tenant.roles.read", "tenant.roles.read"])


@pytest.mark.parametrize(
    "value",
    ["roles.read", "Tenant.roles.read", "tenant.roles", "tenant.roles.*", "tenant..read"],
)
def test_invalid_permission_id_is_rejected(value: str) -> None:
    with pytest.raises(InvalidPermissionIdError):
        PermissionId(value)


def test_role_domain_contract_uses_stable_keys_and_uuid7() -> None:
    assert RoleKey("tenant_admin") == "tenant_admin"
    with pytest.raises(InvalidRoleKeyError):
        RoleKey("Tenant Admin")
    assert new_role_id().version == 7
    assert {status.value for status in RoleStatus} == {"active", "inactive"}


def test_permission_literals_are_centralized_in_the_catalog() -> None:
    violations: list[str] = []
    for path in APP_ROOT.rglob("*.py"):
        if path == CATALOG_FILE:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and node.value in {permission.value for permission in Permission}
            ):
                violations.append(f"{path.relative_to(APP_ROOT)}:{node.lineno}")
    assert violations == []


def test_application_code_contains_no_role_name_decisions() -> None:
    forbidden_attributes = {"role", "roles", "role_name"}
    violations: list[str] = []
    for path in APP_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Compare):
                continue
            operands = [node.left, *node.comparators]
            if any(
                (isinstance(item, ast.Name) and item.id in forbidden_attributes)
                or (isinstance(item, ast.Attribute) and item.attr in forbidden_attributes)
                for item in operands
            ):
                violations.append(f"{path.relative_to(APP_ROOT)}:{node.lineno}")
    assert violations == []


def test_authorization_service_is_the_only_decision_path() -> None:
    violations: list[str] = []
    protected_tables = {"auth.roles", "auth.role_permissions", "auth.membership_roles"}
    for path in APP_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                path not in {SERVICE_FILE, RBAC_MODEL_FILE}
                and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == "authorize"
            ):
                violations.append(f"decision:{path.relative_to(APP_ROOT)}:{node.lineno}")
            if (
                path not in {SERVICE_FILE, RBAC_MODEL_FILE}
                and isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and any(table in node.value for table in protected_tables)
            ):
                violations.append(f"table:{path.relative_to(APP_ROOT)}:{node.lineno}")
    assert violations == []
