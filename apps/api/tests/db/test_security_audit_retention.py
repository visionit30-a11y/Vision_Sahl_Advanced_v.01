"""Real PostgreSQL proofs for the dedicated audit-retention capability.

Every destructive proof fails closed outside the explicitly configured disposable
sahl_ci database. Fixtures own generated records; no live retention run is a test.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from threading import Barrier

import pytest
from sqlalchemy import Connection, Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.pool import NullPool

from app.core.config import Settings

PRUNE = "SELECT * FROM auth.prune_security_events(:batch)"
APPEND_SIGNATURE = (
    "auth.append_security_event(uuid,text,text,text,uuid,uuid,uuid,bytea,"
    "uuid,uuid,uuid,text,text,smallint,bigint)"
)
FORGE = (
    "SELECT auth.append_security_event(:id,'security_events_pruned','success',"
    "'retention_expired',NULL,NULL,NULL,NULL,:correlation,NULL,NULL,NULL,NULL,NULL,1)"
)


@dataclass
class RetentionFixture:
    owner: Engine = field(repr=False)
    maintenance: Engine = field(repr=False)
    runtime: Engine = field(repr=False)
    initial_ids: set[uuid.UUID] = field(repr=False)
    ids: list[uuid.UUID] = field(default_factory=list)

    def seed(self, ages: list[timedelta]) -> list[uuid.UUID]:
        with self.owner.begin() as db:
            now = db.scalar(text("SELECT clock_timestamp()"))
            return self.seed_at(db, [now - age for age in ages])

    def seed_at(self, db: Connection, times: list[datetime]) -> list[uuid.UUID]:
        generated = [uuid.uuid7() for _ in times]
        self.ids.extend(generated)
        for identity, created_at in zip(generated, times, strict=True):
            db.execute(
                text(
                    "INSERT INTO auth.security_events(id,event_type,result,correlation_id,"
                    "created_at) VALUES (:id,'login_failure','failure',:correlation,"
                    "clock_timestamp())"
                ),
                {"id": identity, "correlation": str(uuid.uuid4())},
            )
            # Backdate only our synthetic fixture row as the owner. The real writer
            # keeps server-created timestamps and is never altered for the proof.
            db.execute(
                text("UPDATE auth.security_events SET created_at=:created_at WHERE id=:id"),
                {"id": identity, "created_at": created_at},
            )
        return generated

    def prune(self, batch: int | None = 1000) -> tuple[int, bool]:
        with self.maintenance.begin() as db:
            row = db.execute(text(PRUNE), {"batch": batch}).one()
            return row.deleted_count, row.remaining_expired

    def remaining(self) -> set[uuid.UUID]:
        with self.owner.connect() as db:
            return set(
                db.scalars(
                    text("SELECT id FROM auth.security_events WHERE id=ANY(:ids)"),
                    {"ids": self.ids},
                )
            )

    def events(self) -> list:
        with self.owner.connect() as db:
            return [
                row
                for row in db.execute(
                    text(
                        "SELECT * FROM auth.security_events WHERE "
                        "event_type='security_events_pruned' ORDER BY created_at,id"
                    )
                )
                if row.id not in self.initial_ids
            ]


@pytest.fixture
def retention(settings: Settings) -> Iterator[RetentionFixture]:
    raw = os.environ.get("SECURITY_MAINTENANCE_DATABASE_URL")
    if settings.app_env != "test" or not raw:
        pytest.fail("audit_retention_test_database_required", pytrace=False)
    urls = [
        make_url(raw),
        make_url(settings.database_url),
        make_url(settings.required_migration_database_url),
    ]
    locations = {(url.host, url.port or 5432, url.database) for url in urls}
    if (
        len(locations) != 1
        or urls[0].host not in {"localhost", "127.0.0.1"}
        or any(url.database != "sahl_ci" or url.drivername != "postgresql+psycopg" for url in urls)
        or urls[0].username != "sahl_maintenance_test"
    ):
        pytest.fail("audit_retention_test_database_required", pytrace=False)
    owner = create_engine(urls[2], poolclass=NullPool, hide_parameters=True)
    runtime = create_engine(urls[1], poolclass=NullPool, hide_parameters=True)
    maintenance = create_engine(urls[0], poolclass=NullPool, hide_parameters=True)
    fixture: RetentionFixture | None = None
    try:
        with owner.connect() as db:
            if db.scalar(text("SELECT current_database()")) != "sahl_ci":
                pytest.fail("audit_retention_test_database_required", pytrace=False)
            if db.scalar(
                text(
                    "SELECT EXISTS(SELECT 1 FROM auth.security_events "
                    "WHERE created_at<clock_timestamp()-interval '2160 hours')"
                )
            ):
                pytest.fail("audit_retention_test_requires_no_existing_expired_rows", pytrace=False)
            baseline = set(db.scalars(text("SELECT id FROM auth.security_events")))
        with maintenance.connect() as db:
            assert db.scalar(text("SELECT session_user")) == "sahl_maintenance_test"
            assert db.scalar(
                text("SELECT pg_has_role(session_user,'sahl_security_maintenance','USAGE')")
            )
        fixture = RetentionFixture(owner, maintenance, runtime, baseline)
        yield fixture
    finally:
        if fixture is not None:
            own_events = [row.id for row in fixture.events()]
            with owner.begin() as db:
                db.execute(
                    text("DELETE FROM auth.security_events WHERE id=ANY(:ids)"),
                    {"ids": fixture.ids + own_events},
                )
        maintenance.dispose()
        runtime.dispose()
        owner.dispose()


def test_empty_is_idempotent_and_emits_no_event(retention: RetentionFixture) -> None:
    assert retention.prune() == (0, False)
    assert retention.prune(1) == (0, False)
    assert retention.events() == []


def test_only_expired_records_and_one_exact_event(retention: RetentionFixture) -> None:
    old, recent, future = retention.seed(
        [timedelta(days=91), timedelta(days=89), timedelta(days=-1)]
    )
    assert retention.prune() == (1, False)
    assert retention.remaining() == {recent, future}
    assert old not in retention.remaining()
    [event] = retention.events()
    assert event.result == "success"
    assert event.reason_code == "retention_expired"
    assert event.affected_count == 1
    assert event.id.version == 7
    assert uuid.UUID(event.correlation_id).variant == uuid.RFC_4122
    for name in (
        "user_id",
        "session_id",
        "membership_id",
        "role_id",
        "target_membership_id",
        "permission_id",
        "subject_digest",
        "subject_kind",
        "subject_key_id",
    ):
        assert getattr(event, name) is None


@pytest.mark.parametrize("zone", ["UTC", "America/New_York", "Pacific/Apia"])
def test_exact_cutoff_and_microsecond_neighbors_use_real_server_time(
    retention: RetentionFixture, zone: str
) -> None:
    with retention.maintenance.begin() as db:
        db.execute(text("SELECT set_config('TimeZone',:zone,true)"), {"zone": zone})
        cutoff = db.scalar(text("SELECT transaction_timestamp()-interval '2160 hours'"))
        with retention.owner.begin() as owner:
            older, exact, younger = retention.seed_at(
                owner,
                [cutoff - timedelta(microseconds=1), cutoff, cutoff + timedelta(microseconds=1)],
            )
        result = db.execute(text(PRUNE), {"batch": 1000}).one()
        assert tuple(result) == (1, False)
    assert retention.remaining() == {exact, younger}
    assert older not in retention.remaining()
    assert retention.events()[0].affected_count == 1


def test_old_transaction_can_only_delay_expiration(retention: RetentionFixture) -> None:
    with retention.maintenance.begin() as db:
        transaction_start = db.scalar(text("SELECT transaction_timestamp()"))
        with retention.owner.begin() as owner:
            retention.seed_at(owner, [transaction_start - timedelta(days=90)])
        assert tuple(db.execute(text(PRUNE), {"batch": 1000}).one()) == (0, False)
    assert retention.prune() == (1, False)


@pytest.mark.parametrize("batch", [None, 0, -1, 1001, 2147483647])
def test_invalid_batch_rejected_without_mutation(
    retention: RetentionFixture, batch: int | None
) -> None:
    [identity] = retention.seed([timedelta(days=91)])
    with pytest.raises(DBAPIError) as failure:
        retention.prune(batch)
    assert getattr(failure.value.orig, "sqlstate", None) == "22023"
    assert retention.remaining() == {identity}
    assert retention.events() == []


def test_batch_bound_order_and_resume(retention: RetentionFixture) -> None:
    newest, oldest, middle = retention.seed(
        [timedelta(days=91), timedelta(days=93), timedelta(days=92)]
    )
    assert retention.prune(1) == (1, True)
    assert retention.remaining() == {newest, middle}
    assert oldest not in retention.remaining()
    assert retention.prune(1) == (1, True)
    assert retention.remaining() == {newest}
    assert retention.prune(1) == (1, False)
    assert retention.prune(1) == (0, False)
    assert [event.affected_count for event in retention.events()] == [1, 1, 1]


def test_maximum_batch_never_exceeds_1000(retention: RetentionFixture) -> None:
    retention.seed([timedelta(days=91)] * 1001)
    assert retention.prune(1000) == (1000, True)
    assert len(retention.remaining()) == 1
    assert retention.prune(1000) == (1, False)
    assert [event.affected_count for event in retention.events()] == [1000, 1]


def test_equal_timestamps_use_id_order(retention: RetentionFixture) -> None:
    with retention.owner.begin() as owner:
        then = owner.scalar(text("SELECT clock_timestamp()-interval '2200 hours'"))
        identities = retention.seed_at(owner, [then, then, then])
    assert retention.prune(1) == (1, True)
    assert retention.remaining() == set(sorted(identities)[1:])


def test_concurrent_batches_do_not_double_delete(retention: RetentionFixture) -> None:
    retention.seed([timedelta(days=91)] * 30)
    barrier = Barrier(3)

    def execute_batch() -> tuple[int, bool]:
        barrier.wait(timeout=10)
        return retention.prune(10)

    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda _: execute_batch(), range(3)))
    assert sum(result[0] for result in results) == 30
    assert retention.remaining() == set()
    events = retention.events()
    assert len(events) == 3
    assert len({event.id for event in events}) == 3
    assert sum(event.affected_count for event in events) == 30
    assert retention.prune() == (0, False)


def test_locked_expired_rows_report_pending_without_waiting(retention: RetentionFixture) -> None:
    [identity] = retention.seed([timedelta(days=91)])
    with retention.owner.begin() as owner:
        owner.execute(
            text("SELECT id FROM auth.security_events WHERE id=:id FOR UPDATE"), {"id": identity}
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(retention.prune).result(timeout=10) == (0, True)
        assert retention.events() == []
    assert retention.prune() == (1, False)


def test_uncommitted_other_batch_is_not_falsely_drained(retention: RetentionFixture) -> None:
    retention.seed([timedelta(days=91), timedelta(days=91)])
    with retention.maintenance.connect() as first:
        assert first.execute(text(PRUNE), {"batch": 1}).one().deleted_count == 1
        assert retention.prune(1) == (1, True)
        first.rollback()
    assert len(retention.remaining()) == 1
    assert retention.prune(1) == (1, False)
    assert sum(event.affected_count for event in retention.events()) == 2


def test_caller_rollback_restores_deletion_and_event(retention: RetentionFixture) -> None:
    [identity] = retention.seed([timedelta(days=91)])
    with retention.maintenance.connect() as db:
        assert db.execute(text(PRUNE), {"batch": 1000}).one().deleted_count == 1
        db.rollback()
    assert retention.remaining() == {identity}
    assert retention.events() == []


def test_mandatory_event_failure_rolls_back_deletion(retention: RetentionFixture) -> None:
    [identity] = retention.seed([timedelta(days=91)])
    with retention.owner.begin() as owner:
        owner.execute(
            text(
                "ALTER TABLE auth.security_events ADD CONSTRAINT g4_retention_event_failure "
                "CHECK (event_type <> 'security_events_pruned') NOT VALID"
            )
        )
    try:
        with pytest.raises(DBAPIError):
            retention.prune()
        assert retention.remaining() == {identity}
        assert retention.events() == []
    finally:
        with retention.owner.begin() as owner:
            owner.execute(
                text("ALTER TABLE auth.security_events DROP CONSTRAINT g4_retention_event_failure")
            )


@pytest.mark.parametrize("role", ["runtime", "owner"])
def test_runtime_and_migration_logins_cannot_prune(retention: RetentionFixture, role: str) -> None:
    [identity] = retention.seed([timedelta(days=91)])
    engine = getattr(retention, role)
    with engine.begin() as db, pytest.raises(DBAPIError) as failure:
        db.execute(text(PRUNE), {"batch": 1000})
    assert getattr(failure.value.orig, "sqlstate", None) == "42501"
    assert retention.remaining() == {identity}
    assert retention.events() == []


@pytest.mark.parametrize("role", ["runtime", "maintenance", "owner"])
def test_forged_prune_event_cannot_be_appended(retention: RetentionFixture, role: str) -> None:
    with getattr(retention, role).begin() as db, pytest.raises(DBAPIError):
        db.execute(text(FORGE), {"id": uuid.uuid7(), "correlation": uuid.uuid4()})
    assert retention.events() == []


@pytest.mark.parametrize("role", ["runtime", "maintenance"])
@pytest.mark.parametrize("operation", ["SELECT", "UPDATE", "DELETE", "TRUNCATE", "INSERT"])
def test_runtime_and_maintenance_have_no_direct_audit_table_access(
    retention: RetentionFixture, role: str, operation: str
) -> None:
    statements = {
        "SELECT": "SELECT id FROM auth.security_events LIMIT 1",
        "UPDATE": "UPDATE auth.security_events SET result='failure' WHERE false",
        "DELETE": "DELETE FROM auth.security_events WHERE false",
        "TRUNCATE": "TRUNCATE auth.security_events",
        "INSERT": "INSERT INTO auth.security_events SELECT * FROM auth.security_events WHERE false",
    }
    with getattr(retention, role).begin() as db, pytest.raises(DBAPIError) as failure:
        db.execute(text(statements[operation]))
    assert getattr(failure.value.orig, "sqlstate", None) == "42501"


def test_accidental_append_grant_denies_purge_and_forged_events(
    retention: RetentionFixture,
) -> None:
    [identity] = retention.seed([timedelta(days=91)])
    with retention.owner.begin() as owner:
        owner.execute(
            text(f"GRANT EXECUTE ON FUNCTION {APPEND_SIGNATURE} TO sahl_security_maintenance")
        )
    try:
        with pytest.raises(DBAPIError):
            retention.prune()
        with retention.maintenance.begin() as db, pytest.raises(DBAPIError):
            db.execute(text(FORGE), {"id": uuid.uuid7(), "correlation": uuid.uuid4()})
        assert retention.remaining() == {identity}
        assert retention.events() == []
    finally:
        with retention.owner.begin() as owner:
            owner.execute(
                text(
                    f"REVOKE EXECUTE ON FUNCTION {APPEND_SIGNATURE} FROM sahl_security_maintenance"
                )
            )


@pytest.mark.parametrize("grant", ["SELECT", "SELECT (id)", "INSERT", "UPDATE", "DELETE"])
def test_accidental_table_or_column_grants_fail_closed(
    retention: RetentionFixture, grant: str
) -> None:
    [identity] = retention.seed([timedelta(days=91)])
    with retention.owner.begin() as owner:
        owner.execute(text(f"GRANT {grant} ON auth.security_events TO sahl_security_maintenance"))
    try:
        with pytest.raises(DBAPIError):
            retention.prune()
        assert retention.remaining() == {identity}
    finally:
        with retention.owner.begin() as owner:
            owner.execute(
                text(f"REVOKE {grant} ON auth.security_events FROM sahl_security_maintenance")
            )


def test_set_role_keeps_dedicated_session_identity(retention: RetentionFixture) -> None:
    retention.seed([timedelta(days=91)])
    with retention.maintenance.begin() as db:
        db.execute(text("SET LOCAL ROLE sahl_security_maintenance"))
        assert db.scalar(text("SELECT session_user")) == "sahl_maintenance_test"
        assert tuple(db.execute(text(PRUNE), {"batch": 1000}).one()) == (1, False)


def test_privilege_catalog_owner_fixed_path_and_exact_grants(retention: RetentionFixture) -> None:
    with retention.owner.connect() as db:
        function = db.execute(
            text(
                "SELECT p.prosecdef,p.proconfig,p.provolatile,r.rolname "
                "FROM pg_proc p JOIN pg_roles r ON r.oid=p.proowner "
                "WHERE p.oid='auth.prune_security_events(integer)'::regprocedure"
            )
        ).one()
        assert function.rolname == "sahl_migrator"
        assert function.prosecdef
        assert function.proconfig == ["search_path=pg_catalog"]
        assert function.provolatile == "v"
        privileges = db.execute(
            text(
                "SELECT coalesce(r.rolname,'PUBLIC'),a.privilege_type,a.is_grantable "
                "FROM pg_proc p CROSS JOIN LATERAL aclexplode(p.proacl) a "
                "LEFT JOIN pg_roles r ON r.oid=a.grantee "
                "WHERE p.oid='auth.prune_security_events(integer)'::regprocedure"
            )
        ).all()
        assert set(privileges) == {
            ("sahl_migrator", "EXECUTE", False),
            ("sahl_security_maintenance", "EXECUTE", False),
        }
        assert not db.scalar(
            text(
                "SELECT EXISTS(SELECT 1 FROM pg_class c "
                "JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname IN ('auth','app','public') AND "
                "pg_get_userbyid(c.relowner) IN ('sahl_app','sahl_security_maintenance',"
                "'sahl_maintenance_test'))"
            )
        )
        definition = db.scalar(
            text(
                "SELECT indexdef FROM pg_indexes WHERE schemaname='auth' "
                "AND indexname='ix_security_events_retention'"
            )
        )
        assert "(created_at, id)" in definition
        assert (
            db.scalar(text("SELECT version_num FROM public.alembic_version"))
            == "0017_foundation_fk_indexes"
        )
    with retention.maintenance.connect() as db:
        assert (
            db.scalar(
                text(
                    "SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
                    "WHERE n.nspname='auth' AND "
                    "has_function_privilege(session_user,p.oid,'EXECUTE')"
                )
            )
            == 1
        )
        assert not db.scalar(text("SELECT has_schema_privilege(session_user,'auth','CREATE')"))


def test_runtime_cannot_set_role_to_maintenance(retention: RetentionFixture) -> None:
    [identity] = retention.seed([timedelta(days=91)])
    with retention.runtime.begin() as db, pytest.raises(DBAPIError) as failure:
        db.execute(text("SET LOCAL ROLE sahl_security_maintenance"))
    assert getattr(failure.value.orig, "sqlstate", None) == "42501"
    assert retention.remaining() == {identity}
    assert retention.events() == []


@pytest.mark.parametrize("operation", ["prune", "append"])
def test_forged_tenant_and_retention_gucs_never_authorize_runtime(
    retention: RetentionFixture, operation: str
) -> None:
    [identity] = retention.seed([timedelta(days=91)])
    with retention.runtime.begin() as db:
        db.execute(
            text(
                "SELECT set_config('app.current_tenant_id',:tenant,true),"
                "set_config('app.tenant_id',:tenant,true),"
                "set_config('app.retention_context','sahl_security_maintenance',true),"
                "set_config('app.security_maintenance','true',true),"
                "set_config('app.audit_retention_authorized','true',true)"
            ),
            {"tenant": str(uuid.uuid4())},
        )
        assert db.scalar(text("SELECT session_user")) == "sahl_app"
        with pytest.raises(DBAPIError):
            if operation == "prune":
                db.execute(text(PRUNE), {"batch": 1000})
            else:
                db.execute(text(FORGE), {"id": uuid.uuid7(), "correlation": uuid.uuid4()})
    assert retention.remaining() == {identity}
    assert retention.events() == []
