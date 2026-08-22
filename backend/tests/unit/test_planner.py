from app.core.states import TaskStatus, WorkflowStatus
from app.orchestration.planner import TaskSnapshot, plan

P = TaskStatus.PENDING
Q = TaskStatus.QUEUED
R = TaskStatus.RUNNING
S = TaskStatus.SUCCEEDED
F = TaskStatus.FAILED


def snap(key: str, status: TaskStatus, deps: tuple[str, ...] = (), attempts: int = 0):
    return TaskSnapshot(task_key=key, status=status, depends_on=deps, attempt_count=attempts)


class TestSourceReadiness:
    def test_source_task_is_ready_on_a_fresh_run(self) -> None:
        tasks = (snap("a", P), snap("b", P, ("a",)))
        decisions = plan(WorkflowStatus.PENDING, tasks)

        assert decisions.start_run is True
        assert decisions.ready_task_keys == ("a",)
        assert decisions.run_succeeded is False

    def test_multiple_independent_sources_are_all_ready(self) -> None:
        tasks = (snap("a", P), snap("b", P), snap("c", P, ("a", "b")))
        decisions = plan(WorkflowStatus.PENDING, tasks)

        assert decisions.ready_task_keys == ("a", "b")

    def test_queued_task_is_not_re_reported_as_ready(self) -> None:
        tasks = (snap("a", Q), snap("b", P, ("a",)))
        decisions = plan(WorkflowStatus.RUNNING, tasks)

        assert decisions.ready_task_keys == ()
        assert decisions.is_noop


class TestSequentialReadiness:
    def test_downstream_exposed_only_after_upstream_succeeds(self) -> None:
        running = (snap("a", R), snap("b", P, ("a",)))
        assert plan(WorkflowStatus.RUNNING, running).ready_task_keys == ()

        done = (snap("a", S, attempts=1), snap("b", P, ("a",)))
        assert plan(WorkflowStatus.RUNNING, done).ready_task_keys == ("b",)

    def test_chain_exposes_one_task_at_a_time(self) -> None:
        tasks = (
            snap("extract", S),
            snap("transform", S, ("extract",)),
            snap("validate", P, ("transform",)),
            snap("load", P, ("validate",)),
        )
        assert plan(WorkflowStatus.RUNNING, tasks).ready_task_keys == ("validate",)


class TestFanOut:
    def test_one_success_exposes_every_branch_simultaneously(self) -> None:
        tasks = (
            snap("split", S),
            snap("shard_0", P, ("split",)),
            snap("shard_1", P, ("split",)),
            snap("shard_2", P, ("split",)),
            snap("shard_3", P, ("split",)),
            snap("merge", P, ("shard_0", "shard_1", "shard_2", "shard_3")),
        )
        decisions = plan(WorkflowStatus.RUNNING, tasks)

        assert decisions.ready_task_keys == ("shard_0", "shard_1", "shard_2", "shard_3")
        assert "merge" not in decisions.ready_task_keys


class TestFanIn:
    def _shards(self, statuses: list[TaskStatus]) -> tuple[TaskSnapshot, ...]:
        return (
            snap("split", S),
            *[snap(f"shard_{i}", st, ("split",)) for i, st in enumerate(statuses)],
            snap("merge", P, tuple(f"shard_{i}" for i in range(len(statuses)))),
        )

    def test_merge_blocked_while_any_shard_incomplete(self) -> None:
        # Note the PENDING case: shard_3 itself is legitimately ready (its
        # own dependency succeeded), but merge must still be withheld.
        for last in (R, Q, P):
            ready = plan(WorkflowStatus.RUNNING, self._shards([S, S, S, last])).ready_task_keys
            assert "merge" not in ready, f"merge must stay blocked while shard_3 is {last}"

    def test_merge_ready_only_when_last_dependency_succeeds(self) -> None:
        decisions = plan(WorkflowStatus.RUNNING, self._shards([S, S, S, S]))
        assert decisions.ready_task_keys == ("merge",)

    def test_merge_not_ready_if_a_dependency_failed(self) -> None:
        assert plan(WorkflowStatus.RUNNING, self._shards([S, S, S, F])).ready_task_keys == ()


class TestRunCompletion:
    def test_run_succeeded_when_all_tasks_succeeded(self) -> None:
        tasks = (snap("a", S), snap("b", S, ("a",)))
        decisions = plan(WorkflowStatus.RUNNING, tasks)

        assert decisions.run_succeeded is True
        assert decisions.ready_task_keys == ()

    def test_run_not_succeeded_while_work_remains(self) -> None:
        tasks = (snap("a", S), snap("b", R, ("a",)))
        assert plan(WorkflowStatus.RUNNING, tasks).run_succeeded is False


class TestIdempotence:
    def test_finished_run_produces_no_decisions(self) -> None:
        tasks = (snap("a", S), snap("b", S, ("a",)))

        for terminal in (
            WorkflowStatus.SUCCEEDED,
            WorkflowStatus.FAILED,
            WorkflowStatus.CANCELLED,
        ):
            decisions = plan(terminal, tasks)
            assert decisions.is_noop, f"{terminal} should be a no-op"
            assert decisions.ready_task_keys == ()
            assert decisions.run_succeeded is False
            assert decisions.start_run is False

    def test_planning_is_pure_and_repeatable(self) -> None:
        tasks = (snap("split", S), snap("shard_0", P, ("split",)))
        first = plan(WorkflowStatus.RUNNING, tasks)
        second = plan(WorkflowStatus.RUNNING, tasks)
        assert first == second
