"""Client-controlled values cannot establish trusted HTTP context in Phase 2A."""

from __future__ import annotations

from typing import Annotated, Any

import pytest
from fastapi import Depends, FastAPI
from httpx import AsyncClient

from app.api.dependencies import get_tenant_resolver, require_tenant_context
from app.core.context import CORRELATION_ID_HEADER
from app.models.tenant import new_tenant_id
from app.tenancy.context import TenantContext


@pytest.mark.parametrize(
    "source",
    ["missing", "body", "query", "header", "x-tenant-id", "membership", "host", "all"],
)
async def test_request_data_never_establishes_tenant_context(
    app: FastAPI, client: AsyncClient, source: str
) -> None:
    calls: list[bool] = []

    # This route exists in the test application only, never in the product router.
    @app.post("/_test/tenant-context")
    def tenant_scoped_route(
        context: Annotated[TenantContext, Depends(require_tenant_context)],
    ) -> dict[str, str]:
        calls.append(True)
        return {"tenant_id": str(context.tenant_id)}

    identity = str(new_tenant_id())
    url = "/_test/tenant-context"
    options: dict[str, Any] = {}
    headers: dict[str, str] = {CORRELATION_ID_HEADER: "tenant-context-request"}
    if source in {"body", "all"}:
        options["json"] = {"tenant_id": identity, "tenant": {"id": identity}}
    if source in {"query", "all"}:
        options["params"] = {"tenant_id": identity, "tenant": identity}
    if source == "membership":
        options["json"] = {"membership_id": identity}
        options["params"] = {"membership_id": identity}
        headers["Cookie"] = f"membership_id={identity}"
    if source in {"header", "all"}:
        headers["Tenant-ID"] = identity
    if source in {"x-tenant-id", "all"}:
        headers["X-Tenant-ID"] = identity
    if source in {"host", "all"}:
        url = f"http://{identity}.testserver/_test/tenant-context"

    response = await client.post(url, headers=headers, **options)

    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "internal_error",
            "message": "A trusted tenant context is required.",
            "correlation_id": "tenant-context-request",
        }
    }
    assert calls == []
    assert identity not in response.text
    assert response.headers[CORRELATION_ID_HEADER] == "tenant-context-request"


def test_the_production_factory_registers_no_tenant_resolver_override(app: FastAPI) -> None:
    assert get_tenant_resolver not in app.dependency_overrides
    assert require_tenant_context not in app.dependency_overrides
    assert "/_test/tenant-context" not in app.openapi()["paths"]
