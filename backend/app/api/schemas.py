"""Pydantic response schemas. ORM objects never cross the API boundary."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.core.states import TaskStatus, TriggerType, WorkflowStatus


class WorkflowSummary(BaseModel):
    key: str
    name: str
    description: str | None
    version: int
    is_active: bool
    task_count: int


class WorkflowDetail(BaseModel):
    key: str
    name: str
    description: str | None
    version: int
    is_active: bool
    spec: dict[str, Any]


class TriggerRunRequest(BaseModel):
    params: dict[str, Any] = {}


class TaskRunSummary(BaseModel):
    id: uuid.UUID
    task_key: str
    handler: str
    status: TaskStatus
    depends_on: list[str]
    attempt_count: int
    max_attempts: int
    worker_id: str | None
    started_at: datetime | None
    finished_at: datetime | None
    duration_ms: int | None
    output: dict[str, Any] | None
    error_type: str | None
    error_message: str | None


class RunDetail(BaseModel):
    id: uuid.UUID
    definition_key: str
    status: WorkflowStatus
    trigger_type: TriggerType
    params: dict[str, Any]
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    duration_ms: int | None
    error: str | None
    tasks: list[TaskRunSummary]


class AttemptDetail(BaseModel):
    attempt_number: int
    status: str
    worker_id: str
    celery_task_id: str | None
    started_at: datetime
    finished_at: datetime | None
    duration_ms: int | None
    error_type: str | None
    error_message: str | None


class TaskRunDetail(TaskRunSummary):
    params: dict[str, Any]
    timeout_seconds: int
    attempts: list[AttemptDetail]
