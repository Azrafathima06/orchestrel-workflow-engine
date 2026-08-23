"""Recovery sweeps against real PostgreSQL.

Each test constructs a genuine durability hole in persisted state — a task
committed as QUEUED with no message, an attempt whose lease has expired, a
RETRYING task whose release message vanished — and asserts the sweeper
reconstructs the right action from the database alone.

Nothing here fabricates a WorkerLost row or hand-edits a status to pretend
recovery happened: the tests set up the *precondition* (an overdue
timestamp) and let the real sweep produce the outcome.
"""

from __future__ import annotations

import threading

import pytest
from sqlalchemy import select, text

from app.config import get_settings
from app.core.errors import RetriableError
from app.core.states import AttemptStatus, TaskStatus
from app.db.models import TaskAttempt, TaskRun
from app.handlers.registry import _REGISTRY
from app.logging import get_logger
from app.orchestration.dispatch import RecordingDispatcher
from app.orchestration.reconciler import reconcile_run
from app.orchestration.recovery import (
    SweepReport,
    reconcile_stalled_runs,
    recover_expired_leases,
    recover_overdue_retries,
    recover_stale_queued,
    recovery_sweep,
)
from app.orchestration.release import release_retry_task
from app.orchestration.runner import execute_task_attempt
from tests.integration.factories import make_run, make_spec

settings = get_settings()

RETRY_CFG = {
    "max_attempts": 3,
    "backoff_seconds": 0.05,
    "backoff_factor": 2.0,
    "max_backoff_seconds": 1.0,
    "jitter": 0.0,
}


@pytest.fixture
def handlers() -> list[int]:
    calls: list[int] = []

    def ok(context, params, upstream_outputs):
        calls.append(context.attempt_number)
        return {"attempt": context.attempt_number}

    def flaky(context, params, upstream_outputs):
        calls.append(context.attempt_number)
        raise RetriableError("always transient")

    _REGISTRY["test.ok"] = ok
    _REGISTRY["test.flaky"] = flaky
    try:
        yield calls
    finally:
        for n in ("test.ok", "test.flaky"):
            _REGISTRY.pop(n, None)


def _spec(handler="test.ok", retry: dict | None = None, key="rec") -> dict:
    task: dict = {"key": "solo", "handler": handler, "params": {}, "depends_on": []}
    if retry:
        task["retry"] = retry
    return make_spec(key, [task])


def _task(session_factory, run_id, key="solo") -> TaskRun:
    with session_factory() as s:
        return s.execute(
            select(TaskRun).where(TaskRun.run_id == run_id, TaskRun.task_key == key)
        ).scalar_one()


def _attempts(session_factory, task_id) -> list[TaskAttempt]:
    with session_factory() as s:
        return list(
            s.execute(
                select(TaskAttempt)
                .where(TaskAttempt.task_run_id == task_id)
                .order_by(TaskAttempt.attempt_number)
            )
            .scalars()
            .all()
        )


def _sql(session_factory, stmt: str, **params) -> None:
    """Age a timestamp using the database clock, to create an overdue condition.

    This is the only thing tests fabricate: the passage of time. Statuses,
    attempt rows, and error types are always produced by real code paths.
    """
    with session_factory() as s:
        s.execute(text(stmt), params)
        s.commit()


def _queued_task(session_factory, handler="test.ok", retry=None):
    with session_factory() as s:
        run = make_run(s, _spec(handler, retry))
    reconcile_run(run.id, RecordingDispatcher(), session_factory)
    return run, _task(session_factory, run.id)


# ------------------------------------------------------------- stale QUEUED


