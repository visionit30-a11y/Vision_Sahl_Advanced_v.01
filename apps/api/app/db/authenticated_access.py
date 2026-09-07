"""Database composition for resolving trusted authenticated tenant access."""

from __future__ import annotations

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
    async with _engine.begin() as connection:
        sessions = SessionService(PostgresSessionStore(connection))
        authority = PostgresMembershipAuthority(connection)
        return await TrustedTenantService(sessions, authority).resolve(bearer)
