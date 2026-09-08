"""Database composition for resolving trusted authenticated tenant access."""

from __future__ import annotations

from app.audit.request_events import SecurityDenialAuditor, audited_auth_transaction
from app.auth.postgres import PostgresSessionStore
from app.auth.sessions import SessionService
from app.auth.tenants import (
    PostgresMembershipAuthority,
    TrustedTenantAccess,
    TrustedTenantService,
)
from app.db.session import _engine


async def trusted_access_from_bearer(bearer: str) -> TrustedTenantAccess:
    """Resolve authentication in one caller-hidden database transaction."""
    async with audited_auth_transaction(_engine) as (connection, audit):
        sessions = SessionService(PostgresSessionStore(connection))
        authority = PostgresMembershipAuthority(connection)
        trusted = TrustedTenantService(sessions, authority)
        audit.session = await trusted._session(bearer)
        return await trusted.resolve(bearer)


def get_security_denial_auditor() -> SecurityDenialAuditor:
    """Keep engine composition behind the database boundary, outside HTTP."""
    return SecurityDenialAuditor(_engine)
