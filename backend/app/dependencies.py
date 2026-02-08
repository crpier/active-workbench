from __future__ import annotations

from functools import lru_cache

from backend.app.config import AppSettings, load_settings
from backend.app.repositories.audit_repository import AuditRepository
from backend.app.repositories.database import Database
from backend.app.repositories.idempotency_repository import IdempotencyRepository
from backend.app.repositories.jobs_repository import JobsRepository
from backend.app.repositories.memory_repository import MemoryRepository
from backend.app.repositories.vault_repository import VaultRepository
from backend.app.services.tool_dispatcher import ToolDispatcher


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    return load_settings()


@lru_cache(maxsize=1)
def get_dispatcher() -> ToolDispatcher:
    settings = get_settings()
    database = Database(settings.db_path)
    database.initialize()

    return ToolDispatcher(
        audit_repository=AuditRepository(database),
        idempotency_repository=IdempotencyRepository(database),
        memory_repository=MemoryRepository(database),
        jobs_repository=JobsRepository(database),
        vault_repository=VaultRepository(settings.vault_dir),
        default_timezone=settings.default_timezone,
    )


def reset_cached_dependencies() -> None:
    get_dispatcher.cache_clear()
    get_settings.cache_clear()
