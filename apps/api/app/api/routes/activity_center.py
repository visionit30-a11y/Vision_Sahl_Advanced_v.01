"""HTTP boundary for the shared notifications, tasks, and activity center."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response

from app.activity_center.contracts import (
    DashboardSummary,
    MarkAllResult,
    NotificationPreferences,
    NotificationRecord,
    NotificationSummary,
    PreferenceUpdate,
    TaskBucket,
    TaskRecord,
)
from app.activity_center.service import activity_center_service
from app.api.authorization_dependencies import require_permission
from app.authorization.contracts import AuthorizationGrant
from app.authorization.permissions import Permission

router = APIRouter(prefix="/activity-center", tags=["activity-center"])
read_grant = require_permission(Permission.TENANT_WORKFLOW_REQUESTS_READ)
task_grant = require_permission(Permission.TENANT_WORKFLOW_APPROVALS_DECIDE)
preference_grant = require_permission(Permission.TENANT_USER_UI_SETTINGS_MANAGE_SELF)


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


@router.get("/notifications", response_model=list[NotificationRecord])
async def notifications(
    response: Response, grant: Annotated[AuthorizationGrant, Depends(read_grant)]
) -> list[NotificationRecord]:
    _no_store(response)
    return await activity_center_service.notifications(grant)


@router.get("/notifications/summary", response_model=NotificationSummary)
async def notification_summary(
    response: Response, grant: Annotated[AuthorizationGrant, Depends(read_grant)]
) -> NotificationSummary:
    _no_store(response)
    return await activity_center_service.notification_summary(grant)


@router.post("/notifications/{notification_id}/read", response_model=NotificationRecord)
async def mark_notification_read(
    notification_id: uuid.UUID,
    response: Response,
    grant: Annotated[AuthorizationGrant, Depends(read_grant)],
) -> NotificationRecord:
    _no_store(response)
    return await activity_center_service.mark_read(grant, notification_id)


@router.post("/notifications/read-all", response_model=MarkAllResult)
async def mark_all_notifications_read(
    response: Response, grant: Annotated[AuthorizationGrant, Depends(read_grant)]
) -> MarkAllResult:
    _no_store(response)
    return await activity_center_service.mark_all_read(grant)


@router.get("/tasks", response_model=list[TaskRecord])
async def tasks(
    response: Response,
    grant: Annotated[AuthorizationGrant, Depends(task_grant)],
    bucket: Annotated[TaskBucket | None, Query()] = None,
    request_type: Annotated[str | None, Query(pattern=r"^[a-z][a-z0-9_]{0,62}$")] = None,
    created_from: Annotated[datetime | None, Query()] = None,
    created_to: Annotated[datetime | None, Query()] = None,
) -> list[TaskRecord]:
    _no_store(response)
    return await activity_center_service.tasks(
        grant, bucket, request_type, created_from, created_to
    )


@router.get("/preferences", response_model=NotificationPreferences)
async def preferences(
    response: Response, grant: Annotated[AuthorizationGrant, Depends(preference_grant)]
) -> NotificationPreferences:
    _no_store(response)
    return await activity_center_service.preferences(grant)


@router.put("/preferences", response_model=NotificationPreferences)
async def update_preferences(
    payload: PreferenceUpdate,
    response: Response,
    grant: Annotated[AuthorizationGrant, Depends(preference_grant)],
) -> NotificationPreferences:
    _no_store(response)
    return await activity_center_service.update_preferences(grant, payload)


@router.get("/dashboard", response_model=DashboardSummary)
async def dashboard(
    response: Response, grant: Annotated[AuthorizationGrant, Depends(read_grant)]
) -> DashboardSummary:
    _no_store(response)
    return await activity_center_service.dashboard(grant)
