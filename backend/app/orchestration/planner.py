"""Pure planning: given a snapshot of a run's state, decide what should happen next.

No SQL, no Celery, no I/O of any kind. The planner answers one question —
"given these task states right now, what should the reconciler do?" — as a
function of its inputs. That makes every interesting orchestration decision
(fan-out exposure, fan-in gating, failure isolation, run completion,
idempotence on a finished run) testable in microseconds.

The reconciler is responsible for applying these decisions under a row lock;
the planner never assumes its decisions will succeed.
"""

from collections import deque
from dataclasses import dataclass, field

from app.core.states import TASK_TERMINAL_STATUSES, TaskStatus, WorkflowStatus

# A dependency in one of these states means a dependent task can never run:
# its input will never be produced. Distinct from "not finished yet".
TERMINAL_BAD_STATUSES: frozenset[TaskStatus] = frozenset(
    {TaskStatus.FAILED, TaskStatus.UPSTREAM_FAILED, TaskStatus.CANCELLED}
)

# States that mean work is still happening or could still happen.
IN_FLIGHT_STATUSES: frozenset[TaskStatus] = frozenset(
    {TaskStatus.QUEUED, TaskStatus.RUNNING, TaskStatus.RETRYING}
)


@dataclass(frozen=True)
class TaskSnapshot:
    """A task's state as loaded from the database, stripped of ORM identity."""

    task_key: str
    status: TaskStatus
    depends_on: tuple[str, ...]
    attempt_count: int


@dataclass(frozen=True)
class BlockedTask:
    """A task that can never run, and the upstream failure responsible."""

    task_key: str
    blocked_by: str


@dataclass(frozen=True)
class Decisions:
    """What the reconciler should do, in the order it should do it."""

    start_run: bool = False
    ready_task_keys: tuple[str, ...] = field(default_factory=tuple)
    blocked_tasks: tuple[BlockedTask, ...] = field(default_factory=tuple)
    run_succeeded: bool = False
    run_failed: bool = False
    run_error: str | None = None

    @property
    def is_noop(self) -> bool:
        return not (
            self.start_run
            or self.ready_task_keys
            or self.blocked_tasks
            or self.run_succeeded
            or self.run_failed
        )


def plan(run_status: WorkflowStatus, tasks: tuple[TaskSnapshot, ...]) -> Decisions:
    """Decide the next actions for a run.

    Readiness rule: a PENDING task becomes ready only when *every* one of its
    dependencies is SUCCEEDED. Fan-out falls out of this naturally (one
    upstream success can satisfy several tasks in the same pass); so does
    fan-in (a join stays PENDING until its last dependency succeeds).

    Blocking rule: a PENDING task whose dependency reached a terminal-bad
    state can never run, so it — and everything downstream of it — becomes
    UPSTREAM_FAILED. Tasks on unrelated branches are untouched, which is
    exactly what failure isolation means here.
    """
    # A run that has already reached a terminal state is immutable. Returning
    # a no-op here is what makes repeated reconciliation free and safe —
    # duplicate reconcile messages are expected, not exceptional.
    if run_status in (WorkflowStatus.SUCCEEDED, WorkflowStatus.FAILED, WorkflowStatus.CANCELLED):
        return Decisions()

    status_by_key = {task.task_key: task.status for task in tasks}

    blocked = _propagate_blocked(tasks, status_by_key)
    blocked_keys = {b.task_key for b in blocked}

    ready = tuple(
        sorted(
            task.task_key
            for task in tasks
            if task.status == TaskStatus.PENDING
            and task.task_key not in blocked_keys
            and all(status_by_key.get(dep) == TaskStatus.SUCCEEDED for dep in task.depends_on)
        )
    )

    # Project the effect of this pass's blocking decisions before judging
    # whether the run is finished — otherwise a run would need an extra
    # reconcile just to notice it had settled.
    projected = {
        key: (TaskStatus.UPSTREAM_FAILED if key in blocked_keys else status)
        for key, status in status_by_key.items()
    }

    all_succeeded = bool(tasks) and all(s == TaskStatus.SUCCEEDED for s in projected.values())
    any_bad = any(s in TERMINAL_BAD_STATUSES for s in projected.values())

    # Work remains if anything is in flight, or if a PENDING task still has a
    # path to running (all deps either succeeded or still could).
    work_remains = bool(ready) or any(
        s in IN_FLIGHT_STATUSES for s in projected.values()
    ) or any(
        _may_still_run(task, projected)
        for task in tasks
        if projected[task.task_key] == TaskStatus.PENDING
    )

    run_failed = any_bad and not work_remains
    run_error = _summarise_failure(tasks, projected) if run_failed else None

    # Only start the run if it is PENDING and there is genuinely something to
    # do — a run whose tasks are all already terminal should not flip to
    # RUNNING on its way to a terminal state.
    start_run = run_status == WorkflowStatus.PENDING and bool(ready or not all_terminal(tasks))

    return Decisions(
        start_run=start_run,
        ready_task_keys=ready,
        blocked_tasks=blocked,
        run_succeeded=all_succeeded,
        run_failed=run_failed,
        run_error=run_error,
    )


