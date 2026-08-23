"""Releasing a RETRYING task once its backoff has genuinely elapsed.

The distinction this module enforces:

  RETRYING — waiting for `next_attempt_at`, which is persisted and
             authoritative. Not eligible to run.
  QUEUED   — eligible, and a message exists (or the sweeper will make one).

Only the persisted `next_attempt_at`, compared against the *database* clock,
decides when that transition may happen. A release message that arrives
early, twice, or out of order cannot shorten a backoff — it simply fails the
guard. That is what makes the retry timing shown to a user real rather than
decorative.

Both `release_retry` (the delayed message) and the recovery sweeper call
`try_release`, so the two paths cannot both win.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.states import TaskStatus
from app.db.models import TaskRun
from app.logging import get_logger
from app.orchestration.dispatch import Dispatcher

logger = get_logger(__name__)

# A release message that lost its race with the clock reschedules itself
# rather than being dropped, but only a bounded number of times; after that
# the recovery sweeper owns the task.
MAX_EARLY_RESCHEDULES = 3


@dataclass(frozen=True)
class ReleaseResult:
    released: bool
    reason: str
    remaining_seconds: float | None = None


def try_release(
    session: Session, task_run_id: uuid.UUID, expected_attempt: int
) -> ReleaseResult:
    """Guarded RETRYING -> QUEUED transition, inside the caller's transaction.

    Returns released=True only for the single caller that wins the CAS.
    """
    released = session.execute(
        update(TaskRun)
        .where(
            TaskRun.id == task_run_id,
            TaskRun.status == TaskStatus.RETRYING,
            TaskRun.attempt_count == expected_attempt - 1,
            # The load-bearing predicate: eligibility is decided by the
            # persisted timestamp against the database clock, never by when
            # a message happened to arrive.
            TaskRun.next_attempt_at <= func.now(),
        )
        .values(
            status=TaskStatus.QUEUED,
            queued_at=func.now(),
            dispatch_count=1,
            next_attempt_at=None,
        )
        .returning(TaskRun.id)
    ).scalar_one_or_none()

    if released is not None:
        return ReleaseResult(released=True, reason="released")

    # Zero rows: work out why, so early delivery can be distinguished from
    # a genuinely stale message.
    row = session.execute(
        select(
            TaskRun.status,
            TaskRun.attempt_count,
            func.extract("epoch", TaskRun.next_attempt_at - func.now()),
        ).where(TaskRun.id == task_run_id)
    ).one_or_none()

    if row is None:
        return ReleaseResult(released=False, reason="unknown_task")

    status, attempt_count, remaining = row

    if status != TaskStatus.RETRYING:
        return ReleaseResult(released=False, reason=f"not_retrying:{status.value}")
    if attempt_count != expected_attempt - 1:
        return ReleaseResult(released=False, reason="attempt_mismatch")
    if remaining is not None and remaining > 0:
        return ReleaseResult(
            released=False, reason="too_early", remaining_seconds=float(remaining)
        )
    return ReleaseResult(released=False, reason="lost_race")


def release_retry_task(
    task_run_id: uuid.UUID,
    expected_attempt: int,
    dispatcher: Dispatcher,
    session_factory,
    reschedule_count: int = 0,
) -> None:
    """Handle one delayed release message end to end."""
    log = logger.bind(task_run_id=str(task_run_id), attempt=expected_attempt)

    with session_factory() as session:
        result = try_release(session, task_run_id, expected_attempt)
        if result.released:
            session.commit()
        else:
            session.rollback()

    if result.released:
        log.info("retry_released")
        # Strictly after commit.
        dispatcher.dispatch_task(task_run_id, expected_attempt)
        return

    if result.reason == "too_early":
        remaining = (result.remaining_seconds or 0.0) + 0.5
        if reschedule_count < MAX_EARLY_RESCHEDULES:
            log.info(
                "early_retry_release",
                remaining_seconds=round(remaining, 3),
                reschedule_count=reschedule_count + 1,
            )
            dispatcher.dispatch_release_retry(task_run_id, expected_attempt, remaining)
        else:
            # Give up rescheduling; the sweeper will pick this up once
            # next_attempt_at is overdue by the grace period.
            log.warning("early_retry_release_exhausted", remaining_seconds=round(remaining, 3))
        return

    log.info("stale_retry_release", reason=result.reason)
