from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend.app.dependencies import reset_cached_dependencies
from backend.app.main import create_app
from backend.app.models.tool_contracts import WRITE_TOOLS, ToolName
from backend.app.repositories.database import Database
from backend.app.repositories.mobile_api_key_repository import MobileApiKeyRepository

ALL_TOOLS: tuple[ToolName, ...] = (
    "youtube.likes.list_recent",
    "youtube.likes.search_recent_content",
    "youtube.transcript.get",
    "bucket.item.add",
    "bucket.item.update",
    "bucket.item.complete",
    "bucket.item.search",
    "bucket.item.recommend",
    "bucket.health.report",
    "memory.create",
    "memory.list",
    "memory.search",
    "memory.delete",
    "memory.undo",
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


@contextmanager
def _configured_mobile_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    mobile_api_key: str | None = None,
    mobile_rate_limit_max_requests: int = 30,
) -> Iterator[TestClient]:
    data_dir = tmp_path / "runtime-data-auth"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "youtube-token.json").write_text("{}", encoding="utf-8")
    (data_dir / "youtube-client-secret.json").write_text("{}", encoding="utf-8")

    monkeypatch.setenv("ACTIVE_WORKBENCH_DATA_DIR", str(data_dir))
    monkeypatch.setenv("ACTIVE_WORKBENCH_ENABLE_SCHEDULER", "0")
    monkeypatch.setenv("ACTIVE_WORKBENCH_YOUTUBE_MODE", "oauth")
    monkeypatch.setenv("ACTIVE_WORKBENCH_SUPADATA_API_KEY", "test-supadata-key")
    monkeypatch.setenv("ACTIVE_WORKBENCH_BUCKET_TMDB_API_KEY", "test-tmdb-key")
    monkeypatch.setenv("ACTIVE_WORKBENCH_BUCKET_ENRICHMENT_ENABLED", "0")
    if mobile_api_key is None:
        monkeypatch.delenv("ACTIVE_WORKBENCH_MOBILE_API_KEY", raising=False)
    else:
        monkeypatch.setenv("ACTIVE_WORKBENCH_MOBILE_API_KEY", mobile_api_key)
    monkeypatch.setenv(
        "ACTIVE_WORKBENCH_MOBILE_SHARE_RATE_LIMIT_MAX_REQUESTS",
        str(mobile_rate_limit_max_requests),
    )
    monkeypatch.setenv("ACTIVE_WORKBENCH_MOBILE_SHARE_RATE_LIMIT_WINDOW_SECONDS", "60")

    reset_cached_dependencies()
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client
    reset_cached_dependencies()


@contextmanager
def _configured_mobile_client_with_device_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    device_name: str,
    mobile_rate_limit_max_requests: int = 30,
) -> Iterator[tuple[TestClient, str, str]]:
    data_dir = tmp_path / "runtime-data-device-keys"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "youtube-token.json").write_text("{}", encoding="utf-8")
    (data_dir / "youtube-client-secret.json").write_text("{}", encoding="utf-8")
    db_path = data_dir / "state.db"

    database = Database(db_path)
    database.initialize()
    key_record, token = MobileApiKeyRepository(database).create_key(device_name)

    monkeypatch.setenv("ACTIVE_WORKBENCH_DATA_DIR", str(data_dir))
    monkeypatch.setenv("ACTIVE_WORKBENCH_ENABLE_SCHEDULER", "0")
    monkeypatch.setenv("ACTIVE_WORKBENCH_YOUTUBE_MODE", "oauth")
    monkeypatch.setenv("ACTIVE_WORKBENCH_SUPADATA_API_KEY", "test-supadata-key")
    monkeypatch.setenv("ACTIVE_WORKBENCH_BUCKET_TMDB_API_KEY", "test-tmdb-key")
    monkeypatch.setenv("ACTIVE_WORKBENCH_BUCKET_ENRICHMENT_ENABLED", "0")
    monkeypatch.delenv("ACTIVE_WORKBENCH_MOBILE_API_KEY", raising=False)
    monkeypatch.setenv(
        "ACTIVE_WORKBENCH_MOBILE_SHARE_RATE_LIMIT_MAX_REQUESTS",
        str(mobile_rate_limit_max_requests),
    )
    monkeypatch.setenv("ACTIVE_WORKBENCH_MOBILE_SHARE_RATE_LIMIT_WINDOW_SECONDS", "60")

    reset_cached_dependencies()
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client, token, key_record.key_id
    reset_cached_dependencies()


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers.get("X-Request-ID")


