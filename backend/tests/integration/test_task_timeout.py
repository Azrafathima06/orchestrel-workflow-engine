"""Per-task execution timeouts actually stop work.

Before these limits existed, `timeout_seconds` only sized the recovery
lease. A handler that overran it kept burning CPU while the sweeper
declared the attempt lost and started a NEW one — so a single trigger could
multiply into several concurrent runaway loops on one machine. That is the
amplification these tests exist to prevent.

Driven through InlineDispatcher, which runs the real runner against a real
database with no broker, so the guarantee is proven at the orchestration
layer rather than only in Celery configuration.
"""

from __future__ import annotations

import time

import pytest

from app.core.errors import TaskTimeout
from app.core.states import AttemptStatus, TaskStatus
from app.db.models import TaskAttempt, TaskRun
from app.handlers.registry import handler
from app.orchestration.dispatch import InlineDispatcher
from app.orchestration.runner import handler_time_limit
from tests.integration.factories import make_run, make_spec

# Registered once at import. Spins on real CPU rather than sleeping, so the
# timeout has to interrupt genuine computation the way it would in
# production — a sleep() would prove only that signals interrupt sleeps.
_EXECUTIONS: list[float] = []


@handler("test.spins_forever")
def _spins_forever(context, params, upstream_outputs):
    started = time.monotonic()
    try:
        while True:
            sum(i * i for i in range(10_000))
    finally:
        _EXECUTIONS.append(time.monotonic() - started)


@handler("test.finishes_fast")
def _finishes_fast(context, params, upstream_outputs):
    return {"ok": True}


@pytest.fixture(autouse=True)
def _clear_executions():
    _EXECUTIONS.clear()
    yield
    _EXECUTIONS.clear()


class TestHandlerTimeLimitPrimitive:
    def test_raises_task_timeout_when_exceeded(self) -> None:
        start = time.monotonic()

        with pytest.raises(TaskTimeout):
            with handler_time_limit(1):
                while True:
                    sum(i * i for i in range(10_000))

        # Interrupted promptly, not left to run to completion.
        assert time.monotonic() - start < 5

    def test_does_not_interfere_with_fast_work(self) -> None:
        with handler_time_limit(30):
            result = sum(range(100))

        assert result == 4950

    def test_alarm_is_disarmed_afterwards(self) -> None:
        """A leaked alarm would fire during an unrelated later task."""
        with handler_time_limit(1):
            pass

        time.sleep(1.5)  # would raise here if the alarm were still armed

    def test_zero_disables_the_limit(self) -> None:
        with handler_time_limit(0):
            pass


class TestTimeoutThroughTheRunner:
    def test_overrunning_task_is_stopped_and_recorded(self, session_factory) -> None:
        spec = make_spec(
            "timeout",
            [
                {
                    "key": "slow",
                    "handler": "test.spins_forever",
                    "params": {},
                    "depends_on": [],
                    "timeout_seconds": 1,
                    "retry": {"max_attempts": 1},
                }
            ],
        )
        with session_factory() as s:
            run = make_run(s, spec)
            run_id = run.id

        started = time.monotonic()
        InlineDispatcher(session_factory).dispatch_reconcile(run_id)
        elapsed = time.monotonic() - started

        with session_factory() as s:
            task = s.query(TaskRun).filter_by(run_id=run_id, task_key="slow").one()
            attempts = s.query(TaskAttempt).filter_by(task_run_id=task.id).all()

        # The handler was genuinely interrupted rather than running to term.
        assert elapsed < 20
        assert _EXECUTIONS and _EXECUTIONS[0] < 10

        # Accounting is the ordinary failure accounting, not a special case.
        assert task.status == TaskStatus.FAILED
        assert task.error_type == "TaskTimeout"
        assert len(attempts) == 1
        assert attempts[0].status == AttemptStatus.FAILED
        assert attempts[0].error_type == "TaskTimeout"

    def test_timeout_is_retriable_and_consumes_the_retry_budget(
        self, session_factory
    ) -> None:
        """A timeout is transient by classification, so it retries — but a
        bounded number of times. Unbounded retries of a runaway handler would
        reproduce the amplification this guard exists to stop."""
        spec = make_spec(
            "timeoutretry",
            [
                {
                    "key": "slow",
                    "handler": "test.spins_forever",
                    "params": {},
                    "depends_on": [],
                    "timeout_seconds": 1,
                    "retry": {
                        "max_attempts": 2,
                        "backoff_seconds": 0,
                        "backoff_factor": 1.0,
                        "max_backoff_seconds": 0,
                        "jitter": 0.0,
                    },
                }
            ],
        )
        with session_factory() as s:
            run = make_run(s, spec)
            run_id = run.id

        InlineDispatcher(session_factory).dispatch_reconcile(run_id)

        with session_factory() as s:
            task = s.query(TaskRun).filter_by(run_id=run_id, task_key="slow").one()
            attempts = s.query(TaskAttempt).filter_by(task_run_id=task.id).all()

        assert task.status == TaskStatus.FAILED
        assert task.attempt_count == 2
        assert len(attempts) == 2
        assert {a.error_type for a in attempts} == {"TaskTimeout"}
        # Exactly two executions — no zombie kept running alongside the retry.
        assert len(_EXECUTIONS) == 2

    def test_downstream_task_is_upstream_failed_not_executed(
        self, session_factory
    ) -> None:
        spec = make_spec(
            "timeoutdag",
            [
                {
                    "key": "slow",
                    "handler": "test.spins_forever",
                    "params": {},
                    "depends_on": [],
                    "timeout_seconds": 1,
                    "retry": {"max_attempts": 1},
                },
                {
                    "key": "after",
                    "handler": "test.finishes_fast",
                    "params": {},
                    "depends_on": ["slow"],
                },
            ],
        )
        with session_factory() as s:
            run = make_run(s, spec)
            run_id = run.id

        InlineDispatcher(session_factory).dispatch_reconcile(run_id)

        with session_factory() as s:
            after = s.query(TaskRun).filter_by(run_id=run_id, task_key="after").one()

        assert after.status == TaskStatus.UPSTREAM_FAILED
        assert after.attempt_count == 0

    def test_task_within_its_timeout_is_unaffected(self, session_factory) -> None:
        spec = make_spec(
            "timeoutok",
            [
                {
                    "key": "quick",
                    "handler": "test.finishes_fast",
                    "params": {},
                    "depends_on": [],
                    "timeout_seconds": 30,
                }
            ],
        )
        with session_factory() as s:
            run = make_run(s, spec)
            run_id = run.id

        InlineDispatcher(session_factory).dispatch_reconcile(run_id)

        with session_factory() as s:
            task = s.query(TaskRun).filter_by(run_id=run_id, task_key="quick").one()

        assert task.status == TaskStatus.SUCCEEDED
        assert task.output == {"ok": True}
