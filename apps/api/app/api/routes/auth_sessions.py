"""Real session transport for the established frontend authentication client."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict

from app.api.auth_dependencies import session_bearer_from_cookie
from app.api.authorization_dependencies import get_security_denial_auditor
from app.auth.http import (
    CsrfRejectedError,
    clear_session_cookie,
    expose_csrf_token,
    set_session_cookie,
    validate_csrf_bootstrap_origin,
)
from app.core.config import get_settings
from app.db.auth_http import SessionIdentity, SessionMembership, auth_http_service

router = APIRouter(prefix="/auth", tags=["authentication"])
SessionBearer = Annotated[str, Depends(session_bearer_from_cookie)]


class SessionIdentityResponse(BaseModel):
    id: uuid.UUID
    email: str
    selectedMembershipId: uuid.UUID | None

    @classmethod
    def from_identity(cls, identity: SessionIdentity) -> SessionIdentityResponse:
        return cls(
            id=identity.id,
            email=identity.email,
            selectedMembershipId=identity.selected_membership_id,
        )


class SessionMembershipResponse(BaseModel):
    id: uuid.UUID
    tenantId: uuid.UUID
    tenantName: str

    @classmethod
    def from_membership(cls, membership: SessionMembership) -> SessionMembershipResponse:
        return cls(
            id=membership.id,
            tenantId=membership.tenant_id,
            tenantName=membership.tenant_name,
        )


class TenantSwitchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    membership_id: uuid.UUID


@router.get("/me", response_model=SessionIdentityResponse)
async def me(bearer: SessionBearer) -> SessionIdentityResponse:
    return SessionIdentityResponse.from_identity(await auth_http_service.me(bearer))


@router.get("/memberships", response_model=list[SessionMembershipResponse])
async def memberships(bearer: SessionBearer) -> list[SessionMembershipResponse]:
    return [
        SessionMembershipResponse.from_membership(item)
        for item in await auth_http_service.memberships(bearer)
    ]


@router.get("/csrf", status_code=204)
async def csrf(request: Request, response: Response, bearer: SessionBearer) -> None:
    settings = get_settings()
    try:
        validate_csrf_bootstrap_origin(
            request,
            set(settings.auth_origin_list),
            local_http_origin=settings.auth_local_http_origin,
        )
    except CsrfRejectedError as error:
        await get_security_denial_auditor().request_denied(error, request, origin_failure=True)
        raise

    expose_csrf_token(response, await auth_http_service.bootstrap_csrf(bearer, request))


@router.post("/tenant/switch", status_code=204)
async def switch_tenant(
    payload: TenantSwitchRequest, request: Request, response: Response, bearer: SessionBearer
) -> None:
    issued = await auth_http_service.switch(bearer, payload.membership_id, request)
    set_session_cookie(response, issued.secrets.bearer)
    expose_csrf_token(response, issued.secrets.csrf_token)


@router.post("/logout", status_code=204)
async def logout(request: Request, response: Response, bearer: SessionBearer) -> None:
    await auth_http_service.logout(bearer, request)
    clear_session_cookie(response)
