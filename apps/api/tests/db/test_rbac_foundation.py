"""Live PostgreSQL contracts for the tenant-owned RBAC foundation."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from sqlalchemy import Connection, Engine, create_engine, delete, select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from app.authorization.permissions import Permission
from app.core.config import Settings
from app.models.authorization import Role

RBAC_TABLES = ("roles", "role_permissions", "membership_roles")


@dataclass(frozen=True)
class RbacFixture:
    tenant_a: uuid.UUID
    tenant_b: uuid.UUID
    membership_a: uuid.UUID
    membership_b: uuid.UUID
    role_a: uuid.UUID
    role_b: uuid.UUID


def _set_tenant(connection: Connection, tenant_id: uuid.UUID) -> None:
    connection.execute(
        text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
        {"tenant_id": str(tenant_id)},
    )


@pytest.fixture
def rbac_fixture(
    settings: Settings, application_engine: Engine, migration_role: str
) -> Iterator[RbacFixture]:
    values = [uuid.uuid7() for _ in range(8)]
    tenant_a, tenant_b, user_a, user_b, membership_a, membership_b, role_a, role_b = values
    slug_a, slug_b = f"rbac-{tenant_a.hex[-12:]}", f"rbac-{tenant_b.hex[-12:]}"
    email_a, email_b = f"{slug_a}@example.test", f"{slug_b}@example.test"
    migration_engine = create_engine(settings.required_migration_database_url, poolclass=NullPool)
    with migration_engine.begin() as connection:
        assert connection.scalar(text("SELECT current_user")) == migration_role
        connection.execute(
            text(
                "INSERT INTO public.tenants(id,slug,name_ar,name_en,status) "
                "VALUES (:a,:slug_a,'A','A','active'),"
                "(:b,:slug_b,'B','B','active')"
            ),
            {"a": tenant_a, "b": tenant_b, "slug_a": slug_a, "slug_b": slug_b},
        )
        connection.execute(
            text(
                "INSERT INTO auth.users(id,email,normalized_email,status) "
                "VALUES (:a,:email_a,:email_a,'active'),"
                "(:b,:email_b,:email_b,'active')"
            ),
            {"a": user_a, "b": user_b, "email_a": email_a, "email_b": email_b},
        )
        connection.execute(
            text(
                "INSERT INTO auth.tenant_memberships"
                "(id,user_id,tenant_id,status,joined_at) "
                "VALUES (:ma,:ua,:ta,'active',now()),(:mb,:ub,:tb,'active',now())"
            ),
            {
                "ma": membership_a,
                "ua": user_a,
                "ta": tenant_a,
                "mb": membership_b,
                "ub": user_b,
                "tb": tenant_b,
            },
        )
    with application_engine.begin() as connection:
        _set_tenant(connection, tenant_a)
        connection.execute(
            text(
                "INSERT INTO auth.roles(id,tenant_id,key,display_name) "
                "VALUES (:r,:t,'reader','Reader')"
            ),
            {"r": role_a, "t": tenant_a},
        )
    with application_engine.begin() as connection:
        _set_tenant(connection, tenant_b)
        connection.execute(
            text(
                "INSERT INTO auth.roles(id,tenant_id,key,display_name) "
                "VALUES (:r,:t,'reader','Reader')"
            ),
            {"r": role_b, "t": tenant_b},
        )
    state = RbacFixture(tenant_a, tenant_b, membership_a, membership_b, role_a, role_b)
    try:
        yield state
    finally:
        for tenant in (tenant_a, tenant_b):
            with application_engine.begin() as connection:
                _set_tenant(connection, tenant)
                for table in ("membership_roles", "role_permissions", "roles"):
                    connection.execute(text(f"DELETE FROM auth.{table}"))
        with migration_engine.begin() as connection:
            connection.execute(
                text("DELETE FROM auth.tenant_memberships WHERE id IN (:a,:b)"),
                {"a": membership_a, "b": membership_b},
            )
            connection.execute(
                text("DELETE FROM auth.users WHERE id IN (:a,:b)"), {"a": user_a, "b": user_b}
            )
            connection.execute(
                text("DELETE FROM public.tenants WHERE id IN (:a,:b)"),
                {"a": tenant_a, "b": tenant_b},
            )
        migration_engine.dispose()


def test_rbac_tables_have_exact_rls_owner_and_grants(
    app_connection: Connection, migration_role: str, application_role: str
) -> None:
    for table in RBAC_TABLES:
        metadata = app_connection.execute(
            text(
                "SELECT pg_get_userbyid(relowner) owner,relrowsecurity,"
                "relforcerowsecurity FROM pg_class "
                "WHERE oid=CAST(:table AS regclass)"
            ),
            {"table": f"auth.{table}"},
        ).one()
        assert (metadata.owner, metadata.relrowsecurity, metadata.relforcerowsecurity) == (
            migration_role,
            True,
            True,
        )
        policy = app_connection.execute(
            text(
                "SELECT polcmd,polpermissive,polroles,"
                "pg_get_expr(polqual,polrelid) using_expr,"
                "pg_get_expr(polwithcheck,polrelid) check_expr "
                "FROM pg_policy WHERE polrelid=CAST(:table AS regclass)"
            ),
            {"table": f"auth.{table}"},
        ).one()
        app_oid = app_connection.scalar(
            text("SELECT oid FROM pg_roles WHERE rolname=:role"), {"role": application_role}
        )
        assert (policy.polcmd, policy.polpermissive, list(policy.polroles)) == (
            "*",
            True,
            [app_oid],
        )
        assert "app.current_tenant_id()" in policy.using_expr
        assert "app.current_tenant_id()" in policy.check_expr
        allowed = {
            privilege
            for privilege in (
                "SELECT",
                "INSERT",
                "UPDATE",
                "DELETE",
                "TRUNCATE",
                "REFERENCES",
                "TRIGGER",
                "MAINTAIN",
            )
            if app_connection.scalar(
                text(
                    "SELECT has_table_privilege(current_user,CAST(:table AS regclass),:privilege)"
                ),
                {"table": f"auth.{table}", "privilege": privilege},
            )
        }
        assert allowed == {"SELECT", "INSERT", "UPDATE", "DELETE"}
        assert (
            app_connection.scalar(
                text(
                    "SELECT count(*) FROM information_schema.role_table_grants "
                    "WHERE table_schema='auth' AND table_name=:table "
                    "AND grantee='PUBLIC'"
                ),
                {"table": table},
            )
            == 0
        )


def test_missing_context_has_no_access(
    app_connection: Connection, rbac_fixture: RbacFixture
) -> None:
    assert app_connection.execute(text("SELECT id FROM auth.roles")).all() == []
    with pytest.raises(DBAPIError):
        app_connection.execute(
            text(
                "INSERT INTO auth.roles(id,tenant_id,key,display_name) "
                "VALUES (:id,:tenant,'none','None')"
            ),
            {"id": uuid.uuid7(), "tenant": rbac_fixture.tenant_a},
        )
    app_connection.rollback()


def test_role_requires_an_existing_tenant(app_connection: Connection) -> None:
    unknown_tenant = uuid.uuid7()
    _set_tenant(app_connection, unknown_tenant)
    with pytest.raises(IntegrityError):
        app_connection.execute(
            text(
                "INSERT INTO auth.roles(id,tenant_id,key,display_name) "
                "VALUES (:id,:tenant,'orphan','Orphan')"
            ),
            {"id": uuid.uuid7(), "tenant": unknown_tenant},
        )
    app_connection.rollback()


def test_raw_sql_cross_tenant_crud_is_denied(
    app_connection: Connection, rbac_fixture: RbacFixture
) -> None:
    _set_tenant(app_connection, rbac_fixture.tenant_a)
    assert app_connection.execute(
        text("SELECT id FROM auth.roles ORDER BY id")
    ).scalars().all() == [rbac_fixture.role_a]
    with pytest.raises(DBAPIError):
        app_connection.execute(
            text(
                "INSERT INTO auth.roles(id,tenant_id,key,display_name) "
                "VALUES (:id,:tenant,'foreign','Foreign')"
            ),
            {"id": uuid.uuid7(), "tenant": rbac_fixture.tenant_b},
        )
    app_connection.rollback()
    _set_tenant(app_connection, rbac_fixture.tenant_a)
    with pytest.raises(DBAPIError):
        app_connection.execute(
            text("UPDATE auth.roles SET tenant_id=:b WHERE id=:a"),
            {"a": rbac_fixture.role_a, "b": rbac_fixture.tenant_b},
        )
    app_connection.rollback()
    _set_tenant(app_connection, rbac_fixture.tenant_a)
    assert (
        app_connection.execute(
            text("DELETE FROM auth.roles WHERE id=:id"), {"id": rbac_fixture.role_b}
        ).rowcount
        == 0
    )


def test_orm_cannot_read_another_tenant(
    app_connection: Connection, rbac_fixture: RbacFixture
) -> None:
    with Session(bind=app_connection) as session:
        _set_tenant(app_connection, rbac_fixture.tenant_a)
        roles = session.scalars(select(Role)).all()
        assert [role.id for role in roles] == [rbac_fixture.role_a]
        assert (
            session.execute(
                update(Role)
                .where(Role.id == rbac_fixture.role_b)
                .values(display_name="Compromised")
            ).rowcount
            == 0
        )
        assert session.execute(delete(Role).where(Role.id == rbac_fixture.role_b)).rowcount == 0


def test_orm_cannot_write_another_tenant(
    app_connection: Connection, rbac_fixture: RbacFixture
) -> None:
    with Session(bind=app_connection) as session:
        _set_tenant(app_connection, rbac_fixture.tenant_a)
        session.add(
            Role(
                id=uuid.uuid7(),
                tenant_id=rbac_fixture.tenant_b,
                key="foreign",
                display_name="Foreign",
            )
        )
        with pytest.raises(DBAPIError):
            session.flush()
        session.rollback()


def test_composite_fks_reject_cross_tenant_links(
    app_connection: Connection, rbac_fixture: RbacFixture
) -> None:
    _set_tenant(app_connection, rbac_fixture.tenant_a)
    with pytest.raises(IntegrityError):
        app_connection.execute(
            text(
                "INSERT INTO auth.role_permissions(tenant_id,role_id,permission_id) "
                "VALUES (:tenant,:role,:permission)"
            ),
            {
                "tenant": rbac_fixture.tenant_a,
                "role": rbac_fixture.role_b,
                "permission": Permission.TENANT_ROLES_READ.value,
            },
        )
    app_connection.rollback()
    _set_tenant(app_connection, rbac_fixture.tenant_a)
    with pytest.raises(IntegrityError):
        app_connection.execute(
            text(
                "INSERT INTO auth.membership_roles(tenant_id,membership_id,role_id) "
                "VALUES (:tenant,:membership,:role)"
            ),
            {
                "tenant": rbac_fixture.tenant_a,
                "membership": rbac_fixture.membership_b,
                "role": rbac_fixture.role_a,
            },
        )
    app_connection.rollback()


def test_database_rejects_invalid_permission_id(
    app_connection: Connection, rbac_fixture: RbacFixture
) -> None:
    _set_tenant(app_connection, rbac_fixture.tenant_a)
    with pytest.raises(IntegrityError):
        app_connection.execute(
            text(
                "INSERT INTO auth.role_permissions(tenant_id,role_id,permission_id) "
                "VALUES (:tenant,:role,'tenant.roles.*')"
            ),
            {"tenant": rbac_fixture.tenant_a, "role": rbac_fixture.role_a},
        )
    app_connection.rollback()


def test_duplicate_role_permission_is_rejected(
    app_connection: Connection, rbac_fixture: RbacFixture
) -> None:
    _set_tenant(app_connection, rbac_fixture.tenant_a)
    statement = text(
        "INSERT INTO auth.role_permissions(tenant_id,role_id,permission_id) "
        "VALUES (:tenant,:role,:permission)"
    )
    parameters = {
        "tenant": rbac_fixture.tenant_a,
        "role": rbac_fixture.role_a,
        "permission": Permission.TENANT_ROLES_READ.value,
    }
    app_connection.execute(statement, parameters)
    with pytest.raises(IntegrityError):
        app_connection.execute(statement, parameters)
    app_connection.rollback()
