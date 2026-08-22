.PHONY: dev down logs health migrate test lint

# Local host tooling (migrate/test/lint) talks to Postgres via the port
# published in docker-compose.yml, not the in-network "postgres" hostname
# the api/worker containers use.
LOCAL_DATABASE_URL := postgresql+psycopg://workflow:workflow@localhost:5432/workflow_engine

# Three workers by default so fan-out genuinely lands on distinct
# containers rather than only looking distributed.
dev:
	docker compose up --build --scale worker=3

down:
	docker compose down

logs:
	docker compose logs -f api

health:
	curl -i http://localhost:8000/health

migrate:
	cd backend && DATABASE_URL=$(LOCAL_DATABASE_URL) uv run alembic upgrade head

test:
	cd backend && DATABASE_URL=$(LOCAL_DATABASE_URL) uv run pytest

lint:
	cd backend && uv run ruff check .
