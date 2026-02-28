from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

ToolName = Literal[
    "youtube.likes.list_recent",
    "youtube.likes.search_recent_content",
    "youtube.watch_later.list",
    "youtube.watch_later.search_content",
    "youtube.watch_later.recommend",
    "youtube.transcript.get",
    "bucket.item.add",
    "bucket.item.update",
    "bucket.item.complete",
    "bucket.item.search",
    "bucket.item.recommend",
    "bucket.health.report",
    "memory.create",
    "memory.list",
    "memory.search",
    "memory.delete",
    "memory.undo",
]

WRITE_TOOLS: frozenset[str] = frozenset(
    {
        "bucket.item.add",
        "bucket.item.update",
        "bucket.item.complete",
        "memory.create",
        "memory.delete",
        "memory.undo",
    }
)


class ToolContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timezone: str = Field(default="Europe/Bucharest")
    session_id: str | None = Field(default=None)


class ToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool: ToolName
    request_id: UUID
    idempotency_key: UUID | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    context: ToolContext = Field(default_factory=ToolContext)


class ProvenanceRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str
    id: str


class ToolError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    retryable: bool = False


def _default_result() -> dict[str, Any]:
    return {}


def _default_provenance() -> list[ProvenanceRef]:
    return []


class ToolResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    request_id: UUID
    result: dict[str, Any] = Field(default_factory=_default_result)
    provenance: list[ProvenanceRef] = Field(default_factory=_default_provenance)
    audit_event_id: str | None = None
    undo_token: str | None = None
    error: ToolError | None = None


class ToolCatalogEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: ToolName
    description: str
    write_operation: bool
    ready_for_use: bool
    readiness_note: str | None = None
