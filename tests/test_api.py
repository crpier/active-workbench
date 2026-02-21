from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient

from backend.app.models.tool_contracts import WRITE_TOOLS, ToolName

ALL_TOOLS: tuple[ToolName, ...] = (
    "youtube.likes.list_recent",
    "youtube.likes.search_recent_content",
    "youtube.transcript.get",
    "vault.recipe.save",
    "vault.note.save",
    "bucket.item.add",
    "bucket.item.update",
    "bucket.item.complete",
    "bucket.item.search",
    "bucket.item.recommend",
    "bucket.health.report",
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
    assert response.headers.get("X-Request-ID")


def test_tool_catalog_exposes_expected_tools(client: TestClient) -> None:
    response = client.get("/tools")
    assert response.status_code == 200
    data = response.json()
    names = [item["name"] for item in data]
    assert set(names) == set(ALL_TOOLS)


def test_tool_catalog_marks_only_youtube_tools_ready(client: TestClient) -> None:
    response = client.get("/tools")
    assert response.status_code == 200
    data = response.json()

    ready_tools = {item["name"] for item in data if item["ready_for_use"] is True}
    not_ready_tools = {item["name"] for item in data if item["ready_for_use"] is False}

    assert ready_tools == {
        "youtube.likes.list_recent",
        "youtube.likes.search_recent_content",
        "youtube.transcript.get",
        "bucket.item.add",
        "bucket.item.update",
        "bucket.item.complete",
        "bucket.item.search",
        "bucket.item.recommend",
        "bucket.health.report",
    }
    assert not_ready_tools == set(ALL_TOOLS) - ready_tools

    for item in data:
        if item["name"] in ready_tools:
            assert item["readiness_note"] is None
        else:
            assert isinstance(item["readiness_note"], str) and item["readiness_note"]


def test_each_tool_endpoint_accepts_valid_envelope(client: TestClient) -> None:
    for tool in ALL_TOOLS:
        payload = {"query": "soup"} if tool == "youtube.likes.search_recent_content" else None
        response = client.post(f"/tools/{tool}", json=_request_body(tool, payload=payload))
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
    history_result = history.json()["result"]
    assert "quota" in history_result
    videos = history_result["videos"]
    assert videos
    assert videos[0]["liked_at"]
    assert "description" in videos[0]
    assert "channel_title" in videos[0]
    assert "tags" in videos[0]
    video_id = str(videos[0]["video_id"])

    transcript = client.post(
        "/tools/youtube.transcript.get",
        json=_request_body("youtube.transcript.get", payload={"video_id": video_id}),
    )
    assert transcript.status_code == 200
    transcript_result = transcript.json()["result"]
    assert "quota" in transcript_result
    transcript_text = str(transcript_result["transcript"])

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
            payload={"url": "https://www.youtube.com/watch?v=test_micro_001"},
        ),
    )
    assert response.status_code == 200
    assert response.json()["result"]["video_id"] == "test_micro_001"


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


def test_youtube_likes_cache_miss_policy_from_time_scope(client: TestClient) -> None:
    response = client.post(
        "/tools/youtube.likes.list_recent",
        json=_request_body(
            "youtube.likes.list_recent",
            payload={"query": "a while ago I saw a quantum cryptography lecture", "limit": 5},
        ),
    )
    assert response.status_code == 200
    cache = response.json()["result"]["cache"]
    assert cache["miss"] is True
    assert cache["time_scope"] == "historical"
    assert cache["miss_policy"] == "none"
    assert cache["recent_probe"]["pages_requested"] == 0


def test_youtube_likes_cache_miss_policy_explicit_probe(client: TestClient) -> None:
    response = client.post(
        "/tools/youtube.likes.list_recent",
        json=_request_body(
                "youtube.likes.list_recent",
                payload={
                    "query": "soup",
                    "time_scope": "recent",
                    "cache_miss_policy": "probe_recent",
                    "recent_probe_pages": 2,
                },
        ),
    )
    assert response.status_code == 200
    cache = response.json()["result"]["cache"]
    assert cache["time_scope"] == "recent"
    assert cache["miss_policy"] == "probe_recent"
    assert cache["recent_probe"]["pages_requested"] == 2


