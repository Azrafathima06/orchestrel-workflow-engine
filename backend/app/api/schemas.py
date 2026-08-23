"""Pydantic response schemas. ORM objects never cross the API boundary."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.core.states import TaskStatus, TriggerType, WorkflowStatus

# ------------------------------------------------------------------ shared


class TaskCounts(BaseModel):
    total: int = 0
    pending: int = 0
    queued: int = 0
    running: int = 0
    retrying: int = 0
    succeeded: int = 0
    failed: int = 0
    upstream_failed: int = 0
    cancelled: int = 0


class RunSummary(BaseModel):
    id: uuid.UUID
    definition_key: str
    workflow_name: str
    status: WorkflowStatus
    trigger_type: TriggerType
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    duration_ms: int | None
    retry_count: int
    error: str | None
    task_counts: TaskCounts


class TaskRef(BaseModel):
    task_run_id: uuid.UUID
    task_key: str
    status: TaskStatus


# --------------------------------------------------------------- workflows


class WorkflowSummary(BaseModel):
    key: str
    name: str
    description: str | None
    version: int
    is_active: bool
    task_count: int
    last_run: RunSummary | None
    recent_success_count: int
    recent_failure_count: int


class WorkflowNode(BaseModel):
    task_key: str
    handler: str
    depends_on: list[str]
    max_attempts: int
    timeout_seconds: int


class WorkflowEdge(BaseModel):
    source: str
    target: str


class WorkflowDetail(BaseModel):
    key: str
    name: str
    description: str | None
    version: int
    is_active: bool
    spec: dict[str, Any]
    params_schema: dict[str, Any]
    nodes: list[WorkflowNode]
    edges: list[WorkflowEdge]
    recent_runs: list[RunSummary]


class TriggerRunRequest(BaseModel):
    params: dict[str, Any] = {}


# --------------------------------------------------------------------- runs


class RunListResponse(BaseModel):
    items: list[RunSummary]
    next_cursor: str | None


class TaskRunSummary(BaseModel):
    id: uuid.UUID
    task_key: str
    handler: str
    status: TaskStatus
    depends_on: list[str]
    attempt_count: int
    max_attempts: int
    # Retry / recovery evidence, all read from persisted state.
    next_attempt_at: datetime | None
    dispatch_count: int
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
    workflow_name: str
    status: WorkflowStatus
    trigger_type: TriggerType
    params: dict[str, Any]
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    duration_ms: int | None
    error: str | None
    retry_count: int
    task_counts: TaskCounts
    tasks: list[TaskRunSummary]
    edges: list[WorkflowEdge]


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
    traceback: str | None
    logs: list[dict[str, Any]] | None


class TaskRunDetail(TaskRunSummary):
    params: dict[str, Any]
    timeout_seconds: int
    dependencies: list[TaskRef]
    dependents: list[TaskRef]
    attempts: list[AttemptDetail]


# -------------------------------------------------------------------- stats


class RunCounts(BaseModel):
    total: int
    succeeded: int
    failed: int
    running: int
    cancelled: int


class DailyCount(BaseModel):
    date: str
    succeeded: int
    failed: int


class StatsOverview(BaseModel):
    runs: RunCounts
    success_rate: float | None
    avg_duration_ms: float | None
    p95_duration_ms: float | None
    retries: int
    tasks_executed: int
    recovered_tasks: int
    daily: list[DailyCount]


# ------------------------------------------------------------------ workers


class WorkerObservation(BaseModel):
    worker_id: str
    first_seen_at: datetime
    last_seen_at: datetime
    attempts_total: int
    attempts_1h: int
    currently_running: int
    liveness: str  # "active" | "idle" | "stale"


# ----------------------------------------------------------------- health


class ComponentHealth(BaseModel):
    ok: bool
    latency_ms: float | None = None
    error: str | None = None


class ReadyResponse(BaseModel):
    database: ComponentHealth
    broker: ComponentHealth
    workers_observed_5m: int
