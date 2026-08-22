.PHONY: dev down logs health

dev:
	docker compose up --build

down:
	docker compose down

logs:
	docker compose logs -f api

health:
	curl -i http://localhost:8000/health
