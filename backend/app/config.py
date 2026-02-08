from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppSettings:
    data_dir: Path
    vault_dir: Path
    db_path: Path
    default_timezone: str
    youtube_mode: str
    scheduler_enabled: bool
    scheduler_poll_interval_seconds: int


DEFAULT_DATA_DIR = ".active-workbench"


def _env_bool(value: str | None, *, default: bool) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def load_settings() -> AppSettings:
    data_dir = Path(os.getenv("ACTIVE_WORKBENCH_DATA_DIR", DEFAULT_DATA_DIR)).resolve()
    vault_dir = Path(os.getenv("ACTIVE_WORKBENCH_VAULT_DIR", str(data_dir / "vault"))).resolve()
    db_path = Path(os.getenv("ACTIVE_WORKBENCH_DB_PATH", str(data_dir / "state.db"))).resolve()
    default_timezone = os.getenv("ACTIVE_WORKBENCH_DEFAULT_TIMEZONE", "Europe/Bucharest")
    youtube_mode = os.getenv("ACTIVE_WORKBENCH_YOUTUBE_MODE", "fixture")
    scheduler_enabled = _env_bool(
        os.getenv("ACTIVE_WORKBENCH_ENABLE_SCHEDULER"),
        default=True,
    )
    scheduler_poll_interval_seconds = int(
        os.getenv("ACTIVE_WORKBENCH_SCHEDULER_POLL_INTERVAL_SECONDS", "30")
    )

    return AppSettings(
        data_dir=data_dir,
        vault_dir=vault_dir,
        db_path=db_path,
        default_timezone=default_timezone,
        youtube_mode=youtube_mode,
        scheduler_enabled=scheduler_enabled,
        scheduler_poll_interval_seconds=scheduler_poll_interval_seconds,
    )
