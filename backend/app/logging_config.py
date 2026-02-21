from __future__ import annotations

import logging
import sys
from pathlib import Path

import structlog
from structlog.typing import EventDict, Processor

from backend.app.config import AppSettings

LOG_FILE_NAME = "active-workbench.log"
TELEMETRY_LOG_FILE_NAME = "active-workbench-telemetry.log"


def configure_application_logging(settings: AppSettings) -> Path:
    log_dir = settings.log_dir
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / LOG_FILE_NAME
    telemetry_log_file = log_dir / TELEMETRY_LOG_FILE_NAME

    _configure_structlog()

    logger = logging.getLogger("active_workbench")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    _reset_handlers(logger)

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(_build_file_formatter())

    console_stream = sys.stdout
    console_handler = logging.StreamHandler(stream=console_stream)
    console_handler.setLevel(_resolve_log_level(settings.log_level))
    console_handler.setFormatter(
        _build_console_formatter(enable_colors=_stream_supports_color(console_stream))
    )

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
    _configure_telemetry_logger(telemetry_log_file)

    logger.info(
        (
            "logging configured console_level=%s file_level=%s file_rotation=%s "
            "path=%s telemetry_path=%s"
        ),
        settings.log_level.upper(),
        "DEBUG",
        "external",
        log_file,
        telemetry_log_file,
    )
    return log_file


def _resolve_log_level(raw_level: str) -> int:
    normalized = raw_level.strip().upper()
    resolved = getattr(logging, normalized, None)
    if isinstance(resolved, int):
        return resolved
    return logging.INFO


def _configure_structlog() -> None:
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.filter_by_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )


def _reset_handlers(logger: logging.Logger) -> None:
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()


def _configure_telemetry_logger(log_file: Path) -> None:
    telemetry_logger = logging.getLogger("active_workbench.telemetry")
    telemetry_logger.setLevel(logging.INFO)
    telemetry_logger.propagate = False
    _reset_handlers(telemetry_logger)

    telemetry_file_handler = logging.FileHandler(log_file, encoding="utf-8")
    telemetry_file_handler.setLevel(logging.INFO)
    telemetry_file_handler.setFormatter(_build_file_formatter())
    telemetry_logger.addHandler(telemetry_file_handler)


def _build_console_formatter(*, enable_colors: bool) -> structlog.stdlib.ProcessorFormatter:
    return structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=_shared_pre_chain(),
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.dev.ConsoleRenderer(colors=enable_colors),
        ],
    )


def _build_file_formatter() -> structlog.stdlib.ProcessorFormatter:
    return structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=_shared_pre_chain(),
        processors=[
            _add_record_metadata,
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(sort_keys=True),
        ],
    )


def _shared_pre_chain() -> list[Processor]:
    return [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True, key="timestamp"),
    ]


def _add_record_metadata(
    _logger: logging.Logger,
    _method_name: str,
    event_dict: EventDict,
) -> EventDict:
    record = event_dict.get("_record")
    if isinstance(record, logging.LogRecord):
        event_dict["pathname"] = record.pathname
        event_dict["lineno"] = record.lineno
        event_dict["func_name"] = record.funcName
        event_dict["process"] = record.process
        event_dict["thread"] = record.thread
        event_dict["thread_name"] = record.threadName
    return event_dict


def _stream_supports_color(stream: object) -> bool:
    isatty = getattr(stream, "isatty", None)
    if callable(isatty):
        try:
            return bool(isatty())
        except Exception:
            return False
    return False
