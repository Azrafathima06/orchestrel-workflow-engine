"""Pure DAG validation and dependency-resolution utilities.

Operates entirely on WorkflowSpec / TaskSpec (app.core.spec) and plain
Python structures — no persistence, no framework. This is what makes the
orchestration engine's hardest correctness property (the DAG is a real
DAG, and dependencies resolve correctly) testable in milliseconds.
"""

from collections import deque
from collections.abc import Collection, Iterator, Mapping
from dataclasses import dataclass

from app.core.spec import WorkflowSpec
from app.core.states import TaskStatus


@dataclass(frozen=True)
class ValidationError:
    """One semantic problem found in a WorkflowSpec.

    `validate_dag` returns a list of ALL problems it finds, not just the
    first — so a single bad spec can be fixed in one pass instead of an
    error-fix-resubmit loop.
    """

    code: str
    message: str
    task_key: str | None = None
    cycle: tuple[str, ...] | None = None


def dependency_map(spec: WorkflowSpec) -> dict[str, tuple[str, ...]]:
    """task_key -> the keys it directly depends on (as declared in the spec)."""
    return {task.key: task.depends_on for task in spec.tasks}


def reverse_dependency_map(spec: WorkflowSpec) -> dict[str, tuple[str, ...]]:
    """task_key -> the keys that directly depend on it (its direct dependents).

    This is the forward execution direction: an edge here means "when this
    task succeeds, that task may become ready" — the opposite direction of
    `depends_on`.
    """
    dependents: dict[str, list[str]] = {task.key: [] for task in spec.tasks}
    for task in spec.tasks:
        for dep in task.depends_on:
            if dep in dependents:
                dependents[dep].append(task.key)
    return {key: tuple(values) for key, values in dependents.items()}


def validate_dag(
    spec: WorkflowSpec, known_handlers: Collection[str] | None = None
) -> list[ValidationError]:
    """Validate the semantic correctness of a workflow spec's task graph.

    `known_handlers`, if given, is checked against each task's `handler`
    string. It is a plain collection of names rather than the actual
    handler registry object, so this module never needs to import
    anything from app.handlers.
    """
    keys = [task.key for task in spec.tasks]
    key_set = set(keys)

    errors: list[ValidationError] = []
    errors.extend(_check_duplicate_keys(keys))
    errors.extend(_check_dependencies(spec, key_set))
    errors.extend(_check_has_source_task(spec))
    if known_handlers is not None:
        errors.extend(_check_handlers(spec, known_handlers))

    # Cycle detection walks the edges implied by `depends_on`. That walk is
    # only meaningful once every edge points at a real, unique task and no
    # task points at itself — otherwise "the graph" isn't well-defined yet.
    broken_edge_codes = {"duplicate_task_key", "unknown_dependency", "self_dependency"}
    if not any(error.code in broken_edge_codes for error in errors):
        errors.extend(_check_acyclic(key_set, dependency_map(spec)))

    return errors


def _check_duplicate_keys(keys: list[str]) -> list[ValidationError]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for key in keys:
        if key in seen:
            duplicates.add(key)
        seen.add(key)
    return [
        ValidationError(
            code="duplicate_task_key",
            message=f"task key '{key}' is defined more than once",
            task_key=key,
        )
        for key in sorted(duplicates)
    ]


def _check_dependencies(spec: WorkflowSpec, key_set: set[str]) -> list[ValidationError]:
    errors: list[ValidationError] = []
    for task in spec.tasks:
        for dep in task.depends_on:
            if dep == task.key:
                errors.append(
                    ValidationError(
                        code="self_dependency",
                        message=f"task '{task.key}' cannot depend on itself",
                        task_key=task.key,
                    )
                )
            elif dep not in key_set:
                errors.append(
                    ValidationError(
                        code="unknown_dependency",
                        message=f"task '{task.key}' depends on unknown task '{dep}'",
                        task_key=task.key,
                    )
                )
    return errors


def _check_has_source_task(spec: WorkflowSpec) -> list[ValidationError]:
    if any(len(task.depends_on) == 0 for task in spec.tasks):
        return []
    return [
        ValidationError(
            code="no_source_task",
            message="workflow has no task without dependencies; nothing could ever start",
        )
    ]


def _check_handlers(spec: WorkflowSpec, known_handlers: Collection[str]) -> list[ValidationError]:
    handler_set = set(known_handlers)
    return [
        ValidationError(
            code="unknown_handler",
            message=f"task '{task.key}' references unknown handler '{task.handler}'",
            task_key=task.key,
        )
        for task in spec.tasks
        if task.handler not in handler_set
    ]


