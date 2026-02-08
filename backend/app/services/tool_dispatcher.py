from __future__ import annotations

from typing import Any

from backend.app.models.tool_contracts import (
    WRITE_TOOLS,
    ToolCatalogEntry,
    ToolName,
    ToolRequest,
    ToolResponse,
)

TOOL_DESCRIPTIONS: dict[ToolName, str] = {
    "youtube.history.list_recent": "List recently watched YouTube videos.",
    "youtube.transcript.get": "Retrieve transcript for a YouTube video.",
    "vault.recipe.save": "Persist a recipe note in markdown.",
    "vault.note.save": "Persist a generic knowledge note in markdown.",
    "vault.bucket_list.add": "Add an item to the bucket list.",
    "memory.create": "Create a memory record for future retrieval.",
    "memory.undo": "Undo a memory write action.",
    "reminder.schedule": "Schedule a local reminder job.",
    "context.suggest_for_query": "Return context-aware suggestions for a user query.",
    "digest.weekly_learning.generate": "Generate a weekly learning digest artifact.",
    "review.routine.generate": "Generate the routine review artifact.",
    "recipe.extract_from_transcript": "Extract recipe details from transcript text.",
    "summary.extract_key_ideas": "Extract key ideas from transcript text.",
    "actions.extract_from_notes": "Extract action items from saved notes.",
}


class ToolDispatcher:
    """Executes tool calls through a uniform response envelope.

    Initial implementation is placeholder-only, returning deterministic payloads
    and metadata so client and contract work can proceed before full business logic.
    """

    def list_tools(self) -> list[ToolCatalogEntry]:
        return [
            ToolCatalogEntry(
                name=name,
                description=description,
                write_operation=name in WRITE_TOOLS,
            )
            for name, description in TOOL_DESCRIPTIONS.items()
        ]

    def execute(self, tool_name: ToolName, request: ToolRequest) -> ToolResponse:
        result: dict[str, Any] = {
            "tool": tool_name,
            "status": "accepted",
            "echo_payload": request.payload,
        }
        audit_event_id = f"evt_{request.request_id}"
        undo_token = f"undo_{request.request_id}" if tool_name in WRITE_TOOLS else None

        return ToolResponse(
            ok=True,
            request_id=request.request_id,
            result=result,
            provenance=[],
            audit_event_id=audit_event_id,
            undo_token=undo_token,
            error=None,
        )