class TestStaleQueuedRecovery:
    def test_fresh_queued_task_is_not_touched(self, session_factory, handlers) -> None:
        run, task = _queued_task(session_factory)

        d = RecordingDispatcher()
        report = recover_stale_queued(d, session_factory, SweepReport())

        assert report.queued_redispatched == 0
        assert d.tasks == []
        assert _task(session_factory, run.id).dispatch_count == 1

    def test_stale_queued_task_is_redispatched(self, session_factory, handlers) -> None:
        run, task = _queued_task(session_factory)
        _sql(
            session_factory,
            "UPDATE task_run SET queued_at = now() - make_interval(secs => :s) WHERE id = :i",
            s=settings.queued_stale_seconds + 60,
            i=task.id,
        )

        d = RecordingDispatcher()
        report = recovery_sweep(d, session_factory)

        assert report.queued_redispatched == 1
        after = _task(session_factory, run.id)
        assert after.status == TaskStatus.QUEUED
        assert after.dispatch_count == 2, "recovery intervention is recorded"
        assert after.queued_at > task.queued_at, "staleness clock is refreshed"
        assert len(d.tasks) == 1
        assert d.tasks[0].task_run_id == task.id
        assert d.tasks[0].expected_attempt == 1, "same attempt is re-delivered"

    def test_redispatched_task_still_executes_exactly_once(
        self, session_factory, handlers
    ) -> None:
        """Re-delivery is safe: the runner's claim guard admits only one."""
        run, task = _queued_task(session_factory)
        _sql(
            session_factory,
            "UPDATE task_run SET queued_at = now() - make_interval(secs => :s) WHERE id = :i",
            s=settings.queued_stale_seconds + 60,
            i=task.id,
        )
        recovery_sweep(RecordingDispatcher(), session_factory)

        # Both the original (lost) message and the recovery message arrive.
        execute_task_attempt(task.id, 1, RecordingDispatcher(), session_factory)
        execute_task_attempt(task.id, 1, RecordingDispatcher(), session_factory)

        assert handlers == [1], "handler ran exactly once"
        assert len(_attempts(session_factory, task.id)) == 1

    def test_two_concurrent_sweepers_redispatch_once(self, session_factory, handlers) -> None:
        run, task = _queued_task(session_factory)
        _sql(
            session_factory,
            "UPDATE task_run SET queued_at = now() - make_interval(secs => :s) WHERE id = :i",
            s=settings.queued_stale_seconds + 60,
            i=task.id,
        )

        dispatchers = [RecordingDispatcher() for _ in range(4)]
        barrier = threading.Barrier(4)
        errors: list[BaseException] = []

        def sweep(d):
            try:
                barrier.wait(timeout=10)
                recovery_sweep(d, session_factory)
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=sweep, args=(d,)) for d in dispatchers]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        assert not errors, f"sweep raised: {errors!r}"
        total = sum(len(d.tasks) for d in dispatchers)
        assert total == 1, f"expected exactly one redispatch, got {total}"
        assert _task(session_factory, run.id).dispatch_count == 2

    def test_exceeding_max_dispatch_attempts_fails_as_undeliverable(
        self, session_factory, handlers
    ) -> None:
        run, task = _queued_task(session_factory)
        _sql(
            session_factory,
            "UPDATE task_run SET queued_at = now() - make_interval(secs => :s), "
            "dispatch_count = :d WHERE id = :i",
            s=settings.queued_stale_seconds + 60,
            d=settings.max_dispatch_attempts,
            i=task.id,
        )

        d = RecordingDispatcher()
        report = recovery_sweep(d, session_factory)

        assert report.undeliverable_failed == 1
        assert report.queued_redispatched == 0
        after = _task(session_factory, run.id)
        assert after.status == TaskStatus.FAILED
        assert after.error_type == "UndeliverableTask"
        assert d.tasks == [], "no further delivery attempts"
        assert len(d.reconciles) == 1, "run must be reconciled after a terminal failure"


# ---------------------------------------------------------- expired leases


