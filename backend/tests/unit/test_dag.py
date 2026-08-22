from app.core.dag import descendants, ready_task_keys, topological_sort, validate_dag
from app.core.spec import TaskSpec, WorkflowSpec
from app.core.states import TaskStatus


def _task(key: str, depends_on: tuple[str, ...] = ()) -> TaskSpec:
    return TaskSpec(key=key, handler="noop", depends_on=depends_on)


def _spec(*tasks: TaskSpec, key: str = "wf") -> WorkflowSpec:
    return WorkflowSpec(key=key, name=key, tasks=tasks)


def _assert_respects_dependencies(spec: WorkflowSpec, order: tuple[str, ...]) -> None:
    index = {key: i for i, key in enumerate(order)}
    for task in spec.tasks:
        for dep in task.depends_on:
            assert index[dep] < index[task.key], f"{dep} must precede {task.key}"


# ---------------------------------------------------------------- valid graphs


def test_single_task_is_valid() -> None:
    spec = _spec(_task("a"))
    assert validate_dag(spec) == []
    assert topological_sort(spec) == ("a",)


def test_sequential_chain_is_valid() -> None:
    spec = _spec(_task("a"), _task("b", ("a",)), _task("c", ("b",)))
    assert validate_dag(spec) == []
    order = topological_sort(spec)
    assert order == ("a", "b", "c")
    _assert_respects_dependencies(spec, order)


def test_diamond_is_valid() -> None:
    spec = _spec(
        _task("a"),
        _task("b", ("a",)),
        _task("c", ("a",)),
        _task("d", ("b", "c")),
    )
    assert validate_dag(spec) == []
    _assert_respects_dependencies(spec, topological_sort(spec))


def test_wide_fan_out_is_valid() -> None:
    spec = _spec(_task("a"), *[_task(f"b{i}", ("a",)) for i in range(5)])
    assert validate_dag(spec) == []
    _assert_respects_dependencies(spec, topological_sort(spec))


def test_fan_in_is_valid() -> None:
    shards = [_task(f"shard_{i}") for i in range(5)]
    merge = _task("merge", tuple(t.key for t in shards))
    spec = _spec(*shards, merge)
    assert validate_dag(spec) == []
    _assert_respects_dependencies(spec, topological_sort(spec))


def test_disconnected_components_are_valid() -> None:
    spec = _spec(_task("a"), _task("b", ("a",)), _task("c"), _task("d", ("c",)))
    assert validate_dag(spec) == []
    _assert_respects_dependencies(spec, topological_sort(spec))


# -------------------------------------------------------------- invalid graphs


def test_unknown_dependency_reported() -> None:
    spec = _spec(_task("a", ("missing",)))
    errors = validate_dag(spec)
    codes = {e.code for e in errors}
    assert "unknown_dependency" in codes


def test_self_dependency_reported() -> None:
    spec = _spec(_task("a", ("a",)))
    errors = validate_dag(spec)
    codes = {e.code for e in errors}
    assert "self_dependency" in codes


def test_duplicate_task_key_reported_once_per_key() -> None:
    spec = _spec(_task("a"), _task("a"), _task("a"))
    errors = validate_dag(spec)
    duplicate_errors = [e for e in errors if e.code == "duplicate_task_key"]
    assert len(duplicate_errors) == 1
    assert duplicate_errors[0].task_key == "a"


def test_two_node_cycle_reports_actual_path() -> None:
    spec = _spec(_task("a", ("b",)), _task("b", ("a",)))
    errors = validate_dag(spec)
    cycle_errors = [e for e in errors if e.code == "cycle"]
    assert len(cycle_errors) == 1

    cycle = cycle_errors[0].cycle
    assert cycle is not None
    assert cycle[0] == cycle[-1]  # closed loop
    assert set(cycle) == {"a", "b"}


def test_three_node_cycle_reports_actual_path() -> None:
    # transform depends on extract, validate depends on transform,
    # extract depends on validate -- the exact motivating example from
    # the architecture doc.
    spec = _spec(
        _task("extract", ("validate",)),
        _task("transform", ("extract",)),
        _task("validate", ("transform",)),
    )
    errors = validate_dag(spec)
    cycle_errors = [e for e in errors if e.code == "cycle"]
    assert len(cycle_errors) == 1

    cycle = cycle_errors[0].cycle
    assert cycle is not None
    assert cycle == ("extract", "transform", "validate", "extract")
    assert " → ".join(cycle) in cycle_errors[0].message


