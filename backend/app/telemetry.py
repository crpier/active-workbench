from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, Protocol

import structlog

_SENSITIVE_ATTRIBUTE_TOKENS: frozenset[str] = frozenset(
    {
        "api_key",
        "authorization",
        "body",
        "content",
        "cookie",
        "payload",
        "secret",
        "text",
        "token",
        "transcript",
    }
)
_MAX_STRING_LENGTH = 160


class TelemetrySink(Protocol):
    def emit(self, *, event_name: str, attributes: Mapping[str, Any]) -> None:
        ...


class NoOpTelemetrySink:
    def emit(self, *, event_name: str, attributes: Mapping[str, Any]) -> None:
        _ = (event_name, attributes)
        return


class StructuredLogTelemetrySink:
    def __init__(self) -> None:
        self._logger = structlog.get_logger("active_workbench.telemetry")

    def emit(self, *, event_name: str, attributes: Mapping[str, Any]) -> None:
        self._logger.info(
            "telemetry",
            telemetry_event=event_name,
            **dict(attributes),
        )


@dataclass(frozen=True)
class TelemetryClient:
    enabled: bool
    sink: TelemetrySink

    @classmethod
    def disabled(cls) -> TelemetryClient:
        return cls(enabled=False, sink=NoOpTelemetrySink())

    def emit(self, event_name: str, **attributes: Any) -> None:
        if not self.enabled:
            return
        self.sink.emit(
            event_name=event_name,
            attributes=_sanitize_attributes(attributes),
        )


def build_telemetry_client(*, enabled: bool, sink: Literal["none", "log"]) -> TelemetryClient:
    if not enabled or sink == "none":
        return TelemetryClient.disabled()
    if sink == "log":
        return TelemetryClient(enabled=True, sink=StructuredLogTelemetrySink())

    logging.getLogger("active_workbench.telemetry").warning(
        "unsupported telemetry sink requested; disabling telemetry sink=%s",
        sink,
    )
    return TelemetryClient.disabled()


def _sanitize_attributes(
    attributes: Mapping[str, Any],
) -> dict[str, bool | int | float | str | None]:
    sanitized: dict[str, bool | int | float | str | None] = {}
    for raw_key, raw_value in attributes.items():
        key = str(raw_key).strip().lower()
        if not key:
            continue
        if _is_sensitive_attribute(key):
            sanitized[key] = "[redacted]"
            continue
        sanitized[key] = _sanitize_value(raw_value)
    return sanitized


def _is_sensitive_attribute(key: str) -> bool:
    return any(token in key for token in _SENSITIVE_ATTRIBUTE_TOKENS)


def _sanitize_value(value: Any) -> bool | int | float | str | None:
    if value is None:
        return None
    if isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        compact = " ".join(value.split())
        if len(compact) <= _MAX_STRING_LENGTH:
            return compact
        return f"{compact[:_MAX_STRING_LENGTH]}..."
    return str(type(value).__name__)
