"""HTTP boundary for reusable workflow requests and approval tasks."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.api.authorization_dependencies import (
    get_authorization_service,
    require_authenticated_access,
    require_permission,
)
from app.auth.tenants import TrustedTenantAccess
from app.authorization.contracts import AuthorizationGrant
from app.authorization.permissions import Permission, PermissionId
from app.authorization.service import AuthorizationService
from app.db.tenant_transaction import tenant_transaction
from app.workflow.contracts import (
    ApprovalTaskRecord,
    WorkflowCreate,
    WorkflowDecision,
    WorkflowEventRecord,
    WorkflowRecord,
    WorkflowUpdate,
)
from app.workflow.service import workflow_service

router = APIRouter(prefix="/workflows", tags=["workflows"])
create_grant = require_permission(Permission.TENANT_WORKFLOW_REQUESTS_CREATE)
read_grant = require_permission(Permission.TENANT_WORKFLOW_REQUESTS_READ)
decide_grant = require_permission(Permission.TENANT_WORKFLOW_APPROVALS_DECIDE)


class VersionRequest(BaseModel):
    expected_version: int = Field(gt=0)


class DecisionRequest(VersionRequest):
    decision: WorkflowDecision
    note: str | None = Field(default=None, max_length=1000)


class ApproverResponse(BaseModel):
    membership_id: uuid.UUID
    display_name: str


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


@router.get("/permissions", response_model=list[Permission])
async def permissions(
    response: Response,
    access: Annotated[TrustedTenantAccess, Depends(require_authenticated_access)],
    authorizer: Annotated[AuthorizationService, Depends(get_authorization_service)],
) -> list[Permission]:
    _no_store(response)
    candidates = (
        Permission.TENANT_WORKFLOW_REQUESTS_CREATE,
        Permission.TENANT_WORKFLOW_REQUESTS_READ,
        Permission.TENANT_WORKFLOW_APPROVALS_DECIDE,
    )
    allowed = await authorizer.allowed_permissions(
        access.principal,
        access.context,
        tuple(PermissionId(permission.value) for permission in candidates),
    )
    return [permission for permission in candidates if PermissionId(permission.value) in allowed]


@router.get("/approvers", response_model=list[ApproverResponse])
async def approvers(
    response: Response, grant: Annotated[AuthorizationGrant, Depends(create_grant)]
) -> list[ApproverResponse]:
    _no_store(response)
    async with tenant_transaction(grant.tenant_context) as tx:
        rows = (
            await tx.execute(
                text(
                    "SELECT membership_id,display_name FROM auth.workflow_approvers() "
                    "WHERE membership_id<>:self"
                ),
                {"self": grant.principal.membership_id},
            )
        ).all()
    return [ApproverResponse.model_validate(row._mapping) for row in rows]


@router.post("/requests", response_model=WorkflowRecord, status_code=201)
async def create_request(
    payload: WorkflowCreate,
    response: Response,
    grant: Annotated[AuthorizationGrant, Depends(create_grant)],
) -> WorkflowRecord:
    _no_store(response)
    return await workflow_service.create(grant, payload)


@router.put("/requests/{request_id}", response_model=WorkflowRecord)
async def update_request(
    request_id: uuid.UUID,
    payload: WorkflowUpdate,
    response: Response,
    grant: Annotated[AuthorizationGrant, Depends(create_grant)],
) -> WorkflowRecord:
    _no_store(response)
    return await workflow_service.update(grant, request_id, payload)


@router.post("/requests/{request_id}/submit", response_model=WorkflowRecord)
async def submit_request(
    request_id: uuid.UUID,
    payload: VersionRequest,
    response: Response,
    grant: Annotated[AuthorizationGrant, Depends(create_grant)],
) -> WorkflowRecord:
    _no_store(response)
    return await workflow_service.submit(grant, request_id, payload.expected_version)


@router.get("/requests", response_model=list[WorkflowRecord])
async def list_requests(
    response: Response, grant: Annotated[AuthorizationGrant, Depends(read_grant)]
) -> list[WorkflowRecord]:
    _no_store(response)
    return await workflow_service.list_requests(grant)


@router.get("/requests/{request_id}", response_model=WorkflowRecord)
async def get_request(
    request_id: uuid.UUID,
    response: Response,
    grant: Annotated[AuthorizationGrant, Depends(read_grant)],
) -> WorkflowRecord:
    _no_store(response)
    return await workflow_service.get(grant, request_id)


@router.get("/requests/{request_id}/history", response_model=list[WorkflowEventRecord])
async def history(
    request_id: uuid.UUID,
    response: Response,
    grant: Annotated[AuthorizationGrant, Depends(read_grant)],
) -> list[WorkflowEventRecord]:
    _no_store(response)
    return await workflow_service.history(grant, request_id)


@router.get("/approvals/inbox", response_model=list[ApprovalTaskRecord])
async def inbox(
    response: Response, grant: Annotated[AuthorizationGrant, Depends(decide_grant)]
) -> list[ApprovalTaskRecord]:
    _no_store(response)
    return await workflow_service.inbox(grant)


@router.post("/approvals/{task_id}/decision", response_model=WorkflowRecord)
async def decide(
    task_id: uuid.UUID,
    payload: DecisionRequest,
    response: Response,
    grant: Annotated[AuthorizationGrant, Depends(decide_grant)],
) -> WorkflowRecord:
    _no_store(response)
    return await workflow_service.decide(
        grant, task_id, payload.decision, payload.expected_version, payload.note
    )
