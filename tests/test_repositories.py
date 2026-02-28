from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from backend.app.repositories.database import Database
from backend.app.repositories.youtube_cache_repository import (
    WATCH_LATER_STATUS_ACTIVE,
    WATCH_LATER_STATUS_REMOVED_NOT_LIKED,
    WATCH_LATER_STATUS_REMOVED_WATCHED,
    CachedLikeVideo,
    YouTubeCacheRepository,
)
from backend.app.repositories.youtube_quota_repository import YouTubeQuotaRepository


def test_youtube_quota_repository_records_daily_usage(tmp_path: Path) -> None:
    db = Database(tmp_path / "state.db")
    db.initialize()
    quota_repo = YouTubeQuotaRepository(db)

    first = quota_repo.record_and_snapshot(
        tool_name="youtube.likes.list_recent",
        estimated_units_this_call=2,
        daily_limit=10_000,
        warning_threshold=8_000,
    )
    second = quota_repo.record_and_snapshot(
        tool_name="youtube.transcript.get",
        estimated_units_this_call=1,
        daily_limit=10_000,
        warning_threshold=8_000,
    )

    assert first.estimated_units_this_call == 2
    assert second.estimated_units_today == 3
    assert second.estimated_calls_today == 2
    assert second.warning is False


def test_youtube_quota_repository_sets_warning(tmp_path: Path) -> None:
    db = Database(tmp_path / "state.db")
    db.initialize()
    quota_repo = YouTubeQuotaRepository(db)

    snapshot = quota_repo.record_and_snapshot(
        tool_name="youtube.likes.list_recent",
        estimated_units_this_call=8_000,
        daily_limit=10_000,
        warning_threshold=8_000,
    )
    assert snapshot.warning is True


def test_youtube_cache_repository_likes_replace_and_list(tmp_path: Path) -> None:
    db = Database(tmp_path / "state.db")
    db.initialize()
    cache_repo = YouTubeCacheRepository(db)

    cache_repo.replace_likes(
        videos=[
            CachedLikeVideo(
                video_id="vid_1",
                title="First",
                liked_at="2026-02-08T12:00:00+00:00",
                video_published_at="2026-02-07T12:00:00+00:00",
                description="desc 1",
                channel_title="chan 1",
                tags=("one", "two"),
            ),
            CachedLikeVideo(
                video_id="vid_2",
                title="Second",
                liked_at="2026-02-07T12:00:00+00:00",
                video_published_at="2026-02-06T12:00:00+00:00",
                description=None,
                channel_title=None,
                tags=(),
            ),
        ],
        max_items=10,
    )

    last_sync_at = cache_repo.get_likes_last_sync_at()
    assert last_sync_at is not None

    listed = cache_repo.list_likes(limit=10)
    assert [video.video_id for video in listed] == ["vid_1", "vid_2"]
    assert listed[0].tags == ("one", "two")


def test_youtube_cache_repository_transcript_ttl(tmp_path: Path) -> None:
    db = Database(tmp_path / "state.db")
    db.initialize()
    cache_repo = YouTubeCacheRepository(db)

    cache_repo.upsert_transcript(
        video_id="vid_3",
        title="Transcript Video",
        transcript="hello world",
        source="youtube_captions",
        initial_request_source="likes",
        segments=[{"text": "hello", "start": 0.0, "duration": 1.0}],
    )

    fresh = cache_repo.get_fresh_transcript(video_id="vid_3", ttl_seconds=3600)
    assert fresh is not None
    assert fresh.transcript == "hello world"
    assert fresh.segments[0]["text"] == "hello"

    stale = cache_repo.get_fresh_transcript(video_id="vid_3", ttl_seconds=0)
    assert stale is None


def test_youtube_cache_repository_transcript_sync_candidate_and_status(tmp_path: Path) -> None:
    db = Database(tmp_path / "state.db")
    db.initialize()
    cache_repo = YouTubeCacheRepository(db)

    cache_repo.upsert_likes(
        videos=[
            CachedLikeVideo(
                video_id="recent_1",
                title="Recent One",
                liked_at="2026-02-10T12:00:00+00:00",
            ),
            CachedLikeVideo(
                video_id="recent_2",
                title="Recent Two",
                liked_at="2026-02-10T11:00:00+00:00",
            ),
        ],
        max_items=100,
    )
    cache_repo.upsert_transcript(
        video_id="recent_1",
        title="Recent One",
        transcript="already cached",
        source="youtube_captions",
        initial_request_source="likes",
        segments=[],
    )

    candidate = cache_repo.get_next_transcript_candidate(
        not_before=datetime.now(UTC),
    )
    assert candidate is not None
    assert candidate.video_id == "recent_2"

    next_attempt = datetime.now(UTC) + timedelta(minutes=30)
    cache_repo.mark_transcript_sync_failure(
        video_id="recent_2",
        attempts=1,
        next_attempt_at=next_attempt,
        error="temporary failure",
    )

    blocked = cache_repo.get_next_transcript_candidate(
        not_before=datetime.now(UTC),
    )
    assert blocked is None

    cache_repo.mark_transcript_sync_success(video_id="recent_2")
    assert cache_repo.get_transcript_sync_attempts(video_id="recent_2") == 2


def test_youtube_cache_repository_watch_later_snapshot_transitions(tmp_path: Path) -> None:
    db = Database(tmp_path / "state.db")
    db.initialize()
    cache_repo = YouTubeCacheRepository(db)

    first = cache_repo.apply_watch_later_snapshot(
        video_ids=["watch_1", "watch_2"],
        generated_at_utc="2026-02-28T10:00:00+00:00",
        source_client="tests",
    )
    assert first["accepted"] is True
    assert first["dedupe_skipped"] is False
    assert cache_repo.count_watch_later(statuses=(WATCH_LATER_STATUS_ACTIVE,)) == 2

    cache_repo.upsert_likes(
        videos=[
            CachedLikeVideo(
                video_id="watch_1",
                title="Watched Item",
                liked_at="2026-02-28T11:00:00+00:00",
            )
        ]
    )

    second = cache_repo.apply_watch_later_snapshot(
        video_ids=["watch_2"],
        generated_at_utc="2026-02-28T11:30:00+00:00",
        source_client="tests",
    )
    assert second["accepted"] is True
    assert second["dedupe_skipped"] is False
    assert second["videos_marked_removed_watched"] == 1
    assert second["videos_marked_removed_not_liked"] == 0
    assert cache_repo.count_watch_later(statuses=(WATCH_LATER_STATUS_ACTIVE,)) == 1
    assert cache_repo.count_watch_later(statuses=(WATCH_LATER_STATUS_REMOVED_WATCHED,)) == 1

    third = cache_repo.apply_watch_later_snapshot(
        video_ids=["watch_2"],
        generated_at_utc="2026-02-28T11:45:00+00:00",
        source_client="tests",
    )
    assert third["accepted"] is True
    assert third["dedupe_skipped"] is True

    fourth = cache_repo.apply_watch_later_snapshot(
        video_ids=[],
        generated_at_utc="2026-02-28T12:00:00+00:00",
        source_client="tests",
    )
    assert fourth["accepted"] is True
    assert fourth["videos_marked_removed_not_liked"] == 1
    assert cache_repo.count_watch_later(statuses=(WATCH_LATER_STATUS_REMOVED_NOT_LIKED,)) == 1
