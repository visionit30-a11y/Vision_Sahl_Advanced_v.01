"""Typed contracts for the shared workflow lifecycle."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

WORKFLOW_TYPE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


class WorkflowStatus(StrEnum):
    DRAFT = "draft"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    RETURNED = "returned"


class WorkflowDecision(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    RETURN = "return"


class WorkflowCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=False)
    request_type: str = Field(min_length=1, max_length=63)
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=2000)
    approver_membership_id: uuid.UUID

    @field_validator("request_type")
    @classmethod
    def valid_type(cls, value: str) -> str:
        if WORKFLOW_TYPE.fullmatch(value) is None:
            raise ValueError("Invalid workflow request type.")
        return value

    @field_validator("title")
    @classmethod
    def non_blank_title(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Title must not be blank.")
        return value


class WorkflowUpdate(BaseModel):
    expected_version: int = Field(gt=0)
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=2000)
    approver_membership_id: uuid.UUID

    @field_validator("title")
    @classmethod
    def non_blank_title(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Title must not be blank.")
        return value


class WorkflowRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    tenant_id: uuid.UUID
    requester_membership_id: uuid.UUID
    approver_membership_id: uuid.UUID
    request_type: str
    title: str
    description: str
    status: WorkflowStatus
    version: int
    created_at: datetime
    updated_at: datetime
    submitted_at: datetime | None
    completed_at: datetime | None


class ApprovalTaskRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    request_id: uuid.UUID
    title: str
    request_type: str
    requester_membership_id: uuid.UUID
    status: str
    version: int
    created_at: datetime
    due_at: datetime


class WorkflowEventRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    actor_membership_id: uuid.UUID
    actor_kind: str
    event_type: str
    from_status: str | None
    to_status: str
    note: str | None
    created_at: datetime
