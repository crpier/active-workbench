set shell := ["bash", "-lc"]

default:
  @just --list

setup:
  uv sync --all-groups

run:
  uv run uvicorn backend.app.main:app --reload

lint:
  uv run ruff check .

format:
  uv run ruff format .

typecheck:
  uv run pyright

test:
  uv run pytest --cov=backend --cov-report=term-missing

check: lint typecheck test

openapi:
  uv run python -m backend.app.scripts.export_openapi

gen-client: openapi
  cd tools-ts && npm install && npm run generate:client

ts-typecheck:
  cd tools-ts && npm run typecheck