def test_mobile_share_article_saves_link(client: TestClient) -> None:
    response = client.post(
        "/mobile/v1/share/article",
        json={
            "url": "https://example.com/posts/interesting-article?utm_source=twitter",
            "source_app": "com.twitter.android",
            "shared_text": "Read this later",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "saved"
    assert body["backend_status"] == "created"
    assert body["bucket_item_id"].startswith("bucket_")
    assert body["canonical_url"] == "https://example.com/posts/interesting-article?utm_source=twitter"


def test_mobile_share_article_duplicate_returns_already_exists(client: TestClient) -> None:
    payload = {"url": "https://example.com/posts/dupe-me"}
    first = client.post("/mobile/v1/share/article", json=payload)
    second = client.post("/mobile/v1/share/article", json=payload)

    assert first.status_code == 200
    assert second.status_code == 200

    first_body = first.json()
    second_body = second.json()

    assert first_body["status"] == "saved"
    assert second_body["status"] == "already_exists"
    assert second_body["backend_status"] == "already_exists"
    assert second_body["bucket_item_id"] == first_body["bucket_item_id"]


def test_mobile_share_article_rejects_invalid_url(client: TestClient) -> None:
    response = client.post(
        "/mobile/v1/share/article",
        json={"url": "not-a-valid-url"},
    )
    assert response.status_code == 422


def test_mobile_share_article_rejects_invalid_timezone(client: TestClient) -> None:
    response = client.post(
        "/mobile/v1/share/article",
        json={"url": "https://example.com/article", "timezone": "Mars/Olympus"},
    )
    assert response.status_code == 422


def test_mobile_share_article_ignores_legacy_auth_when_configured(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _configured_mobile_client(tmp_path, monkeypatch, mobile_api_key="secret-key") as client:
        response = client.post(
            "/mobile/v1/share/article",
            json={"url": "https://example.com/no-auth-needed"},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "saved"

        wrong_header = client.post(
            "/mobile/v1/share/article",
            headers={"Authorization": "Bearer wrong-key"},
            json={"url": "https://example.com/wrong-header-still-works"},
        )
        assert wrong_header.status_code == 200
        assert wrong_header.json()["status"] == "saved"

        legacy_header = client.post(
            "/mobile/v1/share/article",
            headers={"Authorization": "Bearer secret-key"},
            json={"url": "https://example.com/legacy-header-still-works"},
        )
        assert legacy_header.status_code == 200
        assert legacy_header.json()["status"] == "saved"


def test_mobile_share_article_ignores_device_keys_when_present(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _configured_mobile_client_with_device_key(
        tmp_path,
        monkeypatch,
        device_name="pixel-test",
    ) as configured:
        client, device_token, _key_id = configured
        response = client.post(
            "/mobile/v1/share/article",
            json={"url": "https://example.com/device-share-no-header"},
        )
        assert response.status_code == 200

        invalid = client.post(
            "/mobile/v1/share/article",
            headers={"Authorization": "Bearer mkey_missing.invalidsecretvalue"},
            json={"url": "https://example.com/device-share-wrong-header"},
        )
        assert invalid.status_code == 200

        authorized = client.post(
            "/mobile/v1/share/article",
            headers={"Authorization": f"Bearer {device_token}"},
            json={"url": "https://example.com/device-share-valid-header"},
        )
        assert authorized.status_code == 200
        assert authorized.json()["status"] == "saved"


def test_mobile_share_article_rejects_revoked_device_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _configured_mobile_client_with_device_key(
        tmp_path,
        monkeypatch,
        device_name="pixel-revoked",
    ) as configured:
        client, device_token, key_id = configured
        data_dir = tmp_path / "runtime-data-device-keys"
        database = Database(data_dir / "state.db")
        database.initialize()
        repository = MobileApiKeyRepository(database)
        assert repository.revoke_key(key_id) is True

        response = client.post(
            "/mobile/v1/share/article",
            headers={"Authorization": f"Bearer {device_token}"},
            json={"url": "https://example.com/revoked-key"},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "saved"


def test_mobile_share_article_applies_rate_limit_when_configured(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _configured_mobile_client(
        tmp_path,
        monkeypatch,
        mobile_api_key="secret-key",
        mobile_rate_limit_max_requests=1,
    ) as client:
        first = client.post(
            "/mobile/v1/share/article",
            json={"url": "https://example.com/rate-limit-first"},
        )
        assert first.status_code == 200
        assert first.headers.get("X-RateLimit-Limit") == "1"
        assert first.headers.get("X-RateLimit-Remaining") == "0"

        second = client.post(
            "/mobile/v1/share/article",
            json={"url": "https://example.com/rate-limit-second"},
        )
        assert second.status_code == 429
        assert second.headers.get("Retry-After") is not None


def test_tool_catalog_exposes_expected_tools(client: TestClient) -> None:
    response = client.get("/tools")
    assert response.status_code == 200
    data = response.json()
    names = [item["name"] for item in data]
    assert set(names) == set(ALL_TOOLS)


def test_tool_catalog_marks_all_tools_ready(client: TestClient) -> None:
    response = client.get("/tools")
    assert response.status_code == 200
    data = response.json()

    ready_tools = {item["name"] for item in data if item["ready_for_use"] is True}
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
        "memory.create",
        "memory.list",
        "memory.search",
        "memory.delete",
        "memory.undo",
    }
    assert ready_tools == set(ALL_TOOLS)

    for item in data:
        assert item["readiness_note"] is None


def test_each_tool_endpoint_accepts_valid_envelope(client: TestClient) -> None:
    for tool in ALL_TOOLS:
        payload: dict[str, Any] | None = None
        if tool == "youtube.likes.search_recent_content":
            payload = {"query": "soup"}
        elif tool == "memory.create":
            payload = {"text": "Remember to buy leeks"}
        elif tool == "memory.search":
            payload = {"query": "leeks"}
        elif tool == "memory.delete":
            payload = {"memory_id": "mem_missing"}
        response = client.post(f"/tools/{tool}", json=_request_body(tool, payload=payload))
        assert response.status_code == 200, tool
        body = response.json()
        assert body["result"]["tool"] == tool
        if tool in WRITE_TOOLS:
            assert body["audit_event_id"].startswith("evt_")


def test_tool_endpoint_rejects_tool_mismatch(client: TestClient) -> None:
    response = client.post(
        "/tools/bucket.item.add",
        json=_request_body("youtube.likes.list_recent"),
    )
    assert response.status_code == 400
    assert "does not match endpoint" in response.json()["detail"]


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
    assert create_body["result"]["memory"]["text"] == "User bought leeks"
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


def test_memory_list_search_and_delete(client: TestClient) -> None:
    create_response = client.post(
        "/tools/memory.create",
        json=_request_body(
            "memory.create",
            payload={"text": "Prefer morning deep work", "tags": ["preference", "work"]},
        ),
    )
    assert create_response.status_code == 200
    memory_id = str(create_response.json()["result"]["memory_id"])

    list_response = client.post(
        "/tools/memory.list",
        json=_request_body("memory.list", payload={"limit": 5}),
    )
    assert list_response.status_code == 200
    listed_ids = {entry["id"] for entry in list_response.json()["result"]["entries"]}
    assert memory_id in listed_ids

    search_response = client.post(
        "/tools/memory.search",
        json=_request_body("memory.search", payload={"query": "deep work"}),
    )
    assert search_response.status_code == 200
    search_ids = {entry["id"] for entry in search_response.json()["result"]["entries"]}
    assert memory_id in search_ids

    delete_response = client.post(
        "/tools/memory.delete",
        json=_request_body("memory.delete", payload={"memory_id": memory_id}),
    )
    assert delete_response.status_code == 200
    assert delete_response.json()["result"]["status"] == "deleted"

    post_delete = client.post(
        "/tools/memory.search",
        json=_request_body("memory.search", payload={"query": "deep work"}),
    )
    assert post_delete.status_code == 200
    post_delete_ids = {entry["id"] for entry in post_delete.json()["result"]["entries"]}
    assert memory_id not in post_delete_ids


def test_memory_create_rejects_empty_payload(client: TestClient) -> None:
    response = client.post(
        "/tools/memory.create",
        json={
            "tool": "memory.create",
            "request_id": str(uuid4()),
            "idempotency_key": str(uuid4()),
            "payload": {},
            "context": {"timezone": "Europe/Bucharest", "session_id": "test"},
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "invalid_input"


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
