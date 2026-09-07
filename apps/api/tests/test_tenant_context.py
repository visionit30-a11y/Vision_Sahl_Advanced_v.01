"""Fail-closed identity, context and service-resolution contracts."""

from __future__ import annotations

import inspect
from dataclasses import FrozenInstanceError
from typing import cast
from uuid import UUID, uuid4

import pytest
import structlog
from structlog.testing import capture_logs

from app.api.dependencies import get_tenant_resolver, require_tenant_context
from app.models.tenant import TenantId, new_tenant_id
from app.tenancy import resolution
from app.tenancy.context import (
    InvalidTenantIdError,
    TenantContext,
    TenantContextRequiredError,
    parse_tenant_id,
    require_context,
    validate_tenant_id,
)
from app.tenancy.explicit import ExplicitTenantResolver
from app.tenancy.resolution import NoTenantResolver, TenantResolver

INVALID_IDENTITIES: list[object] = [
    None,
    "not-a-uuid",
    str(new_tenant_id()),
    uuid4(),
    UUID(int=0),
    42,
]


def test_context_keeps_the_typed_identity_immutable() -> None:
    identity = new_tenant_id()
    context = TenantContext(identity)

    assert context.tenant_id is identity
    assert require_context(context) is context
    with pytest.raises(FrozenInstanceError):
        context.tenant_id = new_tenant_id()  # type: ignore[misc]


@pytest.mark.parametrize("invalid", INVALID_IDENTITIES)
def test_invalid_identity_cannot_construct_a_context(invalid: object) -> None:
    with pytest.raises(InvalidTenantIdError):
        TenantContext(cast(TenantId, invalid))


@pytest.mark.parametrize("invalid", INVALID_IDENTITIES)
def test_explicit_resolver_rejects_invalid_identity_at_construction(invalid: object) -> None:
    with pytest.raises(InvalidTenantIdError):
        ExplicitTenantResolver(cast(TenantId, invalid))


def test_text_conversion_is_explicit_and_keeps_the_same_identity() -> None:
    identity = new_tenant_id()
    parsed: TenantId = parse_tenant_id(str(identity))

    assert parsed == identity
    assert validate_tenant_id(parsed) is parsed


@pytest.mark.parametrize("invalid", [None, 42, "", "not-a-uuid", str(uuid4()), str(UUID(int=0))])
def test_invalid_text_has_no_fallback_identity(invalid: object) -> None:
    with pytest.raises(InvalidTenantIdError) as failure:
        parse_tenant_id(cast(str, invalid))

    assert failure.value.code == "internal_error"
    assert failure.value.status_code == 500
    assert failure.value.details is None


@pytest.mark.parametrize("missing", [None, new_tenant_id(), {}])
def test_a_service_cannot_accept_missing_or_unwrapped_context(missing: object) -> None:
    with pytest.raises(TenantContextRequiredError):
        require_context(cast(TenantContext, missing))


def test_the_service_boundary_revalidates_a_corrupted_context() -> None:
    context = TenantContext(new_tenant_id())
    object.__setattr__(context, "tenant_id", "not-a-uuid")

    with pytest.raises(InvalidTenantIdError):
        require_context(context)


def test_explicit_resolution_propagates_identity_through_service_calls() -> None:
    identity = new_tenant_id()
    resolver: TenantResolver = ExplicitTenantResolver(identity)

    def inner_service(context: TenantContext) -> TenantId:
        return require_context(context).tenant_id

    def outer_service(context: TenantContext) -> TenantId:
        return inner_service(require_context(context))

    assert outer_service(resolver.resolve()) is identity


def test_http_default_always_refuses_and_logs_missing_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A fresh lazy logger keeps capture independent of previous cached loggers.
    monkeypatch.setattr(resolution, "logger", structlog.get_logger())
    resolver = get_tenant_resolver()
    assert type(resolver) is NoTenantResolver
    assert set(inspect.signature(NoTenantResolver.resolve).parameters) == {"self"}

    with capture_logs() as logs, pytest.raises(TenantContextRequiredError) as failure:
        resolver.resolve()

    assert failure.value.status_code == 500
    assert failure.value.code == "internal_error"
    assert logs == [{"event": "tenant_context_missing", "log_level": "error"}]


def test_dependency_rejects_an_optional_result_from_an_incorrect_resolver() -> None:
    class IncorrectResolver:
        def resolve(self) -> TenantContext:
            return cast(TenantContext, None)

    with pytest.raises(TenantContextRequiredError):
        require_tenant_context(IncorrectResolver())
