"""Batch SQL aggregate queries shared by the list/detail/stats endpoints.

Kept separate from serializers.py: these are genuine grouped aggregates over
potentially many rows (per-run task counts, retry sums, worker activity),
not one-object ORM -> Pydantic mapping. Each is a single query regardless of
how many runs/tasks it covers, to avoid N+1 queries on a list page.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.schemas import TaskCounts
from app.db.models import TaskRun


def task_counts_for_runs(
    session: Session, run_ids: list[uuid.UUID]
) -> dict[uuid.UUID, TaskCounts]:
    """Per-status task counts for every run_id given, in one grouped query."""
    counts: dict[uuid.UUID, TaskCounts] = {rid: TaskCounts() for rid in run_ids}
    if not run_ids:
        return counts

    rows = session.execute(
        select(TaskRun.run_id, TaskRun.status, func.count())
        .where(TaskRun.run_id.in_(run_ids))
        .group_by(TaskRun.run_id, TaskRun.status)
    ).all()
    for run_id, status, n in rows:
        tc = counts[run_id]
        setattr(tc, status.value, n)
        tc.total += n
    return counts


def retry_counts_for_runs(session: Session, run_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    """Retries per run: sum over its tasks of (attempt_count - 1), floored at 0.

    A task with attempt_count=1 succeeded or failed on its first try and
    contributes 0; attempt_count=3 means 2 retries happened.
    """
    result: dict[uuid.UUID, int] = {rid: 0 for rid in run_ids}
    if not run_ids:
        return result

    retries_expr = func.sum(func.greatest(TaskRun.attempt_count - 1, 0))
    rows = session.execute(
        select(TaskRun.run_id, retries_expr)
        .where(TaskRun.run_id.in_(run_ids))
        .group_by(TaskRun.run_id)
    ).all()
    for run_id, total in rows:
        result[run_id] = int(total or 0)
    return result
