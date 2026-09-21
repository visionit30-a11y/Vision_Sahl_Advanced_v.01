"""Typed public contracts for the shared activity center."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class NotificationKind(StrEnum):
    REQUEST_SUBMITTED = "request_submitted"
    APPROVAL_REQUESTED = "approval_requested"
    REQUEST_RETURNED = "request_returned"
    REQUEST_REJECTED = "request_rejected"
    REQUEST_APPROVED = "request_approved"
    TASK_OVERDUE = "task_overdue"


class NotificationRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    request_id: uuid.UUID
    kind: NotificationKind
    title_snapshot: str
    read_at: datetime | None
    created_at: datetime


class NotificationSummary(BaseModel):
    unread_count: int


class MarkAllResult(BaseModel):
    marked_count: int


class TaskBucket(StrEnum):
    OPEN = "open"
    COMPLETED = "completed"
    OVERDUE = "overdue"


class TaskRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    request_id: uuid.UUID
    title: str
    request_type: str
    status: str
    bucket: TaskBucket
    version: int
    created_at: datetime
    due_at: datetime
    decided_at: datetime | None


class NotificationPreferences(BaseModel):
    approval_requested: bool = True
    request_approved: bool = True
    request_rejected: bool = True
    request_returned: bool = True
    overdue_tasks: bool = True
    version: int = Field(default=1, gt=0)


class PreferenceUpdate(BaseModel):
    approval_requested: bool
    request_approved: bool
    request_rejected: bool
    request_returned: bool
    overdue_tasks: bool
    expected_version: int = Field(gt=0)


class RecentActivity(BaseModel):
    request_id: uuid.UUID
    title: str
    event_type: str
    actor_kind: str
    from_status: str | None
    to_status: str
    created_at: datetime


class DashboardSummary(BaseModel):
    unread_notifications: int
    pending_tasks: int
    overdue_tasks: int
    recent_activity: list[RecentActivity]
