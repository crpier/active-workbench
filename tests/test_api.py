from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient

from backend.app.models.tool_contracts import WRITE_TOOLS, ToolName

ALL_TOOLS: tuple[ToolName, ...] = (
    "youtube.likes.list_recent",
    "youtube.transcript.get",
    "vault.recipe.save",
    "vault.note.save",
    "vault.bucket_list.add",
    "vault.bucket_list.prioritize",
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


def _runtime_data_dir() -> Path:
    return Path(os.environ["ACTIVE_WORKBENCH_DATA_DIR"])


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
        json=_request_body("youtube.likes.list_recent"),
    )
    assert response.status_code == 400
    assert "does not match endpoint" in response.json()["detail"]


def test_recipe_workflow_end_to_end(client: TestClient) -> None:
    history = client.post(
        "/tools/youtube.likes.list_recent",
        json=_request_body("youtube.likes.list_recent", payload={"query": "cook", "limit": 3}),
    )
    assert history.status_code == 200
    videos = history.json()["result"]["videos"]
    assert videos
    video_id = str(videos[0]["video_id"])

    transcript = client.post(
        "/tools/youtube.transcript.get",
        json=_request_body("youtube.transcript.get", payload={"video_id": video_id}),
    )
    assert transcript.status_code == 200
    transcript_text = str(transcript.json()["result"]["transcript"])

    recipe = client.post(
        "/tools/recipe.extract_from_transcript",
        json=_request_body(
            "recipe.extract_from_transcript",
            payload={"video_id": video_id, "transcript": transcript_text, "title": "Leek Soup"},
        ),
    )
    assert recipe.status_code == 200
    recipe_markdown = str(recipe.json()["result"]["markdown"])

    save = client.post(
        "/tools/vault.recipe.save",
        json=_request_body(
            "vault.recipe.save",
            payload={
                "title": "Leek Soup",
                "markdown": recipe_markdown,
                "source_refs": [{"type": "youtube_video", "id": video_id}],
            },
        ),
    )
    assert save.status_code == 200
    saved_path = _runtime_data_dir() / str(save.json()["result"]["path"])
    assert saved_path.exists()

    memory = client.post(
        "/tools/memory.create",
        json=_request_body(
            "memory.create",
            payload={
                "type": "recipe_capture",
                "recipe_title": "Leek Soup",
                "source_refs": [{"type": "youtube_video", "id": video_id}],
            },
        ),
    )
    assert memory.status_code == 200
    assert memory.json()["undo_token"]


def test_summary_workflow_end_to_end(client: TestClient) -> None:
    history = client.post(
        "/tools/youtube.likes.list_recent",
        json=_request_body(
            "youtube.likes.list_recent",
            payload={"query": "microservices", "limit": 3},
        ),
    )
    assert history.status_code == 200
    videos = history.json()["result"]["videos"]
    assert videos
    video_id = str(videos[0]["video_id"])

    transcript = client.post(
        "/tools/youtube.transcript.get",
        json=_request_body("youtube.transcript.get", payload={"video_id": video_id}),
    )
    transcript_text = str(transcript.json()["result"]["transcript"])

    summary = client.post(
        "/tools/summary.extract_key_ideas",
        json=_request_body(
            "summary.extract_key_ideas",
            payload={"video_id": video_id, "transcript": transcript_text, "max_points": 4},
        ),
    )
    assert summary.status_code == 200
    key_ideas = summary.json()["result"]["key_ideas"]
    assert key_ideas

    body = "\n".join(f"- {item}" for item in key_ideas)
    save = client.post(
        "/tools/vault.note.save",
        json=_request_body(
            "vault.note.save",
            payload={
                "title": "Microservices Interesting Ideas",
                "body": body,
                "source_refs": [{"type": "youtube_video", "id": video_id}],
            },
        ),
    )
    assert save.status_code == 200
    path = _runtime_data_dir() / str(save.json()["result"]["path"])
    assert path.exists()


def test_transcript_accepts_youtube_url_payload(client: TestClient) -> None:
    response = client.post(
        "/tools/youtube.transcript.get",
        json=_request_body(
            "youtube.transcript.get",
            payload={"url": "https://www.youtube.com/watch?v=fixture_micro_001"},
        ),
    )
    assert response.status_code == 200
    assert response.json()["result"]["video_id"] == "fixture_micro_001"


def test_transcript_rejects_invalid_video_identifier(client: TestClient) -> None:
    response = client.post(
        "/tools/youtube.transcript.get",
        json=_request_body(
            "youtube.transcript.get",
            payload={"url": "https://example.com/not-a-youtube-url"},
        ),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "invalid_input"


def test_bucket_list_and_prioritization(client: TestClient) -> None:
    add_first = client.post(
        "/tools/vault.bucket_list.add",
        json=_request_body(
            "vault.bucket_list.add",
            payload={"title": "Watch Andor", "body": "effort: low\ncost: medium"},
        ),
    )
    add_second = client.post(
        "/tools/vault.bucket_list.add",
        json=_request_body(
            "vault.bucket_list.add",
            payload={"title": "Watch Severance", "body": "effort: low\ncost: high"},
        ),
    )
    assert add_first.status_code == 200
    assert add_second.status_code == 200

    prioritized = client.post(
        "/tools/vault.bucket_list.prioritize",
        json=_request_body("vault.bucket_list.prioritize", payload={}),
    )
    assert prioritized.status_code == 200
    items = prioritized.json()["result"]["items"]
    assert len(items) >= 2


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


def test_reminder_and_recipe_context_suggestion(client: TestClient) -> None:
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


def test_actions_digest_and_routine_review(client: TestClient) -> None:
    note_save = client.post(
        "/tools/vault.note.save",
        json=_request_body(
            "vault.note.save",
            payload={
                "title": "Microservices actions",
                "body": "TODO: Define service boundaries\nWe should add distributed tracing",
            },
        ),
    )
    assert note_save.status_code == 200

    actions = client.post(
        "/tools/actions.extract_from_notes",
        json=_request_body("actions.extract_from_notes", payload={}),
    )
    assert actions.status_code == 200
    extracted_actions = actions.json()["result"]["actions"]
    assert extracted_actions

    digest = client.post(
        "/tools/digest.weekly_learning.generate",
        json=_request_body("digest.weekly_learning.generate", payload={}),
    )
    assert digest.status_code == 200
    digest_path = _runtime_data_dir() / str(digest.json()["result"]["path"])
    assert digest_path.exists()

    review = client.post(
        "/tools/review.routine.generate",
        json=_request_body("review.routine.generate", payload={}),
    )
    assert review.status_code == 200
    review_path = _runtime_data_dir() / str(review.json()["result"]["path"])
    assert review_path.exists()


def test_due_reminder_jobs_execute_on_next_tool_call(client: TestClient) -> None:
    past_run = "2025-01-01T08:00:00+00:00"
    schedule_response = client.post(
        "/tools/reminder.schedule",
        json=_request_body(
            "reminder.schedule",
            payload={"item": "old leeks", "run_at": past_run},
        ),
    )
    assert schedule_response.status_code == 200

    trigger_response = client.post(
        "/tools/context.suggest_for_query",
        json=_request_body(
            "context.suggest_for_query",
            payload={"query": "anything"},
        ),
    )
    assert trigger_response.status_code == 200

    reviews_dir = _runtime_data_dir() / "vault" / "reviews"
    review_files = list(reviews_dir.glob("*.md"))
    assert review_files


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
