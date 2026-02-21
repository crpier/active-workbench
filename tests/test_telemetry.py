from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from backend.app.telemetry import TelemetryClient, build_telemetry_client


class _CaptureSink:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def emit(self, *, event_name: str, attributes: Mapping[str, Any]) -> None:
        self.events.append((event_name, dict(attributes)))


def test_telemetry_client_redacts_sensitive_fields() -> None:
    sink = _CaptureSink()
    client = TelemetryClient(enabled=True, sink=sink)

    client.emit(
        "tool.execute.start",
        request_id="req_123",
        payload={"title": "sensitive"},
        transcript="very long transcript text",
        api_key="secret",
        count=3,
    )

    assert len(sink.events) == 1
    event_name, attributes = sink.events[0]
    assert event_name == "tool.execute.start"
    assert attributes["request_id"] == "req_123"
    assert attributes["count"] == 3
    assert attributes["payload"] == "[redacted]"
    assert attributes["transcript"] == "[redacted]"
    assert attributes["api_key"] == "[redacted]"


def test_disabled_telemetry_client_does_not_emit() -> None:
    sink = _CaptureSink()
    client = TelemetryClient(enabled=False, sink=sink)

    client.emit("tool.execute.start", request_id="req_1")
    assert sink.events == []


def test_build_telemetry_client_none_sink_is_disabled() -> None:
    client = build_telemetry_client(enabled=True, sink="none")
    assert client.enabled is False
