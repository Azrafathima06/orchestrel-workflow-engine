"""ORM -> Pydantic conversion, in one place so route handlers stay thin."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.aggregates import retry_counts_for_runs, task_counts_for_runs
from app.api.schemas import (
    AttemptDetail,
    RunDetail,
    RunSummary,
    TaskCounts,
    TaskRef,
    TaskRunDetail,
    TaskRunSummary,
    WorkflowEdge,
)
from app.config import get_settings
from app.core.states import AttemptStatus
from app.db.models import TaskAttempt, TaskRun, WorkflowRun

settings = get_settings()

# Absolute paths inside the container add nothing for a reader and leak the
# deployment's internal layout. The frames themselves are genuinely useful
# observability, so we keep them and rewrite only the path prefix.
_PATH_PREFIXES = ("/app/", "/opt/venv/lib/python3.12/site-packages/")


def sanitize_traceback(text: str | None) -> str | None:
    """Strip absolute container paths from a persisted traceback.

    Development keeps full paths (they are clickable in an editor);
    production shows repo-relative frames only. Never touches the exception
    type or message, which are the parts a viewer actually reasons about.
    """
    if not text or not settings.is_production:
        return text

    cleaned = text
    for prefix in _PATH_PREFIXES:
        cleaned = cleaned.replace(f'File "{prefix}', 'File "')
    return cleaned


def spec_snapshot_to_edges(spec: dict[str, Any]) -> list[WorkflowEdge]:
    """Dependency edges straight from a frozen spec document.

    Used for both live workflow definitions and a run's frozen
    spec_snapshot, so a run's DAG always renders exactly as it looked when
    triggered even if the definition has since changed.
    """
    edges: list[WorkflowEdge] = []
    for task in spec.get("tasks", []):
        for dep in task.get("depends_on", []):
            edges.append(WorkflowEdge(source=dep, target=task["key"]))
    return edges


def _latest_worker_id(session: Session, task_run_id) -> str | None:
    """Worker that ran this task's most recent attempt, if any.

    Read from task_attempt rather than stored on task_run: the attempt row
    is the actual execution evidence, and with retries a task can have been
    executed by several different workers.
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
        next_attempt_at=task.next_attempt_at,
        dispatch_count=task.dispatch_count,
        worker_id=_latest_worker_id(session, task.id),
        started_at=task.started_at,
        finished_at=task.finished_at,
        duration_ms=task.duration_ms,
        output=task.output,
        error_type=task.error_type,
        error_message=task.error_message,
    )


def run_to_summary(
    run: WorkflowRun,
    workflow_name: str,
    task_counts: TaskCounts,
    retry_count: int,
) -> RunSummary:
    return RunSummary(
        id=run.id,
        definition_key=run.definition_key,
        workflow_name=workflow_name,
        status=run.status,
        trigger_type=run.trigger_type,
        created_at=run.created_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
        duration_ms=run.duration_ms,
        retry_count=retry_count,
        error=run.error,
        task_counts=task_counts,
    )


def run_to_detail(session: Session, run: WorkflowRun, workflow_name: str) -> RunDetail:
    tasks = (
        session.execute(select(TaskRun).where(TaskRun.run_id == run.id).order_by(TaskRun.task_key))
        .scalars()
        .all()
    )
    counts = task_counts_for_runs(session, [run.id])[run.id]
    retries = retry_counts_for_runs(session, [run.id])[run.id]

    return RunDetail(
        id=run.id,
        definition_key=run.definition_key,
        workflow_name=workflow_name,
        status=run.status,
        trigger_type=run.trigger_type,
        params=run.params,
        created_at=run.created_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
        duration_ms=run.duration_ms,
        error=run.error,
        retry_count=retries,
        task_counts=counts,
        tasks=[task_to_summary(session, t) for t in tasks],
        edges=spec_snapshot_to_edges(run.spec_snapshot),
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

    all_tasks = (
        session.execute(select(TaskRun).where(TaskRun.run_id == task.run_id)).scalars().all()
    )
    by_key = {t.task_key: t for t in all_tasks}

    dependencies = [
        TaskRef(task_run_id=by_key[dep].id, task_key=dep, status=by_key[dep].status)
        for dep in task.depends_on
        if dep in by_key
    ]
    dependents = [
        TaskRef(task_run_id=t.id, task_key=t.task_key, status=t.status)
        for t in all_tasks
        if task.task_key in t.depends_on
    ]

    summary = task_to_summary(session, task)
    return TaskRunDetail(
        **summary.model_dump(),
        params=task.params,
        timeout_seconds=task.timeout_seconds,
        dependencies=dependencies,
        dependents=dependents,
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
                traceback=sanitize_traceback(a.traceback),
                logs=a.logs,
            )
            for a in attempts
        ],
    )
