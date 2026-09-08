"""Central HTTP authorization boundary built on trusted Phase 2B access."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, Request

from app.api.auth_dependencies import session_bearer_from_cookie
from app.auth.http import (
    require_session_bearer,
    validate_expected_membership,
    validate_session_csrf,
)
from app.auth.tenants import TrustedTenantAccess
from app.authorization.contracts import AuthorizationGrant
from app.authorization.permissions import Permission, PermissionId
from app.authorization.service import AuthorizationDecision, AuthorizationService
from app.core.config import get_settings
from app.core.errors import AppError
from app.db.authenticated_access import trusted_access_from_bearer


class AuthorizationDeniedError(AppError):
    code = "forbidden"
    status_code = 403
    message = "The requested resource is not available."


async def require_authenticated_access(
    request: Request,
    bearer: Annotated[str, Depends(session_bearer_from_cookie)],
) -> TrustedTenantAccess:
    access = await trusted_access_from_bearer(require_session_bearer(bearer))
    settings = get_settings()
    validate_expected_membership(request, access.principal.membership_id)
    validate_session_csrf(
        request,
        access.session,
        set(settings.auth_origin_list),
        local_http_origin=settings.auth_local_http_origin,
    )
    return access


def get_authorization_service() -> AuthorizationService:
    return AuthorizationService()


PermissionDependency = Callable[..., Awaitable[AuthorizationGrant]]


def require_permission(permission: Permission) -> PermissionDependency:
    """Bind a route to one catalog entry while leaving the decision in the service."""
    if type(permission) is not Permission:
        raise TypeError("Routes must bind permissions from the central Permission catalog.")
    permission_id = PermissionId(permission.value)

    async def dependency(
        access: Annotated[TrustedTenantAccess, Depends(require_authenticated_access)],
        authorizer: Annotated[AuthorizationService, Depends(get_authorization_service)],
    ) -> AuthorizationGrant:
        principal = access.principal if isinstance(access, TrustedTenantAccess) else None
        context = access.context if isinstance(access, TrustedTenantAccess) else None
        decision = await authorizer.authorize(principal, context, permission_id)
        if decision is not AuthorizationDecision.ALLOW or principal is None or context is None:
            raise AuthorizationDeniedError()
        return AuthorizationGrant(principal, context, permission_id)

    return dependency
