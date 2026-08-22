"""ORM -> Pydantic conversion, in one place so route handlers stay thin."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas import AttemptDetail, RunDetail, TaskRunDetail, TaskRunSummary
from app.core.states import AttemptStatus
from app.db.models import TaskAttempt, TaskRun, WorkflowRun


def _latest_worker_id(session: Session, task_run_id) -> str | None:
    """Worker that ran this task's most recent attempt, if any.

    Read from task_attempt rather than stored on task_run: the attempt row
    is the actual execution evidence, and with retries (M5) a task can have
    been executed by several different workers.
    """
    return session.execute(
        select(TaskAttempt.worker_id)
        .where(TaskAttempt.task_run_id == task_run_id)
        .order_by(TaskAttempt.attempt_number.desc())
        .limit(1)
    ).scalar_one_or_none()


def task_to_summary(session: Session, task: TaskRun) -> TaskRunSummary:
    return TaskRunSummary(
        id=task.id,
        task_key=task.task_key,
        handler=task.handler,
        status=task.status,
        depends_on=list(task.depends_on),
        attempt_count=task.attempt_count,
        max_attempts=task.max_attempts,
        worker_id=_latest_worker_id(session, task.id),
        started_at=task.started_at,
        finished_at=task.finished_at,
        duration_ms=task.duration_ms,
        output=task.output,
        error_type=task.error_type,
        error_message=task.error_message,
    )


def run_to_detail(session: Session, run: WorkflowRun) -> RunDetail:
    tasks = (
        session.execute(select(TaskRun).where(TaskRun.run_id == run.id).order_by(TaskRun.task_key))
        .scalars()
        .all()
    )
    return RunDetail(
        id=run.id,
        definition_key=run.definition_key,
        status=run.status,
        trigger_type=run.trigger_type,
        params=run.params,
        created_at=run.created_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
        duration_ms=run.duration_ms,
        error=run.error,
        tasks=[task_to_summary(session, t) for t in tasks],
    )


def task_to_detail(session: Session, task: TaskRun) -> TaskRunDetail:
    attempts = (
        session.execute(
            select(TaskAttempt)
            .where(TaskAttempt.task_run_id == task.id)
            .order_by(TaskAttempt.attempt_number)
        )
        .scalars()
        .all()
    )
    summary = task_to_summary(session, task)
    return TaskRunDetail(
        **summary.model_dump(),
        params=task.params,
        timeout_seconds=task.timeout_seconds,
        attempts=[
            AttemptDetail(
                attempt_number=a.attempt_number,
                status=AttemptStatus(a.status).value,
                worker_id=a.worker_id,
                celery_task_id=a.celery_task_id,
                started_at=a.started_at,
                finished_at=a.finished_at,
                duration_ms=a.duration_ms,
                error_type=a.error_type,
                error_message=a.error_message,
            )
            for a in attempts
        ],
    )