class TestWorkerLossRecovery:
    def _running_with_expired_lease(self, session_factory, retry=RETRY_CFG):
        run, task = _queued_task(session_factory, "test.ok", retry)
        # Claim the attempt for real, then abandon it: the worker "freezes"
        # before completing, so the attempt row stays RUNNING.
        with session_factory() as s:
            s.execute(
                text(
                    "UPDATE task_run SET status='running', attempt_count=1, "
                    "started_at=now(), queued_at=NULL, dispatch_count=0, "
                    "lease_expires_at=now() - interval '10 seconds' WHERE id=:i"
                ),
                {"i": task.id},
            )
            s.execute(
                text(
                    "INSERT INTO task_attempt (id, task_run_id, attempt_number, status, "
                    "worker_id, started_at) VALUES (gen_random_uuid(), :i, 1, 'running', "
                    "'frozen-worker:99', now())"
                ),
                {"i": task.id},
            )
            s.commit()
        return run, task

    def test_expired_lease_marks_attempt_worker_lost_and_retries(
        self, session_factory, handlers
    ) -> None:
        run, task = self._running_with_expired_lease(session_factory)

        d = RecordingDispatcher()
        report = recovery_sweep(d, session_factory)

        assert report.leases_reclaimed == 1

        attempts = _attempts(session_factory, task.id)
        assert len(attempts) == 1
        assert attempts[0].status == AttemptStatus.FAILED
        assert attempts[0].error_type == "WorkerLost"
        assert "lease expired" in attempts[0].error_message
        assert attempts[0].worker_id == "frozen-worker:99"
        assert attempts[0].finished_at is not None

        after = _task(session_factory, run.id)
        assert after.status == TaskStatus.RETRYING, "WorkerLost uses the normal retry path"
        assert after.next_attempt_at is not None
        assert after.lease_expires_at is None
        assert len(d.releases) == 1
        assert d.releases[0].expected_attempt == 2

    def test_expired_lease_with_no_attempts_left_fails_the_task(
        self, session_factory, handlers
    ) -> None:
        run, task = self._running_with_expired_lease(
            session_factory, retry={**RETRY_CFG, "max_attempts": 1}
        )

        d = RecordingDispatcher()
        report = recovery_sweep(d, session_factory)

        assert report.leases_reclaimed == 1
        after = _task(session_factory, run.id)
        assert after.status == TaskStatus.FAILED
        assert after.error_type == "WorkerLost"
        assert d.releases == []
        assert len(d.reconciles) == 1

    def test_valid_lease_is_not_reclaimed(self, session_factory, handlers) -> None:
        run, task = _queued_task(session_factory, "test.ok", RETRY_CFG)
        with session_factory() as s:
            s.execute(
                text(
                    "UPDATE task_run SET status='running', attempt_count=1, started_at=now(), "
                    "lease_expires_at=now() + interval '5 minutes' WHERE id=:i"
                ),
                {"i": task.id},
            )
            s.commit()

        d = RecordingDispatcher()
        report = recovery_sweep(d, session_factory)

        assert report.leases_reclaimed == 0
        assert _task(session_factory, run.id).status == TaskStatus.RUNNING

    def test_zombie_completion_cannot_overwrite_recovered_state(
        self, session_factory, handlers
    ) -> None:
        """The headline safety property.

        Attempt 1's worker freezes; recovery reclaims the lease and mints
        attempt 2. The frozen worker then wakes and tries to commit success
        for attempt 1. Its guarded write must match zero rows.
        """
        run, task = self._running_with_expired_lease(session_factory)
        recovery_sweep(RecordingDispatcher(), session_factory)

        state_before = _task(session_factory, run.id)
        assert state_before.status == TaskStatus.RETRYING

        # The zombie returns, still believing it owns attempt 1.
        from app.orchestration.runner import _complete_success

        _complete_success(
            session_factory,
            task.id,
            attempt_number=1,
            output={"zombie": "stale result"},
            log=get_logger("test"),
        )

        after = _task(session_factory, run.id)
        assert after.status == TaskStatus.RETRYING, "state must not regress"
        assert after.output is None, "stale output must not be persisted"
        assert after.attempt_count == state_before.attempt_count

        attempts = _attempts(session_factory, task.id)
        assert len(attempts) == 1
        assert attempts[0].status == AttemptStatus.FAILED, "attempt 1 stays WorkerLost"


# --------------------------------------------------------- overdue RETRYING


class TestLostRetryReleaseRecovery:
    def _retrying_task(self, session_factory):
        run, task = _queued_task(session_factory, "test.flaky", RETRY_CFG)
        execute_task_attempt(task.id, 1, RecordingDispatcher(), session_factory)
        assert _task(session_factory, run.id).status == TaskStatus.RETRYING
        return run, task

    def test_overdue_retry_is_released_by_the_sweeper(
        self, session_factory, handlers
    ) -> None:
        run, task = self._retrying_task(session_factory)
        # The release message was lost; the task is now well past due.
        _sql(
            session_factory,
            "UPDATE task_run SET next_attempt_at = now() - make_interval(secs => :s) WHERE id = :i",
            s=settings.retry_release_grace_seconds + 30,
            i=task.id,
        )

        d = RecordingDispatcher()
        report = recovery_sweep(d, session_factory)

        assert report.retries_released == 1
        after = _task(session_factory, run.id)
        assert after.status == TaskStatus.QUEUED
        assert after.next_attempt_at is None
        assert len(d.tasks) == 1
        assert d.tasks[0].expected_attempt == 2

    def test_retry_within_grace_period_is_left_to_the_release_message(
        self, session_factory, handlers
    ) -> None:
        run, task = self._retrying_task(session_factory)
        # Due, but not yet past the grace period: the countdown message
        # should still be given its chance.
        _sql(
            session_factory,
            "UPDATE task_run SET next_attempt_at = now() - interval '1 second' WHERE id = :i",
            i=task.id,
        )

        report = recovery_sweep(RecordingDispatcher(), session_factory)

        assert report.retries_released == 0
        assert _task(session_factory, run.id).status == TaskStatus.RETRYING

    def test_sweeper_and_release_message_race_releases_exactly_once(
        self, session_factory, handlers
    ) -> None:
        run, task = self._retrying_task(session_factory)
        _sql(
            session_factory,
            "UPDATE task_run SET next_attempt_at = now() - make_interval(secs => :s) WHERE id = :i",
            s=settings.retry_release_grace_seconds + 30,
            i=task.id,
        )

        sweeper_d = RecordingDispatcher()
        release_d = RecordingDispatcher()
        barrier = threading.Barrier(2)
        errors: list[BaseException] = []

        def do_sweep():
            try:
                barrier.wait(timeout=10)
                recover_overdue_retries(
                    sweeper_d,
                    session_factory,
                    SweepReport(),
                )
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        def do_release():
            try:
                barrier.wait(timeout=10)
                release_retry_task(task.id, 2, release_d, session_factory)
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=do_sweep), threading.Thread(target=do_release)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        assert not errors, f"race raised: {errors!r}"
        total = len(sweeper_d.tasks) + len(release_d.tasks)
        assert total == 1, f"exactly one release expected, got {total}"
        assert _task(session_factory, run.id).status == TaskStatus.QUEUED


