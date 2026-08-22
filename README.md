# Distributed Workflow Orchestration & Automation Engine

A DAG-based workflow orchestration platform: define multi-step workflows with
task dependencies, execute them across distributed workers, and track run
history and per-task state — all backed by persisted state, not mocked
dashboard statistics.

This project is under active, milestone-by-milestone development. This
README currently reflects **M0 (repository foundation)** only; it will grow
as the DAG engine, distributed workers, retries, and dashboard are built.

## Current stack

- **Backend:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2.x, structlog
- **Local infrastructure:** PostgreSQL 16 (Docker), Redis 7 (Docker)
- **Dependency management:** [uv](https://docs.astral.sh/uv/)
- **Containerization:** Docker Compose

Database migrations, the DAG engine, Celery workers, and the React dashboard
are not implemented yet — they arrive in later milestones.

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
