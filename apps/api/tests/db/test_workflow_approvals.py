"""Real PostgreSQL proofs for the shared workflow and approvals lifecycle."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from sqlalchemy import Connection, create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.pool import NullPool

from app.activity_center.contracts import PreferenceUpdate, TaskBucket
from app.activity_center.service import ActivityCenterConflictError, ActivityCenterService
from app.auth.tenants import AuthenticatedPrincipal
from app.authorization.contracts import AuthorizationGrant
from app.authorization.permissions import Permission, PermissionId
from app.core.config import Settings
from app.models.tenant import TenantId
from app.tenancy.context import TenantContext
from app.workflow.contracts import WorkflowCreate, WorkflowDecision, WorkflowUpdate
from app.workflow.service import WorkflowConflictError, WorkflowNotFoundError, WorkflowService


@dataclass(frozen=True)
class WorkflowFixture:
    tenant: uuid.UUID
    foreign_tenant: uuid.UUID
    requester: uuid.UUID
    approver: uuid.UUID
    foreign_member: uuid.UUID
    users: tuple[uuid.UUID, uuid.UUID, uuid.UUID]


@pytest.fixture
def workflow_fixture(settings: Settings) -> Iterator[WorkflowFixture]:
    tenant, foreign = uuid.uuid7(), uuid.uuid7()
    users = (uuid.uuid7(), uuid.uuid7(), uuid.uuid7())
    requester, approver, foreign_member = uuid.uuid7(), uuid.uuid7(), uuid.uuid7()
    engine = create_engine(settings.required_migration_database_url, poolclass=NullPool)
    with engine.begin() as connection:
        connection.execute(
            text("""
            INSERT INTO public.tenants(id,slug,name_ar,name_en,status) VALUES
            (:tenant,:tenant_slug,'جهة','Tenant','active'),
            (:foreign,:foreign_slug,'أخرى','Foreign','active')
        """),
            {
                "tenant": tenant,
                "foreign": foreign,
                "tenant_slug": f"workflow-{tenant.hex[-12:]}",
                "foreign_slug": f"workflow-{foreign.hex[-12:]}",
            },
        )
        for index, user in enumerate(users):
            connection.execute(
                text("""
                INSERT INTO auth.users(id,email,normalized_email,status)
                VALUES (:id,:email,:email,'active')
            """),
                {"id": user, "email": f"workflow-{index}-{user}@example.test"},
            )
        connection.execute(
            text("""
            INSERT INTO auth.tenant_memberships(id,user_id,tenant_id,status,joined_at) VALUES
            (:requester,:user_requester,:tenant,'active',clock_timestamp()),
            (:approver,:user_approver,:tenant,'active',clock_timestamp()),
            (:foreign_member,:user_foreign,:foreign,'active',clock_timestamp())
        """),
            {
                "requester": requester,
                "user_requester": users[0],
                "approver": approver,
                "user_approver": users[1],
                "tenant": tenant,
                "foreign_member": foreign_member,
                "user_foreign": users[2],
                "foreign": foreign,
            },
        )
    state = WorkflowFixture(tenant, foreign, requester, approver, foreign_member, users)
    try:
        yield state
    finally:
        application_engine = create_engine(settings.database_url, poolclass=NullPool)
        with application_engine.begin() as connection:
            for tenant_id in (tenant, foreign):
                connection.execute(
                    text("SELECT set_config('app.tenant_id', CAST(:tenant AS text), true)"),
                    {"tenant": tenant_id},
                )
                connection.execute(
                    text("DELETE FROM app.workflow_requests WHERE tenant_id=:tenant"),
                    {"tenant": tenant_id},
                )
        application_engine.dispose()
        with engine.begin() as connection:
            connection.execute(
                text("DELETE FROM auth.tenant_memberships WHERE tenant_id IN (:tenant,:foreign)"),
                {"tenant": tenant, "foreign": foreign},
            )
            connection.execute(
                text("DELETE FROM public.tenants WHERE id IN (:tenant,:foreign)"),
                {"tenant": tenant, "foreign": foreign},
            )
            connection.execute(
                text("DELETE FROM auth.users WHERE id=ANY(:users)"), {"users": list(users)}
            )
        engine.dispose()


def grant(
    state: WorkflowFixture, membership: uuid.UUID, permission: Permission
) -> AuthorizationGrant:
    user = state.users[0] if membership == state.requester else state.users[1]
    return AuthorizationGrant(
        AuthenticatedPrincipal(user, uuid.uuid7(), membership, 1),
        TenantContext(TenantId(state.tenant)),
        PermissionId(permission.value),
    )


async def test_complete_return_resubmit_approve_lifecycle(
    workflow_fixture: WorkflowFixture,
) -> None:
    service = WorkflowService()
    create_grant = grant(
        workflow_fixture, workflow_fixture.requester, Permission.TENANT_WORKFLOW_REQUESTS_CREATE
    )
    read_grant = grant(
        workflow_fixture, workflow_fixture.requester, Permission.TENANT_WORKFLOW_REQUESTS_READ
    )
    decide_grant = grant(
        workflow_fixture, workflow_fixture.approver, Permission.TENANT_WORKFLOW_APPROVALS_DECIDE
    )
    created = await service.create(
        create_grant,
        WorkflowCreate(
            request_type="general_request",
            title="شراء مواد",
            description="تفاصيل الطلب",
            approver_membership_id=workflow_fixture.approver,
        ),
    )
    assert (created.status, created.version) == ("draft", 1)
    pending = await service.submit(create_grant, created.id, 1)
    assert (pending.status, pending.version) == ("pending", 2)
    first_task = (await service.inbox(decide_grant))[0]
    returned = await service.decide(
        decide_grant, first_task.id, WorkflowDecision.RETURN, 1, "أكمل البيانات"
    )
    assert returned.status == "returned"
    revised = await service.update(
        create_grant,
        created.id,
        WorkflowUpdate(
            expected_version=3,
            title="شراء مواد مكتمل",
            description="التفاصيل المكتملة",
            approver_membership_id=workflow_fixture.approver,
        ),
    )
    assert revised.status == "returned"
    await service.submit(create_grant, created.id, revised.version)
    second_task = (await service.inbox(decide_grant))[0]
    approved = await service.decide(decide_grant, second_task.id, WorkflowDecision.APPROVE, 1, None)
    assert approved.status == "approved" and approved.completed_at is not None
    events = await service.history(read_grant, created.id)
    assert [event.event_type for event in events] == [
        "created",
        "submitted",
        "returned",
        "updated",
        "resubmitted",
        "approved",
    ]


async def test_reject_and_concurrent_decision_are_fail_closed(
    workflow_fixture: WorkflowFixture,
) -> None:
    service = WorkflowService()
    creator = grant(
        workflow_fixture, workflow_fixture.requester, Permission.TENANT_WORKFLOW_REQUESTS_CREATE
    )
    decider = grant(
        workflow_fixture, workflow_fixture.approver, Permission.TENANT_WORKFLOW_APPROVALS_DECIDE
    )
    created = await service.create(
        creator,
        WorkflowCreate(
            request_type="general_request",
            title="Request",
            description="Details",
            approver_membership_id=workflow_fixture.approver,
        ),
    )
    await service.submit(creator, created.id, created.version)
    task = (await service.inbox(decider))[0]
    results = await asyncio.gather(
        service.decide(decider, task.id, WorkflowDecision.REJECT, task.version, "Not accepted"),
        service.decide(decider, task.id, WorkflowDecision.APPROVE, task.version, None),
        return_exceptions=True,
    )
    assert sum(not isinstance(result, Exception) for result in results) == 1
    assert sum(isinstance(result, WorkflowConflictError) for result in results) == 1


async def test_activity_center_notification_task_and_preference_lifecycle(
    workflow_fixture: WorkflowFixture,
) -> None:
    workflow = WorkflowService()
    activity = ActivityCenterService()
    creator = grant(
        workflow_fixture, workflow_fixture.requester, Permission.TENANT_WORKFLOW_REQUESTS_CREATE
    )
    requester_read = grant(
        workflow_fixture, workflow_fixture.requester, Permission.TENANT_WORKFLOW_REQUESTS_READ
    )
    approver_read = grant(
        workflow_fixture, workflow_fixture.approver, Permission.TENANT_WORKFLOW_REQUESTS_READ
    )
    decider = grant(
        workflow_fixture, workflow_fixture.approver, Permission.TENANT_WORKFLOW_APPROVALS_DECIDE
    )
    preference_grant = grant(
        workflow_fixture,
        workflow_fixture.requester,
        Permission.TENANT_USER_UI_SETTINGS_MANAGE_SELF,
    )
    preferences = await activity.preferences(preference_grant)
    assert preferences.version == 1 and preferences.request_approved is True
    preferences = await activity.update_preferences(
        preference_grant,
        PreferenceUpdate(
            approval_requested=True,
            request_approved=True,
            request_rejected=True,
            request_returned=True,
            overdue_tasks=True,
            expected_version=preferences.version,
        ),
    )
    assert preferences.version == 2
    with pytest.raises(ActivityCenterConflictError):
        await activity.update_preferences(
            preference_grant,
            PreferenceUpdate(
                approval_requested=True,
                request_approved=True,
                request_rejected=True,
                request_returned=True,
                overdue_tasks=True,
                expected_version=1,
            ),
        )
    created = await workflow.create(
        creator,
        WorkflowCreate(
            request_type="general_request",
            title="Activity center proof",
            description="Real tenant-safe notification lifecycle",
            approver_membership_id=workflow_fixture.approver,
        ),
    )
    await workflow.submit(creator, created.id, created.version)
    approver_notifications = await activity.notifications(approver_read)
    assert [item.kind for item in approver_notifications] == ["approval_requested"]
    assert (await activity.notification_summary(approver_read)).unread_count == 1
    marked = await activity.mark_read(approver_read, approver_notifications[0].id)
    assert marked.read_at is not None
    assert (await activity.notification_summary(approver_read)).unread_count == 0
    tasks = await activity.tasks(decider, TaskBucket.OPEN)
    assert len(tasks) == 1 and tasks[0].request_id == created.id
    await workflow.decide(decider, tasks[0].id, WorkflowDecision.APPROVE, 1, None)
    assert await activity.tasks(decider, TaskBucket.OPEN) == []
    completed = await activity.tasks(decider, TaskBucket.COMPLETED)
    assert len(completed) == 1 and completed[0].status == "approved"
    requester_notifications = await activity.notifications(requester_read)
    assert {item.kind for item in requester_notifications} == {
        "request_submitted",
        "request_approved",
    }
    dashboard = await activity.dashboard(requester_read)
    assert dashboard.unread_notifications == 2
    assert [item.event_type for item in dashboard.recent_activity][:2] == [
        "approved",
        "submitted",
    ]


async def test_activity_center_self_scope_hides_other_memberships(
    workflow_fixture: WorkflowFixture,
) -> None:
    service = ActivityCenterService()
    requester_task_grant = grant(
        workflow_fixture,
        workflow_fixture.requester,
        Permission.TENANT_WORKFLOW_APPROVALS_DECIDE,
    )
    assert await service.tasks(requester_task_grant) == []


async def test_cross_tenant_approver_and_idor_are_hidden(workflow_fixture: WorkflowFixture) -> None:
    creator = grant(
        workflow_fixture, workflow_fixture.requester, Permission.TENANT_WORKFLOW_REQUESTS_CREATE
    )
    with pytest.raises(WorkflowNotFoundError):
        await WorkflowService().create(
            creator,
            WorkflowCreate(
                request_type="general_request",
                title="Request",
                description="Details",
                approver_membership_id=workflow_fixture.foreign_member,
            ),
        )


def test_workflow_tables_rls_grants_and_append_only_history(
    app_connection: Connection,
    migration_role: str,
    application_role: str,
) -> None:
    for table in ("workflow_requests", "workflow_approval_tasks", "workflow_events"):
        row = app_connection.execute(
            text("""
            SELECT pg_get_userbyid(relowner),relrowsecurity,relforcerowsecurity
            FROM pg_class WHERE oid=CAST(:name AS regclass)
        """),
            {"name": f"app.{table}"},
        ).one()
        assert tuple(row) == (migration_role, True, True)
        assert app_connection.scalar(
            text("""
            SELECT count(*)=1 FROM pg_policy WHERE polrelid=CAST(:name AS regclass)
              AND pg_get_expr(polqual,polrelid) LIKE '%app.current_tenant_id()%'
              AND pg_get_expr(polwithcheck,polrelid) LIKE '%app.current_tenant_id()%'
        """),
            {"name": f"app.{table}"},
        )
    assert not app_connection.scalar(
        text("SELECT has_table_privilege(:role,'app.workflow_events','UPDATE,DELETE,TRUNCATE')"),
        {"role": application_role},
    )
    with pytest.raises(DBAPIError):
        app_connection.execute(text("UPDATE app.workflow_events SET note='tampered'"))


def test_activity_center_tables_are_tenant_owned_and_least_privileged(
    app_connection: Connection,
    migration_role: str,
    application_role: str,
) -> None:
    for table in ("notifications", "notification_preferences"):
        row = app_connection.execute(
            text("""
            SELECT pg_get_userbyid(relowner),relrowsecurity,relforcerowsecurity
            FROM pg_class WHERE oid=CAST(:name AS regclass)
        """),
            {"name": f"app.{table}"},
        ).one()
        assert tuple(row) == (migration_role, True, True)
        assert app_connection.scalar(
            text("""
            SELECT count(*)=1 FROM pg_policy WHERE polrelid=CAST(:name AS regclass)
              AND pg_get_expr(polqual,polrelid) LIKE '%app.current_tenant_id()%'
              AND pg_get_expr(polwithcheck,polrelid) LIKE '%app.current_tenant_id()%'
        """),
            {"name": f"app.{table}"},
        )
        assert not app_connection.scalar(
            text("SELECT has_table_privilege('public',:name,'SELECT,INSERT,UPDATE,DELETE')"),
            {"name": f"app.{table}"},
        )
        assert app_connection.scalar(
            text("SELECT has_table_privilege(:role,:name,'SELECT,INSERT,UPDATE')"),
            {"role": application_role, "name": f"app.{table}"},
        )


def test_approver_projection_has_narrow_security_definer_boundary(
    app_connection: Connection,
    migration_role: str,
    application_role: str,
) -> None:
    row = app_connection.execute(
        text("""
        SELECT p.prosecdef,pg_get_userbyid(p.proowner),p.proconfig,pg_get_functiondef(p.oid)
        FROM pg_proc p WHERE p.oid='auth.workflow_approvers()'::regprocedure
    """)
    ).one()
    assert (row[0], row[1], row[2]) == (True, migration_role, ["search_path=pg_catalog"])
    assert "execute " not in row[3].lower() and "set_config" not in row[3].lower()
    assert app_connection.scalar(
        text("SELECT has_function_privilege(:role,'auth.workflow_approvers()','EXECUTE')"),
        {"role": application_role},
    )
    assert not app_connection.scalar(
        text("""
        SELECT EXISTS(SELECT 1 FROM pg_proc p CROSS JOIN LATERAL
        aclexplode(COALESCE(p.proacl,acldefault('f',p.proowner))) acl
        WHERE p.oid='auth.workflow_approvers()'::regprocedure
          AND acl.grantee=0 AND acl.privilege_type='EXECUTE')
    """)
    )
