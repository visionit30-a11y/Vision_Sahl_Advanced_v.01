"""Blocking post-pytest check for fixture residue and discovered production tables."""

from __future__ import annotations

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from tests.db.rls_catalog import assert_tenant_catalog

ARTIFACTS = text(
    "SELECT 'relation' AS kind, c.relname AS name FROM pg_class c "
    "JOIN pg_namespace n ON n.oid=c.relnamespace "
    "WHERE n.nspname IN ('public','app') AND c.relname LIKE 'tenant_scoped_probe%' "
    "UNION ALL SELECT 'type', t.typname FROM pg_type t "
    "JOIN pg_namespace n ON n.oid=t.typnamespace "
    "WHERE n.nspname IN ('public','app') AND t.typname LIKE '%tenant_scoped_probe%' "
    "UNION ALL SELECT 'function', p.proname FROM pg_proc p "
    "JOIN pg_namespace n ON n.oid=p.pronamespace "
    "WHERE n.nspname IN ('public','app') AND p.proname LIKE '%tenant_scoped_probe%' "
    "UNION ALL SELECT 'policy', policyname FROM pg_policies "
    "WHERE schemaname IN ('public','app') AND "
    "(tablename LIKE 'tenant_scoped_probe%' OR policyname LIKE '%tenant_scoped_probe%')"
)


def main() -> int:
    settings = get_settings()
    application_role = make_url(settings.database_url).username
    migration_role = make_url(settings.required_migration_database_url).username
    assert application_role and migration_role
    engine = create_engine(settings.database_url, poolclass=NullPool)
    try:
        with engine.connect() as connection, connection.begin():
            connection.execute(text("SET TRANSACTION READ ONLY"))
            assert connection.scalar(text("SELECT current_user")) == application_role
            artifacts = connection.execute(ARTIFACTS).all()
            assert artifacts == [], f"Test objects survived teardown: {artifacts!r}"
            discovered = assert_tenant_catalog(
                connection, application_role=application_role, migration_role=migration_role
            )
        print(f"PASS: no probe artifacts; {len(discovered)} production tenant tables verified.")
        return 0
    except Exception as exc:  # noqa: BLE001 - never print connection details from a gate failure
        print(f"FAIL: post-test database guard: {type(exc).__name__}")
        return 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
