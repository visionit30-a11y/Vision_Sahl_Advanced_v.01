"""Central tenant-safe services for notifications, approval tasks, and activity."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import text

from app.activity_center.contracts import (
    DashboardSummary,
    MarkAllResult,
    NotificationPreferences,
    NotificationRecord,
    NotificationSummary,
    PreferenceUpdate,
    RecentActivity,
    TaskBucket,
    TaskRecord,
)
from app.authorization.contracts import AuthorizationBoundaryRequiredError, AuthorizationGrant
from app.authorization.permissions import Permission, PermissionId
from app.core.errors import AppError
from app.db.tenant_transaction import TenantTransaction, tenant_transaction


class ActivityCenterNotFoundError(AppError):
    code = "not_found"
    status_code = 404
    message = "The requested resource was not found."


class ActivityCenterConflictError(AppError):
    code = "conflict"
    status_code = 409
    message = "The request conflicts with the current state."


def _grant(grant: AuthorizationGrant, *permissions: Permission) -> AuthorizationGrant:
    if not isinstance(grant, AuthorizationGrant) or grant.permission_id not in {
        PermissionId(permission.value) for permission in permissions
    }:
        raise AuthorizationBoundaryRequiredError()
    return grant


async def publish_notification(
    tx: TenantTransaction,
    *,
    tenant_id: uuid.UUID,
    recipient_membership_id: uuid.UUID,
    request_id: uuid.UUID,
    kind: str,
    title: str,
) -> None:
    preference_column = {
        "approval_requested": "approval_requested",
        "request_approved": "request_approved",
        "request_rejected": "request_rejected",
        "request_returned": "request_returned",
        "task_overdue": "overdue_tasks",
    }.get(kind)
    if preference_column is not None:
        enabled = await tx.scalar(
            text(
                f"SELECT COALESCE((SELECT {preference_column} FROM app.notification_preferences "
                "WHERE membership_id=:membership),true)"
            ),
            {"membership": recipient_membership_id},
        )
        if enabled is not True:
            return
    await tx.execute(
        text("""
        INSERT INTO app.notifications(
            id,tenant_id,recipient_membership_id,request_id,kind,title_snapshot
        ) VALUES (:id,:tenant,:recipient,:request,:kind,:title)
    """),
        {
            "id": uuid.uuid7(),
            "tenant": tenant_id,
            "recipient": recipient_membership_id,
            "request": request_id,
            "kind": kind,
            "title": title,
        },
    )


class ActivityCenterService:
    async def notifications(self, grant: AuthorizationGrant) -> list[NotificationRecord]:
        grant = _grant(grant, Permission.TENANT_WORKFLOW_REQUESTS_READ)
        async with tenant_transaction(grant.tenant_context) as tx:
            rows = (
                await tx.execute(
                    text("""
                    SELECT id,request_id,kind,title_snapshot,read_at,created_at
                    FROM app.notifications
                    WHERE recipient_membership_id=:membership
                    ORDER BY created_at DESC,id DESC LIMIT 200
                """),
                    {"membership": grant.principal.membership_id},
                )
            ).all()
        return [NotificationRecord.model_validate(row._mapping) for row in rows]

    async def notification_summary(self, grant: AuthorizationGrant) -> NotificationSummary:
        grant = _grant(grant, Permission.TENANT_WORKFLOW_REQUESTS_READ)
        async with tenant_transaction(grant.tenant_context) as tx:
            count = await tx.scalar(
                text(
                    "SELECT count(*) FROM app.notifications "
                    "WHERE recipient_membership_id=:membership AND read_at IS NULL"
                ),
                {"membership": grant.principal.membership_id},
            )
        return NotificationSummary(unread_count=int(count or 0))

    async def mark_read(
        self, grant: AuthorizationGrant, notification_id: uuid.UUID
    ) -> NotificationRecord:
        grant = _grant(grant, Permission.TENANT_WORKFLOW_REQUESTS_READ)
        async with tenant_transaction(grant.tenant_context) as tx:
            row = (
                await tx.execute(
                    text("""
                    UPDATE app.notifications SET read_at=COALESCE(read_at,clock_timestamp())
                    WHERE id=:id AND recipient_membership_id=:membership
                    RETURNING id,request_id,kind,title_snapshot,read_at,created_at
                """),
                    {"id": notification_id, "membership": grant.principal.membership_id},
                )
            ).one_or_none()
        if row is None:
            raise ActivityCenterNotFoundError()
        return NotificationRecord.model_validate(row._mapping)

    async def mark_all_read(self, grant: AuthorizationGrant) -> MarkAllResult:
        grant = _grant(grant, Permission.TENANT_WORKFLOW_REQUESTS_READ)
        async with tenant_transaction(grant.tenant_context) as tx:
            rows = (
                await tx.execute(
                    text("""
                UPDATE app.notifications SET read_at=clock_timestamp()
                WHERE recipient_membership_id=:membership AND read_at IS NULL
                RETURNING id
            """),
                    {"membership": grant.principal.membership_id},
                )
            ).all()
        return MarkAllResult(marked_count=len(rows))

    async def tasks(
        self,
        grant: AuthorizationGrant,
        bucket: TaskBucket | None = None,
        request_type: str | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
    ) -> list[TaskRecord]:
        grant = _grant(grant, Permission.TENANT_WORKFLOW_APPROVALS_DECIDE)
        async with tenant_transaction(grant.tenant_context) as tx:
            await self._materialize_overdue(tx, grant)
            rows = (
                await tx.execute(
                    text("""
                    SELECT task.id,task.request_id,request.title,request.request_type,
                           task.status,task.version,task.created_at,task.due_at,task.decided_at,
                           CASE WHEN task.status='pending' AND task.due_at<clock_timestamp()
                             THEN 'overdue' WHEN task.status='pending' THEN 'open'
                             ELSE 'completed' END AS bucket
                    FROM app.workflow_approval_tasks task
                    JOIN app.workflow_requests request
                      ON request.tenant_id=task.tenant_id AND request.id=task.request_id
                    WHERE task.assignee_membership_id=:membership
                      AND (CAST(:bucket AS text) IS NULL OR
                        (CAST(:bucket AS text)='open' AND task.status='pending'
                          AND task.due_at>=clock_timestamp()) OR
                        (CAST(:bucket AS text)='overdue' AND task.status='pending'
                          AND task.due_at<clock_timestamp()) OR
                        (CAST(:bucket AS text)='completed' AND task.status<>'pending'))
                      AND (CAST(:type AS text) IS NULL OR request.request_type=CAST(:type AS text))
                      AND (CAST(:from_at AS timestamptz) IS NULL
                           OR task.created_at>=CAST(:from_at AS timestamptz))
                      AND (CAST(:to_at AS timestamptz) IS NULL
                           OR task.created_at<=CAST(:to_at AS timestamptz))
                    ORDER BY CASE WHEN task.status='pending' THEN 0 ELSE 1 END,task.due_at,task.id
                """),
                    {
                        "membership": grant.principal.membership_id,
                        "bucket": bucket.value if bucket else None,
                        "type": request_type,
                        "from_at": created_from,
                        "to_at": created_to,
                    },
                )
            ).all()
        return [TaskRecord.model_validate(row._mapping) for row in rows]

    async def preferences(self, grant: AuthorizationGrant) -> NotificationPreferences:
        grant = _grant(grant, Permission.TENANT_USER_UI_SETTINGS_MANAGE_SELF)
        async with tenant_transaction(grant.tenant_context) as tx:
            await tx.execute(
                text("""
                    INSERT INTO app.notification_preferences(tenant_id,membership_id)
                    VALUES (:tenant,:membership)
                    ON CONFLICT (tenant_id,membership_id) DO NOTHING
                """),
                {
                    "tenant": grant.tenant_context.tenant_id,
                    "membership": grant.principal.membership_id,
                },
            )
            row = (
                await tx.execute(
                    text("""
                    SELECT approval_requested,request_approved,request_rejected,
                           request_returned,overdue_tasks,version
                    FROM app.notification_preferences WHERE membership_id=:membership
                """),
                    {"membership": grant.principal.membership_id},
                )
            ).one()
        return NotificationPreferences.model_validate(row._mapping)

    async def update_preferences(
        self, grant: AuthorizationGrant, payload: PreferenceUpdate
    ) -> NotificationPreferences:
        grant = _grant(grant, Permission.TENANT_USER_UI_SETTINGS_MANAGE_SELF)
        async with tenant_transaction(grant.tenant_context) as tx:
            row = (
                await tx.execute(
                    text("""
                    UPDATE app.notification_preferences SET
                      approval_requested=:approval_requested,request_approved=:request_approved,
                      request_rejected=:request_rejected,request_returned=:request_returned,
                      overdue_tasks=:overdue_tasks,version=version+1,updated_at=clock_timestamp()
                    WHERE membership_id=:membership AND version=:expected_version
                    RETURNING approval_requested,request_approved,request_rejected,
                              request_returned,overdue_tasks,version
                """),
                    {**payload.model_dump(), "membership": grant.principal.membership_id},
                )
            ).one_or_none()
        if row is None:
            raise ActivityCenterConflictError()
        return NotificationPreferences.model_validate(row._mapping)

    async def dashboard(self, grant: AuthorizationGrant) -> DashboardSummary:
        grant = _grant(grant, Permission.TENANT_WORKFLOW_REQUESTS_READ)
        async with tenant_transaction(grant.tenant_context) as tx:
            counts = (
                await tx.execute(
                    text("""
                    SELECT
                      (SELECT count(*) FROM app.notifications
                       WHERE recipient_membership_id=:membership AND read_at IS NULL) unread,
                      (SELECT count(*) FROM app.workflow_approval_tasks
                       WHERE assignee_membership_id=:membership AND status='pending') pending,
                      (SELECT count(*) FROM app.workflow_approval_tasks
                       WHERE assignee_membership_id=:membership AND status='pending'
                         AND due_at<clock_timestamp()) overdue
                """),
                    {"membership": grant.principal.membership_id},
                )
            ).one()
            activities = (
                await tx.execute(
                    text("""
                    SELECT event.request_id,request.title,event.event_type,
                      CASE WHEN event.actor_membership_id=request.requester_membership_id
                           THEN 'requester' ELSE 'approver' END actor_kind,
                      event.from_status,event.to_status,event.created_at
                    FROM app.workflow_events event
                    JOIN app.workflow_requests request
                      ON request.tenant_id=event.tenant_id AND request.id=event.request_id
                    WHERE request.requester_membership_id=:membership
                       OR request.approver_membership_id=:membership
                    ORDER BY event.created_at DESC,event.id DESC LIMIT 8
                """),
                    {"membership": grant.principal.membership_id},
                )
            ).all()
        return DashboardSummary(
            unread_notifications=int(counts.unread),
            pending_tasks=int(counts.pending),
            overdue_tasks=int(counts.overdue),
            recent_activity=[RecentActivity.model_validate(row._mapping) for row in activities],
        )

    @staticmethod
    async def _materialize_overdue(tx: TenantTransaction, grant: AuthorizationGrant) -> None:
        rows = (
            await tx.execute(
                text("""
                SELECT task.request_id,request.title
                FROM app.workflow_approval_tasks task
                JOIN app.workflow_requests request
                  ON request.tenant_id=task.tenant_id AND request.id=task.request_id
                WHERE task.assignee_membership_id=:membership AND task.status='pending'
                  AND task.due_at<clock_timestamp()
                  AND NOT EXISTS (
                    SELECT 1 FROM app.notifications notification
                    WHERE notification.recipient_membership_id=task.assignee_membership_id
                      AND notification.request_id=task.request_id
                      AND notification.kind='task_overdue'
                  )
            """),
                {"membership": grant.principal.membership_id},
            )
        ).all()
        for row in rows:
            await publish_notification(
                tx,
                tenant_id=grant.tenant_context.tenant_id,
                recipient_membership_id=grant.principal.membership_id,
                request_id=row.request_id,
                kind="task_overdue",
                title=row.title,
            )


activity_center_service = ActivityCenterService()
