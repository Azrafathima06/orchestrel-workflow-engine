"""The single retry/failure decision, shared by every path that can fail a task.

Two callers reach this code:

- the task runner, when a handler raises;
- the recovery sweeper, when a worker's lease expires (WorkerLost).

Both must produce identical accounting — same attempt numbering, same
backoff curve, same exhaustion rule — so the decision lives here once rather
than being reimplemented per call site. WorkerLost is deliberately an
ordinary RetriableError subclass, so worker loss inherits the retry policy
instead of needing a parallel mechanism.
"""

from __future__ import annotations

import random
import uuid
from collections.abc import Callable
from dataclasses import dataclass

from pydantic import ValidationError
from sqlalchemy import Integer, cast, func, select, update
from sqlalchemy.orm import Session

from app.core.retry import ErrorClassification, RetryPolicy, classify_error, next_backoff
from app.core.spec import WorkflowSpec
from app.core.states import AttemptStatus, TaskStatus
from app.db.models import TaskAttempt, TaskRun, WorkflowRun
from app.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class FailureOutcome:
    """What the caller must do after the transaction commits."""

    retried: bool
    delay_seconds: float | None = None
    next_attempt: int | None = None
    # True when the task reached a terminal state, so the run needs
    # reconciling. False while RETRYING: the branch has not advanced and the
    # DAG must not move on.
    needs_reconcile: bool = False


def resolve_retry_policy(session: Session, task: TaskRun) -> RetryPolicy:
    """Retry policy in force for this task, read from the run's frozen spec.

    Resolution order is task-level policy -> workflow defaults -> system
    defaults, and it is evaluated against `workflow_run.spec_snapshot`
    rather than the live definition: a run must keep behaving the way it was
    defined when it was triggered, even if the definition changes later.

    task_run.max_attempts (resolved at materialisation) stays authoritative
    for the attempt ceiling, so the exhaustion rule cannot drift from what
    the API already reported.
    """
    snapshot = session.execute(
        select(WorkflowRun.spec_snapshot).where(WorkflowRun.id == task.run_id)
    ).scalar_one_or_none()

    if not snapshot:
        return RetryPolicy(max_attempts=task.max_attempts)

    try:
        spec = WorkflowSpec.model_validate(snapshot)
    except ValidationError:
        # A snapshot that no longer parses should not stop us failing a task
        # correctly; fall back to the ceiling already on the row.
        logger.warning("retry_policy_snapshot_unparseable", task_run_id=str(task.id))
        return RetryPolicy(max_attempts=task.max_attempts)

    task_spec = next((t for t in spec.tasks if t.key == task.task_key), None)
    if task_spec is None:
        return RetryPolicy(max_attempts=task.max_attempts)

    policy = spec.effective_retry_policy(task_spec)
    # Keep the ceiling the row advertises, in case the two ever disagree.
    return policy.model_copy(update={"max_attempts": task.max_attempts})


def apply_failure(
    session: Session,
    task_run_id: uuid.UUID,
    attempt_number: int,
    exc: Exception,
    policy: RetryPolicy,
    rand: Callable[[], float] = random.random,
    traceback_text: str | None = None,
) -> FailureOutcome | None:
    """Record an attempt failure and decide retry vs. terminal failure.

    Runs inside the caller's transaction. Returns None if the guarded writes
    matched no rows, meaning this attempt was already superseded (the
    caller should treat that as an orphaned completion and change nothing).
    """
    error_type = type(exc).__name__
    error_message = str(exc)[:2000]
    classification = classify_error(exc)

    finished = session.execute(
        update(TaskAttempt)
        .where(
            TaskAttempt.task_run_id == task_run_id,
            TaskAttempt.attempt_number == attempt_number,
            TaskAttempt.status == AttemptStatus.RUNNING,
        )
        .values(
            status=AttemptStatus.FAILED,
            finished_at=func.now(),
            duration_ms=cast(
                func.extract("epoch", func.now() - TaskAttempt.started_at) * 1000, Integer
            ),
            error_type=error_type,
            error_message=error_message,
            traceback=traceback_text,
        )
    ).rowcount

    if finished != 1:
        return None

    retriable = classification == ErrorClassification.RETRIABLE
    attempts_remain = attempt_number < policy.max_attempts

    if retriable and attempts_remain:
        delay = next_backoff(attempt_number, policy, rand)
        updated = session.execute(
            update(TaskRun)
            .where(
                TaskRun.id == task_run_id,
                TaskRun.status == TaskStatus.RUNNING,
                TaskRun.attempt_count == attempt_number,
            )
            .values(
                status=TaskStatus.RETRYING,
                # Anchored to the database clock: `delay` is a relative
                # duration computed in Python, but the persisted instant is
                # produced by PostgreSQL so every process compares against
                # the same clock.
                next_attempt_at=func.now() + func.make_interval(0, 0, 0, 0, 0, 0, delay),
                lease_expires_at=None,
                error_type=error_type,
                error_message=error_message,
                # finished_at deliberately NOT set: the task has not
                # finished, it is waiting to run again.
            )
        ).rowcount

        if updated != 1:
            return None

        return FailureOutcome(
            retried=True,
            delay_seconds=delay,
            next_attempt=attempt_number + 1,
            needs_reconcile=False,
        )

    updated = session.execute(
        update(TaskRun)
        .where(
            TaskRun.id == task_run_id,
            TaskRun.status == TaskStatus.RUNNING,
            TaskRun.attempt_count == attempt_number,
        )
        .values(
            status=TaskStatus.FAILED,
            finished_at=func.now(),
            duration_ms=cast(
                func.extract("epoch", func.now() - TaskRun.started_at) * 1000, Integer
            ),
            lease_expires_at=None,
            next_attempt_at=None,
            error_type=error_type,
            error_message=error_message,
        )
    ).rowcount

    if updated != 1:
        return None

    return FailureOutcome(retried=False, needs_reconcile=True)
