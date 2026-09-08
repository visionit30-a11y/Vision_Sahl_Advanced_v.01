"""Real PostgreSQL guards for the digest-bound auth HTTP projection boundary."""

from __future__ import annotations

import secrets
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.pool import NullPool

from app.core.config import Settings


@dataclass(frozen=True)
class ProjectionFixture:
    migration_engine: Engine = field(repr=False)
    users: tuple[uuid.UUID, uuid.UUID]
    tenants: tuple[uuid.UUID, uuid.UUID]
    memberships: tuple[uuid.UUID, uuid.UUID, uuid.UUID]
    sessions: tuple[uuid.UUID, uuid.UUID]
    digests: tuple[bytes, bytes] = field(repr=False)


@pytest.fixture
def projections(settings: Settings) -> Iterator[ProjectionFixture]:
    engine = create_engine(settings.required_migration_database_url, poolclass=NullPool)
    fixture = ProjectionFixture(
        engine,
        (uuid.uuid7(), uuid.uuid7()),
        (uuid.uuid7(), uuid.uuid7()),
        (uuid.uuid7(), uuid.uuid7(), uuid.uuid7()),
        (uuid.uuid7(), uuid.uuid7()),
        (secrets.token_bytes(32), secrets.token_bytes(32)),
    )
    now = datetime.now(UTC)
    try:
        with engine.begin() as db:
            for tenant in fixture.tenants:
                db.execute(
                    text(
                        "INSERT INTO public.tenants(id,slug,name_ar,name_en,status) "
                        "VALUES (:id,:slug,'اختبار','HTTP projection','active')"
                    ),
                    {"id": tenant, "slug": f"http-projection-{tenant.hex}"},
                )
            for user, session, digest in zip(
                fixture.users, fixture.sessions, fixture.digests, strict=True
            ):
                db.execute(
                    text(
                        "INSERT INTO auth.users(id,email,normalized_email,status) "
                        "VALUES (:id,:email,:email,'active')"
                    ),
                    {"id": user, "email": f"http-projection-{user.hex}@example.test"},
                )
                db.execute(
                    text("""
                    INSERT INTO auth.sessions
                    (id,user_id,bearer_digest,csrf_digest,security_version,created_at,
                     authenticated_at,last_seen_at,idle_expires_at,absolute_expires_at)
                    VALUES (:id,:user,:digest,:csrf,1,:now,:now,:now,:idle,:absolute)
                """),
                    {
                        "id": session,
                        "user": user,
                        "digest": digest,
                        "csrf": secrets.token_bytes(32),
                        "now": now,
                        "idle": now + timedelta(minutes=30),
                        "absolute": now + timedelta(hours=8),
                    },
                )
            for membership, user, tenant in (
                (fixture.memberships[0], fixture.users[0], fixture.tenants[0]),
                (fixture.memberships[1], fixture.users[0], fixture.tenants[1]),
                (fixture.memberships[2], fixture.users[1], fixture.tenants[0]),
            ):
                db.execute(
                    text("""
                    INSERT INTO auth.tenant_memberships(id,user_id,tenant_id,status,joined_at)
                    VALUES (:id,:user,:tenant,'active',:now)
                """),
                    {"id": membership, "user": user, "tenant": tenant, "now": now},
                )
        yield fixture
    finally:
        with engine.begin() as db:
            for user in fixture.users:
                db.execute(text("DELETE FROM auth.sessions WHERE user_id=:id"), {"id": user})
                db.execute(
                    text("DELETE FROM auth.tenant_memberships WHERE user_id=:id"), {"id": user}
                )
                db.execute(text("DELETE FROM auth.users WHERE id=:id"), {"id": user})
            for tenant in fixture.tenants:
                db.execute(text("DELETE FROM public.tenants WHERE id=:id"), {"id": tenant})
        engine.dispose()


@pytest.mark.parametrize("function", ["session_identity", "session_memberships"])
def test_projection_function_has_only_approved_security_boundary(
    application_engine: Engine, application_role: str, migration_role: str, function: str
) -> None:
    with application_engine.connect() as db:
        row = db.execute(
            text("""
            SELECT p.prosecdef, p.proisstrict, p.provolatile,
                   pg_get_userbyid(p.proowner) AS owner, p.proconfig,
                   oidvectortypes(p.proargtypes) AS arguments,
                   has_function_privilege(:app,p.oid,'EXECUTE') AS app_execute,
                   has_function_privilege('public',p.oid,'EXECUTE') AS public_execute,
                   pg_get_functiondef(p.oid) AS definition
            FROM pg_proc AS p JOIN pg_namespace AS n ON n.oid=p.pronamespace
            WHERE n.nspname='auth' AND p.proname=:name
        """),
            {"app": application_role, "name": function},
        ).one()
    assert row.prosecdef is True and row.proisstrict is True
    assert row.provolatile == "s"
    assert row.owner == migration_role and row.owner != application_role
    assert row.proconfig == ["search_path=pg_catalog"]
    assert row.arguments == "bytea"
    assert row.app_execute is True and row.public_execute is False
    for forbidden in ("EXECUTE", "SET_CONFIG", "ROW_SECURITY", "BYPASSRLS", "INSERT", "DELETE"):
        assert forbidden not in row.definition.upper()


@pytest.mark.parametrize("table", ["auth.users", "auth.tenant_memberships", "public.tenants"])
def test_projection_adds_no_runtime_table_access(application_engine: Engine, table: str) -> None:
    with application_engine.connect() as db:
        assert (
            db.scalar(
                text(
                    "SELECT has_table_privilege(current_user,:table,'SELECT,INSERT,UPDATE,DELETE')"
                ),
                {"table": table},
            )
            is False
        )


