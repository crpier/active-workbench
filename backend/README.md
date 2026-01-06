# Workbench Backend

FastAPI backend service for voice note capture.

## Features

- Receives voice notes from Android app
- Creates individual markdown files in vault's limbo/ directory
- Auto-commits and pushes to git

## Installation

```bash
cd ~/Projects/active-workbench/backend
uv venv
source .venv/bin/activate
uv pip install -e .
```

## Running Locally

```bash
uvicorn src.main:app --reload --host 0.0.0.0 --port 8765
```

## Testing

```bash
# Test health endpoint
curl http://localhost:8765/health

# Test capture endpoint
curl -X POST http://localhost:8765/api/capture \
  -H "Content-Type: application/json" \
  -d '{"text": "Test voice note about keyboard practice"}'
```

## Configuration

Create `~/.config/workbench/config.yaml`:

```yaml
vault_path: /home/crpier/vault
```

## VPS Deployment

See implementation plan for systemd service configuration.
