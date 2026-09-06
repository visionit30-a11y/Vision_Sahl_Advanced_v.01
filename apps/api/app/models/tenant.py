"""The tenant: the platform's unit of ownership.

Two identifiers, and the difference between them is a security boundary.

``id`` is a UUIDv7 and it is the only identity anything trusts. Every isolation
policy written from here on compares against it and against nothing else.

``slug`` is for people and for URLs. It is never a reference of trust, never
compared against by a policy, and never resolved into a tenant on the strength
of a request alone. See ADR-0014.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from enum import StrEnum
from typing import NewType

from sqlalchemy import CheckConstraint, DateTime, Enum, String, func, text
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

TenantId = NewType("TenantId", uuid.UUID)
"""A tenant's identity. Wrapped so a bare UUID cannot be passed where one belongs."""


def new_tenant_id() -> TenantId:
    """Generate a tenant identity.

    UUIDv7 from the standard library, available since Python 3.14 - the project
    baseline. Time ordered, so the index stays local as tenant owned tables
    grow, and unguessable, so identities cannot be enumerated. There is
    deliberately no fallback to uuid4 and no third party generator: a silent
    change of version here would change the index behaviour of every tenant
    owned table without anyone deciding to.
    """
    return TenantId(uuid.uuid7())


SLUG_MIN_LENGTH = 3
SLUG_MAX_LENGTH = 63
"""63 is the DNS label limit, so a slug stays valid if it ever becomes a subdomain."""

SLUG_PATTERN = r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$"
"""Lowercase ASCII, letters digits and hyphen, starting and ending alphanumeric."""

SLUG_FORBIDDEN_SEQUENCE = "--"

_SLUG_REGEX = re.compile(SLUG_PATTERN)


class InvalidTenantSlugError(ValueError):
    """Raised when a slug does not meet the contract in ADR-0014."""


def validate_tenant_slug(slug: str) -> str:
    """Return the slug if it meets the contract, or say exactly what is wrong.

    The same three rules are enforced by the CHECK constraint in migration
    0002, and a test compares that constraint's text against the constants
    above so the two cannot drift apart.
    """
    if not SLUG_MIN_LENGTH <= len(slug) <= SLUG_MAX_LENGTH:
        raise InvalidTenantSlugError(
            f"A slug is between {SLUG_MIN_LENGTH} and {SLUG_MAX_LENGTH} characters; "
            f"this one is {len(slug)}."
        )
    if not _SLUG_REGEX.fullmatch(slug):
        raise InvalidTenantSlugError(
            "A slug uses lowercase letters, digits and hyphens, and starts and ends "
            "with a letter or a digit."
        )
    if SLUG_FORBIDDEN_SEQUENCE in slug:
        raise InvalidTenantSlugError("A slug may not contain two hyphens in a row.")
    return slug


class TenantStatus(StrEnum):
    """Where a tenant is in its life.

    The database permits these values and nothing else. Which move is allowed
    from which is domain logic below, not a trigger: a business rule belongs
    where it is read, tested and reviewed with the rest of the logic, and
    changing it should not require a migration (ADR-0014).
    """

    PENDING = "pending"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    ARCHIVED = "archived"


ALLOWED_STATUS_TRANSITIONS: dict[TenantStatus, frozenset[TenantStatus]] = {
    TenantStatus.PENDING: frozenset({TenantStatus.ACTIVE, TenantStatus.ARCHIVED}),
    TenantStatus.ACTIVE: frozenset({TenantStatus.SUSPENDED, TenantStatus.ARCHIVED}),
    TenantStatus.SUSPENDED: frozenset({TenantStatus.ACTIVE, TenantStatus.ARCHIVED}),
    TenantStatus.ARCHIVED: frozenset(),
}
"""Archived is final. Suspension is reversible; archival is not."""


class InvalidTenantStatusTransitionError(ValueError):
    """Raised when a status change is not one the lifecycle allows."""


def can_transition(current: TenantStatus, target: TenantStatus) -> bool:
    """Whether the lifecycle allows this move. Staying put is not a move."""
    return target in ALLOWED_STATUS_TRANSITIONS[current]


def assert_transition_allowed(current: TenantStatus, target: TenantStatus) -> None:
    """Raise unless the lifecycle allows this move."""
    if not can_transition(current, target):
        raise InvalidTenantStatusTransitionError(
            f"A tenant cannot move from {current.value} to {target.value}."
        )


class Tenant(Base):
    """A non profit organisation on the platform.

    A platform table, declared as such rather than by omission (FR-MT-07): it is
    not tenant owned and the tenant isolation policy is not what governs it.
    """

    __tablename__ = "tenants"
    __table_args__ = (
        CheckConstraint(
            f"char_length(slug) BETWEEN {SLUG_MIN_LENGTH} AND {SLUG_MAX_LENGTH} "
            f"AND slug ~ '{SLUG_PATTERN}' "
            f"AND slug !~ '{SLUG_FORBIDDEN_SEQUENCE}'",
            name="slug_shape",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, default=new_tenant_id
    )
    slug: Mapped[str] = mapped_column(String(SLUG_MAX_LENGTH), unique=True, nullable=False)
    name_ar: Mapped[str] = mapped_column(String(200), nullable=False)
    name_en: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[TenantStatus] = mapped_column(
        Enum(
            TenantStatus,
            name="tenant_status",
            values_callable=lambda enum: [member.value for member in enum],
        ),
        nullable=False,
        server_default=text(f"'{TenantStatus.PENDING.value}'::tenant_status"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        """Identity and slug only: a tenant's names are its own, not log material."""
        return f"<Tenant id={self.id} slug={self.slug!r} status={self.status.value}>"
