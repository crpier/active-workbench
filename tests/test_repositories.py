from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from backend.app.repositories.database import Database
from backend.app.repositories.jobs_repository import JobsRepository
from backend.app.repositories.vault_repository import VaultRepository
from backend.app.repositories.youtube_cache_repository import (
    CachedLikeVideo,
    YouTubeCacheRepository,
)
from backend.app.repositories.youtube_quota_repository import YouTubeQuotaRepository


def test_jobs_repository_schedule_and_due(tmp_path: Path) -> None:
    db = Database(tmp_path / "state.db")
    db.initialize()
    jobs = JobsRepository(db)

    run_at = datetime.now(UTC) - timedelta(minutes=1)
    job_id = jobs.schedule_reminder(run_at, "Europe/Bucharest", {"item": "leeks"})
    assert job_id.startswith("job_")

    due = jobs.list_due_jobs(datetime.now(UTC), limit=5)
    assert due
    assert due[0].job_id == job_id

    jobs.mark_completed(job_id, {"ok": True})
    assert jobs.list_due_jobs(datetime.now(UTC), limit=5) == []


def test_jobs_repository_weekly_reschedule(tmp_path: Path) -> None:
    db = Database(tmp_path / "state.db")
    db.initialize()
    jobs = JobsRepository(db)

    now = datetime.now(UTC)
    weekly_id = jobs.ensure_weekly_routine_review(now, "Europe/Bucharest")
    same_id = jobs.ensure_weekly_routine_review(now, "Europe/Bucharest")
    assert weekly_id == same_id

    next_run = now + timedelta(days=7)
    jobs.reschedule_weekly(weekly_id, next_run)


def test_vault_repository_save_and_list(tmp_path: Path) -> None:
    vault = VaultRepository(tmp_path / "vault")

    saved = vault.save_document(
        category="notes",
        title="Microservices",
        body="Key note body",
        tool_name="vault.note.save",
        source_refs=[{"type": "youtube_video", "id": "abc"}],
    )
    assert saved.relative_path.startswith("vault/notes/")

    docs = vault.list_documents("notes")
    assert docs
    assert docs[0].title == "Microservices"


def test_vault_repository_handles_missing_or_invalid_files(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    notes_dir = vault_root / "notes"
    notes_dir.mkdir(parents=True)

    (notes_dir / "bad.md").write_text("no frontmatter", encoding="utf-8")

    vault = VaultRepository(vault_root)
    docs = vault.list_documents("notes")
    assert docs == []


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
        segments=[{"text": "hello", "start": 0.0, "duration": 1.0}],
    )

    fresh = cache_repo.get_fresh_transcript(video_id="vid_3", ttl_seconds=3600)
    assert fresh is not None
    assert fresh.transcript == "hello world"
    assert fresh.segments[0]["text"] == "hello"

    stale = cache_repo.get_fresh_transcript(video_id="vid_3", ttl_seconds=0)
    assert stale is None