# ------------------------------------------------------------- stalled runs


class TestStalledRunRecovery:
    def test_stalled_run_is_reconciled(self, session_factory, handlers) -> None:
        with session_factory() as s:
            run = make_run(s, _spec())
        reconcile_run(run.id, RecordingDispatcher(), session_factory)
        # Task finished but the reconcile message vanished, leaving the run
        # RUNNING with nothing in flight.
        with session_factory() as s:
            s.execute(
                text(
                    "UPDATE task_run SET status='succeeded', attempt_count=1, "
                    "finished_at = now() - make_interval(secs => :s), output='{}'::jsonb "
                    "WHERE run_id = :r"
                ),
                {"s": settings.run_stall_seconds + 60, "r": run.id},
            )
            s.commit()

        d = RecordingDispatcher()
        report = recovery_sweep(d, session_factory)

        assert report.runs_reconciled == 1
        assert len(d.reconciles) == 1
        assert d.reconciles[0].run_id == run.id

    def test_pending_run_whose_first_reconcile_was_lost_is_recovered(
        self, session_factory, handlers
    ) -> None:
        """A run is committed with all its tasks BEFORE its first reconcile
        message is published. If that message is lost, the run would sit in
        PENDING forever with nothing else to notice it — so the stall sweep
        must cover PENDING, not only RUNNING."""
        with session_factory() as s:
            run = make_run(s, _spec())
        # No reconcile ever happened: the message vanished.
        _sql(
            session_factory,
            "UPDATE workflow_run SET created_at = now() - make_interval(secs => :s) WHERE id = :i",
            s=settings.run_stall_seconds + 60,
            i=run.id,
        )

        d = RecordingDispatcher()
        report = recovery_sweep(d, session_factory)

        assert report.runs_reconciled == 1
        assert [r.run_id for r in d.reconciles] == [run.id]

    def test_active_run_is_not_considered_stalled(self, session_factory, handlers) -> None:
        run, task = _queued_task(session_factory)  # task is QUEUED = in flight

        report = reconcile_stalled_runs(
            RecordingDispatcher(),
            session_factory,
            SweepReport(),
        )

        assert report.runs_reconciled == 0


class TestSweepReport:
    def test_clean_system_reports_no_actions(self, session_factory, handlers) -> None:
        report = recovery_sweep(RecordingDispatcher(), session_factory)
        assert report.total_actions == 0
        assert set(report.as_dict()) == {
            "queued_redispatched",
            "undeliverable_failed",
            "leases_reclaimed",
            "retries_released",
            "runs_reconciled",
        }

    def test_expired_lease_sweep_is_idempotent(self, session_factory, handlers) -> None:
        run, task = _queued_task(session_factory, "test.ok", RETRY_CFG)
        with session_factory() as s:
            s.execute(
                text(
                    "UPDATE task_run SET status='running', attempt_count=1, started_at=now(), "
                    "lease_expires_at=now() - interval '10 seconds' WHERE id=:i"
                ),
                {"i": task.id},
            )
            s.execute(
                text(
                    "INSERT INTO task_attempt (id, task_run_id, attempt_number, status, "
                    "worker_id, started_at) VALUES (gen_random_uuid(), :i, 1, 'running', "
                    "'w:1', now())"
                ),
                {"i": task.id},
            )
            s.commit()

        first = recover_expired_leases(
            RecordingDispatcher(),
            session_factory,
            SweepReport(),
        )
        second = recover_expired_leases(
            RecordingDispatcher(),
            session_factory,
            SweepReport(),
        )

        assert first.leases_reclaimed == 1
        assert second.leases_reclaimed == 0, "a reclaimed lease must not be reclaimed twice"
