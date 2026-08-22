# Distributed Workflow Orchestration & Automation Engine

A DAG-based workflow orchestration platform: define multi-step workflows with
task dependencies, execute them across distributed workers, and track run
history and per-task state — all backed by persisted state, not mocked
dashboard statistics.

This project is under active, milestone-by-milestone development. This
README reflects what is **actually implemented and verified today**; see
"Not yet implemented" for what is deliberately absent.

## What works today

- **DAG-based workflow execution** — workflows are declarative JSON documents
  validated as real DAGs (cycle detection, dependency resolution) before they
  are persisted.
- **PostgreSQL-persisted workflow state** — every run, task, and execution
  attempt is durable. Restarting the API loses nothing.
- **Dependency resolution** — a task becomes runnable only when all of its
  dependencies have succeeded, decided by our own planner and reconciler.
- **Distributed Celery workers** — task execution happens on worker processes,
  never in the API. Redis is transport only; it holds no workflow state and no
  result backend is configured.
- **Multi-worker Docker execution** — `docker compose up -d --scale worker=3`
  runs three independent worker containers.
- **Fan-out and fan-in** — one upstream success can expose several tasks at
  once; a join task waits until every one of its dependencies has succeeded.
- **Real parallel execution** — verified mechanically, not by inspection:
  `scripts/parallelism_report.py` computes distinct worker counts and
  interval overlap from persisted `task_attempt` rows.
- **Per-task worker identity** — each attempt records the real
  `hostname:pid` of the process that executed it.
- **Run and task history through the API** — run status, task states,
  attempts, outputs, timestamps, and durations.

## Current stack

- **Backend:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2.x, Alembic, structlog
- **Task transport:** Celery 5 over Redis 7 (no result backend)
- **Local infrastructure:** PostgreSQL 16 (Docker), Redis 7 (Docker)
- **Dependency management:** [uv](https://docs.astral.sh/uv/)
- **Containerization:** Docker Compose

## Not yet implemented

Stated explicitly so nothing above is mistaken for more than it is:

- automatic retries and exponential backoff (retry *policy* is implemented
  and unit-tested; nothing retries at runtime yet — a failed task fails)
- failure isolation / `UPSTREAM_FAILED` propagation
- worker crash recovery and broker-loss recovery
- scheduled (cron) execution
- React dashboard
- public deployment

## Architecture foundation

- **PostgreSQL persistence model.** Six tables — `workflow_definition`,
  `workflow_run`, `task_run`, `task_attempt`, `schedule`, `schedule_fire` —
  managed by Alembic migrations. This is where run history, task state, and
  execution attempts live. Every value shown by the API is written by an
  actual execution; nothing is placeholder data.
- **Declarative JSON DAG specification.** A workflow is a Pydantic-validated
  document (`app/core/spec.py`): a list of tasks with dependencies, a
  string `handler` lookup key (never executable code), and an optional
  per-task retry policy that falls back to workflow-level defaults.
- **Framework-independent DAG validator.** `app/core/dag.py` validates task
  graphs — duplicate/unknown/self dependencies, at-least-one source task,
  and cycle detection via Kahn's algorithm, which also extracts the actual
  cycle path (e.g. `extract → transform → validate → extract`) rather than
  reporting only "cycle detected." It also provides the dependency-readiness
  and failure-propagation utilities the planner uses. This
  module has zero dependency on FastAPI, SQLAlchemy, or Celery — enforced by
  an automated import-boundary test, not just a convention.
- **Explicit state machines.** Workflow and task status are modeled as
  enums with an explicit legal-transition table (`app/core/states.py`);
  illegal transitions raise rather than silently succeed.
- **Retry policy (not yet retry execution).** `app/core/retry.py` computes
  exponential backoff with jitter and classifies errors as retriable or
  permanent. This is the policy the task runner will apply once retry
  execution lands; today a failed task fails without retrying.
- **Orchestration layer.** A pure `planner` decides what should happen next
  from a snapshot of task states; a `reconciler` applies those decisions
  under a `SELECT ... FOR UPDATE` row lock, using guarded compare-and-set
  updates so concurrent reconciles cannot double-dispatch a task; a `runner`
  executes one attempt in three phases (claim / execute / complete) and
  never holds a transaction open across handler computation.
- **Celery is transport, not the engine.** No chains, groups, or chords —
  the DAG lives in PostgreSQL and our reconciler advances it. A `Dispatcher`
  abstraction keeps `.apply_async()` out of orchestration code, which is why
  the whole engine can be tested without a broker running.

## Local prerequisites

- Docker Desktop (or a compatible Docker Engine + Compose v2)

No local Python or `uv` installation is required to run the project —
everything runs inside Docker.

## Running locally

```bash
cp .env.example .env
make dev            # or: docker compose up --build -d --scale worker=3
```

Startup is staged so nothing races schema creation:
`postgres healthy → migrate → seed → api + workers`. Both migrate and seed
are idempotent. On Apple Silicon and other arm64 hosts every image runs
natively — no emulation.

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

### Running a workflow

```bash
curl -s http://localhost:8000/api/v1/workflows

RUN=$(curl -s -X POST http://localhost:8000/api/v1/workflows/fanout_join/runs \
  -H 'Content-Type: application/json' -d '{"params":{}}' | jq -r .id)

curl -s http://localhost:8000/api/v1/runs/$RUN | jq
```

The trigger returns `202 Accepted` immediately with every task still
`pending` — the API commits state and publishes one message; it never runs
handler code.

### Verifying parallelism yourself

```bash
cd backend && uv run python scripts/parallelism_report.py $RUN
```

Prints a `task_key | worker_id | started_at | finished_at | duration_ms`
table straight from `task_attempt`, then computes how many distinct workers
ran shards and how many shard intervals overlap. Exits non-zero if the run
does not actually demonstrate parallelism.

### Two demo workflows

- **`sequential_etl`** — `extract → transform → validate → load`. Each stage
  regenerates its data deterministically from the previous stage's descriptor
  and independently verifies the upstream result, so output passing is
  load-bearing rather than decorative.
- **`fanout_join`** — `split → 4 shards → merge`. Shards run concurrently on
  different workers; `merge` waits for all four, then verifies the combined
  aggregate against a single-pass recomputation.

Handlers do real CPU work (SHA-256 digests and aggregation), not `sleep()`.
Intermediate outputs are compact descriptors — a seed plus a range plus
checksums — so JSONB payloads stay small while remaining verifiable.

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
