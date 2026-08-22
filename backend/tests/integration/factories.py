"""Helpers for building real workflow definitions and runs in the test database."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.core.spec import WorkflowSpec
from app.core.states import TriggerType
from app.db.models import WorkflowDefinition, WorkflowRun
from app.orchestration.materialize import create_run

# Every fixture-created definition carries this prefix so the cleanup
# fixture can remove exactly the test data and never touch seeded
# workflows sharing the development database.
TEST_KEY_PREFIX = "zz_test__"


def make_spec(key: str, tasks: list[dict[str, Any]], name: str | None = None) -> dict[str, Any]:
    """Build a spec document, validating it the same way the seeder would."""
    doc = {
        "key": key,
        "name": name or key,
        "description": "test fixture",
        "defaults": {"retry": {"max_attempts": 1}, "timeout_seconds": 60},
        "tasks": tasks,
    }
    WorkflowSpec.model_validate(doc)  # fail fast on a malformed fixture
    return doc


def persist_definition(session: Session, spec_doc: dict[str, Any]) -> WorkflowDefinition:
    definition = WorkflowDefinition(
        id=uuid.uuid4(),
        # Unique per test so parallel/repeated runs never collide on the
        # workflow_definition.key unique constraint.
        key=f"{TEST_KEY_PREFIX}{spec_doc['key']}_{uuid.uuid4().hex[:8]}",
        version=1,
        name=spec_doc["name"],
        description=spec_doc.get("description"),
        spec=spec_doc,
        is_active=True,
    )
    session.add(definition)
    session.flush()
    return definition


def make_run(session: Session, spec_doc: dict[str, Any], params: dict | None = None) -> WorkflowRun:
    definition = persist_definition(session, spec_doc)
    run = create_run(
        session, definition, params=params or {}, trigger_type=TriggerType.MANUAL
    )
    session.commit()
    return run


# A trivial handler used by orchestration tests that care about DAG
# progression rather than about what a handler computes.
NOOP = "test.noop"


def linear_spec(key: str = "linear") -> dict[str, Any]:
    return make_spec(
        key,
        [
            {"key": "a", "handler": NOOP, "params": {}, "depends_on": []},
            {"key": "b", "handler": NOOP, "params": {}, "depends_on": ["a"]},
            {"key": "c", "handler": NOOP, "params": {}, "depends_on": ["b"]},
        ],
    )


def fanout_spec(key: str = "fanout", shards: int = 4) -> dict[str, Any]:
    tasks: list[dict[str, Any]] = [
        {"key": "split", "handler": NOOP, "params": {}, "depends_on": []}
    ]
    for i in range(shards):
        tasks.append(
            {"key": f"shard_{i}", "handler": NOOP, "params": {"i": i}, "depends_on": ["split"]}
        )
    tasks.append(
        {
            "key": "merge",
            "handler": NOOP,
            "params": {},
            "depends_on": [f"shard_{i}" for i in range(shards)],
        }
    )
    return make_spec(key, tasks)
