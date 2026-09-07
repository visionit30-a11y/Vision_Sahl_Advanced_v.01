"""PostgreSQL schema and privilege proof for password credentials."""

from sqlalchemy import Connection, text


def test_password_credential_contract(app_connection: Connection, migration_role: str) -> None:
    columns = app_connection.execute(
        text("""
        SELECT a.attname, a.attnotnull, format_type(a.atttypid,a.atttypmod)
        FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid
        JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='auth' AND c.relname='password_credentials'
          AND a.attnum>0 AND NOT a.attisdropped ORDER BY a.attnum
    """)
    ).all()
    assert columns == [
        ("user_id", True, "uuid"),
        ("password_hash", True, "text"),
        ("credential_version", True, "integer"),
        ("changed_at", True, "timestamp with time zone"),
    ]
    constraints = set(
        app_connection.execute(
            text("""
        SELECT conname FROM pg_constraint con JOIN pg_class c ON c.oid=con.conrelid
        JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='auth' AND c.relname='password_credentials'
    """)
        ).scalars()
    )
    assert {
        "pk_password_credentials",
        "fk_password_credentials_user_id_users",
        "ck_password_credentials_credential_version_positive",
        "ck_password_credentials_password_hash_argon2id",
    } <= constraints
    owner = app_connection.scalar(
        text("""
        SELECT pg_get_userbyid(c.relowner) FROM pg_class c
        JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='auth' AND c.relname='password_credentials'
    """)
    )
    assert owner == migration_role


def test_no_plaintext_columns_or_rls_contract_change(app_connection: Connection) -> None:
    row = app_connection.execute(
        text("""
        SELECT relrowsecurity, relforcerowsecurity,
          (SELECT count(*) FROM pg_policy WHERE polrelid=c.oid)
        FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='auth' AND c.relname='password_credentials'
    """)
    ).one()
    assert tuple(row) == (False, False, 0)
    names = set(
        app_connection.execute(
            text("""
        SELECT a.attname FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid
        JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='auth' AND c.relname='password_credentials'
          AND a.attnum>0 AND NOT a.attisdropped
    """)
        ).scalars()
    )
    assert names == {"user_id", "password_hash", "credential_version", "changed_at"}