def test_youtube_likes_exposes_pagination_and_limit_metadata(client: TestClient) -> None:
    response = client.post(
        "/tools/youtube.likes.list_recent",
        json=_request_body(
            "youtube.likes.list_recent",
            payload={"limit": 1, "cursor": 1},
        ),
    )
    assert response.status_code == 200
    body = response.json()["result"]
    assert body["requested_limit"] == 1
    assert body["applied_limit"] == 1
    assert body["requested_cursor"] == 1
    assert body["cursor"] == 1
    assert body["next_cursor"] == 2
    assert body["has_more"] is True
    assert body["truncated"] is True
    assert body["total_matches"] == 3
    assert body["videos"][0]["video_id"] == "test_micro_001"

    clamped = client.post(
        "/tools/youtube.likes.list_recent",
        json=_request_body(
            "youtube.likes.list_recent",
            payload={"limit": 200},
        ),
    )
    assert clamped.status_code == 200
    clamped_body = clamped.json()["result"]
    assert clamped_body["requested_limit"] == 200
    assert clamped_body["applied_limit"] == 100
    assert clamped_body["has_more"] is False
    assert clamped_body["truncated"] is False
    assert clamped_body["total_matches"] == 3
    assert len(clamped_body["videos"]) == 3


def test_youtube_likes_compact_payload_mode(client: TestClient) -> None:
    response = client.post(
        "/tools/youtube.likes.list_recent",
        json=_request_body(
            "youtube.likes.list_recent",
            payload={"limit": 2, "compact": True},
        ),
    )
    assert response.status_code == 200
    body = response.json()["result"]
    assert body["compact"] is True
    first = body["videos"][0]
    assert "description" not in first
    assert "channel_title" in first
    assert "video_id" in first


def test_youtube_likes_search_recent_content_returns_matches(client: TestClient) -> None:
    response = client.post(
        "/tools/youtube.likes.search_recent_content",
        json=_request_body(
            "youtube.likes.search_recent_content",
            payload={"query": "soup", "window_days": 30, "limit": 5},
        ),
    )
    assert response.status_code == 200
    body = response.json()["result"]
    assert body["matches"]
    assert body["coverage"]["recent_videos_count"] >= 1
    assert "matched_in" in body["matches"][0]


def test_structured_bucket_recommend_completion_and_health(client: TestClient) -> None:
    add_john_wick = client.post(
        "/tools/bucket.item.add",
        json=_request_body(
            "bucket.item.add",
            payload={
                "title": "John Wick: Chapter 2",
                "domain": "movie",
                "duration_minutes": 122,
                "genres": ["Action", "Crime", "Thriller"],
                "rating": 7.4,
                "auto_enrich": False,
            },
        ),
    )
    add_short_action = client.post(
        "/tools/bucket.item.add",
        json=_request_body(
            "bucket.item.add",
            payload={
                "title": "Fast Action Short",
                "domain": "movie",
                "duration_minutes": 88,
                "genres": ["Action"],
                "rating": 6.8,
                "auto_enrich": False,
            },
        ),
    )
    add_drama = client.post(
        "/tools/bucket.item.add",
        json=_request_body(
            "bucket.item.add",
            payload={
                "title": "Slow Drama",
                "domain": "movie",
                "duration_minutes": 140,
                "genres": ["Drama"],
                "rating": 8.3,
                "auto_enrich": False,
            },
        ),
    )
    assert add_john_wick.status_code == 200
    assert add_short_action.status_code == 200
    assert add_drama.status_code == 200

    recommend = client.post(
        "/tools/bucket.item.recommend",
        json=_request_body(
            "bucket.item.recommend",
            payload={
                "domain": "movie",
                "genre": "action",
                "target_duration_minutes": 90,
                "limit": 2,
            },
        ),
    )
    assert recommend.status_code == 200
    recommendations = recommend.json()["result"]["recommendations"]
    assert recommendations
    first_title = recommendations[0]["bucket_item"]["title"]
    assert first_title in {"Fast Action Short", "John Wick: Chapter 2"}

    fast_item_id = add_short_action.json()["result"]["bucket_item"]["item_id"]
    complete_fast = client.post(
        "/tools/bucket.item.complete",
        json=_request_body(
            "bucket.item.complete",
            payload={"item_id": fast_item_id},
        ),
    )
    assert complete_fast.status_code == 200
    assert complete_fast.json()["result"]["bucket_item"]["status"] == "completed"

    active_search = client.post(
        "/tools/bucket.item.search",
        json=_request_body(
            "bucket.item.search",
            payload={"domain": "movie", "query": "Fast Action Short"},
        ),
    )
    assert active_search.status_code == 200
    assert active_search.json()["result"]["count"] == 0

    include_completed_search = client.post(
        "/tools/bucket.item.search",
        json=_request_body(
            "bucket.item.search",
            payload={
                "domain": "movie",
                "query": "Fast Action Short",
                "include_completed": True,
            },
        ),
    )
    assert include_completed_search.status_code == 200
    assert include_completed_search.json()["result"]["count"] == 1

    health = client.post(
        "/tools/bucket.health.report",
        json=_request_body("bucket.health.report", payload={"stale_after_days": 0, "limit": 5}),
    )
    assert health.status_code == 200
    report = health.json()["result"]["report"]
    assert report["totals"]["active"] >= 2
    assert report["totals"]["completed"] >= 1
    assert isinstance(report["quick_wins"], list)


