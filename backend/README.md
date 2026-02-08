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
k3s_kubeconfig: /etc/rancher/k3s/k3s.yaml
```

## VPS Deployment

See implementation plan for systemd service configuration.

## K3s Operations

The backend exposes a small set of K3s helper endpoints that shell out to `kubectl`
using the configured kubeconfig.

```bash
# List nodes
curl http://localhost:8765/api/k3s/nodes

# List namespaces
curl http://localhost:8765/api/k3s/namespaces

# List pods in a namespace
curl http://localhost:8765/api/k3s/pods/default

# Apply a manifest
curl -X POST http://localhost:8765/api/k3s/apply \
  -H "Content-Type: application/json" \
  -d '{"manifest": "apiVersion: v1\nkind: Namespace\nmetadata:\n  name: demo"}'

# Delete a resource
curl -X DELETE http://localhost:8765/api/k3s/resource \
  -H "Content-Type: application/json" \
  -d '{"kind": "namespace", "name": "demo"}'
```
