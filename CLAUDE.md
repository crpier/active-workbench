# Active Workbench - Context for Claude

## Project Overview
Active Workbench is a personal knowledge management system consisting of a backend API service and a CLI tool for capturing and organizing notes, daybook entries, and project information.

## Architecture

### Backend (`/backend`)
- **Framework**: FastAPI (Python)
- **Purpose**: REST API service for capturing notes and syncing with an Obsidian vault
- **Key Components**:
  - `src/api/capture.py` - API endpoints for capturing content
  - `src/services/vault_writer.py` - Writes content to Obsidian vault
  - `src/services/git_sync.py` - Handles git synchronization
  - `src/models/capture.py` - Data models
  - `src/config.py` - Configuration management
- **Deployment**: Can run as a systemd service (see `workbench.service`)

### CLI (`/cli`)
- **Framework**: Python CLI tool
- **Purpose**: Command-line interface for managing daybook, projects, and writing
- **Key Components**:
  - `src/wb/cli.py` - Main CLI entry point
  - `src/wb/commands/daybook.py` - Daybook management
  - `src/wb/commands/projects.py` - Project management
  - `src/wb/commands/writing.py` - Writing utilities
  - `src/wb/vault.py` - Vault operations
  - `src/wb/config.py` - CLI configuration

## Technology Stack
- **Python 3.14** (based on __pycache__ artifacts)
- **FastAPI** - Backend web framework
- **uv** - Python package manager (pyproject.toml + uv.lock)
- **Git** - Version control and vault sync

## Development Setup
1. Backend and CLI use `pyproject.toml` for dependency management
2. Use `uv` for installing dependencies
3. Backend has a test script: `backend/test_local.sh`
4. Backend can be deployed as a systemd service

## Important Notes
- The system integrates with an Obsidian vault for note storage
- Git synchronization is a core feature
- This is currently in Phase 1 (see `PHASE1_STATUS.md`)
- All files are currently staged but not committed (new repository)

## File Locations
- Backend deployment guide: `backend/DEPLOYMENT.md`
- Quick start guide: `QUICKSTART.md`
- CLI documentation: `cli/README.md`
