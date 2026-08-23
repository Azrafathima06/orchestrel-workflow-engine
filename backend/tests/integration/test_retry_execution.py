"""Retry execution against real PostgreSQL.

The central assertion running through this file: a task waiting to retry is
persisted as RETRYING with a real `next_attempt_at`, and *stays* that way
until the database clock says it is due. Nothing here simulates a state
transition — handlers genuinely raise and the engine genuinely reacts.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select, text

from app.core.errors import PermanentError, RetriableError
from app.core.states import AttemptStatus, TaskStatus
from app.db.models import TaskAttempt, TaskRun
from app.handlers.registry import _REGISTRY
from app.orchestration.dispatch import RecordingDispatcher
from app.orchestration.reconciler import reconcile_run
from app.orchestration.release import release_retry_task, try_release
from app.orchestration.runner import execute_task_attempt
from tests.integration.factories import make_run, make_spec

FAST_RETRY = {
    "max_attempts": 4,
    "backoff_seconds": 0.05,
    "backoff_factor": 2.0,
    "max_backoff_seconds": 1.0,
    "jitter": 0.0,
}


@pytest.fixture
def attempts_log() -> list[int]:
    """Handlers whose behaviour depends on the attempt number."""
    seen: list[int] = []

    def fails_until(context, params, upstream_outputs):
        seen.append(context.attempt_number)
        if context.attempt_number < int(params.get("fail_until", 99)):
            raise RetriableError(f"transient failure on attempt {context.attempt_number}")
        return {"succeeded_on": context.attempt_number}

    def always_permanent(context, params, upstream_outputs):
        seen.append(context.attempt_number)
        raise PermanentError("this can never succeed")

    _REGISTRY["test.fails_until"] = fails_until
    _REGISTRY["test.permanent"] = always_permanent
    try:
        yield seen
    finally:
        for name in ("test.fails_until", "test.permanent"):
            _REGISTRY.pop(name, None)


def _spec(handler: str, params: dict | None = None, retry: dict | None = None) -> dict:
    task: dict = {"key": "solo", "handler": handler, "params": params or {}, "depends_on": []}
    if retry:
        task["retry"] = retry
    return make_spec("retry", [task])


def _task(session_factory, run_id, key="solo") -> TaskRun:
    with session_factory() as s:
        return s.execute(
            select(TaskRun).where(TaskRun.run_id == run_id, TaskRun.task_key == key)
        ).scalar_one()


def _attempts(session_factory, task_run_id) -> list[TaskAttempt]:
    with session_factory() as s:
        return list(
            s.execute(
                select(TaskAttempt)
                .where(TaskAttempt.task_run_id == task_run_id)
                .order_by(TaskAttempt.attempt_number)
            )
            .scalars()
            .all()
        )


def _db_now(session_factory):
    with session_factory() as s:
        return s.execute(select(func.now())).scalar_one()


def _start_and_run_first_attempt(session_factory, spec, dispatcher=None):
    with session_factory() as s:
        run = make_run(s, spec)
    reconcile_run(run.id, RecordingDispatcher(), session_factory)
    task = _task(session_factory, run.id)
    d = dispatcher or RecordingDispatcher()
    execute_task_attempt(task.id, 1, d, session_factory)
    return run, task, d


class TestRetryScheduling:
    def test_retriable_failure_enters_retrying_with_future_next_attempt_at(
        self, session_factory, attempts_log
    ) -> None:
        spec = _spec("test.fails_until", {"fail_until": 99}, FAST_RETRY)
        run, task, d = _start_and_run_first_attempt(session_factory, spec)

        after = _task(session_factory, run.id)
        assert after.status == TaskStatus.RETRYING
        assert after.attempt_count == 1
        assert after.next_attempt_at is not None
        # Compared against the DATABASE clock, not Python's.
        assert after.next_attempt_at > _db_now(session_factory)
        assert after.error_type == "RetriableError"
        # A retrying task has not finished.
        assert after.finished_at is None
        assert after.lease_expires_at is None

    def test_failed_attempt_row_is_recorded(self, session_factory, attempts_log) -> None:
        spec = _spec("test.fails_until", {"fail_until": 99}, FAST_RETRY)
        run, task, _ = _start_and_run_first_attempt(session_factory, spec)

        attempts = _attempts(session_factory, task.id)
        assert len(attempts) == 1
        assert attempts[0].status == AttemptStatus.FAILED
        assert attempts[0].error_type == "RetriableError"
        assert attempts[0].traceback is not None
        assert attempts[0].finished_at is not None

    def test_retry_schedules_a_release_not_a_reconcile(
        self, session_factory, attempts_log
    ) -> None:
        """A RETRYING task must not advance the DAG — its branch is still live."""
        spec = _spec("test.fails_until", {"fail_until": 99}, FAST_RETRY)
        run, task, d = _start_and_run_first_attempt(session_factory, spec)

        assert len(d.releases) == 1
        assert d.releases[0].task_run_id == task.id
        assert d.releases[0].expected_attempt == 2
        assert d.releases[0].delay_seconds == pytest.approx(0.05, abs=0.01)
        assert d.reconciles == [], "RETRYING must not trigger reconcile"

    def test_permanent_error_does_not_schedule_a_retry(
        self, session_factory, attempts_log
    ) -> None:
        spec = _spec("test.permanent", {}, FAST_RETRY)
        run, task, d = _start_and_run_first_attempt(session_factory, spec)

        after = _task(session_factory, run.id)
        assert after.status == TaskStatus.FAILED
        assert after.attempt_count == 1, "must not consume further attempts"
        assert after.error_type == "PermanentError"
        assert after.finished_at is not None
        assert d.releases == []
        assert len(d.reconciles) == 1
        assert len(attempts_log) == 1


class TestReleaseGating:
    def test_release_before_next_attempt_at_does_not_release(
        self, session_factory, attempts_log
    ) -> None:
        # A long backoff so the release is definitively premature.
        slow = {**FAST_RETRY, "backoff_seconds": 60.0, "max_backoff_seconds": 60.0}
        spec = _spec("test.fails_until", {"fail_until": 99}, slow)
        run, task, _ = _start_and_run_first_attempt(session_factory, spec)

        d = RecordingDispatcher()
        release_retry_task(task.id, 2, d, session_factory)

        after = _task(session_factory, run.id)
        assert after.status == TaskStatus.RETRYING, "must not release early"
        assert after.next_attempt_at is not None
        assert d.tasks == [], "no execution dispatched"
        # Instead of dropping the message, it reschedules itself.
        assert len(d.releases) == 1

    def test_valid_release_transitions_to_queued_exactly_once(
        self, session_factory, attempts_log
    ) -> None:
        spec = _spec("test.fails_until", {"fail_until": 99}, FAST_RETRY)
        run, task, _ = _start_and_run_first_attempt(session_factory, spec)
        _force_due(session_factory, task.id)

        d = RecordingDispatcher()
        release_retry_task(task.id, 2, d, session_factory)

        after = _task(session_factory, run.id)
        assert after.status == TaskStatus.QUEUED
        assert after.next_attempt_at is None
        assert after.dispatch_count == 1
        assert len(d.tasks) == 1
        assert d.tasks[0].expected_attempt == 2

    def test_duplicate_release_does_not_dispatch_twice(
        self, session_factory, attempts_log
    ) -> None:
        spec = _spec("test.fails_until", {"fail_until": 99}, FAST_RETRY)
        run, task, _ = _start_and_run_first_attempt(session_factory, spec)
        _force_due(session_factory, task.id)

        first, second = RecordingDispatcher(), RecordingDispatcher()
        release_retry_task(task.id, 2, first, session_factory)
        release_retry_task(task.id, 2, second, session_factory)

        assert len(first.tasks) == 1
        assert second.tasks == [], "duplicate release must be a no-op"

    def test_release_for_wrong_attempt_is_rejected(
        self, session_factory, attempts_log
    ) -> None:
        spec = _spec("test.fails_until", {"fail_until": 99}, FAST_RETRY)
        run, task, _ = _start_and_run_first_attempt(session_factory, spec)
        _force_due(session_factory, task.id)

        d = RecordingDispatcher()
        release_retry_task(task.id, 5, d, session_factory)

        assert _task(session_factory, run.id).status == TaskStatus.RETRYING
        assert d.tasks == []


def _force_due(session_factory, task_run_id) -> None:
    """Make a RETRYING task due now, using the database clock.

    Moves the persisted eligibility timestamp into the past rather than
    sleeping, so the test exercises the real gating predicate without
    waiting out a real backoff.
    """
    with session_factory() as s:
        s.execute(
            text("UPDATE task_run SET next_attempt_at = now() - interval '1 second' WHERE id = :i"),
            {"i": task_run_id},
        )
        s.commit()


class TestFullRetryLifecycle:
    def test_task_succeeds_after_two_failed_attempts(
        self, session_factory, attempts_log
    ) -> None:
        spec = _spec("test.fails_until", {"fail_until": 3}, FAST_RETRY)
        with session_factory() as s:
            run = make_run(s, spec)
        reconcile_run(run.id, RecordingDispatcher(), session_factory)
        task = _task(session_factory, run.id)

        # Drive three attempts by hand so the test controls timing rather
        # than waiting out real backoff.
        for attempt in (1, 2, 3):
            execute_task_attempt(task.id, attempt, RecordingDispatcher(), session_factory)
            current = _task(session_factory, run.id)
            if current.status == TaskStatus.RETRYING:
                _force_due(session_factory, task.id)
                release_retry_task(task.id, attempt + 1, RecordingDispatcher(), session_factory)

        final = _task(session_factory, run.id)
        assert final.status == TaskStatus.SUCCEEDED
        assert final.attempt_count == 3
        assert final.output == {"succeeded_on": 3}
        assert final.next_attempt_at is None
        assert attempts_log == [1, 2, 3]

        attempts = _attempts(session_factory, task.id)
        assert [a.attempt_number for a in attempts] == [1, 2, 3]
        assert [a.status for a in attempts] == [
            AttemptStatus.FAILED,
            AttemptStatus.FAILED,
            AttemptStatus.SUCCEEDED,
        ]

    def test_retry_exhaustion_fails_the_task(self, session_factory, attempts_log) -> None:
        spec = _spec("test.fails_until", {"fail_until": 99}, FAST_RETRY)
        with session_factory() as s:
            run = make_run(s, spec)
        reconcile_run(run.id, RecordingDispatcher(), session_factory)
        task = _task(session_factory, run.id)

        for attempt in range(1, 5):  # max_attempts = 4
            execute_task_attempt(task.id, attempt, RecordingDispatcher(), session_factory)
            current = _task(session_factory, run.id)
            if current.status == TaskStatus.RETRYING:
                _force_due(session_factory, task.id)
                release_retry_task(task.id, attempt + 1, RecordingDispatcher(), session_factory)

        final = _task(session_factory, run.id)
        assert final.status == TaskStatus.FAILED
        assert final.attempt_count == 4
        assert final.error_type == "RetriableError"
        assert final.finished_at is not None
        assert attempts_log == [1, 2, 3, 4]

        attempts = _attempts(session_factory, task.id)
        assert len(attempts) == 4
        assert all(a.status == AttemptStatus.FAILED for a in attempts)

    def test_backoff_intervals_increase_geometrically(
        self, session_factory, attempts_log
    ) -> None:
        """Persisted next_attempt_at gaps must follow the configured curve.

        Uses zero jitter and compares the DB-computed delay, so the
        assertion is about the engine's arithmetic rather than wall-clock
        scheduling noise.
        """
        spec = _spec("test.fails_until", {"fail_until": 99}, FAST_RETRY)
        with session_factory() as s:
            run = make_run(s, spec)
        reconcile_run(run.id, RecordingDispatcher(), session_factory)
        task = _task(session_factory, run.id)

        observed: list[float] = []
        for attempt in (1, 2, 3):
            d = RecordingDispatcher()
            execute_task_attempt(task.id, attempt, d, session_factory)
            if d.releases:
                observed.append(d.releases[0].delay_seconds)
            _force_due(session_factory, task.id)
            release_retry_task(task.id, attempt + 1, RecordingDispatcher(), session_factory)

        # base 0.05, factor 2 -> 0.05, 0.10, 0.20
        assert observed == pytest.approx([0.05, 0.10, 0.20], rel=0.01)
        assert observed[1] > observed[0] and observed[2] > observed[1]


class TestReleaseCasDirectly:
    def test_try_release_is_false_when_not_due(self, session_factory, attempts_log) -> None:
        slow = {**FAST_RETRY, "backoff_seconds": 60.0, "max_backoff_seconds": 60.0}
        spec = _spec("test.fails_until", {"fail_until": 99}, slow)
        run, task, _ = _start_and_run_first_attempt(session_factory, spec)

        with session_factory() as s:
            result = try_release(s, task.id, 2)
            s.rollback()

        assert result.released is False
        assert result.reason == "too_early"
        assert result.remaining_seconds and result.remaining_seconds > 0