def test_projection_exposes_only_current_session_identity_and_own_active_memberships(
    projections: ProjectionFixture, application_engine: Engine
) -> None:
    with application_engine.connect() as db:
        identity = (
            db.execute(
                text("SELECT * FROM auth.session_identity(:digest)"),
                {"digest": projections.digests[0]},
            )
            .mappings()
            .one()
        )
        memberships = (
            db.execute(
                text("SELECT * FROM auth.session_memberships(:digest)"),
                {"digest": projections.digests[0]},
            )
            .mappings()
            .all()
        )
        other = (
            db.execute(
                text("SELECT * FROM auth.session_memberships(:digest)"),
                {"digest": projections.digests[1]},
            )
            .mappings()
            .all()
        )
    assert set(identity) == {"user_id", "email", "security_version"}
    assert identity["user_id"] == projections.users[0]
    assert identity["security_version"] == 1
    assert {row["membership_id"] for row in memberships} == set(projections.memberships[:2])
    assert {row["tenant_id"] for row in memberships} == set(projections.tenants)
    assert all(
        set(row) == {"membership_id", "tenant_id", "tenant_name", "membership_version"}
        for row in memberships
    )
    assert len(other) == 1 and other[0]["membership_id"] == projections.memberships[2]


@pytest.mark.parametrize("digest", [None, b"", b"unknown", bytes(32)])
def test_unknown_or_malformed_digest_reveals_nothing(
    projections: ProjectionFixture, application_engine: Engine, digest: bytes | None
) -> None:
    with application_engine.connect() as db:
        assert (
            db.execute(
                text("SELECT * FROM auth.session_identity(:digest)"), {"digest": digest}
            ).all()
            == []
        )
        assert (
            db.execute(
                text("SELECT * FROM auth.session_memberships(:digest)"), {"digest": digest}
            ).all()
            == []
        )


@pytest.mark.parametrize(
    "invalid_state",
    [
        "revoked",
        "idle_expired",
        "absolute_expired",
        "pending_user",
        "suspended_user",
        "archived_user",
        "stale_security_version",
        "deleted_session",
    ],
)
def test_invalid_session_or_user_fails_closed(
    projections: ProjectionFixture, application_engine: Engine, invalid_state: str
) -> None:
    statements = {
        "revoked": "UPDATE auth.sessions SET revoked_at=now(),revoked_reason='logout' WHERE id=:id",
        "idle_expired": "UPDATE auth.sessions SET idle_expires_at=now()-interval '1 second' "
        "WHERE id=:id",
        "absolute_expired": "UPDATE auth.sessions SET idle_expires_at=now()-interval '2 seconds', "
        "absolute_expires_at=now()-interval '1 second' WHERE id=:id",
        "pending_user": "UPDATE auth.users SET status='pending' WHERE id=:user",
        "suspended_user": "UPDATE auth.users SET status='suspended' WHERE id=:user",
        "archived_user": "UPDATE auth.users SET status='archived' WHERE id=:user",
        "stale_security_version": "UPDATE auth.users SET security_version=2 WHERE id=:user",
        "deleted_session": "DELETE FROM auth.sessions WHERE id=:id",
    }
    with projections.migration_engine.begin() as db:
        db.execute(
            text(statements[invalid_state]),
            {"id": projections.sessions[0], "user": projections.users[0]},
        )
    with application_engine.connect() as db:
        assert (
            db.execute(
                text("SELECT * FROM auth.session_identity(:digest)"),
                {"digest": projections.digests[0]},
            ).all()
            == []
        )
        assert (
            db.execute(
                text("SELECT * FROM auth.session_memberships(:digest)"),
                {"digest": projections.digests[0]},
            ).all()
            == []
        )


@pytest.mark.parametrize("invalid_state", ["pending", "suspended", "left", "tenant_suspended"])
def test_membership_projection_omits_unavailable_tenants_and_memberships(
    projections: ProjectionFixture, application_engine: Engine, invalid_state: str
) -> None:
    with projections.migration_engine.begin() as db:
        if invalid_state == "tenant_suspended":
            db.execute(
                text("UPDATE public.tenants SET status='suspended' WHERE id=:id"),
                {"id": projections.tenants[0]},
            )
        else:
            db.execute(
                text("""
                UPDATE auth.tenant_memberships SET status=CAST(:status AS auth.membership_status),
                  left_at=CASE WHEN :status='left' THEN now() ELSE NULL END WHERE id=:id
            """),
                {"status": invalid_state, "id": projections.memberships[0]},
            )
    with application_engine.connect() as db:
        ids = (
            db.execute(
                text("SELECT membership_id FROM auth.session_memberships(:digest)"),
                {"digest": projections.digests[0]},
            )
            .scalars()
            .all()
        )
        assert (
            db.execute(
                text("SELECT * FROM auth.session_identity(:digest)"),
                {"digest": projections.digests[0]},
            ).one()
            is not None
        )
    assert ids == [projections.memberships[1]]


def test_projection_reads_new_membership_version_without_creating_context(
    projections: ProjectionFixture, application_engine: Engine
) -> None:
    with projections.migration_engine.begin() as db:
        db.execute(
            text("UPDATE auth.tenant_memberships SET version=2 WHERE id=:id"),
            {"id": projections.memberships[0]},
        )
    with application_engine.connect() as db:
        before = db.scalar(text("SELECT app.current_tenant_id()"))
        rows = (
            db.execute(
                text("SELECT * FROM auth.session_memberships(:digest)"),
                {"digest": projections.digests[0]},
            )
            .mappings()
            .all()
        )
        after = db.scalar(text("SELECT app.current_tenant_id()"))
    assert before is None and after is None
    assert (
        next(row for row in rows if row["membership_id"] == projections.memberships[0])[
            "membership_version"
        ]
        == 2
    )
