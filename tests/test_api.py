from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.models.tool_contracts import ToolName

client = TestClient(app)


ALL_TOOLS: tuple[ToolName, ...] = (
    "youtube.history.list_recent",
    "youtube.transcript.get",
    "vault.recipe.save",
    "vault.note.save",
    "vault.bucket_list.add",
    "memory.create",
    "memory.undo",
    "reminder.schedule",
    "context.suggest_for_query",
    "digest.weekly_learning.generate",
    "review.routine.generate",
    "recipe.extract_from_transcript",
    "summary.extract_key_ideas",
    "actions.extract_from_notes",
)


def _request_body(tool: ToolName) -> dict[str, object]:
    return {
        "tool": tool,
        "request_id": str(uuid4()),
        "idempotency_key": str(uuid4()),
        "payload": {"example": True},
        "context": {"timezone": "Europe/Bucharest", "session_id": "test"},
    }


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_tool_catalog_exposes_expected_tools() -> None:
    response = client.get("/tools")
    assert response.status_code == 200
    data = response.json()
    names = [item["name"] for item in data]
    assert set(names) == set(ALL_TOOLS)


def test_each_tool_endpoint_accepts_valid_envelope() -> None:
    for tool in ALL_TOOLS:
        response = client.post(f"/tools/{tool}", json=_request_body(tool))
        assert response.status_code == 200, tool
        body = response.json()
        assert body["ok"] is True
        assert body["result"]["tool"] == tool
        assert body["audit_event_id"].startswith("evt_")


def test_tool_endpoint_rejects_tool_mismatch() -> None:
    response = client.post(
        "/tools/vault.recipe.save",
        json=_request_body("youtube.history.list_recent"),
    )
    assert response.status_code == 400
    assert "does not match endpoint" in response.json()["detail"]
