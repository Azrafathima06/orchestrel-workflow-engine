"""Reconciler behaviour against real PostgreSQL.

These use RecordingDispatcher: they assert what the reconciler *decides and
persists*, without executing any handlers.
"""

from __future__ import annotations

from sqlalchemy import select

from app.core.states import TaskStatus, WorkflowStatus
from app.db.models import TaskRun, WorkflowRun
from app.orchestration.dispatch import RecordingDispatcher
from app.orchestration.reconciler import reconcile_run
from tests.integration.factories import fanout_spec, linear_spec, make_run


def _tasks(session_factory, run_id) -> dict[str, TaskRun]:
    with session_factory() as s:
        rows = s.execute(select(TaskRun).where(TaskRun.run_id == run_id)).scalars().all()
        return {t.task_key: t for t in rows}


def _run(session_factory, run_id) -> WorkflowRun:
    with session_factory() as s:
        return s.get(WorkflowRun, run_id)


def _succeed(session_factory, run_id, task_key: str) -> None:
    """Mark a task SUCCEEDED the way the runner would, without running a handler."""
    with session_factory() as s:
        task = s.execute(
            select(TaskRun).where(TaskRun.run_id == run_id, TaskRun.task_key == task_key)
        ).scalar_one()
        task.status = TaskStatus.SUCCEEDED
        task.attempt_count = max(task.attempt_count, 1)
        task.output = {"ok": True}
        s.commit()


class TestFirstReconcile:
    def test_source_task_moves_pending_to_queued_and_starts_run(self, session_factory) -> None:
        with session_factory() as s:
            run = make_run(s, linear_spec())
        d = RecordingDispatcher()

        reconcile_run(run.id, d, session_factory)

        tasks = _tasks(session_factory, run.id)
        assert tasks["a"].status == TaskStatus.QUEUED
        assert tasks["a"].queued_at is not None
        assert tasks["a"].dispatch_count == 1
        assert tasks["b"].status == TaskStatus.PENDING
        assert tasks["c"].status == TaskStatus.PENDING

        reloaded = _run(session_factory, run.id)
        assert reloaded.status == WorkflowStatus.RUNNING
        assert reloaded.started_at is not None

        assert len(d.tasks) == 1
        assert d.tasks[0].task_run_id == tasks["a"].id
        assert d.tasks[0].expected_attempt == 1

    def test_second_reconcile_does_not_dispatch_the_source_twice(self, session_factory) -> None:
        with session_factory() as s:
            run = make_run(s, linear_spec())

        first = RecordingDispatcher()
        reconcile_run(run.id, first, session_factory)
        second = RecordingDispatcher()
        reconcile_run(run.id, second, session_factory)

        assert len(first.tasks) == 1
        assert second.tasks == []  # 'a' is QUEUED now, not PENDING


class TestProgression:
    def test_success_exposes_the_next_task(self, session_factory) -> None:
        with session_factory() as s:
            run = make_run(s, linear_spec())
        reconcile_run(run.id, RecordingDispatcher(), session_factory)

        _succeed(session_factory, run.id, "a")
        d = RecordingDispatcher()
        reconcile_run(run.id, d, session_factory)

        tasks = _tasks(session_factory, run.id)
        assert tasks["b"].status == TaskStatus.QUEUED
        assert tasks["c"].status == TaskStatus.PENDING
        assert len(d.tasks) == 1
        assert d.tasks[0].task_run_id == tasks["b"].id

    def test_fan_out_dispatches_every_branch_in_one_pass(self, session_factory) -> None:
        with session_factory() as s:
            run = make_run(s, fanout_spec())
        reconcile_run(run.id, RecordingDispatcher(), session_factory)

        _succeed(session_factory, run.id, "split")
        d = RecordingDispatcher()
        reconcile_run(run.id, d, session_factory)

        tasks = _tasks(session_factory, run.id)
        for i in range(4):
            assert tasks[f"shard_{i}"].status == TaskStatus.QUEUED
        assert tasks["merge"].status == TaskStatus.PENDING
        assert len(d.tasks) == 4

    def test_fan_in_waits_for_every_shard(self, session_factory) -> None:
        with session_factory() as s:
            run = make_run(s, fanout_spec())
        reconcile_run(run.id, RecordingDispatcher(), session_factory)
        _succeed(session_factory, run.id, "split")
        reconcile_run(run.id, RecordingDispatcher(), session_factory)

        for i in range(3):
            _succeed(session_factory, run.id, f"shard_{i}")
            d = RecordingDispatcher()
            reconcile_run(run.id, d, session_factory)
            assert _tasks(session_factory, run.id)["merge"].status == TaskStatus.PENDING
            assert d.tasks == []

        _succeed(session_factory, run.id, "shard_3")
        d = RecordingDispatcher()
        reconcile_run(run.id, d, session_factory)

        tasks = _tasks(session_factory, run.id)
        assert tasks["merge"].status == TaskStatus.QUEUED
        assert len(d.tasks) == 1
        assert d.tasks[0].task_run_id == tasks["merge"].id


class TestCompletion:
    def test_all_tasks_succeeded_marks_run_succeeded(self, session_factory) -> None:
        with session_factory() as s:
            run = make_run(s, linear_spec())
        reconcile_run(run.id, RecordingDispatcher(), session_factory)

        for key in ("a", "b", "c"):
            _succeed(session_factory, run.id, key)
        reconcile_run(run.id, RecordingDispatcher(), session_factory)

        reloaded = _run(session_factory, run.id)
        assert reloaded.status == WorkflowStatus.SUCCEEDED
        assert reloaded.finished_at is not None
        assert reloaded.duration_ms is not None
        assert reloaded.duration_ms >= 0

    def test_reconciling_a_terminal_run_changes_nothing(self, session_factory) -> None:
        with session_factory() as s:
            run = make_run(s, linear_spec())
        reconcile_run(run.id, RecordingDispatcher(), session_factory)
        for key in ("a", "b", "c"):
            _succeed(session_factory, run.id, key)
        reconcile_run(run.id, RecordingDispatcher(), session_factory)

        before = _run(session_factory, run.id)
        snapshot = (before.status, before.finished_at, before.duration_ms)

        d = RecordingDispatcher()
        reconcile_run(run.id, d, session_factory)
        reconcile_run(run.id, d, session_factory)

        after = _run(session_factory, run.id)
        assert (after.status, after.finished_at, after.duration_ms) == snapshot
        assert d.tasks == []
        assert d.reconciles == []

    def test_reconciling_an_unknown_run_is_a_safe_noop(self, session_factory) -> None:
        import uuid

        d = RecordingDispatcher()
        reconcile_run(uuid.uuid4(), d, session_factory)
        assert d.tasks == []
