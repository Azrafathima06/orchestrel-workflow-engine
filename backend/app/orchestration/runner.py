"""Executes exactly one attempt of one task.

Three phases, deliberately separated by transaction boundaries:

  A. CLAIM    — short transaction. Atomically move QUEUED -> RUNNING and
                create the task_attempt row. Losing this race means the
                delivery is stale; the handler must not run.
  B. EXECUTE  — NO transaction held. Handler computation can take seconds;
                holding a database connection (and on Postgres, a row lock)
                across it would be a self-inflicted scalability bug.
  C. COMPLETE — short transaction. Guarded write of the outcome.

The guards in A and C are what make at-least-once delivery safe: a duplicate
message cannot execute the same attempt twice, and a worker whose attempt was
reclaimed cannot overwrite newer state.
"""

from __future__ import annotations

import contextlib
import json
import os
import signal
import socket
import threading
import traceback
import uuid
from typing import Any

from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy import Integer, cast, func, select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.errors import TaskTimeout
from app.core.states import AttemptStatus, TaskStatus
from app.db.models import TaskAttempt, TaskRun
from app.handlers import get_handler
from app.handlers.registry import HandlerContext
from app.logging import get_logger
from app.orchestration.dispatch import Dispatcher
from app.orchestration.failure import apply_failure, resolve_retry_policy

logger = get_logger(__name__)
settings = get_settings()


def worker_identity() -> str:
    """Real identity of the process executing this attempt: "hostname:pid".

    Inside Docker the hostname is the container ID, so scaled worker
    containers yield genuinely distinct identities, and the prefork child's
    PID distinguishes execution slots within one container. Nothing here is
    generated or randomised — this is the actual process doing the work,
    which is what makes task_attempt.worker_id real evidence of
    distribution.
    """
    return f"{socket.gethostname()}:{os.getpid()}"


class OutputTooLarge(Exception):
    """A handler returned more JSON than we are willing to persist."""


@contextlib.contextmanager
def handler_time_limit(seconds: int):
    """Interrupt a handler that overruns its task's configured timeout_seconds.

    This is what makes `timeout_seconds` mean something. Before it existed,
    the value only sized the recovery lease: a runaway handler kept burning
    CPU while the lease expired and the sweeper minted a NEW attempt, so a
    single request could multiply into several concurrent runaway loops on
    one machine.

    SIGALRM, deliberately: it interrupts the running Python frame in the
    process actually doing the work, so the CPU stops immediately and the
    exception travels the ordinary failure path (TaskTimeout subclasses
    RetriableError, so accounting, backoff, and the CAS completion guard all
    behave exactly as they do for any other retriable error).

    Falls back to no-op when it cannot arm — a non-main thread, or a
    platform without SIGALRM. Celery's own soft/hard `task_time_limit` is
    configured as the backstop for that case, so the guarantee degrades to
    the worker level rather than disappearing.
    """
    if seconds <= 0 or threading.current_thread() is not threading.main_thread():
        yield
        return
    if not hasattr(signal, "SIGALRM"):
        yield
        return

    def _on_alarm(signum, frame):
        raise TaskTimeout(f"handler exceeded its {seconds}s timeout")

    previous = signal.signal(signal.SIGALRM, _on_alarm)
    signal.alarm(seconds)
    try:
        yield
    except SoftTimeLimitExceeded as exc:
        # The Celery backstop fired first (only possible if the per-task
        # limit is longer than the worker-wide one). Present it as the same
        # domain error so attempt accounting does not depend on which
        # mechanism caught the overrun.
        raise TaskTimeout(f"handler exceeded its {seconds}s timeout") from exc
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


def _serialize_output(value: Any, limit: int) -> dict[str, Any]:
    """Validate that a handler's return value is JSON-safe and bounded."""
    if not isinstance(value, dict):
        raise TypeError(f"handler must return a dict, got {type(value).__name__}")

    try:
        encoded = json.dumps(value)
    except (TypeError, ValueError) as exc:
        raise TypeError(f"handler output is not JSON-serializable: {exc}") from exc

    size = len(encoded.encode())
    if size > limit:
        # Fail loudly rather than truncating: a silently trimmed output would
        # corrupt every downstream task that reads it.
        raise OutputTooLarge(f"handler output is {size} bytes, limit is {limit}")

    return value


