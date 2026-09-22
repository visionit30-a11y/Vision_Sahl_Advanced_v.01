"""Atomic, tenant-scoped workflow lifecycle behind typed grants."""

from __future__ import annotations

import uuid

from sqlalchemy import text

from app.activity_center.service import publish_notification
from app.authorization.contracts import AuthorizationBoundaryRequiredError, AuthorizationGrant
from app.authorization.permissions import Permission, PermissionId
from app.core.errors import AppError
from app.db.tenant_transaction import TenantTransaction, tenant_transaction
from app.workflow.contracts import (
    ApprovalTaskRecord,
    WorkflowCreate,
    WorkflowDecision,
    WorkflowEventRecord,
    WorkflowRecord,
    WorkflowUpdate,
)


class WorkflowNotFoundError(AppError):
    code = "not_found"
    status_code = 404
    message = "The requested resource was not found."


class WorkflowConflictError(AppError):
    code = "conflict"
    status_code = 409
    message = "The request conflicts with the current state."


def _grant(grant: AuthorizationGrant, permission: Permission) -> AuthorizationGrant:
    if not isinstance(grant, AuthorizationGrant) or grant.permission_id != PermissionId(
        permission.value
    ):
        raise AuthorizationBoundaryRequiredError()
    return grant


class WorkflowService:
    async def create(self, grant: AuthorizationGrant, payload: WorkflowCreate) -> WorkflowRecord:
        grant = _grant(grant, Permission.TENANT_WORKFLOW_REQUESTS_CREATE)
        if payload.approver_membership_id == grant.principal.membership_id:
            raise WorkflowConflictError()
        request_id = uuid.uuid7()
        async with tenant_transaction(grant.tenant_context) as tx:
            await self._active_membership(tx, payload.approver_membership_id)
            row = (
                await tx.execute(
                    text("""
                INSERT INTO app.workflow_requests(
                    id,tenant_id,requester_membership_id,approver_membership_id,
                    request_type,title,description
                ) VALUES (:id,:tenant,:requester,:approver,:type,:title,:description)
                RETURNING *
            """),
                    {
                        "id": request_id,
                        "tenant": grant.tenant_context.tenant_id,
                        "requester": grant.principal.membership_id,
                        "approver": payload.approver_membership_id,
                        "type": payload.request_type,
                        "title": payload.title,
                        "description": payload.description,
                    },
                )
            ).one()
            await self._event(tx, grant, request_id, "created", None, "draft", None)
        return WorkflowRecord.model_validate(row._mapping)

    async def update(
        self, grant: AuthorizationGrant, request_id: uuid.UUID, payload: WorkflowUpdate
    ) -> WorkflowRecord:
        grant = _grant(grant, Permission.TENANT_WORKFLOW_REQUESTS_CREATE)
        if payload.approver_membership_id == grant.principal.membership_id:
            raise WorkflowConflictError()
        async with tenant_transaction(grant.tenant_context) as tx:
            await self._active_membership(tx, payload.approver_membership_id)
            previous = await tx.scalar(
                text(
                    "SELECT status FROM app.workflow_requests WHERE id=:id "
                    "AND requester_membership_id=:requester "
                    "AND status IN ('draft','returned') AND version=:version FOR UPDATE"
                ),
                {
                    "id": request_id,
                    "requester": grant.principal.membership_id,
                    "version": payload.expected_version,
                },
            )
            if previous is None:
                raise WorkflowConflictError()
            row = (
                await tx.execute(
                    text("""
                UPDATE app.workflow_requests
                SET title=:title,description=:description,approver_membership_id=:approver,
                    version=version+1,updated_at=clock_timestamp(),completed_at=NULL
                WHERE id=:id AND requester_membership_id=:requester
                  AND status IN ('draft','returned') AND version=:version
                RETURNING *
            """),
                    {
                        "id": request_id,
                        "requester": grant.principal.membership_id,
                        "title": payload.title,
                        "description": payload.description,
                        "approver": payload.approver_membership_id,
                        "version": payload.expected_version,
                    },
                )
            ).one_or_none()
            if row is None:
                raise WorkflowConflictError()
            await self._event(tx, grant, request_id, "updated", str(previous), str(previous), None)
        return WorkflowRecord.model_validate(row._mapping)

    async def submit(
        self, grant: AuthorizationGrant, request_id: uuid.UUID, expected_version: int
    ) -> WorkflowRecord:
        grant = _grant(grant, Permission.TENANT_WORKFLOW_REQUESTS_CREATE)
        task_id = uuid.uuid7()
        async with tenant_transaction(grant.tenant_context) as tx:
            previous = await tx.scalar(
                text(
                    "SELECT status FROM app.workflow_requests WHERE id=:id "
                    "AND requester_membership_id=:requester "
                    "AND status IN ('draft','returned') AND version=:version FOR UPDATE"
                ),
                {
                    "id": request_id,
                    "requester": grant.principal.membership_id,
                    "version": expected_version,
                },
            )
            if previous is None:
                raise WorkflowConflictError()
            row = (
                await tx.execute(
                    text("""
                UPDATE app.workflow_requests SET status='pending',version=version+1,
                    submitted_at=clock_timestamp(),updated_at=clock_timestamp(),completed_at=NULL
                WHERE id=:id AND requester_membership_id=:requester
                  AND status IN ('draft','returned') AND version=:version
                RETURNING *
            """),
                    {
                        "id": request_id,
                        "requester": grant.principal.membership_id,
                        "version": expected_version,
                    },
                )
            ).one_or_none()
            if row is None:
                raise WorkflowConflictError()
            await self._active_membership(tx, row.approver_membership_id)
            await tx.execute(
                text("""
                UPDATE app.workflow_approval_tasks SET status='cancelled',version=version+1,
                    decided_at=clock_timestamp() WHERE request_id=:request AND status='pending'
            """),
                {"request": request_id},
            )
            await tx.execute(
                text("""
                INSERT INTO app.workflow_approval_tasks(
                    id,tenant_id,request_id,assignee_membership_id
                )
                VALUES (:id,:tenant,:request,:assignee)
            """),
                {
                    "id": task_id,
                    "tenant": grant.tenant_context.tenant_id,
                    "request": request_id,
                    "assignee": row.approver_membership_id,
                },
            )
            event = "resubmitted" if previous == "returned" else "submitted"
            await self._event(tx, grant, request_id, event, str(previous), "pending", None)
            await publish_notification(
                tx,
                tenant_id=grant.tenant_context.tenant_id,
                recipient_membership_id=grant.principal.membership_id,
                request_id=request_id,
                kind="request_submitted",
                title=row.title,
            )
            await publish_notification(
                tx,
                tenant_id=grant.tenant_context.tenant_id,
                recipient_membership_id=row.approver_membership_id,
                request_id=request_id,
                kind="approval_requested",
                title=row.title,
            )
        return WorkflowRecord.model_validate(row._mapping)

    async def list_requests(self, grant: AuthorizationGrant) -> list[WorkflowRecord]:
        grant = _grant(grant, Permission.TENANT_WORKFLOW_REQUESTS_READ)
        async with tenant_transaction(grant.tenant_context) as tx:
            rows = (
                await tx.execute(
                    text("""
                SELECT * FROM app.workflow_requests
                WHERE requester_membership_id=:membership OR approver_membership_id=:membership
                ORDER BY updated_at DESC,id DESC
            """),
                    {"membership": grant.principal.membership_id},
                )
            ).all()
        return [WorkflowRecord.model_validate(row._mapping) for row in rows]

    async def get(self, grant: AuthorizationGrant, request_id: uuid.UUID) -> WorkflowRecord:
        grant = _grant(grant, Permission.TENANT_WORKFLOW_REQUESTS_READ)
        async with tenant_transaction(grant.tenant_context) as tx:
            row = (
                await tx.execute(
                    text("""
                SELECT * FROM app.workflow_requests WHERE id=:id
                  AND (requester_membership_id=:membership OR approver_membership_id=:membership)
            """),
                    {"id": request_id, "membership": grant.principal.membership_id},
                )
            ).one_or_none()
        if row is None:
            raise WorkflowNotFoundError()
        return WorkflowRecord.model_validate(row._mapping)

    async def history(
        self, grant: AuthorizationGrant, request_id: uuid.UUID
    ) -> list[WorkflowEventRecord]:
        await self.get(grant, request_id)
        async with tenant_transaction(grant.tenant_context) as tx:
            rows = (
                await tx.execute(
                    text("""
                SELECT event.id,event.actor_membership_id,event.event_type,event.from_status,
                  event.to_status,event.note,event.created_at,
                  CASE WHEN event.actor_membership_id=request.requester_membership_id
                       THEN 'requester' ELSE 'approver' END actor_kind
                FROM app.workflow_events event
                JOIN app.workflow_requests request
                  ON request.tenant_id=event.tenant_id AND request.id=event.request_id
                WHERE event.request_id=:id ORDER BY event.created_at,event.id
            """),
                    {"id": request_id},
                )
            ).all()
        return [WorkflowEventRecord.model_validate(row._mapping) for row in rows]

    async def inbox(self, grant: AuthorizationGrant) -> list[ApprovalTaskRecord]:
        grant = _grant(grant, Permission.TENANT_WORKFLOW_APPROVALS_DECIDE)
        async with tenant_transaction(grant.tenant_context) as tx:
            rows = (
                await tx.execute(
                    text("""
                SELECT task.id,task.request_id,request.title,request.request_type,
                       request.requester_membership_id,task.status,task.version,
                       task.created_at,task.due_at
                FROM app.workflow_approval_tasks task
                JOIN app.workflow_requests request
                  ON request.tenant_id=task.tenant_id AND request.id=task.request_id
                WHERE task.assignee_membership_id=:membership AND task.status='pending'
                ORDER BY task.created_at,task.id
            """),
                    {"membership": grant.principal.membership_id},
                )
            ).all()
        return [ApprovalTaskRecord.model_validate(row._mapping) for row in rows]

    async def decide(
        self,
        grant: AuthorizationGrant,
        task_id: uuid.UUID,
        decision: WorkflowDecision,
        expected_version: int,
        note: str | None,
    ) -> WorkflowRecord:
        grant = _grant(grant, Permission.TENANT_WORKFLOW_APPROVALS_DECIDE)
        note = note if note and note.strip() else None
        if decision in {WorkflowDecision.REJECT, WorkflowDecision.RETURN} and note is None:
            raise WorkflowConflictError()
        status = {
            WorkflowDecision.APPROVE: "approved",
            WorkflowDecision.REJECT: "rejected",
            WorkflowDecision.RETURN: "returned",
        }[decision]
        async with tenant_transaction(grant.tenant_context) as tx:
            task = (
                await tx.execute(
                    text("""
                UPDATE app.workflow_approval_tasks
                SET status=:status,decision_note=:note,
                    decided_at=clock_timestamp(),version=version+1
                WHERE id=:id AND assignee_membership_id=:membership
                  AND status='pending' AND version=:version
                RETURNING request_id
            """),
                    {
                        "id": task_id,
                        "membership": grant.principal.membership_id,
                        "status": status,
                        "note": note,
                        "version": expected_version,
                    },
                )
            ).one_or_none()
            if task is None:
                raise WorkflowConflictError()
            row = (
                await tx.execute(
                    text("""
                UPDATE app.workflow_requests
                SET status=CAST(:status AS VARCHAR(16)),version=version+1,
                    updated_at=clock_timestamp(),
                    completed_at=CASE WHEN CAST(:status AS VARCHAR(16))
                    IN ('approved','rejected')
                    THEN clock_timestamp() ELSE NULL END
                WHERE id=:request AND status='pending' RETURNING *
            """),
                    {"request": task.request_id, "status": status},
                )
            ).one_or_none()
            if row is None:
                raise WorkflowConflictError()
            await self._event(tx, grant, row.id, status, "pending", status, note)
            await publish_notification(
                tx,
                tenant_id=grant.tenant_context.tenant_id,
                recipient_membership_id=row.requester_membership_id,
                request_id=row.id,
                kind=f"request_{status}",
                title=row.title,
            )
        return WorkflowRecord.model_validate(row._mapping)

    @staticmethod
    async def _active_membership(tx: TenantTransaction, membership_id: uuid.UUID) -> None:
        if (
            await tx.scalar(
                text("SELECT auth.is_active_membership_in_tenant(:membership,:tenant)"),
                {
                    "membership": membership_id,
                    "tenant": await tx.scalar(text("SELECT app.current_tenant_id()")),
                },
            )
            is not True
        ):
            raise WorkflowNotFoundError()

    @staticmethod
    async def _event(
        tx: TenantTransaction,
        grant: AuthorizationGrant,
        request_id: uuid.UUID,
        event_type: str,
        from_status: str | None,
        to_status: str,
        note: str | None,
    ) -> None:
        await tx.execute(
            text("""
            INSERT INTO app.workflow_events(id,tenant_id,request_id,actor_membership_id,
                event_type,from_status,to_status,note)
            VALUES (:id,:tenant,:request,:actor,:event,:from_status,:to_status,:note)
        """),
            {
                "id": uuid.uuid7(),
                "tenant": grant.tenant_context.tenant_id,
                "request": request_id,
                "actor": grant.principal.membership_id,
                "event": event_type,
                "from_status": from_status,
                "to_status": to_status,
                "note": note,
            },
        )


workflow_service = WorkflowService()
