# Distributed Workflow Orchestration & Automation Engine

A DAG-based workflow orchestration platform: define multi-step workflows with
task dependencies, execute them across distributed workers, and track run
history and per-task state — all backed by persisted state, not mocked
dashboard statistics.

This project is under active, milestone-by-milestone development. This
README currently reflects **M0 (repository foundation)** and **M1+M2
(database schema and pure orchestration domain)**; it will grow as
distributed execution, retries, and the dashboard are built.

## Current stack

- **Backend:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2.x, Alembic, structlog
- **Local infrastructure:** PostgreSQL 16 (Docker), Redis 7 (Docker)
- **Dependency management:** [uv](https://docs.astral.sh/uv/)
- **Containerization:** Docker Compose

Distributed task execution (Celery workers), automatic retries actually
running, scheduling, the REST API beyond `/health`, and the React dashboard
are not implemented yet — they arrive in later milestones. What exists today
is the durable data model those milestones will write to, and the pure
validation/state-machine logic they'll call.

## Architecture foundation

- **PostgreSQL persistence model.** Six tables — `workflow_definition`,
  `workflow_run`, `task_run`, `task_attempt`, `schedule`, `schedule_fire` —
  managed by Alembic migrations. This is where run history, task state, and
  retry attempts will live once execution exists; nothing here is populated
  by placeholder data.
- **Declarative JSON DAG specification.** A workflow is a Pydantic-validated
  document (`app/core/spec.py`): a list of tasks with dependencies, a
  string `handler` lookup key (never executable code), and an optional
  per-task retry policy that falls back to workflow-level defaults.
- **Framework-independent DAG validator.** `app/core/dag.py` validates task
  graphs — duplicate/unknown/self dependencies, at-least-one source task,
  and cycle detection via Kahn's algorithm, which also extracts the actual
  cycle path (e.g. `extract → transform → validate → extract`) rather than
  reporting only "cycle detected." It also provides the dependency-readiness
  and failure-propagation utilities the future scheduler will call. This
  module has zero dependency on FastAPI, SQLAlchemy, or Celery — enforced by
  an automated import-boundary test, not just a convention.
- **Explicit state machines.** Workflow and task status are modeled as
  enums with an explicit legal-transition table (`app/core/states.py`);
  illegal transitions raise rather than silently succeed.
- **Retry policy (not yet retry execution).** `app/core/retry.py` computes
  exponential backoff with jitter and classifies errors as retriable or
  permanent. This is the policy the future task runner will apply — no
  task actually executes or retries yet.

## Local prerequisites

- Docker Desktop (or a compatible Docker Engine + Compose v2)

No local Python or `uv` installation is required to run the project —
everything runs inside Docker.

## Running locally (M0)

```bash
cp .env.example .env
make dev
```

This builds and starts three containers: PostgreSQL, Redis, and the FastAPI
API. On Apple Silicon and other arm64 hosts, all images run natively — no
emulation.

## Verifying it's working

```bash
make health
# or
curl -i http://localhost:8000/health
```

Expect `HTTP/1.1 200 OK` with a body like:

```json
{"status": "ok", "version": "0.1.0"}
```

Other useful commands:

```bash
make logs   # follow API logs
make down   # stop and remove containers
```

## Development

Running the stack (`make dev`) needs only Docker. Running migrations or the
test suite from the host additionally needs [uv](https://docs.astral.sh/uv/)
installed locally (`uv sync` inside `backend/` once).

```bash
make dev       # start postgres + redis + api first, in another shell:
make migrate   # alembic upgrade head, against the Postgres port Compose publishes
make test      # full pytest suite (unit + PostgreSQL integration tests)
make lint      # ruff check
```

The integration suite runs against a real PostgreSQL database (not SQLite —
the schema relies on JSONB, native arrays, and native enum types), using the
same Postgres container `make dev` starts.
