set shell := ["bash", "-lc"]

default:
  @just --list

setup:
  uv sync --all-groups

run:
  uv run uvicorn backend.app.main:app --reload --port 8000 --host 0.0.0.0

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

youtube-auth:
  ACTIVE_WORKBENCH_YOUTUBE_MODE=oauth uv run python -m backend.app.scripts.youtube_oauth_setup

youtube-auth-secret CLIENT_SECRET_PATH:
  ACTIVE_WORKBENCH_YOUTUBE_MODE=oauth uv run python -m backend.app.scripts.youtube_oauth_setup --client-secret "{{CLIENT_SECRET_PATH}}"

mobile-key-create DEVICE_NAME:
  uv run python -m backend.app.scripts.mobile_api_keys create --device-name "{{DEVICE_NAME}}"

mobile-key-list:
  uv run python -m backend.app.scripts.mobile_api_keys list

mobile-key-list-all:
  uv run python -m backend.app.scripts.mobile_api_keys list --all

mobile-key-revoke KEY_ID:
  uv run python -m backend.app.scripts.mobile_api_keys revoke --key-id "{{KEY_ID}}"
