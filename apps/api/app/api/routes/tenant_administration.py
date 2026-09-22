"""HTTP boundary for tenant-scoped user and access administration."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field

from app.api.authorization_dependencies import require_permission
from app.authorization.contracts import AuthorizationGrant
from app.authorization.permissions import Permission
from app.services.tenant_administration import tenant_administration_service

router = APIRouter(prefix="/tenant-admin", tags=["tenant-administration"])
read_users = require_permission(Permission.TENANT_USERS_READ)
invite_users = require_permission(Permission.TENANT_USERS_INVITE)
manage_users = require_permission(Permission.TENANT_USERS_MANAGE)
read_roles = require_permission(Permission.TENANT_ROLES_READ)
read_audit = require_permission(Permission.TENANT_ACCESS_AUDIT_READ)


class TenantUserResponse(BaseModel):
    membership_id: uuid.UUID
    user_id: uuid.UUID
    email: str
    user_status: str
    membership_status: str
    membership_version: int
    joined_at: datetime | None
    left_at: datetime | None
    role_ids: tuple[uuid.UUID, ...]
    role_keys: tuple[str, ...]
    role_titles: tuple[str, ...]


class InviteUserRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    email: str = Field(min_length=3, max_length=254, repr=False)


class InviteUserResponse(BaseModel):
    membership_id: uuid.UUID


class MembershipStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["active", "suspended"]
    expected_version: int = Field(gt=0)


class MembershipStatusResponse(BaseModel):
    status: str
    version: int


class TenantRoleResponse(BaseModel):
    role_id: uuid.UUID
    role_key: str
    display_name: str
    status: str
    kind: str
    version: int
    permissions: tuple[str, ...]


class AccessEventResponse(BaseModel):
    id: uuid.UUID
    event_type: str
    actor_membership_id: uuid.UUID | None
    target_membership_id: uuid.UUID
    role_id: uuid.UUID | None
    created_at: datetime


@router.get("/users", response_model=list[TenantUserResponse])
async def users(
    grant: Annotated[AuthorizationGrant, Depends(read_users)],
) -> list[TenantUserResponse]:
    return [
        TenantUserResponse.model_validate(item, from_attributes=True)
        for item in await tenant_administration_service.list_users(grant)
    ]


@router.post("/users/invitations", response_model=InviteUserResponse, status_code=201)
async def invite(
    payload: InviteUserRequest,
    grant: Annotated[AuthorizationGrant, Depends(invite_users)],
) -> InviteUserResponse:
    return InviteUserResponse(
        membership_id=await tenant_administration_service.invite(grant, payload.email)
    )


@router.patch("/memberships/{membership_id}/status", response_model=MembershipStatusResponse)
async def membership_status(
    membership_id: uuid.UUID,
    payload: MembershipStatusRequest,
    grant: Annotated[AuthorizationGrant, Depends(manage_users)],
) -> MembershipStatusResponse:
    status, version = await tenant_administration_service.set_membership_status(
        grant,
        membership_id,
        status=payload.status,
        expected_version=payload.expected_version,
    )
    return MembershipStatusResponse(status=status, version=version)


@router.get("/roles", response_model=list[TenantRoleResponse])
async def roles(
    grant: Annotated[AuthorizationGrant, Depends(read_roles)],
) -> list[TenantRoleResponse]:
    return [
        TenantRoleResponse.model_validate(item, from_attributes=True)
        for item in await tenant_administration_service.list_roles(grant)
    ]


@router.get("/access-events", response_model=list[AccessEventResponse])
async def access_events(
    grant: Annotated[AuthorizationGrant, Depends(read_audit)],
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[AccessEventResponse]:
    return [
        AccessEventResponse.model_validate(item, from_attributes=True)
        for item in await tenant_administration_service.access_history(grant, limit=limit)
    ]
