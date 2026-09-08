"""Live PostgreSQL contracts for validated UI settings persistence."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from sqlalchemy import Connection, create_engine, delete, select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from app.core.config import Settings
from app.models.ui_settings import TenantUiSettings, UserUiSettings


@dataclass(frozen=True)
class UiSettingsFixture:
    tenant_a: uuid.UUID
    tenant_b: uuid.UUID
    user_a: uuid.UUID
    user_b: uuid.UUID


def _set_tenant(connection: Connection, tenant_id: uuid.UUID) -> None:
    connection.execute(
        text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
        {"tenant_id": str(tenant_id)},
    )


@pytest.fixture
def ui_settings_fixture(settings: Settings, migration_role: str) -> Iterator[UiSettingsFixture]:
    tenant_a, tenant_b, user_a, user_b = (uuid.uuid7() for _ in range(4))
    engine = create_engine(settings.required_migration_database_url, poolclass=NullPool)
    with engine.begin() as connection:
        assert connection.scalar(text("SELECT current_user")) == migration_role
        connection.execute(
            text(
                "INSERT INTO public.tenants(id,slug,name_ar,name_en,status) VALUES "
                "(:a,:sa,'A','A','active'),(:b,:sb,'B','B','active')"
            ),
            {
                "a": tenant_a,
                "b": tenant_b,
                "sa": f"ui-{tenant_a.hex[-12:]}",
                "sb": f"ui-{tenant_b.hex[-12:]}",
            },
        )
        connection.execute(
            text(
                "INSERT INTO auth.users(id,email,normalized_email,status) VALUES "
                "(:a,:ea,:ea,'active'),(:b,:eb,:eb,'active')"
            ),
            {
                "a": user_a,
                "b": user_b,
                "ea": f"ui-{user_a.hex[-12:]}@example.test",
                "eb": f"ui-{user_b.hex[-12:]}@example.test",
            },
        )
    try:
        yield UiSettingsFixture(tenant_a, tenant_b, user_a, user_b)
    finally:
        with engine.begin() as connection:
            connection.execute(
                text("DELETE FROM auth.users WHERE id IN (:a,:b)"),
                {"a": user_a, "b": user_b},
            )
            connection.execute(
                text("DELETE FROM public.tenants WHERE id IN (:a,:b)"),
                {"a": tenant_a, "b": tenant_b},
            )
        engine.dispose()


def test_raw_sql_tenant_isolation_and_cross_tenant_writes(
    ui_settings_fixture: UiSettingsFixture, app_connection: Connection
) -> None:
    state = ui_settings_fixture
    _set_tenant(app_connection, state.tenant_a)
    app_connection.execute(
        text("INSERT INTO app.tenant_ui_settings(tenant_id,settings) VALUES (:id,:settings)"),
        {"id": state.tenant_a, "settings": '{"theme":"sand-warm"}'},
    )
    _set_tenant(app_connection, state.tenant_b)
    assert app_connection.execute(text("SELECT tenant_id FROM app.tenant_ui_settings")).all() == []
    assert app_connection.execute(
        text(
            "UPDATE app.tenant_ui_settings SET settings='{}'::jsonb "
            "WHERE tenant_id=:id RETURNING tenant_id"
        ),
        {"id": state.tenant_a},
    ).scalar_one_or_none() is None
    assert app_connection.execute(
        text("DELETE FROM app.tenant_ui_settings WHERE tenant_id=:id RETURNING tenant_id"),
        {"id": state.tenant_a},
    ).scalar_one_or_none() is None
    with pytest.raises(DBAPIError), app_connection.begin_nested():
        app_connection.execute(
            text("INSERT INTO app.tenant_ui_settings(tenant_id) VALUES (:id)"),
            {"id": state.tenant_a},
        )


def test_orm_obeys_rls_for_tenant_and_user_rows(
    ui_settings_fixture: UiSettingsFixture, app_connection: Connection
) -> None:
    state = ui_settings_fixture
    with Session(bind=app_connection) as session:
        _set_tenant(app_connection, state.tenant_a)
        session.add(TenantUiSettings(tenant_id=state.tenant_a, settings={"theme": "teal-calm"}))
        session.add(
            UserUiSettings(
                tenant_id=state.tenant_a,
                user_id=state.user_a,
                settings={"printPreset": "ink-saving"},
            )
        )
        session.flush()
        _set_tenant(app_connection, state.tenant_b)
        assert session.scalars(select(TenantUiSettings)).all() == []
        assert session.scalars(select(UserUiSettings)).all() == []
        assert session.execute(
            update(TenantUiSettings)
            .where(TenantUiSettings.tenant_id == state.tenant_a)
            .values(settings={})
            .returning(TenantUiSettings.tenant_id)
        ).scalar_one_or_none() is None
        assert session.execute(
            delete(UserUiSettings)
            .where(UserUiSettings.user_id == state.user_a)
            .returning(UserUiSettings.user_id)
        ).scalar_one_or_none() is None


def test_database_rejects_unknown_keys_values_and_non_objects(
    ui_settings_fixture: UiSettingsFixture, app_connection: Connection
) -> None:
    _set_tenant(app_connection, ui_settings_fixture.tenant_a)
    for raw in ('{"unknown":"value"}', '{"theme":"unknown"}', '[]', '{"theme":null}'):
        with pytest.raises(DBAPIError), app_connection.begin_nested():
            app_connection.execute(
                text(
                    "INSERT INTO app.tenant_ui_settings(tenant_id,settings) "
                    "VALUES (:tenant,CAST(:settings AS jsonb))"
                ),
                {"tenant": ui_settings_fixture.tenant_a, "settings": raw},
            )


def test_unique_user_scope_and_optimistic_version_conflict(
    ui_settings_fixture: UiSettingsFixture, app_connection: Connection
) -> None:
    state = ui_settings_fixture
    _set_tenant(app_connection, state.tenant_a)
    app_connection.execute(
        text(
            "INSERT INTO app.user_ui_settings(tenant_id,user_id,settings) "
            "VALUES (:tenant,:user,'{}'::jsonb)"
        ),
        {"tenant": state.tenant_a, "user": state.user_a},
    )
    with pytest.raises(IntegrityError), app_connection.begin_nested():
        app_connection.execute(
            text(
                "INSERT INTO app.user_ui_settings(tenant_id,user_id,settings) "
                "VALUES (:tenant,:user,'{}'::jsonb)"
            ),
            {"tenant": state.tenant_a, "user": state.user_a},
        )
    changed = app_connection.execute(
        text(
            "UPDATE app.user_ui_settings SET settings=:settings,version=version+1 "
            "WHERE tenant_id=:tenant AND user_id=:user AND version=1 RETURNING version"
        ),
        {
            "tenant": state.tenant_a,
            "user": state.user_a,
            "settings": '{"theme":"navy-institutional"}',
        },
    ).scalar_one()
    assert changed == 2
    assert app_connection.execute(
        text(
            "UPDATE app.user_ui_settings SET settings='{}'::jsonb,version=version+1 "
            "WHERE tenant_id=:tenant AND user_id=:user AND version=1 RETURNING version"
        ),
        {"tenant": state.tenant_a, "user": state.user_a},
    ).scalar_one_or_none() is None


def test_platform_classification_ownership_and_least_grants(
    app_connection: Connection, application_role: str, migration_role: str
) -> None:
    rows = app_connection.execute(
        text(
            "SELECT c.relname,pg_get_userbyid(c.relowner) owner,c.relrowsecurity,"
            "c.relforcerowsecurity FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname='app' AND c.relname IN "
            "('platform_ui_settings','tenant_ui_settings','user_ui_settings') ORDER BY c.relname"
        )
    ).all()
    assert [(row.relname, row.owner) for row in rows] == [
        ("platform_ui_settings", migration_role),
        ("tenant_ui_settings", migration_role),
        ("user_ui_settings", migration_role),
    ]
    assert (rows[0].relrowsecurity, rows[0].relforcerowsecurity) == (False, False)
    assert [(row.relrowsecurity, row.relforcerowsecurity) for row in rows[1:]] == [
        (True, True),
        (True, True),
    ]
    assert app_connection.scalar(
        text("SELECT has_table_privilege(:role,'app.platform_ui_settings','SELECT')"),
        {"role": application_role},
    )
    for privilege in ("INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"):
        assert not app_connection.scalar(
            text(
                "SELECT has_table_privilege(:role,'app.platform_ui_settings',:privilege)"
            ),
            {"role": application_role, "privilege": privilege},
        )


def test_catalog_discovers_only_tenant_and_user_settings(
    app_connection: Connection,
) -> None:
    discovered = set(
        app_connection.execute(
            text(
                "SELECT n.nspname||'.'||c.relname FROM pg_class c "
                "JOIN pg_namespace n ON n.oid=c.relnamespace "
                "JOIN pg_attribute a ON a.attrelid=c.oid AND a.attname='tenant_id' "
                "WHERE n.nspname='app' AND c.relkind='r'"
            )
        ).scalars()
    )
    assert "app.platform_ui_settings" not in discovered
    assert {"app.tenant_ui_settings", "app.user_ui_settings"} <= discovered
