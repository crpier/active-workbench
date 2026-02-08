from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from backend.app.config import AppSettings

LOG_FILE_NAME = "active-workbench.log"
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def configure_application_logging(settings: AppSettings) -> Path:
    log_dir = settings.log_dir
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / LOG_FILE_NAME

    logger = logging.getLogger("active_workbench")
    logger.setLevel(_resolve_log_level(settings.log_level))
    logger.propagate = False

    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=max(1, settings.log_max_bytes),
        backupCount=max(1, settings.log_backup_count),
        encoding="utf-8",
    )
    file_handler.setFormatter(logging.Formatter(LOG_FORMAT))
    logger.addHandler(file_handler)
    logger.info("logging configured level=%s path=%s", settings.log_level.upper(), log_file)
    return log_file


def _resolve_log_level(raw_level: str) -> int:
    normalized = raw_level.strip().upper()
    resolved = getattr(logging, normalized, None)
    if isinstance(resolved, int):
        return resolved
    return logging.INFO
