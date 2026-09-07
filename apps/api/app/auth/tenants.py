"""Trusted session-to-membership resolution and safe tenant switching."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.auth.sessions import IssuedSession, SessionRecord, SessionService, token_digest
from app.core.errors import AppError
from app.models.tenant import TenantId
from app.tenancy.context import TenantContext


class TenantAccessDeniedError(AppError):
    code = "tenant_access_denied"
    status_code = 403
    message = "The requested tenant context is not available."


class SessionRejectedError(AppError):
    code = "invalid_session"
    status_code = 401
    message = "Authentication is required."


@dataclass(frozen=True, slots=True)
class MembershipProof:
    tenant_id: uuid.UUID
    membership_id: uuid.UUID
    membership_version: int


@dataclass(frozen=True, slots=True)
class AuthenticatedPrincipal:
    user_id: uuid.UUID
    session_id: uuid.UUID
    membership_id: uuid.UUID
    membership_version: int


@dataclass(frozen=True, slots=True)
class TrustedTenantAccess:
    principal: AuthenticatedPrincipal
    context: TenantContext
    session: SessionRecord


@dataclass(frozen=True, slots=True)
class SwitchedTenantAccess:
    access: TrustedTenantAccess
    issued_session: IssuedSession


class MembershipAuthority(Protocol):
    async def resolve_active(
        self,
        *,
        user_id: uuid.UUID,
        membership_id: uuid.UUID,
        membership_version: int | None,
        security_version: int,
    ) -> MembershipProof | None: ...


class PostgresMembershipAuthority:
    """Call only the fixed SECURITY DEFINER signature; no direct catalogue SELECT."""

    def __init__(self, connection: AsyncConnection) -> None:
        self.connection = connection

    async def resolve_active(
        self,
        *,
        user_id: uuid.UUID,
        membership_id: uuid.UUID,
        membership_version: int | None,
        security_version: int,
    ) -> MembershipProof | None:
        row = (
            await self.connection.execute(
                text("""
            SELECT tenant_id,membership_id,membership_version
            FROM auth.resolve_active_membership(
              :user_id, :membership_id, :membership_version, :security_version
            )
        """),
                {
                    "user_id": user_id,
                    "membership_id": membership_id,
                    "membership_version": membership_version,
                    "security_version": security_version,
                },
            )
        ).one_or_none()
        return (
            None
            if row is None
            else MembershipProof(row.tenant_id, row.membership_id, row.membership_version)
        )


class TrustedTenantService:
    def __init__(self, sessions: SessionService, authority: MembershipAuthority) -> None:
        self.sessions = sessions
        self.authority = authority

    async def _session(self, bearer: str) -> SessionRecord:
        now = await self.sessions.store.current_time()
        record = await self.sessions.store.get_by_digest(token_digest(bearer))
        if record is None or not record.is_valid(now=now, security_version=record.security_version):
            raise SessionRejectedError()
        return record

    @staticmethod
    def _access(record: SessionRecord, proof: MembershipProof) -> TrustedTenantAccess:
        principal = AuthenticatedPrincipal(
            record.user_id, record.id, proof.membership_id, proof.membership_version
        )
        return TrustedTenantAccess(principal, TenantContext(TenantId(proof.tenant_id)), record)

    async def resolve(self, bearer: str) -> TrustedTenantAccess:
        record = await self._session(bearer)
        if record.selected_membership_id is None or record.selected_membership_version is None:
            raise TenantAccessDeniedError()
        proof = await self.authority.resolve_active(
            user_id=record.user_id,
            membership_id=record.selected_membership_id,
            membership_version=record.selected_membership_version,
            security_version=record.security_version,
        )
        if proof is None:
            raise TenantAccessDeniedError()
        return self._access(record, proof)

    async def switch(self, bearer: str, membership_selector: uuid.UUID) -> SwitchedTenantAccess:
        record = await self._session(bearer)
        proof = await self.authority.resolve_active(
            user_id=record.user_id,
            membership_id=membership_selector,
            membership_version=None,
            security_version=record.security_version,
        )
        if proof is None:
            raise TenantAccessDeniedError()
        issued = await self.sessions.rotate_to_membership(
            bearer, record.security_version, proof.membership_id, proof.membership_version
        )
        if issued is None:
            raise SessionRejectedError()
        return SwitchedTenantAccess(self._access(issued.record, proof), issued)
