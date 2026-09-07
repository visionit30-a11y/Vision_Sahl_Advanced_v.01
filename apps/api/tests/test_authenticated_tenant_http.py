"""HTTP boundary: request tenant selectors never become proof."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import Depends, FastAPI
from httpx import AsyncClient

from app.api.dependencies import tenant_context_from_authenticated_access
from app.auth.sessions import SessionRecord
from app.auth.tenants import AuthenticatedPrincipal, TrustedTenantAccess
from app.models.tenant import TenantId
from app.tenancy.context import TenantContext


async def test_forged_request_selectors_cannot_replace_trusted_context(
    app: FastAPI, client: AsyncClient
) -> None:
    now = datetime.now(UTC)
    tenant_id, user_id, membership_id, session_id = (uuid.uuid7() for _ in range(4))
    session = SessionRecord(
        session_id,
        user_id,
        b"b" * 32,
        b"c" * 32,
        1,
        now,
        now,
        now,
        now + timedelta(minutes=30),
        now + timedelta(hours=8),
        selected_membership_id=membership_id,
        selected_membership_version=1,
    )
    access = TrustedTenantAccess(
        AuthenticatedPrincipal(user_id, session_id, membership_id, 1),
        TenantContext(TenantId(tenant_id)),
        session,
    )

    def trusted_context() -> TenantContext:
        return tenant_context_from_authenticated_access(access)

    @app.post("/_test/authenticated-tenant")
    def route(context: TenantContext = Depends(trusted_context)) -> dict[str, str]:
        return {"tenant_id": str(context.tenant_id)}

    forged = str(uuid.uuid7())
    response = await client.post(
        "/_test/authenticated-tenant?tenant_id=" + forged + "&membership_id=" + forged,
        headers={"X-Tenant-ID": forged},
        json={"tenant_id": forged, "membership_id": forged},
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"tenant_id": str(tenant_id)}
    assert forged not in response.text
