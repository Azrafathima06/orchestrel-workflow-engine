"""Pure planning: given a snapshot of a run's state, decide what should happen next.

No SQL, no Celery, no I/O of any kind. The planner answers one question —
"given these task states right now, what should the reconciler do?" — as a
function of its inputs. That makes every interesting orchestration decision
(fan-out exposure, fan-in gating, run completion, idempotence on a finished
run) testable in microseconds.

The reconciler is responsible for applying these decisions under a row lock;
the planner never assumes its decisions will succeed.
"""

from dataclasses import dataclass, field

from app.core.states import TASK_TERMINAL_STATUSES, TaskStatus, WorkflowStatus


@dataclass(frozen=True)
class TaskSnapshot:
    """A task's state as loaded from the database, stripped of ORM identity."""

    task_key: str
    status: TaskStatus
    depends_on: tuple[str, ...]
    attempt_count: int


@dataclass(frozen=True)
class Decisions:
    """What the reconciler should do, in the order it should do it."""

    start_run: bool = False
    ready_task_keys: tuple[str, ...] = field(default_factory=tuple)
    run_succeeded: bool = False

    @property
    def is_noop(self) -> bool:
        return not self.start_run and not self.ready_task_keys and not self.run_succeeded


def plan(run_status: WorkflowStatus, tasks: tuple[TaskSnapshot, ...]) -> Decisions:
    """Decide the next actions for a run.

    Readiness rule: a PENDING task becomes ready only when *every* one of its
    dependencies is SUCCEEDED. Fan-out falls out of this naturally (one
    upstream success can satisfy several tasks in the same pass); so does
    fan-in (a join stays PENDING until its last dependency succeeds).
    """
    # A run that has already reached a terminal state is immutable. Returning
    # a no-op here is what makes repeated reconciliation free and safe —
    # duplicate reconcile messages are expected, not exceptional.
    if run_status in (WorkflowStatus.SUCCEEDED, WorkflowStatus.FAILED, WorkflowStatus.CANCELLED):
        return Decisions()

    status_by_key = {task.task_key: task.status for task in tasks}

    ready = tuple(
        sorted(
            task.task_key
            for task in tasks
            if task.status == TaskStatus.PENDING
            and all(status_by_key.get(dep) == TaskStatus.SUCCEEDED for dep in task.depends_on)
        )
    )

    all_succeeded = bool(tasks) and all(task.status == TaskStatus.SUCCEEDED for task in tasks)

    # Only start the run if it is PENDING and there is genuinely something to
    # do — a run whose tasks are all already terminal should not flip to
    # RUNNING on its way to a terminal state.
    start_run = run_status == WorkflowStatus.PENDING and bool(ready or not all_terminal(tasks))

    return Decisions(
        start_run=start_run,
        ready_task_keys=ready,
        run_succeeded=all_succeeded,
    )


def all_terminal(tasks: tuple[TaskSnapshot, ...]) -> bool:
    return all(task.status in TASK_TERMINAL_STATUSES for task in tasks)
