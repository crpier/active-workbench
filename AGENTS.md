# Active Workbench Agent Notes

## Project Overview
Active Workbench is a personal knowledge management system with a FastAPI backend and a Python CLI for capturing, organizing, and compiling notes into a vault-backed workflow. The architecture and workflow details live in `docs/implementation_plan.md` (including the latest architecture flow and Python endpoint examples).

## Architecture Snapshot (aligned with docs)
- **Backend**: FastAPI service that accepts voice capture requests and writes markdown files into `vault/limbo`, then syncs via git. Code lives in `backend/src`.
- **CLI**: Python `wb` CLI (Click-based) for daybook, projects, and writing workflows. Code lives in `cli/src/wb`.
- **Storage**: Markdown vault with `daybook/`, `projects/`, `writing/`, `limbo/`, and `templates/` directories; configuration via `~/.config/workbench/config.yaml`.
- **Frontend (Phase 2)**: Planned SolidJS + TanStack Start triage UI (documented in `docs/implementation_plan.md`).

## Key Paths
- Backend API routes: `backend/src/api/capture.py`
- Backend services: `backend/src/services/`
- Backend config: `backend/src/config.py`
- CLI entrypoint: `cli/src/wb/cli.py`
- CLI commands: `cli/src/wb/commands/`
- CLI config + vault utilities: `cli/src/wb/config.py`, `cli/src/wb/vault.py`

## Runtime + Tooling
- **Python**: 3.12+ (see `pyproject.toml` in `backend/` and `cli/`).
- **Package manager**: `uv` for venv and dependency management.

## Related Documentation
- Implementation plan (architecture flow + Python examples): `docs/implementation_plan.md`
- Backend usage: `backend/README.md`
- CLI usage: `cli/README.md`
