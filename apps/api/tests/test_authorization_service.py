"""Fail-closed unit contracts for the single authorization service."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import pytest

from app.auth.tenants import AuthenticatedPrincipal
from app.authorization.permissions import Permission, PermissionId
from app.authorization.service import AuthorizationDecision, AuthorizationService
from app.models.tenant import TenantId
from app.tenancy.context import TenantContext


@dataclass
class StubRepository:
    allowed: bool = False
    failure: Exception | None = None
    calls: int = 0

    async def has_permission(
        self,
        principal: AuthenticatedPrincipal,
        tenant_context: TenantContext,
        permission_id: PermissionId,
    ) -> bool:
        self.calls += 1
        if self.failure is not None:
            raise self.failure
        return self.allowed


def _inputs() -> tuple[AuthenticatedPrincipal, TenantContext, PermissionId]:
    tenant_id, user_id, session_id, membership_id = (uuid.uuid7() for _ in range(4))
    return (
        AuthenticatedPrincipal(user_id, session_id, membership_id, 1),
        TenantContext(TenantId(tenant_id)),
        PermissionId(Permission.TENANT_ROLES_READ.value),
    )


@pytest.mark.asyncio
async def test_repository_allow_is_the_only_allow_path() -> None:
    principal, context, permission = _inputs()
    repository = StubRepository(allowed=True)
    assert (
        await AuthorizationService(repository).authorize(principal, context, permission)
        is AuthorizationDecision.ALLOW
    )
    assert repository.calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ["principal", "context"])
async def test_missing_trusted_input_denies_without_database_call(missing: str) -> None:
    principal, context, permission = _inputs()
    repository = StubRepository(allowed=True)
    decision = await AuthorizationService(repository).authorize(
        None if missing == "principal" else principal,
        None if missing == "context" else context,
        permission,
    )
    assert decision is AuthorizationDecision.DENY
    assert repository.calls == 0


@pytest.mark.asyncio
async def test_unknown_but_well_formed_permission_denies_without_database_call() -> None:
    principal, context, _ = _inputs()
    repository = StubRepository(allowed=True)
    decision = await AuthorizationService(repository).authorize(
        principal, context, PermissionId("tenant.unknown.read")
    )
    assert decision is AuthorizationDecision.DENY
    assert repository.calls == 0


@pytest.mark.asyncio
async def test_raw_permission_string_denies_without_database_call() -> None:
    principal, context, _ = _inputs()
    repository = StubRepository(allowed=True)
    decision = await AuthorizationService(repository).authorize(
        principal,
        context,
        Permission.TENANT_ROLES_READ,  # type: ignore[arg-type]
    )
    assert decision is AuthorizationDecision.DENY
    assert repository.calls == 0


@pytest.mark.asyncio
async def test_stale_membership_version_denies_without_database_call() -> None:
    principal, context, permission = _inputs()
    stale = AuthenticatedPrincipal(
        principal.user_id, principal.session_id, principal.membership_id, 0
    )
    repository = StubRepository(allowed=True)
    assert (
        await AuthorizationService(repository).authorize(stale, context, permission)
        is AuthorizationDecision.DENY
    )
    assert repository.calls == 0


@pytest.mark.asyncio
async def test_repository_denial_and_failure_both_fail_closed() -> None:
    principal, context, permission = _inputs()
    assert (
        await AuthorizationService(StubRepository()).authorize(principal, context, permission)
        is AuthorizationDecision.DENY
    )
    assert (
        await AuthorizationService(
            StubRepository(failure=RuntimeError("database unavailable"))
        ).authorize(principal, context, permission)
        is AuthorizationDecision.DENY
    )
