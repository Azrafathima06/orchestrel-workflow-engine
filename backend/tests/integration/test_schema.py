"""Schema-level integration tests against the real, migrated PostgreSQL database.

Covers exactly what M1's definition of done asks for: tables exist,
foreign keys work, the unique constraints that later durability
mechanisms depend on actually reject duplicates, enum columns behave,
and cascade delete cleans up a run's tasks and attempts.
"""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError

from app.core.states import AttemptStatus, TaskStatus, TriggerType, WorkflowStatus
from app.db.models import TaskAttempt, TaskRun, WorkflowDefinition, WorkflowRun
from tests.integration.factories import TEST_KEY_PREFIX

EXPECTED_TABLES = {
    "workflow_definition",
    "workflow_run",
    "task_run",
    "task_attempt",
    "schedule",
    "schedule_fire",
}


def test_all_expected_tables_exist(engine) -> None:
    inspector = inspect(engine)
    assert EXPECTED_TABLES <= set(inspector.get_table_names())


def _seed_spec() -> dict:
    """A minimal, genuinely valid sequential_etl spec document — used only
    to prove JSONB round-trips a realistic workflow spec, not to exercise
    DAG semantics (that's app.core.dag's job, covered in tests/unit)."""
    return {
        "key": "sequential_etl",
        "name": "Sequential ETL",
        "description": "development seed workflow for schema validation",
        "tasks": [
            {"key": "extract", "handler": "demo.extract", "depends_on": []},
            {"key": "transform", "handler": "demo.transform", "depends_on": ["extract"]},
        ],
    }


def _make_definition(session, key: str | None = None) -> WorkflowDefinition:
    # Unique by default: this suite shares a database with the seeded
    # production workflow definitions, so a hardcoded key would collide
    # with the real `sequential_etl` row. Callers testing the uniqueness
    # constraint itself pass an explicit key.
    key = key or f"{TEST_KEY_PREFIX}schema_{uuid.uuid4().hex[:8]}"
    definition = WorkflowDefinition(key=key, version=1, name="Sequential ETL", spec=_seed_spec())
    session.add(definition)
    session.flush()
    return definition


def _make_run(session, definition: WorkflowDefinition) -> WorkflowRun:
    run = WorkflowRun(
        definition_id=definition.id,
        definition_key=definition.key,
        spec_snapshot=definition.spec,
        status=WorkflowStatus.PENDING,
        trigger_type=TriggerType.MANUAL,
        params={},
    )
    session.add(run)
    session.flush()
    return run


def _make_task_run(session, run: WorkflowRun, task_key: str = "extract") -> TaskRun:
    task = TaskRun(
        run_id=run.id,
        task_key=task_key,
        handler="demo.extract",
        status=TaskStatus.PENDING,
        depends_on=[],
        params={},
        max_attempts=1,
        timeout_seconds=60,
    )
    session.add(task)
    session.flush()
    return task


class TestWorkflowDefinitionPersistence:
    def test_insert_and_read_back(self, db_session) -> None:
        definition = _make_definition(db_session)

        fetched = db_session.get(WorkflowDefinition, definition.id)

        assert fetched is not None
        assert fetched.key == definition.key
        assert fetched.spec["tasks"][0]["handler"] == "demo.extract"
        assert fetched.is_active is True
        assert fetched.created_at is not None
        assert fetched.created_at.tzinfo is not None  # timestamptz, not naive

    def test_key_uniqueness_enforced(self, db_session) -> None:
        _make_definition(db_session, key=f"{TEST_KEY_PREFIX}dup")
        db_session.add(
            WorkflowDefinition(key=f"{TEST_KEY_PREFIX}dup", version=1, name="Dup", spec={})
        )

        with pytest.raises(IntegrityError):
            db_session.flush()

    def test_version_check_constraint_rejects_zero(self, db_session) -> None:
        db_session.add(
            WorkflowDefinition(
                key=f"{TEST_KEY_PREFIX}bad_version", version=0, name="Bad", spec={}
            )
        )

        with pytest.raises(IntegrityError):
            db_session.flush()


class TestWorkflowRunPersistence:
    def test_fk_to_definition_works(self, db_session) -> None:
        definition = _make_definition(db_session)

        run = _make_run(db_session, definition)
        fetched = db_session.get(WorkflowRun, run.id)

        assert fetched is not None
        assert fetched.definition_id == definition.id
        assert fetched.status == WorkflowStatus.PENDING
        assert fetched.trigger_type == TriggerType.MANUAL

    def test_fk_to_nonexistent_definition_rejected(self, db_session) -> None:
        db_session.add(
            WorkflowRun(
                definition_id=uuid.uuid4(),
                definition_key="ghost",
                spec_snapshot={},
                status=WorkflowStatus.PENDING,
                trigger_type=TriggerType.MANUAL,
                params={},
            )
        )

        with pytest.raises(IntegrityError):
            db_session.flush()

    def test_idempotency_key_uniqueness_enforced(self, db_session) -> None:
        definition = _make_definition(db_session)
        db_session.add(
            WorkflowRun(
                definition_id=definition.id,
                definition_key=definition.key,
                spec_snapshot={},
                status=WorkflowStatus.PENDING,
                trigger_type=TriggerType.API,
                params={},
                idempotency_key="dup-key",
            )
        )
        db_session.flush()

        db_session.add(
            WorkflowRun(
                definition_id=definition.id,
                definition_key=definition.key,
                spec_snapshot={},
                status=WorkflowStatus.PENDING,
                trigger_type=TriggerType.API,
                params={},
                idempotency_key="dup-key",
            )
        )

        with pytest.raises(IntegrityError):
            db_session.flush()


