"""HTTP enforcement, IDOR, and protected service-boundary gates."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.api.authorization_dependencies import (
    get_authorization_service,
    require_authenticated_access,
    require_permission,
)
from app.auth.sessions import SessionRecord
from app.auth.tenants import AuthenticatedPrincipal, TrustedTenantAccess
from app.authorization.contracts import AuthorizationGrant
from app.authorization.permissions import Permission, PermissionId
from app.authorization.service import AuthorizationDecision
from app.models.tenant import TenantId
from app.services.membership_access_service import (
    AuthorizationBoundaryRequiredError,
    MembershipAccessService,
    membership_access_service,
)
from app.tenancy.context import TenantContext


@dataclass
class StubAuthorizer:
    decisions: list[AuthorizationDecision]
    calls: list[tuple[object, object, object]] = field(default_factory=list)

    async def authorize(
        self, principal: object, context: object, permission: object
    ) -> AuthorizationDecision:
        self.calls.append((principal, context, permission))
        return self.decisions.pop(0)


def _access() -> TrustedTenantAccess:
    tenant_id, user_id, session_id, membership_id = (uuid.uuid7() for _ in range(4))
    now = datetime.now(UTC)
    session = SessionRecord(
        session_id,
        user_id,
        bytes([1]) * 32,
        bytes([2]) * 32,
        1,
        now,
        now,
        now,
        now + timedelta(minutes=30),
        now + timedelta(hours=8),
        selected_membership_id=membership_id,
        selected_membership_version=1,
    )
    return TrustedTenantAccess(
        AuthenticatedPrincipal(user_id, session_id, membership_id, 1),
        TenantContext(TenantId(tenant_id)),
        session,
    )


def _authorize(
    app: FastAPI,
    access: TrustedTenantAccess,
    *decisions: AuthorizationDecision,
) -> StubAuthorizer:
    authorizer = StubAuthorizer(list(decisions))

    async def trusted() -> TrustedTenantAccess:
        return access

    app.dependency_overrides[require_authenticated_access] = trusted
    app.dependency_overrides[get_authorization_service] = lambda: authorizer
    return authorizer


@pytest.mark.asyncio
async def test_authenticated_catalog_permission_allows_service_execution(
    app: FastAPI, client: AsyncClient
) -> None:
    access = _access()
    authorizer = _authorize(app, access, AuthorizationDecision.ALLOW)
    response = await client.get("/auth/me/membership")
    assert response.status_code == 200
    assert response.json() == {
        "user_id": str(access.principal.user_id),
        "membership_id": str(access.principal.membership_id),
        "tenant_id": str(access.context.tenant_id),
    }
    assert authorizer.calls == [
        (
            access.principal,
            access.context,
            PermissionId(Permission.TENANT_MEMBERSHIPS_READ.value),
        )
    ]


@pytest.mark.asyncio
async def test_missing_authentication_is_unauthorized(
    client: AsyncClient,
) -> None:
    response = await client.get("/auth/me/membership")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_session"


@pytest.mark.asyncio
async def test_denial_prevents_service_execution_and_hides_internals(
    app: FastAPI, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    access = _access()
    _authorize(app, access, AuthorizationDecision.DENY)
    calls: list[bool] = []

    async def forbidden_service(_self: object, _grant: AuthorizationGrant) -> object:
        calls.append(True)
        raise AssertionError("service must not execute")

    monkeypatch.setattr(type(membership_access_service), "current", forbidden_service)
    response = await client.get(
        "/auth/me/membership",
        headers={"X-Role": "admin", "X-Permission": "tenant.memberships.read"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["message"] == "The requested resource is not available."
    assert calls == []
    body = response.text.lower()
    assert all(word not in body for word in ("role", "permission", "database", "sql"))


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ["principal", "context"])
async def test_missing_principal_or_context_denies(
    app: FastAPI, client: AsyncClient, missing: str
) -> None:
    access = _access()
    malformed = TrustedTenantAccess(
        cast(
            AuthenticatedPrincipal,
            None if missing == "principal" else access.principal,
        ),
        cast(TenantContext, None if missing == "context" else access.context),
        access.session,
    )
    _authorize(app, malformed, AuthorizationDecision.DENY)
    assert (await client.get("/auth/me/membership")).status_code == 403


@pytest.mark.asyncio
async def test_permission_removal_or_inactive_role_denies_the_next_request(
    app: FastAPI, client: AsyncClient
) -> None:
    access = _access()
    _authorize(app, access, AuthorizationDecision.ALLOW, AuthorizationDecision.DENY)
    assert (await client.get("/auth/me/membership")).status_code == 200
    denied = await client.get("/auth/me/membership")
    assert denied.status_code == 403


@pytest.mark.asyncio
async def test_membership_idor_and_cross_tenant_selector_are_non_disclosing(
    app: FastAPI, client: AsyncClient
) -> None:
    access = _access()
    _authorize(app, access, AuthorizationDecision.ALLOW, AuthorizationDecision.ALLOW)
    foreign_membership = uuid.uuid7()
    unknown_membership = uuid.uuid7()
    foreign = await client.get(f"/auth/memberships/{foreign_membership}")
    unknown = await client.get(f"/auth/memberships/{unknown_membership}")
    assert foreign.status_code == unknown.status_code == 404
    assert foreign.json()["error"]["message"] == unknown.json()["error"]["message"]
    assert str(foreign_membership) not in foreign.text
    assert str(unknown_membership) not in unknown.text


@pytest.mark.asyncio
async def test_direct_service_call_without_authorization_grant_is_rejected() -> None:
    with pytest.raises(AuthorizationBoundaryRequiredError):
        await MembershipAccessService().current(cast(AuthorizationGrant, None))


def test_routes_can_bind_only_catalog_permissions() -> None:
    with pytest.raises(TypeError):
        require_permission(cast(Permission, PermissionId("tenant.forged.read")))


def test_api_and_services_contain_no_scattered_authorization_decisions() -> None:
    app_root = Path(__file__).resolve().parents[1] / "app"
    files = [*(app_root / "api").rglob("*.py"), *(app_root / "services").rglob("*.py")]
    source = "\n".join(path.read_text(encoding="utf-8") for path in files)
    assert ".authorize(" not in source.replace(
        (app_root / "api" / "authorization_dependencies.py").read_text(encoding="utf-8"), ""
    )
    assert "role_name" not in source and "is_admin" not in source
    dependency_source = (app_root / "api" / "authorization_dependencies.py").read_text(
        encoding="utf-8"
    )
    outside_boundary = "\n".join(
        path.read_text(encoding="utf-8")
        for path in app_root.rglob("*.py")
        if path
        not in {
            app_root / "api" / "authorization_dependencies.py",
            app_root / "authorization" / "contracts.py",
        }
    )
    assert "AuthorizationGrant(" in dependency_source
    assert "AuthorizationGrant(" not in outside_boundary
