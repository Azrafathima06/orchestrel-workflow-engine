"""Failure isolation: a failed branch must not stop unrelated work.

The distinction being proved:

  FAILED          — the handler ran and failed.
  UPSTREAM_FAILED — the handler never ran, because a dependency failed.

and, crucially, that tasks on branches unrelated to the failure execute to
completion anyway.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.states import TaskStatus, WorkflowStatus
from app.db.models import TaskAttempt, TaskRun, WorkflowRun
from app.orchestration.dispatch import InlineDispatcher
from app.orchestration.reconciler import reconcile_run
from tests.integration.factories import make_run

WORKFLOWS_DIR = Path(__file__).resolve().parents[2] / "workflows"


@pytest.fixture(scope="module")
def isolation_spec() -> dict:
    return json.loads((WORKFLOWS_DIR / "failure_isolation.json").read_text())


@pytest.fixture
def completed_run(session_factory, isolation_spec):
    with session_factory() as s:
        run = make_run(s, isolation_spec)
    reconcile_run(run.id, InlineDispatcher(session_factory), session_factory)
    with session_factory() as s:
        return s.get(WorkflowRun, run.id)


def _tasks(session_factory, run_id) -> dict[str, TaskRun]:
    with session_factory() as s:
        rows = s.execute(select(TaskRun).where(TaskRun.run_id == run_id)).scalars().all()
        return {t.task_key: t for t in rows}


def test_exact_end_state(session_factory, completed_run) -> None:
    tasks = _tasks(session_factory, completed_run.id)

    assert {k: t.status for k, t in tasks.items()} == {
        "seed": TaskStatus.SUCCEEDED,
        # Failing branch
        "branch_a1": TaskStatus.SUCCEEDED,
        "branch_a2": TaskStatus.FAILED,
        "branch_a3": TaskStatus.UPSTREAM_FAILED,
        # Independent branch — untouched by the failure
        "branch_b1": TaskStatus.SUCCEEDED,
        "branch_b2": TaskStatus.SUCCEEDED,
        "branch_b3": TaskStatus.SUCCEEDED,
        # Join depends on the failed branch
        "finalize": TaskStatus.UPSTREAM_FAILED,
    }


def test_run_settles_failed(session_factory, completed_run) -> None:
    assert completed_run.status == WorkflowStatus.FAILED
    assert completed_run.finished_at is not None
    assert completed_run.duration_ms is not None
    assert completed_run.error is not None
    assert "branch_a2" in completed_run.error
    assert "branch_a3" in completed_run.error


def test_independent_branch_actually_executed(session_factory, completed_run) -> None:
    """The proof that isolation is real: branch B has genuine attempt rows,
    real workers, real durations, and real outputs — it was not merely left
    alone in PENDING."""
    tasks = _tasks(session_factory, completed_run.id)

    with session_factory() as s:
        for key in ("branch_b1", "branch_b2", "branch_b3"):
            task = tasks[key]
            attempts = (
                s.execute(select(TaskAttempt).where(TaskAttempt.task_run_id == task.id))
                .scalars()
                .all()
            )
            assert len(attempts) == 1, f"{key} should have executed exactly once"
            assert attempts[0].worker_id
            assert task.output is not None
            assert task.duration_ms is not None
            assert task.finished_at is not None


def test_failed_task_ran_but_upstream_failed_task_did_not(
    session_factory, completed_run
) -> None:
    tasks = _tasks(session_factory, completed_run.id)

    with session_factory() as s:
        # branch_a2 FAILED: it genuinely executed and errored.
        a2_attempts = (
            s.execute(select(TaskAttempt).where(TaskAttempt.task_run_id == tasks["branch_a2"].id))
            .scalars()
            .all()
        )
        assert len(a2_attempts) == 1
        assert a2_attempts[0].worker_id
        assert tasks["branch_a2"].error_type == "PermanentError"
        assert "data quality check failed" in tasks["branch_a2"].error_message

        # branch_a3 UPSTREAM_FAILED: it never ran at all.
        a3_attempts = (
            s.execute(select(TaskAttempt).where(TaskAttempt.task_run_id == tasks["branch_a3"].id))
            .scalars()
            .all()
        )
        assert a3_attempts == [], "an UPSTREAM_FAILED task must never have executed"
        assert tasks["branch_a3"].attempt_count == 0
        assert tasks["branch_a3"].started_at is None
        assert tasks["branch_a3"].error_type == "UpstreamFailed"


def test_upstream_failure_message_names_the_real_culprit(
    session_factory, completed_run
) -> None:
    tasks = _tasks(session_factory, completed_run.id)
    assert "branch_a2" in tasks["branch_a3"].error_message
    # finalize is blocked by its own direct dependency, not the root cause.
    assert "branch_a3" in tasks["finalize"].error_message


def test_permanent_failure_is_not_retried(session_factory, completed_run) -> None:
    tasks = _tasks(session_factory, completed_run.id)
    assert tasks["branch_a2"].attempt_count == 1
    assert tasks["branch_a2"].next_attempt_at is None


def test_reconciling_the_failed_run_again_changes_nothing(
    session_factory, completed_run
) -> None:
    before = _tasks(session_factory, completed_run.id)
    snapshot = {k: (t.status, t.finished_at) for k, t in before.items()}

    reconcile_run(completed_run.id, InlineDispatcher(session_factory), session_factory)

    after = _tasks(session_factory, completed_run.id)
    assert {k: (t.status, t.finished_at) for k, t in after.items()} == snapshot

    with session_factory() as s:
        run = s.get(WorkflowRun, completed_run.id)
        assert run.status == WorkflowStatus.FAILED