def test_structured_bucket_add_requires_domain(client: TestClient) -> None:
    response = client.post(
        "/tools/bucket.item.add",
        json=_request_body(
            "bucket.item.add",
            payload={"title": "Watch Andor", "auto_enrich": False},
        ),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "invalid_input"
    assert "payload.domain" in body["error"]["message"]


def test_structured_bucket_search_includes_unannotated_items(client: TestClient) -> None:
    add_response = client.post(
        "/tools/bucket.item.add",
        json=_request_body(
            "bucket.item.add",
            payload={"title": "Unknown Indie Thing", "domain": "movie", "auto_enrich": False},
        ),
    )
    assert add_response.status_code == 200

    search_response = client.post(
        "/tools/bucket.item.search",
        json=_request_body(
            "bucket.item.search",
            payload={"domain": "movie", "query": "Unknown Indie Thing"},
        ),
    )
    assert search_response.status_code == 200
    result = search_response.json()["result"]
    assert result["count"] == 1
    assert result["annotated_count"] == 0
    assert result["unannotated_count"] == 1
    assert result["items"][0]["annotated"] is False
    assert result["items"][0]["annotation_status"] in {"pending", "failed"}


def test_structured_bucket_recommend_excludes_unannotated_items(client: TestClient) -> None:
    annotated = client.post(
        "/tools/bucket.item.add",
        json=_request_body(
            "bucket.item.add",
            payload={
                "title": "Action Ready",
                "domain": "movie",
                "duration_minutes": 95,
                "genres": ["Action"],
                "rating": 7.2,
                "auto_enrich": False,
            },
        ),
    )
    unannotated = client.post(
        "/tools/bucket.item.add",
        json=_request_body(
            "bucket.item.add",
            payload={"title": "Action Unknown", "domain": "movie", "auto_enrich": False},
        ),
    )
    assert annotated.status_code == 200
    assert unannotated.status_code == 200

    recommend = client.post(
        "/tools/bucket.item.recommend",
        json=_request_body(
            "bucket.item.recommend",
            payload={
                "domain": "movie",
                "target_duration_minutes": 90,
                "limit": 5,
            },
        ),
    )
    assert recommend.status_code == 200
    result = recommend.json()["result"]
    titles = [entry["bucket_item"]["title"] for entry in result["recommendations"]]
    assert "Action Ready" in titles
    assert "Action Unknown" not in titles
    assert result["skipped_unannotated_count"] >= 1


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
