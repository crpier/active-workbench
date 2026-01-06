#!/bin/bash
# Test script for local backend

echo "Starting backend..."
cd ~/Projects/active-workbench/backend
.venv/bin/uvicorn src.main:app --host 0.0.0.0 --port 8765 &
BACKEND_PID=$!

sleep 2

echo -e "\n=== Testing health endpoint ==="
curl http://localhost:8765/api/health
echo

echo -e "\n=== Testing capture endpoint ==="
curl -X POST http://localhost:8765/api/capture \
  -H "Content-Type: application/json" \
  -d '{"text": "Test keyboard practice note - proper finger positioning"}'
echo

echo -e "\n=== Checking limbo directory ==="
ls -lt ~/vault/limbo/*.md | head -3

echo -e "\n=== Stopping backend ==="
kill $BACKEND_PID

echo "Done!"
