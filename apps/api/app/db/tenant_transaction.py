"""The only runtime session boundary for tenant-scoped service work.

The context is an explicit argument, never reconstructed from logging state or
HTTP inputs. A session cannot autobegin or be reused after the boundary closes.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Result, ScalarResult
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql import Executable
from structlog.contextvars import bound_contextvars

from app.db.session import _engine
from app.tenancy.context import TenantContext, require_context


class TenantTransaction:
    """Data operations only: never expose a session, connection or transaction handle."""

    __slots__ = ("__session",)

    def __init__(self, session: AsyncSession) -> None:
        self.__session = session

    async def execute(
        self, statement: Executable, params: Mapping[str, object] | None = None
    ) -> Result[Any]:
        return await self.__session.execute(statement, params)

    async def scalar(
        self, statement: Executable, params: Mapping[str, object] | None = None
    ) -> Any:
        return await self.__session.scalar(statement, params)

    async def scalars(
        self, statement: Executable, params: Mapping[str, object] | None = None
    ) -> ScalarResult[Any]:
        return await self.__session.scalars(statement, params)


_session_factory = async_sessionmaker(
    _engine,
    expire_on_commit=False,
    autobegin=False,
    close_resets_only=False,
)

_TENANT_CONTEXT_SQL = text("SELECT set_config('app.tenant_id', :tenant_id, true)")


@asynccontextmanager
async def tenant_transaction(context: TenantContext) -> AsyncIterator[TenantTransaction]:
    """Validate, begin, bind, execute and commit or roll back one unit of work.

    Validation precedes session acquisition and SQL. PostgreSQL owns the setting's
    transaction lifetime; no session-level reset or default identity is needed.
    Logging carries the same identity temporarily, but is never a source of trust.
    """
    context = require_context(context)
    tenant_id = str(context.tenant_id)
    with bound_contextvars(tenant_id=tenant_id):
        async with _session_factory() as session, session.begin():
            await session.execute(_TENANT_CONTEXT_SQL, {"tenant_id": tenant_id})
            yield TenantTransaction(session)
