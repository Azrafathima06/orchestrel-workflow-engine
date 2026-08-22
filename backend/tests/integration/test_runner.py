"""Task runner behaviour against real PostgreSQL.

Focus: the claim guard (Phase A), attempt evidence, output persistence, and
that a duplicate delivery cannot execute the same attempt twice.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.core.states import AttemptStatus, TaskStatus
from app.db.models import TaskAttempt, TaskRun
from app.handlers.registry import _REGISTRY
from app.orchestration.dispatch import RecordingDispatcher
from app.orchestration.reconciler import reconcile_run
from app.orchestration.runner import execute_task_attempt, worker_identity
from tests.integration.factories import make_run, make_spec


@pytest.fixture
def call_log() -> list[dict]:
    """Registers throwaway handlers for the duration of one test.

    Writes directly to the registry rather than through @handler because the
    decorator deliberately rejects duplicate registration; tests need to
    install a fresh implementation per test.
    """
    calls: list[dict] = []

    def ok(context, params, upstream_outputs):
        calls.append(
            {
                "task_key": context.task_key,
                "attempt": context.attempt_number,
                "worker_id": context.worker_id,
                "upstream": dict(upstream_outputs),
            }
        )
        return {"echo": params.get("value", 1), "task": context.task_key}

    def boom(context, params, upstream_outputs):
        calls.append({"task_key": context.task_key, "attempt": context.attempt_number})
        raise ValueError("handler exploded on purpose")

    def huge(context, params, upstream_outputs):
        return {"blob": "x" * 200_000}

    _REGISTRY["test.ok"] = ok
    _REGISTRY["test.boom"] = boom
    _REGISTRY["test.huge"] = huge
    try:
        yield calls
    finally:
        for name in ("test.ok", "test.boom", "test.huge"):
            _REGISTRY.pop(name, None)


def _single_task_spec(handler: str, params: dict | None = None) -> dict:
    return make_spec(
        "runner", [{"key": "solo", "handler": handler, "params": params or {}, "depends_on": []}]
    )


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


class TestSuccessfulExecution:
    def test_queued_task_executes_once_and_persists_everything(
        self, session_factory, call_log
    ) -> None:
        with session_factory() as s:
            run = make_run(s, _single_task_spec("test.ok", {"value": 99}))
        reconcile_run(run.id, RecordingDispatcher(), session_factory)
        task = _task(session_factory, run.id)

        d = RecordingDispatcher()
        execute_task_attempt(task.id, 1, d, session_factory, celery_task_id="celery-abc")

        assert len(call_log) == 1

        after = _task(session_factory, run.id)
        assert after.status == TaskStatus.SUCCEEDED
        assert after.attempt_count == 1
        assert after.output == {"echo": 99, "task": "solo"}
        assert after.started_at is not None
        assert after.finished_at is not None
        assert after.duration_ms is not None and after.duration_ms >= 0
        assert after.lease_expires_at is None

        attempts = _attempts(session_factory, task.id)
        assert len(attempts) == 1
        assert attempts[0].attempt_number == 1
        assert attempts[0].status == AttemptStatus.SUCCEEDED
        assert attempts[0].worker_id == worker_identity()
        assert attempts[0].celery_task_id == "celery-abc"
        assert attempts[0].finished_at is not None

        # Completion must ask the orchestrator to advance the run.
        assert [r.run_id for r in d.reconciles] == [run.id]

    def test_upstream_outputs_are_passed_to_the_handler(self, session_factory, call_log) -> None:
        spec = make_spec(
            "chain",
            [
                {"key": "first", "handler": "test.ok", "params": {"value": 1}, "depends_on": []},
                {
                    "key": "second",
                    "handler": "test.ok",
                    "params": {"value": 2},
                    "depends_on": ["first"],
                },
            ],
        )
        with session_factory() as s:
            run = make_run(s, spec)

        reconcile_run(run.id, RecordingDispatcher(), session_factory)
        first = _task(session_factory, run.id, "first")
        execute_task_attempt(first.id, 1, RecordingDispatcher(), session_factory)

        reconcile_run(run.id, RecordingDispatcher(), session_factory)
        second = _task(session_factory, run.id, "second")
        execute_task_attempt(second.id, 1, RecordingDispatcher(), session_factory)

        second_call = next(c for c in call_log if c["task_key"] == "second")
        assert second_call["upstream"] == {"first": {"echo": 1, "task": "first"}}


class TestDuplicateDelivery:
    def test_duplicate_delivery_does_not_invoke_the_handler_again(
        self, session_factory, call_log
    ) -> None:
        with session_factory() as s:
            run = make_run(s, _single_task_spec("test.ok"))
        reconcile_run(run.id, RecordingDispatcher(), session_factory)
        task = _task(session_factory, run.id)

        execute_task_attempt(task.id, 1, RecordingDispatcher(), session_factory)
        # Redelivery of the very same message, exactly as Celery would
        # replay it after a visibility timeout.
        d2 = RecordingDispatcher()
        execute_task_attempt(task.id, 1, d2, session_factory)

        assert len(call_log) == 1, "handler must run exactly once"
        assert len(_attempts(session_factory, task.id)) == 1
        assert d2.reconciles == [], "a stale delivery must not trigger a reconcile"

    def test_delivery_for_the_wrong_attempt_number_is_rejected(
        self, session_factory, call_log
    ) -> None:
        with session_factory() as s:
            run = make_run(s, _single_task_spec("test.ok"))
        reconcile_run(run.id, RecordingDispatcher(), session_factory)
        task = _task(session_factory, run.id)

        # Task is QUEUED at attempt_count=0, so only expected_attempt=1 is valid.
        execute_task_attempt(task.id, 2, RecordingDispatcher(), session_factory)
        execute_task_attempt(task.id, 7, RecordingDispatcher(), session_factory)

        assert call_log == []
        assert _task(session_factory, run.id).status == TaskStatus.QUEUED
        assert _attempts(session_factory, task.id) == []

    def test_delivery_for_a_task_that_is_not_queued_is_rejected(
        self, session_factory, call_log
    ) -> None:
        with session_factory() as s:
            run = make_run(s, _single_task_spec("test.ok"))
        # No reconcile: the task is still PENDING, never queued.
        task = _task(session_factory, run.id)

        execute_task_attempt(task.id, 1, RecordingDispatcher(), session_factory)

        assert call_log == []
        assert _task(session_factory, run.id).status == TaskStatus.PENDING

    def test_unknown_task_run_id_is_a_safe_noop(self, session_factory, call_log) -> None:
        execute_task_attempt(uuid.uuid4(), 1, RecordingDispatcher(), session_factory)
        assert call_log == []


class TestFailure:
    def test_handler_exception_is_recorded_cleanly(self, session_factory, call_log) -> None:
        with session_factory() as s:
            run = make_run(s, _single_task_spec("test.boom"))
        reconcile_run(run.id, RecordingDispatcher(), session_factory)
        task = _task(session_factory, run.id)

        d = RecordingDispatcher()
        execute_task_attempt(task.id, 1, d, session_factory)

        after = _task(session_factory, run.id)
        assert after.status == TaskStatus.FAILED
        assert after.error_type == "ValueError"
        assert "handler exploded on purpose" in after.error_message
        assert after.finished_at is not None
        assert after.duration_ms is not None

        attempts = _attempts(session_factory, task.id)
        assert len(attempts) == 1
        assert attempts[0].status == AttemptStatus.FAILED
        assert attempts[0].error_type == "ValueError"
        assert attempts[0].traceback is not None

        # A failure still advances the run, so the DAG can settle.
        assert [r.run_id for r in d.reconciles] == [run.id]

    def test_oversized_output_fails_the_task_rather_than_truncating(
        self, session_factory, call_log
    ) -> None:
        with session_factory() as s:
            run = make_run(s, _single_task_spec("test.huge"))
        reconcile_run(run.id, RecordingDispatcher(), session_factory)
        task = _task(session_factory, run.id)

        execute_task_attempt(task.id, 1, RecordingDispatcher(), session_factory)

        after = _task(session_factory, run.id)
        assert after.status == TaskStatus.FAILED
        assert after.error_type == "OutputTooLarge"
        assert after.output is None, "must not persist a truncated payload"


class TestWorkerIdentity:
    def test_worker_identity_is_hostname_and_pid(self) -> None:
        import os
        import socket

        assert worker_identity() == f"{socket.gethostname()}:{os.getpid()}"
