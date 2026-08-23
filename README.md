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
- **Automatic retries with exponential backoff** — a retriable failure moves
  the task to `RETRYING` with a persisted `next_attempt_at`; it stays there
  until that timestamp is genuinely due by the *database* clock. Each attempt
  is its own `task_attempt` row.
- **Permanent vs. retriable failures** — a `PermanentError` fails immediately
  without consuming retries; unexpected exceptions are retried conservatively
  while preserving the real exception type and traceback.
- **Failure isolation** — a failed task marks only its transitive descendants
  `UPSTREAM_FAILED` (never executed), distinct from `FAILED` (executed and
  errored). Unrelated branches run to completion, and the run settles only
  once no runnable work remains.
- **Worker-loss recovery** — an abandoned attempt's lease expires, the sweeper
  records it as `WorkerLost`, and the ordinary retry path runs a new attempt
  on a surviving worker. Verified by `SIGKILL`ing a container mid-task.
- **Broker-loss recovery** — PostgreSQL is the sole source of truth, so
  destroying Redis mid-run loses no work: the recovery sweep re-dispatches
  stale `QUEUED` tasks, releases overdue retries, and reconciles stalled runs.
- **Zombie-completion safety** — a resurrected worker cannot overwrite state
  that recovery has already advanced past.

## Current stack

- **Backend:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2.x, Alembic, structlog
- **Task transport:** Celery 5 over Redis 7 (no result backend)
- **Local infrastructure:** PostgreSQL 16 (Docker), Redis 7 (Docker)
- **Dependency management:** [uv](https://docs.astral.sh/uv/)
- **Containerization:** Docker Compose

## Reliability model

The guarantee, stated precisely:

> **At-least-once message delivery**, combined with **compare-and-set guarded
> state transitions**, giving **at-most-once committed outcome per attempt
> number**.

- Every state change is `UPDATE ... WHERE <expected status> AND <expected
  attempt>`, acting only on `rowcount == 1`. Under `READ COMMITTED` a blocked
  `UPDATE` re-evaluates its `WHERE` against the committed row, so of N racing
  processes exactly one wins. Duplicate broker deliveries are therefore
  ordinary and harmless, not exceptional.
- State is committed *before* the corresponding message is published, so a
  message never references uncommitted state. The window this opens — a
  process dying between commit and publish — is closed by detection (a
  30-second recovery sweep reading PostgreSQL) rather than by a transactional
  outbox, which would close only that one hole and still require the sweep
  for broker loss and worker loss.
- All durability-sensitive timestamps use PostgreSQL's clock, so recovery
  never depends on clocks agreeing across processes.

**We do not claim exactly-once handler execution.** If a worker becomes
unreachable *after* producing an external side effect but *before* committing
success, its attempt is reclaimed and a later attempt re-runs the handler. Its
stale completion is rejected, so engine state stays correct — but the side
effect already happened. **Handlers are therefore contractually required to be
idempotent.** Every demo handler is deterministic and side-effect-free, so the
contract holds trivially here.

## Not yet implemented

Stated explicitly so nothing above is mistaken for more than it is:

- exactly-once handler execution (see the reliability model above)
- scheduled (cron) execution — Celery Beat currently drives only the recovery
  sweep, not user-defined schedules
- run cancellation
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
- **Retry policy and execution.** `app/core/retry.py` computes exponential
  backoff with jitter (randomness injected, so it is deterministic in tests)
  and classifies errors as retriable or permanent.
  `app/orchestration/failure.py` applies that decision, and is shared by both
  the task runner and lease recovery so `WorkerLost` inherits the ordinary
  retry policy rather than needing a parallel mechanism.
- **Recovery sweep.** `app/orchestration/recovery.py` runs four bounded,
  CAS-guarded queries every 30 seconds (Celery Beat is a dumb heartbeat; all
  intelligence is in the SQL): re-dispatch stale `QUEUED` tasks, reclaim
  expired leases, release overdue retries, and reconcile stalled runs. A
  `dispatch_count` circuit breaker fails a task as `UndeliverableTask` rather
  than re-dispatching forever.
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

### Verifying reliability yourself

```bash
cd backend && uv run python scripts/reliability_report.py $RUN
```

Prints per-task status and attempt counts, then every attempt with its
worker, duration, error type, and the **real gap** between attempts computed
from persisted timestamps — so the backoff curve can be checked rather than
taken on trust. Also summarises `WorkerLost` attempts and sweeper
re-dispatches.

To watch worker-loss recovery live, `docker compose -f docker-compose.yml -f
docker-compose.recovery-test.yml up -d --scale worker=3` uses shortened
recovery thresholds (a test-only overlay — production defaults stay
conservative), then trigger `crash_recovery` and `docker kill` the container
whose id appears as the running task's `worker_id`.

### Two demo workflows

- **`sequential_etl`** — `extract → transform → validate → load`. Each stage
  regenerates its data deterministically from the previous stage's descriptor
  and independently verifies the upstream result, so output passing is
  load-bearing rather than decorative.
- **`fanout_join`** — `split → 4 shards → merge`. Shards run concurrently on
  different workers; `merge` waits for all four, then verifies the combined
  aggregate against a single-pass recomputation.
- **`retry_backoff`** — `prepare → flaky_fetch → persist`. `flaky_fetch` fails
  deterministically for its first `fail_until - 1` attempts. Raise
  `fail_until` above `max_attempts` to demonstrate retry exhaustion instead.
- **`failure_isolation`** — two branches from a shared seed. Branch A fails
  permanently; branch B completes anyway; tasks downstream of the failure are
  `UPSTREAM_FAILED` with zero attempts.
- **`crash_recovery`** — one long-running task, used to demonstrate
  worker-loss recovery by killing its container mid-execution.

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
