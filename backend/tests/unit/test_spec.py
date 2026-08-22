import pytest
from pydantic import ValidationError

from app.core.retry import RetryPolicy
from app.core.spec import TaskSpec, WorkflowDefaults, WorkflowSpec


def _spec(**overrides: object) -> WorkflowSpec:
    base: dict[str, object] = dict(
        key="etl",
        name="ETL",
        tasks=(
            TaskSpec(key="extract", handler="data.extract"),
            TaskSpec(key="transform", handler="data.transform", depends_on=("extract",)),
        ),
    )
    base.update(overrides)
    return WorkflowSpec(**base)  # type: ignore[arg-type]


def test_valid_spec_parses() -> None:
    spec = _spec()
    assert spec.key == "etl"
    assert len(spec.tasks) == 2
    assert spec.tasks[1].depends_on == ("extract",)


def test_workflow_key_must_be_non_empty() -> None:
    with pytest.raises(ValidationError):
        WorkflowSpec(key="", name="x", tasks=(TaskSpec(key="a", handler="h"),))


def test_task_key_must_be_non_empty() -> None:
    with pytest.raises(ValidationError):
        TaskSpec(key="", handler="h")


def test_task_handler_must_be_non_empty() -> None:
    with pytest.raises(ValidationError):
        TaskSpec(key="a", handler="")


def test_workflow_requires_at_least_one_task() -> None:
    with pytest.raises(ValidationError):
        WorkflowSpec(key="empty", name="Empty", tasks=())


def test_invalid_nested_retry_policy_rejected() -> None:
    with pytest.raises(ValidationError):
        TaskSpec.model_validate({"key": "a", "handler": "h", "retry": {"max_attempts": 0}})


def test_invalid_task_timeout_out_of_bounds() -> None:
    with pytest.raises(ValidationError):
        TaskSpec(key="a", handler="h", timeout_seconds=0)
    with pytest.raises(ValidationError):
        TaskSpec(key="a", handler="h", timeout_seconds=999_999)


def test_invalid_workflow_default_timeout_out_of_bounds() -> None:
    with pytest.raises(ValidationError):
        WorkflowDefaults(timeout_seconds=0)


def test_malformed_task_missing_required_fields() -> None:
    with pytest.raises(ValidationError):
        TaskSpec.model_validate({"handler": "h"})  # missing key
    with pytest.raises(ValidationError):
        TaskSpec.model_validate({"key": "a"})  # missing handler


def test_no_arbitrary_code_fields_exist_on_task_spec() -> None:
    """handler is a plain string lookup key; there is no field through
    which a spec could smuggle a callable, eval'd expression, or pickled
    object into the model."""
    assert "handler" in TaskSpec.model_fields
    assert TaskSpec.model_fields["handler"].annotation is str


class TestDefaultInheritance:
    def test_task_without_own_retry_falls_back_to_workflow_default(self) -> None:
        spec = _spec(defaults=WorkflowDefaults(retry=RetryPolicy(max_attempts=3)))
        task = spec.tasks[0]
        assert task.retry is None
        assert spec.effective_retry_policy(task).max_attempts == 3

    def test_task_own_retry_overrides_workflow_default(self) -> None:
        task = TaskSpec(key="a", handler="h", retry=RetryPolicy(max_attempts=5))
        spec = WorkflowSpec(
            key="w",
            name="W",
            tasks=(task,),
            defaults=WorkflowDefaults(retry=RetryPolicy(max_attempts=1)),
        )
        assert spec.effective_retry_policy(task).max_attempts == 5

    def test_task_without_own_timeout_falls_back_to_workflow_default(self) -> None:
        spec = _spec(defaults=WorkflowDefaults(timeout_seconds=120))
        task = spec.tasks[0]
        assert task.timeout_seconds is None
        assert spec.effective_timeout_seconds(task) == 120

    def test_task_own_timeout_overrides_workflow_default(self) -> None:
        task = TaskSpec(key="a", handler="h", timeout_seconds=10)
        spec = WorkflowSpec(
            key="w", name="W", tasks=(task,), defaults=WorkflowDefaults(timeout_seconds=120)
        )
        assert spec.effective_timeout_seconds(task) == 10


def test_spec_is_frozen() -> None:
    spec = _spec()
    with pytest.raises(ValidationError):
        spec.name = "changed"  # type: ignore[misc]