def execute_task_attempt(
    task_run_id: uuid.UUID,
    expected_attempt: int,
    dispatcher: Dispatcher,
    session_factory,
    celery_task_id: str | None = None,
) -> None:
    """Run one attempt of one task, end to end."""
    worker_id = worker_identity()

    claim = _claim(session_factory, task_run_id, expected_attempt, worker_id, celery_task_id)
    if claim is None:
        return

    log = logger.bind(
        run_id=str(claim["run_id"]),
        task_run_id=str(task_run_id),
        task_key=claim["task_key"],
        attempt=claim["attempt_number"],
        worker_id=worker_id,
    )
    log.info("task_started", handler=claim["handler"])

    # ---- Phase B: execute with NO open transaction --------------------
    try:
        handler_fn = get_handler(claim["handler"])
        context = HandlerContext(
            run_id=str(claim["run_id"]),
            task_run_id=str(task_run_id),
            task_key=claim["task_key"],
            attempt_number=claim["attempt_number"],
            worker_id=worker_id,
            logger=log,
        )
        with handler_time_limit(claim["timeout_seconds"]):
            raw_output = handler_fn(context, claim["params"], claim["upstream_outputs"])
        output = _serialize_output(raw_output, settings.max_task_output_bytes)
    except Exception as exc:
        _complete_failure(
            session_factory,
            task_run_id,
            claim["attempt_number"],
            exc,
            claim["run_id"],
            dispatcher,
            log,
        )
        return

    _complete_success(session_factory, task_run_id, claim["attempt_number"], output, log)
    dispatcher.dispatch_reconcile(claim["run_id"])


def _claim(
    session_factory,
    task_run_id: uuid.UUID,
    expected_attempt: int,
    worker_id: str,
    celery_task_id: str | None,
) -> dict[str, Any] | None:
    """Phase A. Atomically take ownership of this attempt, or decline it.

    Returns the execution inputs on success, or None if this delivery is
    stale/duplicate and the handler must not run.
    """
    with session_factory() as session:
        lease_seconds = _lease_seconds(session, task_run_id)

        claimed = session.execute(
            update(TaskRun)
            .where(
                TaskRun.id == task_run_id,
                TaskRun.status == TaskStatus.QUEUED,
                TaskRun.attempt_count == expected_attempt - 1,
            )
            .values(
                status=TaskStatus.RUNNING,
                attempt_count=TaskRun.attempt_count + 1,
                started_at=func.coalesce(TaskRun.started_at, func.now()),
                queued_at=None,
                dispatch_count=0,
                lease_expires_at=func.now() + func.make_interval(0, 0, 0, 0, 0, 0, lease_seconds),
            )
            .returning(TaskRun.id)
        ).scalar_one_or_none()

        if claimed is None:
            session.rollback()
            logger.info(
                "stale_delivery",
                task_run_id=str(task_run_id),
                expected_attempt=expected_attempt,
                worker_id=worker_id,
                reason="task was not QUEUED at the expected attempt",
            )
            return None

        task = session.get(TaskRun, task_run_id)
        assert task is not None  # just updated it inside this transaction

        session.add(
            TaskAttempt(
                task_run_id=task_run_id,
                attempt_number=task.attempt_count,
                status=AttemptStatus.RUNNING,
                worker_id=worker_id,
                celery_task_id=celery_task_id,
                started_at=func.now(),
            )
        )

        upstream_outputs = _load_upstream_outputs(session, task)

        result = {
            "run_id": task.run_id,
            "task_key": task.task_key,
            "handler": task.handler,
            "params": dict(task.params or {}),
            "attempt_number": task.attempt_count,
            "upstream_outputs": upstream_outputs,
            "timeout_seconds": int(task.timeout_seconds or 0),
        }
        session.commit()

    logger.info(
        "task_claimed",
        task_run_id=str(task_run_id),
        task_key=result["task_key"],
        attempt=result["attempt_number"],
        worker_id=worker_id,
    )
    return result


def _lease_seconds(session: Session, task_run_id: uuid.UUID) -> int:
    """Lease length for this attempt: the task's own timeout plus grace."""
    timeout = session.execute(
        select(TaskRun.timeout_seconds).where(TaskRun.id == task_run_id)
    ).scalar_one_or_none()
    if timeout is None:
        return settings.lease_seconds_default
    return int(timeout) + settings.lease_grace_seconds


