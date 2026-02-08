from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient

from backend.app.models.tool_contracts import WRITE_TOOLS, ToolName

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


def _request_body(
    tool: ToolName,
    *,
    payload: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
) -> dict[str, object]:
    return {
        "tool": tool,
        "request_id": str(uuid4()),
        "idempotency_key": idempotency_key or str(uuid4()),
        "payload": payload or {"example": True},
        "context": {"timezone": "Europe/Bucharest", "session_id": "test"},
    }


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_tool_catalog_exposes_expected_tools(client: TestClient) -> None:
    response = client.get("/tools")
    assert response.status_code == 200
    data = response.json()
    names = [item["name"] for item in data]
    assert set(names) == set(ALL_TOOLS)


def test_each_tool_endpoint_accepts_valid_envelope(client: TestClient) -> None:
    for tool in ALL_TOOLS:
        response = client.post(f"/tools/{tool}", json=_request_body(tool))
        assert response.status_code == 200, tool
        body = response.json()
        assert body["result"]["tool"] == tool
        if tool in WRITE_TOOLS:
            assert body["audit_event_id"].startswith("evt_")


def test_tool_endpoint_rejects_tool_mismatch(client: TestClient) -> None:
    response = client.post(
        "/tools/vault.recipe.save",
        json=_request_body("youtube.history.list_recent"),
    )
    assert response.status_code == 400
    assert "does not match endpoint" in response.json()["detail"]


def test_vault_recipe_save_persists_markdown(client: TestClient) -> None:
    response = client.post(
        "/tools/vault.recipe.save",
        json=_request_body(
            "vault.recipe.save",
            payload={
                "title": "Leek Soup",
                "body": "Use the leeks before they expire.",
                "source_refs": [{"type": "youtube_video", "id": "abc123"}],
            },
        ),
    )
    assert response.status_code == 200
    body = response.json()
    saved_path = Path(str(body["result"]["path"]))

    data_dir = Path(os.environ["ACTIVE_WORKBENCH_DATA_DIR"])
    file_path = data_dir / saved_path
    assert file_path.exists()

    content = file_path.read_text(encoding="utf-8")
    assert "# Leek Soup" in content
    assert "youtube_video" in content


def test_memory_create_and_undo(client: TestClient) -> None:
    create_response = client.post(
        "/tools/memory.create",
        json=_request_body("memory.create", payload={"fact": "User bought leeks"}),
    )
    assert create_response.status_code == 200
    create_body = create_response.json()
    undo_token = str(create_body["undo_token"])

    undo_response = client.post(
        "/tools/memory.undo",
        json=_request_body("memory.undo", payload={"undo_token": undo_token}),
    )
    assert undo_response.status_code == 200
    assert undo_response.json()["result"]["status"] == "undone"

    second_undo = client.post(
        "/tools/memory.undo",
        json=_request_body("memory.undo", payload={"undo_token": undo_token}),
    )
    assert second_undo.status_code == 200
    assert second_undo.json()["ok"] is False
    assert second_undo.json()["error"]["code"] == "not_found"


def test_reminder_schedule_feeds_context_suggestions(client: TestClient) -> None:
    schedule_response = client.post(
        "/tools/reminder.schedule",
        json=_request_body(
            "reminder.schedule",
            payload={
                "item": "leeks",
                "days_from_now": 2,
                "hour": 9,
                "minute": 0,
            },
        ),
    )
    assert schedule_response.status_code == 200
    assert schedule_response.json()["result"]["status"] == "scheduled"

    suggestion_response = client.post(
        "/tools/context.suggest_for_query",
        json=_request_body(
            "context.suggest_for_query",
            payload={"query": "Give me a recipe idea"},
        ),
    )
    assert suggestion_response.status_code == 200
    suggestions = suggestion_response.json()["result"]["suggestions"]
    assert any("leeks" in suggestion for suggestion in suggestions)


def test_write_idempotency_returns_same_response(client: TestClient) -> None:
    key = str(uuid4())
    first = client.post(
        "/tools/memory.create",
        json=_request_body(
            "memory.create",
            payload={"fact": "MVP is chat-only"},
            idempotency_key=key,
        ),
    )
    second = client.post(
        "/tools/memory.create",
        json=_request_body(
            "memory.create",
            payload={"fact": "MVP is chat-only"},
            idempotency_key=key,
        ),
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()
