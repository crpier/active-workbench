from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from backend.app.repositories.database import Database
from backend.app.repositories.jobs_repository import JobsRepository
from backend.app.repositories.vault_repository import VaultRepository


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
