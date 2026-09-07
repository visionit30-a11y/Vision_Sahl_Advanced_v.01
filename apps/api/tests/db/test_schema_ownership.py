"""What the database itself says about ownership and privileges.

01-setup.ps1 and .github/ci/setup-database.sql both *perform* the ownership and
grant changes and then report success. Performing a statement without an error
is not the same as reading the result back, and the difference matters here:
a table's owner bypasses row level security unless the table forces it, so the
question "who owns this" has to be answered by the catalogue, not by the script
that meant to set it.

Every assertion below is a read, made as the application role.
"""

from __future__ import annotations

from sqlalchemy import Connection, text


def test_the_connection_is_the_application_role(
    app_connection: Connection, application_role: str
) -> None:
    """The premise of every other test in this package."""
    assert app_connection.execute(text("SELECT current_user")).scalar_one() == application_role


def test_the_public_schema_is_owned_by_the_migration_role(
    app_connection: Connection, migration_role: str, application_role: str
) -> None:
    """Not merely "someone else": the migration role, by name, read from the URL."""
    owner = app_connection.execute(
        text("SELECT pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname = 'public'")
    ).scalar_one()

    assert owner == migration_role
    assert owner != application_role


def test_the_application_role_cannot_create_in_the_public_schema(
    app_connection: Connection,
) -> None:
    """A role that can create objects can create ones it owns, and own its way past RLS."""
    may_create = app_connection.execute(
        text("SELECT has_schema_privilege(current_user, 'public', 'CREATE')")
    ).scalar_one()

    assert may_create is False


def test_create_is_revoked_from_public(app_connection: Connection) -> None:
    """PostgreSQL grants CREATE on public to PUBLIC by default in older versions.

    Leaving it granted would let any role - including the application's - create
    a table it then owns, which is the ownership hole by another route.
    """
    public_may_create = app_connection.execute(
        text("SELECT has_schema_privilege('public', 'public', 'CREATE')")
    ).scalar_one()

    assert public_may_create is False


def test_the_application_role_may_use_the_public_schema(app_connection: Connection) -> None:
    """The other half of the contract: it owns nothing, but it must be able to work."""
    may_use = app_connection.execute(
        text("SELECT has_schema_privilege(current_user, 'public', 'USAGE')")
    ).scalar_one()

    assert may_use is True


def test_the_application_role_owns_no_object(app_connection: Connection) -> None:
    owned = app_connection.execute(
        text(
            "SELECT count(*) FROM pg_class c JOIN pg_roles r ON r.oid = c.relowner "
            "WHERE r.rolname = current_user AND c.relkind IN ('r', 'p', 'v', 'm', 'S')"
        )
    ).scalar_one()

    assert owned == 0


def test_every_table_in_the_public_schema_is_owned_by_the_migration_role(
    app_connection: Connection, migration_role: str
) -> None:
    """Stronger than naming one table: nothing may arrive owned by anyone else.

    This covers alembic_version today and every table a later migration adds,
    without the test needing to know their names.
    """
    foreign = app_connection.execute(
        text(
            "SELECT c.relname, pg_get_userbyid(c.relowner) AS owner "
            "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p') "
            "AND pg_get_userbyid(c.relowner) <> :migration_role "
            "ORDER BY c.relname"
        ),
        {"migration_role": migration_role},
    ).all()

    assert foreign == []


def test_the_application_role_is_neither_superuser_nor_bypassrls(
    app_connection: Connection,
) -> None:
    """The same gate CI runs, asserted from inside the suite as well.

    Either attribute would make every isolation policy written later advisory.
    """
    flags = app_connection.execute(
        text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
    ).one()

    assert flags.rolsuper is False
    assert flags.rolbypassrls is False


def test_the_two_roles_are_not_the_same_role(application_role: str, migration_role: str) -> None:
    """A single role doing both jobs would satisfy several tests above by accident."""
    assert application_role != migration_role
