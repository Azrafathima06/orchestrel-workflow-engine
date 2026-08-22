"""The real demo workflows, executed end to end through InlineDispatcher.

Same reconciler, same runner, same handlers, same database writes as
production — only the transport differs. This proves the engine is correct
independently of Celery, and the Celery E2E run then proves the transport.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.dag import validate_dag
from app.core.spec import WorkflowSpec
from app.core.states import AttemptStatus, TaskStatus, WorkflowStatus
from app.db.models import TaskAttempt, TaskRun, WorkflowRun
from app.handlers import handler_names
from app.orchestration.dispatch import InlineDispatcher
from app.orchestration.reconciler import reconcile_run
from tests.integration.factories import make_run
from tests.integration.overlap import count_overlapping_pairs

WORKFLOWS_DIR = Path(__file__).resolve().parents[2] / "workflows"


def load_workflow(name: str) -> dict:
    return json.loads((WORKFLOWS_DIR / f"{name}.json").read_text())


@pytest.mark.parametrize("name", ["sequential_etl", "fanout_join"])
def test_shipped_workflow_definitions_are_valid(name: str) -> None:
    spec = WorkflowSpec.model_validate(load_workflow(name))
    assert validate_dag(spec, known_handlers=handler_names()) == []


def _run_to_completion(session_factory, spec_doc: dict) -> WorkflowRun:
    with session_factory() as s:
        run = make_run(s, spec_doc)

    # One reconcile kicks it off; the InlineDispatcher then drives the whole
    # DAG synchronously through the real runner.
    reconcile_run(run.id, InlineDispatcher(session_factory), session_factory)

    with session_factory() as s:
        return s.get(WorkflowRun, run.id)


def _tasks(session_factory, run_id) -> dict[str, TaskRun]:
    with session_factory() as s:
        rows = s.execute(select(TaskRun).where(TaskRun.run_id == run_id)).scalars().all()
        return {t.task_key: t for t in rows}


class TestSequentialEtl:
    def test_runs_to_success_in_dependency_order(self, session_factory) -> None:
        run = _run_to_completion(session_factory, load_workflow("sequential_etl"))

        assert run.status == WorkflowStatus.SUCCEEDED
        assert run.duration_ms is not None

        tasks = _tasks(session_factory, run.id)
        assert {k: t.status for k, t in tasks.items()} == {
            "extract": TaskStatus.SUCCEEDED,
            "transform": TaskStatus.SUCCEEDED,
            "validate": TaskStatus.SUCCEEDED,
            "load": TaskStatus.SUCCEEDED,
        }

        # Strict sequencing: each task starts only after its predecessor finished.
        order = ["extract", "transform", "validate", "load"]
        for earlier, later in zip(order, order[1:], strict=False):
            assert tasks[earlier].finished_at <= tasks[later].started_at, (
                f"{later} started before {earlier} finished"
            )

    def test_produces_real_deterministic_output(self, session_factory) -> None:
        run = _run_to_completion(session_factory, load_workflow("sequential_etl"))
        tasks = _tasks(session_factory, run.id)

        assert tasks["extract"].output["record_count"] == 4000
        assert tasks["validate"].output["valid"] == 4000
        assert tasks["validate"].output["invalid"] == 0
        assert len(tasks["load"].output["final_checksum"]) == 64  # sha256 hex

    def test_output_is_deterministic_across_runs(self, session_factory) -> None:
        first = _run_to_completion(session_factory, load_workflow("sequential_etl"))
        second = _run_to_completion(session_factory, load_workflow("sequential_etl"))

        a = _tasks(session_factory, first.id)["load"].output["final_checksum"]
        b = _tasks(session_factory, second.id)["load"].output["final_checksum"]
        assert a == b

    def test_every_task_has_exactly_one_attempt(self, session_factory) -> None:
        run = _run_to_completion(session_factory, load_workflow("sequential_etl"))
        tasks = _tasks(session_factory, run.id)

        with session_factory() as s:
            for task in tasks.values():
                attempts = (
                    s.execute(select(TaskAttempt).where(TaskAttempt.task_run_id == task.id))
                    .scalars()
                    .all()
                )
                assert len(attempts) == 1
                assert attempts[0].status == AttemptStatus.SUCCEEDED
                assert attempts[0].worker_id


class TestFanoutJoin:
    def test_runs_to_success_with_correct_fan_in_ordering(self, session_factory) -> None:
        run = _run_to_completion(session_factory, load_workflow("fanout_join"))

        assert run.status == WorkflowStatus.SUCCEEDED
        tasks = _tasks(session_factory, run.id)
        assert all(t.status == TaskStatus.SUCCEEDED for t in tasks.values())
        assert set(tasks) == {"split", "shard_0", "shard_1", "shard_2", "shard_3", "merge"}

        # split precedes every shard; merge follows every shard.
        for i in range(4):
            shard = tasks[f"shard_{i}"]
            assert tasks["split"].finished_at <= shard.started_at
            assert shard.finished_at <= tasks["merge"].started_at

    def test_merge_verifies_shard_aggregate_against_single_pass(self, session_factory) -> None:
        run = _run_to_completion(session_factory, load_workflow("fanout_join"))
        tasks = _tasks(session_factory, run.id)

        merged = tasks["merge"].output
        assert merged["shards_merged"] == 4
        assert merged["count"] == 12000
        assert merged["verified_against_single_pass"] is True

        # The combined total must equal the sum of the shard outputs.
        shard_sum = sum(tasks[f"shard_{i}"].output["sum"] for i in range(4))
        assert merged["sum"] == shard_sum

    def test_shards_partition_the_keyspace_exhaustively(self, session_factory) -> None:
        run = _run_to_completion(session_factory, load_workflow("fanout_join"))
        tasks = _tasks(session_factory, run.id)

        ranges = sorted(
            (tasks[f"shard_{i}"].output["start"], tasks[f"shard_{i}"].output["end"])
            for i in range(4)
        )
        assert ranges[0][0] == 0
        assert ranges[-1][1] == 12000
        for (_, end), (next_start, _) in zip(ranges, ranges[1:], strict=False):
            assert end == next_start, "shard ranges must be contiguous and non-overlapping"


class TestOverlapHelper:
    """The helper used for the Celery parallelism proof, tested directly."""

    def test_detects_overlap_and_non_overlap(self) -> None:
        from datetime import datetime as dt

        a = ("a", dt(2026, 1, 1, 0, 0, 0), dt(2026, 1, 1, 0, 0, 10))
        b = ("b", dt(2026, 1, 1, 0, 0, 5), dt(2026, 1, 1, 0, 0, 15))
        c = ("c", dt(2026, 1, 1, 0, 0, 20), dt(2026, 1, 1, 0, 0, 30))

        assert count_overlapping_pairs([a, b]) == 1
        assert count_overlapping_pairs([a, c]) == 0
        assert count_overlapping_pairs([a, b, c]) == 1

    def test_touching_intervals_are_not_overlapping(self) -> None:
        from datetime import datetime as dt

        a = ("a", dt(2026, 1, 1, 0, 0, 0), dt(2026, 1, 1, 0, 0, 10))
        b = ("b", dt(2026, 1, 1, 0, 0, 10), dt(2026, 1, 1, 0, 0, 20))
        assert count_overlapping_pairs([a, b]) == 0

    def test_inline_execution_shows_no_overlap(self, session_factory) -> None:
        """Sanity check on the evidence itself: InlineDispatcher is
        single-threaded, so shard intervals must NOT overlap here. Any
        overlap observed in the Celery run is therefore genuine parallelism
        and not an artefact of how the intervals are measured."""
        run = _run_to_completion(session_factory, load_workflow("fanout_join"))
        tasks = _tasks(session_factory, run.id)

        intervals = [
            (f"shard_{i}", tasks[f"shard_{i}"].started_at, tasks[f"shard_{i}"].finished_at)
            for i in range(4)
        ]
        assert count_overlapping_pairs(intervals) == 0
