"""ORM models.

Importing this package registers every model on Base.metadata, which is what
Alembic compares the database against. A model that is not reachable from here
is invisible to autogenerate.
"""

from __future__ import annotations

from app.models.tenant import Tenant

__all__ = ["Tenant"]
