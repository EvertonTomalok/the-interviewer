# One image, two commands (api / worker) -- same code, same dependencies.
# `command:` in docker-compose.yml picks which process runs.
FROM python:3.12-slim AS base

RUN pip install --no-cache-dir uv

WORKDIR /app

COPY pyproject.toml uv.lock* ./
COPY packages/core/pyproject.toml packages/core/pyproject.toml
COPY packages/adapters/pyproject.toml packages/adapters/pyproject.toml
COPY apps/api/pyproject.toml apps/api/pyproject.toml
COPY apps/worker/pyproject.toml apps/worker/pyproject.toml

COPY . .

RUN uv sync --all-packages --no-dev --frozen || uv sync --all-packages --no-dev

ENV PATH="/app/.venv/bin:${PATH}"

EXPOSE 8000

CMD ["uvicorn", "interviewer_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