class TestTaskRunPersistence:
    def test_unique_run_id_task_key_enforced(self, db_session) -> None:
        definition = _make_definition(db_session)
        run = _make_run(db_session, definition)
        _make_task_run(db_session, run, "extract")

        db_session.add(
            TaskRun(
                run_id=run.id,
                task_key="extract",
                handler="demo.extract",
                status=TaskStatus.PENDING,
                depends_on=[],
                params={},
                max_attempts=1,
                timeout_seconds=60,
            )
        )

        with pytest.raises(IntegrityError):
            db_session.flush()

    def test_depends_on_array_round_trips(self, db_session) -> None:
        definition = _make_definition(db_session)
        run = _make_run(db_session, definition)
        _make_task_run(db_session, run, "extract")

        transform = TaskRun(
            run_id=run.id,
            task_key="transform",
            handler="demo.transform",
            status=TaskStatus.PENDING,
            depends_on=["extract"],
            params={},
            max_attempts=1,
            timeout_seconds=60,
        )
        db_session.add(transform)
        db_session.flush()

        fetched = db_session.get(TaskRun, transform.id)
        assert fetched.depends_on == ["extract"]


class TestTaskAttemptPersistence:
    def test_unique_task_run_id_attempt_number_enforced(self, db_session) -> None:
        definition = _make_definition(db_session)
        run = _make_run(db_session, definition)
        task = _make_task_run(db_session, run)
        now = datetime.now(UTC)

        db_session.add(
            TaskAttempt(
                task_run_id=task.id,
                attempt_number=1,
                status=AttemptStatus.SUCCEEDED,
                worker_id="worker-a:1",
                started_at=now,
                finished_at=now,
            )
        )
        db_session.flush()

        db_session.add(
            TaskAttempt(
                task_run_id=task.id,
                attempt_number=1,
                status=AttemptStatus.FAILED,
                worker_id="worker-b:1",
                started_at=now,
            )
        )

        with pytest.raises(IntegrityError):
            db_session.flush()

    def test_multiple_attempts_allowed_for_same_task(self, db_session) -> None:
        definition = _make_definition(db_session)
        run = _make_run(db_session, definition)
        task = _make_task_run(db_session, run)
        now = datetime.now(UTC)

        db_session.add(
            TaskAttempt(
                task_run_id=task.id,
                attempt_number=1,
                status=AttemptStatus.FAILED,
                worker_id="worker-a:1",
                started_at=now,
            )
        )
        db_session.add(
            TaskAttempt(
                task_run_id=task.id,
                attempt_number=2,
                status=AttemptStatus.SUCCEEDED,
                worker_id="worker-b:1",
                started_at=now,
            )
        )
        db_session.flush()

        attempts = db_session.scalars(
            select(TaskAttempt).where(TaskAttempt.task_run_id == task.id)
        ).all()
        assert len(attempts) == 2


class TestCascadeDelete:
    def test_deleting_run_cascades_to_tasks_and_attempts(self, db_session) -> None:
        definition = _make_definition(db_session)
        run = _make_run(db_session, definition)
        task = _make_task_run(db_session, run)
        db_session.add(
            TaskAttempt(
                task_run_id=task.id,
                attempt_number=1,
                status=AttemptStatus.SUCCEEDED,
                worker_id="worker-a:1",
                started_at=datetime.now(UTC),
            )
        )
        db_session.flush()
        task_id = task.id

        db_session.delete(run)
        db_session.flush()

        assert db_session.get(TaskRun, task_id) is None
        remaining_attempts = db_session.scalars(
            select(TaskAttempt).where(TaskAttempt.task_run_id == task_id)
        ).all()
        assert remaining_attempts == []


class TestEnumColumns:
    def test_invalid_enum_value_rejected_at_db_level(self, db_session) -> None:
        definition = _make_definition(db_session)
        run = _make_run(db_session, definition)

        with pytest.raises(Exception):  # noqa: B017 - psycopg raises a DB-level error, not IntegrityError
            db_session.execute(
                text("UPDATE workflow_run SET status = 'not_a_real_status' WHERE id = :id"),
                {"id": run.id},
            )
            db_session.flush()

    def test_every_task_status_value_is_accepted(self, db_session) -> None:
        definition = _make_definition(db_session)
        run = _make_run(db_session, definition)

        for i, status in enumerate(TaskStatus):
            db_session.add(
                TaskRun(
                    run_id=run.id,
                    task_key=f"t{i}",
                    handler="demo.noop",
                    status=status,
                    depends_on=[],
                    params={},
                    max_attempts=1,
                    timeout_seconds=60,
                )
            )

        db_session.flush()  # must not raise for any TaskStatus member
