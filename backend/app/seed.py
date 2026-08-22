"""Load workflow definitions from backend/workflows/*.json into PostgreSQL.

Idempotent: keyed on the stable `key` field, so running it repeatedly never
produces duplicates. A definition whose spec has changed is updated in place
and its version bumped; an unchanged definition is left alone.

Validation happens before persistence, against both the Pydantic shape
(WorkflowSpec) and the DAG semantics (validate_dag, including that every
handler name actually exists in the registry). An invalid definition aborts the
seed loudly rather than landing a broken workflow in the database.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from sqlalchemy import select

from app.core.dag import validate_dag
from app.core.spec import WorkflowSpec
from app.db.models import WorkflowDefinition
from app.db.session import SessionLocal
from app.handlers import handler_names
from app.logging import configure_logging, get_logger

WORKFLOWS_DIR = Path(__file__).resolve().parents[1] / "workflows"

logger = get_logger(__name__)


class InvalidWorkflowDefinition(Exception):
    """A workflow JSON file failed shape or DAG validation."""


def load_spec(path: Path) -> WorkflowSpec:
    """Parse and fully validate one workflow definition file."""
    raw = json.loads(path.read_text())
    spec = WorkflowSpec.model_validate(raw)

    errors = validate_dag(spec, known_handlers=handler_names())
    if errors:
        detail = "; ".join(f"[{e.code}] {e.message}" for e in errors)
        raise InvalidWorkflowDefinition(f"{path.name}: {detail}")

    if spec.key != path.stem:
        raise InvalidWorkflowDefinition(
            f"{path.name}: spec key '{spec.key}' does not match filename stem '{path.stem}'"
        )

    return spec


def seed(session_factory=SessionLocal, workflows_dir: Path = WORKFLOWS_DIR) -> dict[str, str]:
    """Upsert every workflow definition. Returns {key: created|updated|unchanged}."""
    paths = sorted(workflows_dir.glob("*.json"))
    if not paths:
        logger.warning("seed_no_workflows_found", directory=str(workflows_dir))
        return {}

    # Validate everything before writing anything, so one bad file cannot
    # leave the database half-seeded.
    specs = [load_spec(path) for path in paths]

    results: dict[str, str] = {}
    with session_factory() as session:
        for spec in specs:
            payload = spec.model_dump(mode="json")
            existing = session.execute(
                select(WorkflowDefinition).where(WorkflowDefinition.key == spec.key)
            ).scalar_one_or_none()

            if existing is None:
                session.add(
                    WorkflowDefinition(
                        key=spec.key,
                        version=1,
                        name=spec.name,
                        description=spec.description,
                        spec=payload,
                        is_active=True,
                    )
                )
                results[spec.key] = "created"
            elif existing.spec != payload:
                existing.version += 1
                existing.name = spec.name
                existing.description = spec.description
                existing.spec = payload
                results[spec.key] = "updated"
            else:
                results[spec.key] = "unchanged"

        session.commit()

    for key, action in sorted(results.items()):
        logger.info("workflow_seeded", workflow_key=key, action=action)

    return results


def main() -> int:
    from app.config import get_settings

    configure_logging(get_settings())
    try:
        seed()
    except Exception as exc:
        # Non-zero exit matters: Compose treats the seed service as a gate,
        # so a bad definition must stop the stack rather than let workers
        # start against a half-seeded database.
        logger.error("seed_failed", error_type=type(exc).__name__, error=str(exc))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