def _load_upstream_outputs(session: Session, task: TaskRun) -> dict[str, Any]:
    """Outputs of this task's direct dependencies, keyed by their task_key."""
    if not task.depends_on:
        return {}

    rows = session.execute(
        select(TaskRun.task_key, TaskRun.output).where(
            TaskRun.run_id == task.run_id, TaskRun.task_key.in_(list(task.depends_on))
        )
    ).all()
    return {key: output for key, output in rows if output is not None}


def _complete_success(
    session_factory,
    task_run_id: uuid.UUID,
    attempt_number: int,
    output: dict[str, Any],
    log,
) -> None:
    """Phase C (success). Guarded write of SUCCEEDED plus the attempt row."""
    with session_factory() as session:
        updated = session.execute(
            update(TaskRun)
            .where(
                TaskRun.id == task_run_id,
                TaskRun.status == TaskStatus.RUNNING,
                TaskRun.attempt_count == attempt_number,
            )
            .values(
                status=TaskStatus.SUCCEEDED,
                output=output,
                finished_at=func.now(),
                duration_ms=cast(
                    func.extract("epoch", func.now() - TaskRun.started_at) * 1000, Integer
                ),
                lease_expires_at=None,
            )
        ).rowcount

        if updated != 1:
            # Our attempt was reclaimed while we computed. The reclaiming
            # party's state is authoritative; discard our result rather than
            # regressing newer state.
            session.rollback()
            log.warning("orphaned_completion", outcome="succeeded_but_discarded")
            return

        _finish_attempt(session, task_run_id, attempt_number, AttemptStatus.SUCCEEDED)
        session.commit()

    log.info("task_succeeded")


def _complete_failure(
    session_factory,
    task_run_id: uuid.UUID,
    attempt_number: int,
    exc: Exception,
    run_id: uuid.UUID,
    dispatcher: Dispatcher,
    log,
) -> None:
    """Phase C (failure): record the attempt, then retry or fail terminally.

    The decision itself lives in app.orchestration.failure so that lease
    recovery (WorkerLost) produces identical accounting.
    """
    traceback_text = traceback.format_exc()[:8000]

    with session_factory() as session:
        task = session.get(TaskRun, task_run_id)
        if task is None:
            session.rollback()
            return

        policy = resolve_retry_policy(session, task)
        outcome = apply_failure(
            session,
            task_run_id=task_run_id,
            attempt_number=attempt_number,
            exc=exc,
            policy=policy,
            traceback_text=traceback_text,
        )

        if outcome is None:
            # Our attempt was superseded while we were failing it.
            session.rollback()
            log.warning("orphaned_completion", outcome="failed_but_discarded")
            return

        session.commit()

    error_type = type(exc).__name__

    if outcome.retried:
        # An expected retriable failure is not an ERROR-level event: the
        # traceback is persisted on the attempt row for inspection, and the
        # system is behaving as designed.
        log.info(
            "task_retry_scheduled",
            error_type=error_type,
            attempt=attempt_number,
            max_attempts=policy.max_attempts,
            next_attempt=outcome.next_attempt,
            delay_seconds=round(outcome.delay_seconds or 0.0, 3),
        )
        # Strictly after commit, and NOT a reconcile: the task has not
        # terminally failed, so its branch must not advance.
        dispatcher.dispatch_release_retry(
            task_run_id, outcome.next_attempt, outcome.delay_seconds or 0.0
        )
        return

    log.warning("task_failed", error_type=error_type, error_message=str(exc)[:200])
    dispatcher.dispatch_reconcile(run_id)


def _finish_attempt(
    session: Session,
    task_run_id: uuid.UUID,
    attempt_number: int,
    status: AttemptStatus,
    error_type: str | None = None,
    error_message: str | None = None,
    tb: str | None = None,
) -> None:
    session.execute(
        update(TaskAttempt)
        .where(
            TaskAttempt.task_run_id == task_run_id,
            TaskAttempt.attempt_number == attempt_number,
            TaskAttempt.status == AttemptStatus.RUNNING,
        )
        .values(
            status=status,
            finished_at=func.now(),
            duration_ms=cast(
                func.extract("epoch", func.now() - TaskAttempt.started_at) * 1000, Integer
            ),
            error_type=error_type,
            error_message=error_message,
            traceback=tb,
        )
    )