def test_cycle_embedded_in_larger_dag_excludes_unrelated_nodes() -> None:
    # source is a healthy, unrelated predecessor; tail is a healthy node
    # stuck downstream of the cycle but not itself part of it. Only
    # x, y, z form the actual cycle.
    spec = _spec(
        _task("source"),
        _task("x", ("source", "z")),
        _task("y", ("x",)),
        _task("z", ("y",)),
        _task("tail", ("z",)),
    )
    errors = validate_dag(spec)
    cycle_errors = [e for e in errors if e.code == "cycle"]
    assert len(cycle_errors) == 1

    cycle = cycle_errors[0].cycle
    assert cycle is not None
    assert set(cycle) == {"x", "y", "z"}
    assert "source" not in cycle
    assert "tail" not in cycle


def test_no_source_task_reported_when_every_task_has_a_dependency() -> None:
    # A single task whose only dependency doesn't exist: no task has an
    # empty depends_on, so no_source_task fires; the broken reference
    # also fires unknown_dependency; and cycle detection is skipped
    # entirely because the edges aren't well-defined yet.
    spec = _spec(_task("a", ("ghost",)))
    errors = validate_dag(spec)
    codes = {e.code for e in errors}
    assert "no_source_task" in codes
    assert "unknown_dependency" in codes
    assert "cycle" not in codes


def test_validate_dag_reports_all_errors_not_just_the_first() -> None:
    spec = _spec(_task("a", ("a",)), _task("b", ("missing",)))
    errors = validate_dag(spec)
    codes = {e.code for e in errors}
    assert "self_dependency" in codes
    assert "unknown_dependency" in codes
    assert len(errors) >= 2


def test_unknown_handler_reported_when_registry_given() -> None:
    spec = _spec(_task("a"))
    errors = validate_dag(spec, known_handlers={"other.handler"})
    codes = {e.code for e in errors}
    assert "unknown_handler" in codes


def test_known_handler_passes_when_registry_given() -> None:
    spec = _spec(_task("a"))
    errors = validate_dag(spec, known_handlers={"noop"})
    assert errors == []


def test_handler_not_checked_when_registry_omitted() -> None:
    spec = _spec(_task("a"))
    assert validate_dag(spec) == []


def test_topological_sort_raises_on_cyclic_spec() -> None:
    spec = _spec(_task("a", ("b",)), _task("b", ("a",)))
    try:
        topological_sort(spec)
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for a cyclic spec")


# ------------------------------------------------------------------ utilities


def test_descendants_excludes_unrelated_branches() -> None:
    # seed -> branch A (a1 -> a2 -> a3), branch B (b1 -> b2 -> b3), both -> finalize
    spec = _spec(
        _task("seed"),
        _task("a1", ("seed",)),
        _task("a2", ("a1",)),
        _task("a3", ("a2",)),
        _task("b1", ("seed",)),
        _task("b2", ("b1",)),
        _task("b3", ("b2",)),
        _task("finalize", ("a3", "b3")),
    )
    assert descendants("a2", spec) == frozenset({"a3", "finalize"})
    assert descendants("b1", spec) == frozenset({"b2", "b3", "finalize"})
    assert descendants("seed", spec) == frozenset(
        {"a1", "a2", "a3", "b1", "b2", "b3", "finalize"}
    )


def test_descendants_of_leaf_task_is_empty() -> None:
    spec = _spec(_task("a"), _task("b", ("a",)))
    assert descendants("b", spec) == frozenset()


def test_ready_task_keys_requires_all_dependencies_succeeded() -> None:
    spec = _spec(
        _task("split"),
        _task("shard_a", ("split",)),
        _task("shard_b", ("split",)),
        _task("merge", ("shard_a", "shard_b")),
    )

    only_one_shard_done = {
        "split": TaskStatus.SUCCEEDED,
        "shard_a": TaskStatus.SUCCEEDED,
        "shard_b": TaskStatus.RUNNING,
        "merge": TaskStatus.PENDING,
    }
    assert ready_task_keys(spec, only_one_shard_done) == frozenset()

    both_shards_done = {
        "split": TaskStatus.SUCCEEDED,
        "shard_a": TaskStatus.SUCCEEDED,
        "shard_b": TaskStatus.SUCCEEDED,
        "merge": TaskStatus.PENDING,
    }
    assert ready_task_keys(spec, both_shards_done) == frozenset({"merge"})


def test_ready_task_keys_only_considers_pending_tasks() -> None:
    spec = _spec(_task("a"), _task("b", ("a",)))
    statuses = {"a": TaskStatus.SUCCEEDED, "b": TaskStatus.QUEUED}
    # b's dependency is satisfied, but b is already QUEUED, not PENDING —
    # it must not be reported as newly ready.
    assert ready_task_keys(spec, statuses) == frozenset()


def test_ready_task_keys_source_task_is_ready_immediately() -> None:
    spec = _spec(_task("a"), _task("b", ("a",)))
    statuses = {"a": TaskStatus.PENDING, "b": TaskStatus.PENDING}
    assert ready_task_keys(spec, statuses) == frozenset({"a"})
