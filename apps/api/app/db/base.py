"""Declarative base and constraint naming conventions.

Naming conventions are fixed from day one; without them Alembic generates
auto-named constraints that are painful to alter later.
"""

from __future__ import annotations

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Base class for every ORM model.

    Models are registered on this metadata by importing app.models, which is
    what Alembic compares the database against.
    """

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
