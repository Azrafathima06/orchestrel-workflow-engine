"""Run and task history endpoints. Read-only; served entirely from PostgreSQL."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas import RunDetail, TaskRunDetail
from app.api.serializers import run_to_detail, task_to_detail
from app.db.models import TaskRun, WorkflowRun
from app.db.session import get_db

router = APIRouter(prefix="/api/v1/runs", tags=["runs"])


@router.get("/{run_id}", response_model=RunDetail)
def get_run(run_id: uuid.UUID, db: Session = Depends(get_db)) -> RunDetail:
    run = db.get(WorkflowRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return run_to_detail(db, run)


@router.get("/{run_id}/tasks/{task_run_id}", response_model=TaskRunDetail)
def get_task_run(
    run_id: uuid.UUID, task_run_id: uuid.UUID, db: Session = Depends(get_db)
) -> TaskRunDetail:
    task = db.execute(
        select(TaskRun).where(TaskRun.id == task_run_id, TaskRun.run_id == run_id)
    ).scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=404, detail="task run not found")
    return task_to_detail(db, task)
