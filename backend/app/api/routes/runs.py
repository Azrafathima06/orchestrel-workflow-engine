"""Run and task history endpoints. Read-only; served entirely from PostgreSQL."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.aggregates import retry_counts_for_runs, task_counts_for_runs
from app.api.errors import AppError
from app.api.pagination import Cursor
from app.api.schemas import RunDetail, RunListResponse, TaskRunDetail
from app.api.serializers import run_to_detail, run_to_summary, task_to_detail
from app.core.states import TriggerType, WorkflowStatus
from app.db.models import TaskRun, WorkflowDefinition, WorkflowRun
from app.db.session import get_db

router = APIRouter(prefix="/api/v1/runs", tags=["runs"])

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


@router.get("", response_model=RunListResponse)
def list_runs(
    db: Session = Depends(get_db),
    status_filter: WorkflowStatus | None = Query(None, alias="status"),
    workflow: str | None = Query(None, description="filter by workflow definition key"),
    trigger: TriggerType | None = Query(None, description="filter by trigger_type"),
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    cursor: str | None = Query(None),
) -> RunListResponse:
    """Keyset-paginated run history, newest first.

    Ordered by (created_at DESC, id DESC) and never OFFSET — a cursor
    encodes the last row seen, so paging stays O(page size) at any depth
    and is stable even as new runs are inserted between requests.
    """
    query = select(WorkflowRun, WorkflowDefinition.name).join(
        WorkflowDefinition, WorkflowDefinition.id == WorkflowRun.definition_id
    )

    if status_filter is not None:
        query = query.where(WorkflowRun.status == status_filter)
    if workflow is not None:
        query = query.where(WorkflowRun.definition_key == workflow)
    if trigger is not None:
        query = query.where(WorkflowRun.trigger_type == trigger)

    if cursor is not None:
        c = Cursor.decode(cursor)
        query = query.where(
            (WorkflowRun.created_at < c.created_at)
            | ((WorkflowRun.created_at == c.created_at) & (WorkflowRun.id < c.id))
        )

    query = query.order_by(WorkflowRun.created_at.desc(), WorkflowRun.id.desc()).limit(limit + 1)
    rows = db.execute(query).all()

    has_more = len(rows) > limit
    page = rows[:limit]

    run_ids = [r.WorkflowRun.id for r in page]
    counts = task_counts_for_runs(db, run_ids)
    retries = retry_counts_for_runs(db, run_ids)

    items = [
        run_to_summary(
            row.WorkflowRun, row.name, counts[row.WorkflowRun.id], retries[row.WorkflowRun.id]
        )
        for row in page
    ]

    next_cursor = None
    if has_more and page:
        last = page[-1].WorkflowRun
        next_cursor = Cursor(created_at=last.created_at, id=last.id).encode()

    return RunListResponse(items=items, next_cursor=next_cursor)


def _get_run_with_name(db: Session, run_id: uuid.UUID) -> tuple[WorkflowRun, str]:
    row = db.execute(
        select(WorkflowRun, WorkflowDefinition.name)
        .join(WorkflowDefinition, WorkflowDefinition.id == WorkflowRun.definition_id)
        .where(WorkflowRun.id == run_id)
    ).first()
    if row is None:
        raise AppError("run_not_found", "run not found", status_code=404)
    return row.WorkflowRun, row.name


@router.get("/{run_id}", response_model=RunDetail)
def get_run(run_id: uuid.UUID, db: Session = Depends(get_db)) -> RunDetail:
    run, workflow_name = _get_run_with_name(db, run_id)
    return run_to_detail(db, run, workflow_name)


@router.get("/{run_id}/tasks/{task_run_id}", response_model=TaskRunDetail)
def get_task_run(
    run_id: uuid.UUID, task_run_id: uuid.UUID, db: Session = Depends(get_db)
) -> TaskRunDetail:
    task = db.execute(
        select(TaskRun).where(TaskRun.id == task_run_id, TaskRun.run_id == run_id)
    ).scalar_one_or_none()
    if task is None:
        raise AppError("task_not_found", "task run not found", status_code=404)
    return task_to_detail(db, task)
