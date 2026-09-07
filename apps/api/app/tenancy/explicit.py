"""Programmatic resolution for services and tests, excluded from HTTP wiring."""

from __future__ import annotations

from dataclasses import dataclass

from app.models.tenant import TenantId
from app.tenancy.context import TenantContext, validate_tenant_id


@dataclass(frozen=True, slots=True)
class ExplicitTenantResolver:
    """Accept an already typed identity from an explicit non-HTTP caller."""

    tenant_id: TenantId

    def __post_init__(self) -> None:
        validate_tenant_id(self.tenant_id)

    def resolve(self) -> TenantContext:
        return TenantContext(self.tenant_id)