def _propagate_blocked(
    tasks: tuple[TaskSnapshot, ...], status_by_key: dict[str, TaskStatus]
) -> tuple[BlockedTask, ...]:
    """Every PENDING task transitively unreachable because of a failed dependency.

    Breadth-first from the tasks whose *direct* dependency is already
    terminal-bad, then outward along the dependency edges. Each blocked task
    records the specific upstream task responsible, so the eventual error
    message names a real culprit instead of saying "an upstream task failed".
    """
    dependents: dict[str, list[str]] = {t.task_key: [] for t in tasks}
    for task in tasks:
        for dep in task.depends_on:
            if dep in dependents:
                dependents[dep].append(task.task_key)

    by_key = {t.task_key: t for t in tasks}
    blocked: dict[str, str] = {}
    queue: deque[str] = deque()

    # Seed: PENDING tasks with a directly terminal-bad dependency.
    for task in tasks:
        if task.status != TaskStatus.PENDING:
            continue
        for dep in task.depends_on:
            if status_by_key.get(dep) in TERMINAL_BAD_STATUSES:
                blocked[task.task_key] = dep
                queue.append(task.task_key)
                break

    # Spread: anything PENDING downstream of a blocked task is also blocked.
    while queue:
        key = queue.popleft()
        for dependent_key in dependents.get(key, []):
            if dependent_key in blocked:
                continue
            dependent = by_key.get(dependent_key)
            if dependent is None or dependent.status != TaskStatus.PENDING:
                continue
            blocked[dependent_key] = key
            queue.append(dependent_key)

    return tuple(
        BlockedTask(task_key=key, blocked_by=blocked[key]) for key in sorted(blocked)
    )


def _may_still_run(task: TaskSnapshot, projected: dict[str, TaskStatus]) -> bool:
    """True if this PENDING task could still become runnable eventually.

    It can, unless some dependency is already terminal-bad or is itself a
    PENDING task with no path forward.
    """
    for dep in task.depends_on:
        dep_status = projected.get(dep)
        if dep_status in TERMINAL_BAD_STATUSES:
            return False
        if dep_status == TaskStatus.SUCCEEDED:
            continue
        if dep_status in IN_FLIGHT_STATUSES or dep_status == TaskStatus.PENDING:
            continue
        return False
    return True


def _summarise_failure(
    tasks: tuple[TaskSnapshot, ...], projected: dict[str, TaskStatus]
) -> str:
    """Human-readable run-level error naming what actually failed."""
    failed = sorted(k for k, s in projected.items() if s == TaskStatus.FAILED)
    blocked = sorted(k for k, s in projected.items() if s == TaskStatus.UPSTREAM_FAILED)
    cancelled = sorted(k for k, s in projected.items() if s == TaskStatus.CANCELLED)

    parts = []
    if failed:
        parts.append(f"failed: {', '.join(failed)}")
    if blocked:
        parts.append(f"skipped (upstream failed): {', '.join(blocked)}")
    if cancelled:
        parts.append(f"cancelled: {', '.join(cancelled)}")

    bad = len(failed) + len(blocked) + len(cancelled)
    return f"{bad} of {len(tasks)} tasks did not succeed — " + "; ".join(parts)


def all_terminal(tasks: tuple[TaskSnapshot, ...]) -> bool:
    return all(task.status in TASK_TERMINAL_STATUSES for task in tasks)
