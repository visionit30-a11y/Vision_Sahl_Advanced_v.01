"""Authorization-protected views of the caller's existing tenant membership."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.authorization_dependencies import require_permission
from app.authorization.contracts import AuthorizationGrant
from app.authorization.permissions import Permission
from app.services.membership_access_service import membership_access_service

router = APIRouter(prefix="/auth", tags=["authorization"])
membership_read = require_permission(Permission.TENANT_MEMBERSHIPS_READ)


class MembershipResponse(BaseModel):
    user_id: uuid.UUID
    membership_id: uuid.UUID
    tenant_id: uuid.UUID


@router.get("/me/membership", response_model=MembershipResponse)
async def read_current_membership(
    grant: Annotated[AuthorizationGrant, Depends(membership_read)],
) -> MembershipResponse:
    return MembershipResponse.model_validate(
        await membership_access_service.current(grant), from_attributes=True
    )


@router.get("/memberships/{membership_id}", response_model=MembershipResponse)
async def read_membership(
    membership_id: uuid.UUID,
    grant: Annotated[AuthorizationGrant, Depends(membership_read)],
) -> MembershipResponse:
    return MembershipResponse.model_validate(
        await membership_access_service.by_id(grant, membership_id), from_attributes=True
    )