def _check_acyclic(
    keys: set[str], deps: dict[str, tuple[str, ...]]
) -> list[ValidationError]:
    """Kahn's algorithm: O(V + E) topological sort that doubles as cycle detection.

    Repeatedly remove nodes with zero remaining in-degree. If every node
    gets removed, the graph is acyclic. If nodes remain, those leftover
    nodes are exactly the ones involved in (or downstream of) a cycle.
    """
    dependents = _dependents_map(keys, deps)
    in_degree = {key: len(deps[key]) for key in keys}

    queue: deque[str] = deque(sorted(key for key, degree in in_degree.items() if degree == 0))
    visited: list[str] = []
    remaining = dict(in_degree)

    while queue:
        node = queue.popleft()
        visited.append(node)
        for dependent in dependents[node]:
            remaining[dependent] -= 1
            if remaining[dependent] == 0:
                queue.append(dependent)

    if len(visited) == len(keys):
        return []

    cyclic_nodes = keys - set(visited)
    cycle_path = _find_cycle_path(cyclic_nodes, dependents)
    return [
        ValidationError(
            code="cycle",
            message=f"cycle detected: {' → '.join(cycle_path)}",
            cycle=tuple(cycle_path),
        )
    ]


def _dependents_map(keys: set[str], deps: dict[str, tuple[str, ...]]) -> dict[str, list[str]]:
    dependents: dict[str, list[str]] = {key: [] for key in keys}
    for key, ds in deps.items():
        for d in ds:
            if d in dependents:
                dependents[d].append(key)
    return dependents


def _find_cycle_path(cyclic_nodes: set[str], dependents: dict[str, list[str]]) -> list[str]:
    """Iterative DFS over the leftover (cyclic) subgraph to extract one actual cycle path.

    Standard white/gray/black coloring: WHITE = unvisited, GRAY = on the
    current DFS path, BLACK = fully explored. Walking forward along
    `dependents` edges (execution order) and hitting a GRAY node means
    we've found a back-edge — the path from that node's first occurrence
    to here, plus one repeat of it, is the cycle. Restricting traversal to
    `cyclic_nodes` skips any acyclic tail hanging off the cycle (a node
    stuck behind it but not itself part of it).
    """
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {node: WHITE for node in cyclic_nodes}

    for start in sorted(cyclic_nodes):
        if color[start] != WHITE:
            continue

        path: list[str] = [start]
        color[start] = GRAY
        stack: list[tuple[str, Iterator[str]]] = [
            (start, iter(n for n in dependents.get(start, []) if n in cyclic_nodes))
        ]

        while stack:
            node, neighbors = stack[-1]
            neighbor = next(neighbors, None)

            if neighbor is None:
                stack.pop()
                path.pop()
                color[node] = BLACK
                continue

            if color[neighbor] == GRAY:
                cycle_start = path.index(neighbor)
                return [*path[cycle_start:], neighbor]

            if color[neighbor] == WHITE:
                color[neighbor] = GRAY
                path.append(neighbor)
                stack.append(
                    (neighbor, iter(n for n in dependents.get(neighbor, []) if n in cyclic_nodes))
                )

    # Unreachable: _check_acyclic only calls this with a non-empty set of
    # nodes that Kahn's algorithm proved participate in at least one cycle.
    raise AssertionError("no cycle found in a node set Kahn's algorithm reported as cyclic")


def topological_sort(spec: WorkflowSpec) -> tuple[str, ...]:
    """Return task keys in a valid execution order.

    Raises ValueError if the spec contains a cycle — call validate_dag()
    first in any code path where the spec isn't already known-valid.
    """
    keys = {task.key for task in spec.tasks}
    deps = dependency_map(spec)
    dependents = _dependents_map(keys, deps)
    in_degree = {key: len(deps[key]) for key in keys}

    queue: deque[str] = deque(sorted(key for key, degree in in_degree.items() if degree == 0))
    order: list[str] = []
    remaining = dict(in_degree)

    while queue:
        node = queue.popleft()
        order.append(node)
        for dependent in dependents[node]:
            remaining[dependent] -= 1
            if remaining[dependent] == 0:
                queue.append(dependent)

    if len(order) != len(keys):
        raise ValueError("cannot topologically sort a graph containing a cycle")

    return tuple(order)


def descendants(task_key: str, spec: WorkflowSpec) -> frozenset[str]:
    """All tasks that transitively depend on `task_key`, directly or indirectly.

    Used to propagate UPSTREAM_FAILED: when a task fails, exactly this set
    (and no other task) is affected. Unrelated branches are untouched by
    construction, since this is a pure forward-reachability walk.
    """
    forward = reverse_dependency_map(spec)
    seen: set[str] = set()
    queue: deque[str] = deque(forward.get(task_key, ()))

    while queue:
        node = queue.popleft()
        if node in seen:
            continue
        seen.add(node)
        queue.extend(forward.get(node, ()))

    return frozenset(seen)


def ready_task_keys(spec: WorkflowSpec, statuses: Mapping[str, TaskStatus]) -> frozenset[str]:
    """Task keys that are PENDING and whose every dependency has SUCCEEDED.

    Pure function over a plain task_key -> TaskStatus mapping; the future
    planner supplies this mapping from persisted task_run rows and calls
    this on every reconcile. A task with no dependencies is trivially
    ready as soon as it is PENDING.
    """
    ready: set[str] = set()
    for task in spec.tasks:
        if statuses.get(task.key) != TaskStatus.PENDING:
            continue
        if all(statuses.get(dep) == TaskStatus.SUCCEEDED for dep in task.depends_on):
            ready.add(task.key)
    return frozenset(ready)
