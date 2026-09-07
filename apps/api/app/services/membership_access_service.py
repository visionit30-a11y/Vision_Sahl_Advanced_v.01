"""Authorized projections of the existing membership resource."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.authorization.contracts import AuthorizationGrant
from app.core.errors import AppError


class AuthorizationBoundaryRequiredError(AppError):
    message = "An authorization grant is required."


class MembershipResourceNotFoundError(AppError):
    code = "not_found"
    status_code = 404
    message = "The requested resource was not found."


@dataclass(frozen=True, slots=True)
class MembershipView:
    user_id: uuid.UUID
    membership_id: uuid.UUID
    tenant_id: uuid.UUID


class MembershipAccessService:
    """Expose only the membership already proven by authentication and authorization."""

    async def current(self, grant: AuthorizationGrant) -> MembershipView:
        if not isinstance(grant, AuthorizationGrant):
            raise AuthorizationBoundaryRequiredError()
        return MembershipView(
            grant.principal.user_id,
            grant.principal.membership_id,
            grant.tenant_context.tenant_id,
        )

    async def by_id(
        self, grant: AuthorizationGrant, membership_selector: uuid.UUID
    ) -> MembershipView:
        if not isinstance(grant, AuthorizationGrant):
            raise AuthorizationBoundaryRequiredError()
        if membership_selector != grant.principal.membership_id:
            raise MembershipResourceNotFoundError()
        return await self.current(grant)


membership_access_service = MembershipAccessService()
