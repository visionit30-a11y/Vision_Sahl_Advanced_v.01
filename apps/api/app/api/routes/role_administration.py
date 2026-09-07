"""Thin typed HTTP boundary for tenant role administration."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.authorization_dependencies import require_permission
from app.authorization.contracts import AuthorizationGrant
from app.authorization.permissions import Permission
from app.models.authorization import RoleKey
from app.services.role_administration import RoleRecord, role_administration_service

router = APIRouter(prefix="/auth", tags=["authorization"])
manage_roles = require_permission(Permission.TENANT_ROLES_MANAGE)
manage_memberships = require_permission(Permission.TENANT_MEMBERSHIPS_MANAGE)


class RoleCreateRequest(BaseModel):
    key: str = Field(min_length=1, max_length=63)
    display_name: str = Field(min_length=1, max_length=120)


class RoleUpdateRequest(BaseModel):
    expected_version: int = Field(gt=0)
    display_name: str = Field(min_length=1, max_length=120)


class RoleVersionRequest(BaseModel):
    expected_version: int = Field(gt=0)


class PermissionAssignmentRequest(BaseModel):
    permission: Permission


class RoleResponse(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    key: str
    display_name: str
    status: str
    version: int

    @classmethod
    def from_record(cls, record: RoleRecord) -> RoleResponse:
        return cls.model_validate(record, from_attributes=True)


class AssignmentResponse(BaseModel):
    changed: bool


@router.post("/roles", response_model=RoleResponse)
async def create_role(
    payload: RoleCreateRequest,
    grant: Annotated[AuthorizationGrant, Depends(manage_roles)],
) -> RoleResponse:
    record = await role_administration_service.create_role(
        grant, RoleKey(payload.key), payload.display_name
    )
    return RoleResponse.from_record(record)


@router.patch("/roles/{role_id}", response_model=RoleResponse)
async def update_role(
    role_id: uuid.UUID,
    payload: RoleUpdateRequest,
    grant: Annotated[AuthorizationGrant, Depends(manage_roles)],
) -> RoleResponse:
    record = await role_administration_service.update_role(
        grant,
        role_id,
        expected_version=payload.expected_version,
        display_name=payload.display_name,
    )
    return RoleResponse.from_record(record)


@router.post("/roles/{role_id}/disable", response_model=RoleResponse)
async def disable_role(
    role_id: uuid.UUID,
    payload: RoleVersionRequest,
    grant: Annotated[AuthorizationGrant, Depends(manage_roles)],
) -> RoleResponse:
    return RoleResponse.from_record(
        await role_administration_service.disable_role(
            grant, role_id, expected_version=payload.expected_version
        )
    )


@router.put("/roles/{role_id}/permissions", response_model=AssignmentResponse)
async def assign_permission(
    role_id: uuid.UUID,
    payload: PermissionAssignmentRequest,
    grant: Annotated[AuthorizationGrant, Depends(manage_roles)],
) -> AssignmentResponse:
    return AssignmentResponse(
        changed=await role_administration_service.assign_permission(
            grant, role_id, payload.permission
        )
    )


@router.delete("/roles/{role_id}/permissions", response_model=AssignmentResponse)
async def remove_permission(
    role_id: uuid.UUID,
    payload: PermissionAssignmentRequest,
    grant: Annotated[AuthorizationGrant, Depends(manage_roles)],
) -> AssignmentResponse:
    return AssignmentResponse(
        changed=await role_administration_service.remove_permission(
            grant, role_id, payload.permission
        )
    )


@router.put("/memberships/{membership_id}/roles/{role_id}", response_model=AssignmentResponse)
async def assign_role(
    membership_id: uuid.UUID,
    role_id: uuid.UUID,
    grant: Annotated[AuthorizationGrant, Depends(manage_memberships)],
) -> AssignmentResponse:
    return AssignmentResponse(
        changed=await role_administration_service.assign_role(grant, membership_id, role_id)
    )


@router.delete("/memberships/{membership_id}/roles/{role_id}", response_model=AssignmentResponse)
async def remove_role(
    membership_id: uuid.UUID,
    role_id: uuid.UUID,
    grant: Annotated[AuthorizationGrant, Depends(manage_memberships)],
) -> AssignmentResponse:
    return AssignmentResponse(
        changed=await role_administration_service.remove_role(grant, membership_id, role_id)
    )
