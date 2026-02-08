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


DEFAULT_DATA_DIR = ".active-workbench"


def load_settings() -> AppSettings:
    data_dir = Path(os.getenv("ACTIVE_WORKBENCH_DATA_DIR", DEFAULT_DATA_DIR)).resolve()
    vault_dir = Path(os.getenv("ACTIVE_WORKBENCH_VAULT_DIR", str(data_dir / "vault"))).resolve()
    db_path = Path(os.getenv("ACTIVE_WORKBENCH_DB_PATH", str(data_dir / "state.db"))).resolve()
    default_timezone = os.getenv("ACTIVE_WORKBENCH_DEFAULT_TIMEZONE", "Europe/Bucharest")

    return AppSettings(
        data_dir=data_dir,
        vault_dir=vault_dir,
        db_path=db_path,
        default_timezone=default_timezone,
    )
