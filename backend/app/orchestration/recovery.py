"""Recovery: reconstructing, from PostgreSQL alone, work the broker lost.

The engine commits state and *then* publishes. That ordering is deliberate —
a message describing uncommitted state would be rejected as stale — but it
opens a window: a process can die after COMMIT and before publish, leaving
the database saying QUEUED with no message anywhere. Redis can also simply
lose messages (a restart, an eviction, a non-persistent free-tier instance).

Rather than prevent that window with a transactional outbox, we detect it.
An outbox would close exactly one of the four holes below and still require
this sweeper for the others, so detection strictly dominates here. The cost
is bounded latency on a rare path, never correctness.

Four independent responsibilities, each a small guarded query:

  1. stale QUEUED     — committed but never delivered, or delivery lost.
  2. expired lease    — a worker took an attempt and never came back.
  3. overdue RETRYING — the delayed release message vanished.
  4. stalled run      — a reconcile message vanished; recompute from state.

Every claim is a compare-and-set against observed values, so two sweepers
(or a sweeper racing the normal path) cannot both act.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import Integer, cast, func, select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.errors import UndeliverableTask, WorkerLost
from app.core.states import AttemptStatus, TaskStatus, WorkflowStatus
from app.db.models import TaskAttempt, TaskRun, WorkflowRun
from app.logging import get_logger
from app.orchestration.dispatch import Dispatcher
from app.orchestration.failure import apply_failure, resolve_retry_policy
from app.orchestration.release import try_release

logger = get_logger(__name__)
settings = get_settings()


@dataclass
class SweepReport:
    """Counts of what a sweep actually did, for logging and assertions."""

    queued_redispatched: int = 0
    undeliverable_failed: int = 0
    leases_reclaimed: int = 0
    retries_released: int = 0
    runs_reconciled: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def total_actions(self) -> int:
        return (
            self.queued_redispatched
            + self.undeliverable_failed
            + self.leases_reclaimed
            + self.retries_released
            + self.runs_reconciled
        )

    def as_dict(self) -> dict[str, int]:
        return {
            "queued_redispatched": self.queued_redispatched,
            "undeliverable_failed": self.undeliverable_failed,
            "leases_reclaimed": self.leases_reclaimed,
            "retries_released": self.retries_released,
            "runs_reconciled": self.runs_reconciled,
        }


def recovery_sweep(dispatcher: Dispatcher, session_factory) -> SweepReport:
    """Run every recovery responsibility once, with bounded work per pass."""
    report = SweepReport()

    recover_stale_queued(dispatcher, session_factory, report)
    recover_expired_leases(dispatcher, session_factory, report)
    recover_overdue_retries(dispatcher, session_factory, report)
    reconcile_stalled_runs(dispatcher, session_factory, report)

    if report.total_actions:
        logger.info("recovery_sweep_completed", **report.as_dict())
    else:
        logger.debug("recovery_sweep_completed", **report.as_dict())

    return report


# ------------------------------------------------------------- 1. stale QUEUED


def recover_stale_queued(
    dispatcher: Dispatcher, session_factory, report: SweepReport
) -> SweepReport:
    """Re-dispatch QUEUED tasks whose message appears never to have arrived.

    Safe to be wrong: a task in QUEUED provably has not started (the only
    path into handler code is the runner's claim, which moves it out of
    QUEUED), so a redundant re-dispatch costs one message that the claim
    guard then rejects. That asymmetry is why the threshold can be
    aggressive here but must be conservative for RUNNING.
    """
    with session_factory() as session:
        candidates = session.execute(
            select(
                TaskRun.id,
                TaskRun.run_id,
                TaskRun.task_key,
                TaskRun.attempt_count,
                TaskRun.queued_at,
                TaskRun.dispatch_count,
            )
            .join(WorkflowRun, WorkflowRun.id == TaskRun.run_id)
            .where(
                TaskRun.status == TaskStatus.QUEUED,
                WorkflowRun.status == WorkflowStatus.RUNNING,
                TaskRun.queued_at
                < func.now()
                - func.make_interval(0, 0, 0, 0, 0, 0, settings.queued_stale_seconds),
            )
            .order_by(TaskRun.queued_at)
            .limit(settings.sweep_batch)
        ).all()
        session.rollback()

    for task_id, run_id, task_key, attempt_count, queued_at, dispatch_count in candidates:
        if dispatch_count >= settings.max_dispatch_attempts:
            _fail_undeliverable(
                dispatcher, session_factory, task_id, run_id, task_key, attempt_count, report
            )
            continue

        with session_factory() as session:
            # Optimistic claim: `queued_at` doubles as a version token, so a
            # concurrent sweeper that already re-dispatched this task makes
            # this update match zero rows.
            claimed = session.execute(
                update(TaskRun)
                .where(
                    TaskRun.id == task_id,
                    TaskRun.status == TaskStatus.QUEUED,
                    TaskRun.attempt_count == attempt_count,
                    TaskRun.queued_at == queued_at,
                )
                .values(queued_at=func.now(), dispatch_count=TaskRun.dispatch_count + 1)
                .returning(TaskRun.dispatch_count)
            ).scalar_one_or_none()

            if claimed is None:
                session.rollback()
                continue
            session.commit()

        report.queued_redispatched += 1
        logger.warning(
            "queued_task_redispatched",
            run_id=str(run_id),
            task_run_id=str(task_id),
            task_key=task_key,
            attempt=attempt_count + 1,
            dispatch_count=claimed,
        )
        dispatcher.dispatch_task(task_id, attempt_count + 1)

    return report


def _fail_undeliverable(
    dispatcher: Dispatcher,
    session_factory,
    task_id: uuid.UUID,
    run_id: uuid.UUID,
    task_key: str,
    attempt_count: int,
    report: SweepReport,
) -> None:
    """Circuit breaker: stop re-dispatching a task nothing will ever accept."""
    with session_factory() as session:
        failed = session.execute(
            update(TaskRun)
            .where(
                TaskRun.id == task_id,
                TaskRun.status == TaskStatus.QUEUED,
                TaskRun.attempt_count == attempt_count,
            )
            .values(
                status=TaskStatus.FAILED,
                finished_at=func.now(),
                queued_at=None,
                error_type=UndeliverableTask.__name__,
                error_message=(
                    f"task could not be delivered to a worker after "
                    f"{settings.max_dispatch_attempts} dispatch attempts"
                ),
            )
        ).rowcount
        if failed != 1:
            session.rollback()
            return
        session.commit()

    report.undeliverable_failed += 1
    logger.error(
        "undeliverable_task",
        run_id=str(run_id),
        task_run_id=str(task_id),
        task_key=task_key,
        dispatch_attempts=settings.max_dispatch_attempts,
    )
    dispatcher.dispatch_reconcile(run_id)


# ---------------------------------------------------------- 2. expired leases


def recover_expired_leases(
    dispatcher: Dispatcher, session_factory, report: SweepReport
) -> SweepReport:
    """Reclaim attempts whose worker stopped reporting.

    Deliberately does NOT re-deliver the same attempt. A RUNNING task may
    still be executing (a frozen container, a long GC pause), so re-running
    that exact attempt could duplicate side effects and would let a
    resurrected worker's completion race ours. Instead the attempt is failed
    as WorkerLost and the ordinary retry path mints attempt N+1 — after
    which the zombie's completion CAS can no longer match.
    """
    with session_factory() as session:
        candidates = session.execute(
            select(TaskRun.id, TaskRun.run_id, TaskRun.task_key, TaskRun.attempt_count)
            .join(WorkflowRun, WorkflowRun.id == TaskRun.run_id)
            .where(
                TaskRun.status == TaskStatus.RUNNING,
                WorkflowRun.status == WorkflowStatus.RUNNING,
                TaskRun.lease_expires_at.is_not(None),
                TaskRun.lease_expires_at < func.now(),
            )
            .order_by(TaskRun.lease_expires_at)
            .limit(settings.sweep_batch)
        ).all()
        session.rollback()

    for task_id, run_id, task_key, attempt_count in candidates:
        with session_factory() as session:
            task = session.get(TaskRun, task_id)
            if task is None:
                session.rollback()
                continue

            worker_id = session.execute(
                select(TaskAttempt.worker_id).where(
                    TaskAttempt.task_run_id == task_id,
                    TaskAttempt.attempt_number == attempt_count,
                )
            ).scalar_one_or_none()

            policy = resolve_retry_policy(session, task)
            outcome = apply_failure(
                session,
                task_run_id=task_id,
                attempt_number=attempt_count,
                exc=WorkerLost(
                    f"worker lease expired; attempt {attempt_count} abandoned"
                    + (f" (last seen on {worker_id})" if worker_id else "")
                ),
                policy=policy,
                traceback_text=None,
            )

            if outcome is None:
                # The attempt completed between our query and this write.
                session.rollback()
                continue
            session.commit()

        report.leases_reclaimed += 1
        logger.warning(
            "worker_lease_expired",
            run_id=str(run_id),
            task_run_id=str(task_id),
            task_key=task_key,
            attempt=attempt_count,
            worker_id=worker_id,
            retried=outcome.retried,
        )

        if outcome.retried:
            dispatcher.dispatch_release_retry(
                task_id, outcome.next_attempt, outcome.delay_seconds or 0.0
            )
        else:
            dispatcher.dispatch_reconcile(run_id)

    return report


# --------------------------------------------------------- 3. overdue RETRYING


def recover_overdue_retries(
    dispatcher: Dispatcher, session_factory, report: SweepReport
) -> SweepReport:
    """Release RETRYING tasks whose delayed message never arrived.

    Waits an extra grace period beyond `next_attempt_at` so that in the
    healthy case the countdown message always wins and this never fires.
    Uses the identical CAS as `release_retry`, so if both do run, exactly
    one succeeds.
    """
    with session_factory() as session:
        candidates = session.execute(
            select(TaskRun.id, TaskRun.run_id, TaskRun.task_key, TaskRun.attempt_count)
            .join(WorkflowRun, WorkflowRun.id == TaskRun.run_id)
            .where(
                TaskRun.status == TaskStatus.RETRYING,
                WorkflowRun.status == WorkflowStatus.RUNNING,
                TaskRun.next_attempt_at.is_not(None),
                TaskRun.next_attempt_at
                < func.now()
                - func.make_interval(0, 0, 0, 0, 0, 0, settings.retry_release_grace_seconds),
            )
            .order_by(TaskRun.next_attempt_at)
            .limit(settings.sweep_batch)
        ).all()
        session.rollback()

    for task_id, run_id, task_key, attempt_count in candidates:
        expected_attempt = attempt_count + 1
        with session_factory() as session:
            result = try_release(session, task_id, expected_attempt)
            if not result.released:
                session.rollback()
                continue
            session.commit()

        report.retries_released += 1
        logger.warning(
            "stale_retry_release_recovered",
            run_id=str(run_id),
            task_run_id=str(task_id),
            task_key=task_key,
            attempt=expected_attempt,
        )
        dispatcher.dispatch_task(task_id, expected_attempt)

    return report


# ------------------------------------------------------------ 4. stalled runs


def reconcile_stalled_runs(
    dispatcher: Dispatcher, session_factory, report: SweepReport
) -> SweepReport:
    """Re-reconcile runs that show no recent activity.

    The cheapest possible backstop for a lost reconcile message: reconcile
    is idempotent, so the worst case of a false positive is one no-op pass.
    A run is considered quiet when nothing is in flight and the most recent
    task activity is older than RUN_STALL_SECONDS.

    PENDING runs are included deliberately, not just RUNNING ones. A run is
    committed with all its tasks before its first reconcile message is
    published; if that message is lost (broker restart, process death in
    the window between commit and publish) the run would otherwise sit in
    PENDING forever with no other mechanism to notice it.
    """
    with session_factory() as session:
        stalled = session.execute(
            select(WorkflowRun.id)
            .where(
                WorkflowRun.status.in_([WorkflowStatus.PENDING, WorkflowStatus.RUNNING]),
                # Nothing currently moving.
                ~select(TaskRun.id)
                .where(
                    TaskRun.run_id == WorkflowRun.id,
                    TaskRun.status.in_(
                        [TaskStatus.QUEUED, TaskStatus.RUNNING, TaskStatus.RETRYING]
                    ),
                )
                .exists(),
                # And no recent finishes.
                func.coalesce(
                    select(func.max(TaskRun.finished_at))
                    .where(TaskRun.run_id == WorkflowRun.id)
                    .scalar_subquery(),
                    WorkflowRun.created_at,
                )
                < func.now() - func.make_interval(0, 0, 0, 0, 0, 0, settings.run_stall_seconds),
            )
            .limit(settings.sweep_batch)
        ).scalars().all()
        session.rollback()

    for run_id in stalled:
        report.runs_reconciled += 1
        logger.warning("stalled_run_reconciled", run_id=str(run_id))
        dispatcher.dispatch_reconcile(run_id)

    return report


def mark_attempt_lost(session: Session, task_run_id: uuid.UUID, attempt_number: int) -> bool:
    """Close out a RUNNING attempt row as WorkerLost. Used by tests and tooling."""
    return (
        session.execute(
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
                error_type=WorkerLost.__name__,
            )
        ).rowcount
        == 1
    )
