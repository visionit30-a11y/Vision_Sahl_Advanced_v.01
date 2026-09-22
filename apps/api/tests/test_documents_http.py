"""The HTTP document boundary denies before touching storage or a service."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.api.authorization_dependencies import (
    get_authorization_service,
    get_security_denial_auditor,
    require_authenticated_access,
)
from app.auth.tenants import TrustedTenantAccess
from app.authorization.contracts import AuthorizationGrant
from app.authorization.permissions import Permission, PermissionId
from app.authorization.service import AuthorizationDecision
from app.documents.service import workflow_document_service
from app.documents.storage import get_object_storage
from tests.test_http_authorization import StubAuthorizer, _access


def _trusted(app: FastAPI, decision: AuthorizationDecision) -> StubAuthorizer:
    access: TrustedTenantAccess = _access()
    authorizer = StubAuthorizer([decision])

    async def trusted() -> TrustedTenantAccess:
        return access

    app.dependency_overrides[require_authenticated_access] = trusted
    app.dependency_overrides[get_authorization_service] = lambda: authorizer
    app.dependency_overrides[get_security_denial_auditor] = lambda: AsyncMock()
    app.dependency_overrides[get_object_storage] = lambda: object()
    return authorizer


@pytest.mark.asyncio
async def test_missing_session_and_denial_never_touch_document_service(
    app: FastAPI, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    request_id = uuid.uuid7()
    called = False

    async def forbidden(*_args: object) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(workflow_document_service, "list", forbidden)
    response = await client.get(f"/workflows/requests/{request_id}/documents")
    assert response.status_code == 401
    authorizer = _trusted(app, AuthorizationDecision.DENY)
    response = await client.get(f"/workflows/requests/{request_id}/documents")
    assert response.status_code == 403
    assert not called
    assert authorizer.calls[0][2] == PermissionId(Permission.TENANT_WORKFLOW_REQUESTS_READ.value)
    assert "sql" not in response.text.lower()


@pytest.mark.asyncio
async def test_upload_binds_create_grant_and_returns_no_store(
    app: FastAPI, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    request_id = uuid.uuid7()
    authorizer = _trusted(app, AuthorizationDecision.ALLOW)

    async def upload(
        grant: AuthorizationGrant, selected_id: uuid.UUID, file: object, storage: object
    ) -> object:
        assert selected_id == request_id
        assert grant.permission_id == PermissionId(Permission.TENANT_WORKFLOW_REQUESTS_CREATE.value)
        assert storage is not None and file is not None
        return {
            "id": str(uuid.uuid7()),
            "tenant_id": str(grant.tenant_context.tenant_id),
            "request_id": str(request_id),
            "uploaded_by_membership_id": str(grant.principal.membership_id),
            "filename": "memo.pdf",
            "content_type": "application/pdf",
            "byte_size": 8,
            "sha256": "0" * 64,
            "created_at": "2026-01-01T00:00:00Z",
        }

    monkeypatch.setattr(workflow_document_service, "upload", upload)
    response = await client.post(
        f"/workflows/requests/{request_id}/documents",
        files={"upload": ("memo.pdf", b"%PDF-1.7", "application/pdf")},
    )
    assert response.status_code == 201
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json()["request_id"] == str(request_id)
    assert authorizer.calls[0][2] == PermissionId(Permission.TENANT_WORKFLOW_REQUESTS_CREATE.value)
