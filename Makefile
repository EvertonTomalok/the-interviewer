.PHONY: install fmt lint types test cov itest docs-check check up down stack \
        migrate seed dev demo logs clean

install:
	uv sync --all-packages

fmt:
	uv run ruff format .
	uv run ruff check --fix .

lint:
	uv run ruff format --check .
	uv run ruff check .

types:
	uv run mypy

test:
	uv run pytest -q -m "not integration"

cov:
	uv run pytest --cov --cov-fail-under=80 -m "not integration"

itest:
	uv run pytest -m integration

docs-check:
	uv run python scripts/docs_check.py

check: lint types cov docs-check

up:
	docker compose up -d postgres redis

down:
	docker compose down

stack:
	docker compose --profile app up -d --build

migrate:
	@set -a; [ -f .env ] && . ./.env; set +a; uv run --package interviewer-adapters alembic upgrade head

seed:
	uv run python scripts/seed.py

dev:
	uv run python scripts/dev.py

demo:
	uv run python scripts/demo.py

logs:
	docker compose logs -f

clean:
	rm -rf .venv .mypy_cache .pytest_cache .ruff_cache var/blobs
	find . -type d -name __pycache__ -not -path './.git/*' -exec rm -rf {} +
