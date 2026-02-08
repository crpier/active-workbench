from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Any, cast
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from backend.app.models.tool_contracts import (
    WRITE_TOOLS,
    ProvenanceRef,
    ToolCatalogEntry,
    ToolError,
    ToolName,
    ToolRequest,
    ToolResponse,
)
from backend.app.repositories.audit_repository import AuditRepository
from backend.app.repositories.idempotency_repository import IdempotencyRepository
from backend.app.repositories.jobs_repository import JobsRepository
from backend.app.repositories.memory_repository import MemoryRepository
from backend.app.repositories.vault_repository import SavedDocument, VaultRepository

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
    def __init__(
        self,
        *,
        audit_repository: AuditRepository,
        idempotency_repository: IdempotencyRepository,
        memory_repository: MemoryRepository,
        jobs_repository: JobsRepository,
        vault_repository: VaultRepository,
        default_timezone: str,
    ) -> None:
        self._audit_repository = audit_repository
        self._idempotency_repository = idempotency_repository
        self._memory_repository = memory_repository
        self._jobs_repository = jobs_repository
        self._vault_repository = vault_repository
        self._default_timezone = default_timezone

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
        cached = self._load_idempotent_response(tool_name, request.idempotency_key)
        if cached is not None:
            return cached

        if tool_name == "vault.recipe.save":
            response = self._handle_vault_save(request, category="recipes")
        elif tool_name == "vault.note.save":
            response = self._handle_vault_save(request, category="notes")
        elif tool_name == "vault.bucket_list.add":
            response = self._handle_vault_save(request, category="bucket-list")
        elif tool_name == "memory.create":
            response = self._handle_memory_create(request)
        elif tool_name == "memory.undo":
            response = self._handle_memory_undo(request)
        elif tool_name == "reminder.schedule":
            response = self._handle_reminder_schedule(request)
        elif tool_name == "context.suggest_for_query":
            response = self._handle_context_suggest(request)
        else:
            response = self._placeholder_response(tool_name, request)

        response = self._attach_audit_event(tool_name, request, response)
        self._store_idempotent_response(tool_name, request.idempotency_key, response)
        return response

    def _load_idempotent_response(
        self,
        tool_name: ToolName,
        idempotency_key: UUID | None,
    ) -> ToolResponse | None:
        if tool_name not in WRITE_TOOLS or idempotency_key is None:
            return None

        response_json = self._idempotency_repository.get_response_json(
            tool_name,
            str(idempotency_key),
        )
        if response_json is None:
            return None

        return ToolResponse.model_validate_json(response_json)

    def _store_idempotent_response(
        self,
        tool_name: ToolName,
        idempotency_key: UUID | None,
        response: ToolResponse,
    ) -> None:
        if tool_name not in WRITE_TOOLS or idempotency_key is None:
            return
        self._idempotency_repository.store_response_json(
            tool_name,
            str(idempotency_key),
            response.model_dump_json(),
        )

    def _attach_audit_event(
        self,
        tool_name: ToolName,
        request: ToolRequest,
        response: ToolResponse,
    ) -> ToolResponse:
        if tool_name not in WRITE_TOOLS:
            return response

        audit_event_id = self._audit_repository.create_event(
            request_id=request.request_id,
            tool_name=tool_name,
            payload=request.payload,
            result=response.result,
        )
        return response.model_copy(update={"audit_event_id": audit_event_id})

    def _handle_vault_save(self, request: ToolRequest, *, category: str) -> ToolResponse:
        title = _payload_str(request.payload, "title") or "Untitled"
        body = _payload_str(request.payload, "body") or _payload_str(request.payload, "markdown")

        if body is None:
            body = _dict_body(request.payload)

        source_refs = _extract_source_refs(request.payload)
        saved = self._vault_repository.save_document(
            category=category,
            title=title,
            body=body,
            tool_name=request.tool,
            source_refs=source_refs,
        )

        return ToolResponse(
            ok=True,
            request_id=request.request_id,
            result={
                "tool": request.tool,
                "status": "saved",
                "document_id": saved.document_id,
                "path": saved.relative_path,
            },
            provenance=[_vault_provenance(saved)],
            undo_token=None,
            error=None,
        )

    def _handle_memory_create(self, request: ToolRequest) -> ToolResponse:
        source_refs = _extract_source_refs(request.payload)
        content = dict(request.payload)

        memory_id, undo_token = self._memory_repository.create_entry(content, source_refs)

        return ToolResponse(
            ok=True,
            request_id=request.request_id,
            result={
                "tool": request.tool,
                "status": "created",
                "memory_id": memory_id,
            },
            provenance=[ProvenanceRef(type="memory_entry", id=memory_id)],
            undo_token=undo_token,
            error=None,
        )

    def _handle_memory_undo(self, request: ToolRequest) -> ToolResponse:
        undo_token = _payload_str(request.payload, "undo_token")
        if undo_token is None:
            return ToolResponse(
                ok=False,
                request_id=request.request_id,
                result={"tool": request.tool, "status": "failed"},
                provenance=[],
                error=ToolError(
                    code="invalid_input",
                    message="payload.undo_token is required",
                    retryable=False,
                ),
            )

        memory_id = self._memory_repository.undo(undo_token)
        if memory_id is None:
            return ToolResponse(
                ok=False,
                request_id=request.request_id,
                result={"tool": request.tool, "status": "not_found"},
                provenance=[],
                error=ToolError(
                    code="not_found",
                    message="Undo token was not found or already consumed",
                    retryable=False,
                ),
            )

        return ToolResponse(
            ok=True,
            request_id=request.request_id,
            result={
                "tool": request.tool,
                "status": "undone",
                "memory_id": memory_id,
            },
            provenance=[ProvenanceRef(type="memory_entry", id=memory_id)],
            undo_token=None,
            error=None,
        )

    def _handle_reminder_schedule(self, request: ToolRequest) -> ToolResponse:
        timezone_name = request.context.timezone or self._default_timezone
        run_at = _resolve_run_at(request.payload, timezone_name)

        payload: dict[str, object] = dict(request.payload)
        payload["resolved_run_at"] = run_at.isoformat()
        payload["resolved_timezone"] = timezone_name

        job_id = self._jobs_repository.schedule_reminder(
            run_at=run_at,
            timezone=timezone_name,
            payload=payload,
        )

        return ToolResponse(
            ok=True,
            request_id=request.request_id,
            result={
                "tool": request.tool,
                "status": "scheduled",
                "job_id": job_id,
                "run_at": run_at.isoformat(),
                "timezone": timezone_name,
            },
            provenance=[ProvenanceRef(type="job", id=job_id)],
            undo_token=None,
            error=None,
        )

    def _handle_context_suggest(self, request: ToolRequest) -> ToolResponse:
        query = (_payload_str(request.payload, "query") or "").lower()
        upcoming_items = self._jobs_repository.list_upcoming_reminder_items(limit=10)
        suggestions: list[str] = []

        if "recipe" in query or "cook" in query:
            for item in upcoming_items:
                suggestions.append(f"Consider using {item} soon; a reminder is already scheduled.")

        if not suggestions:
            suggestions.append("No strong contextual suggestions were found.")

        return ToolResponse(
            ok=True,
            request_id=request.request_id,
            result={
                "tool": request.tool,
                "status": "ok",
                "suggestions": suggestions,
            },
            provenance=[],
            undo_token=None,
            error=None,
        )

    def _placeholder_response(self, tool_name: ToolName, request: ToolRequest) -> ToolResponse:
        return ToolResponse(
            ok=True,
            request_id=request.request_id,
            result={
                "tool": tool_name,
                "status": "accepted",
                "echo_payload": request.payload,
            },
            provenance=[],
            undo_token=None,
            error=None,
        )


def _payload_str(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if isinstance(value, str):
        stripped = value.strip()
        if stripped:
            return stripped
    return None


def _dict_body(payload: dict[str, Any]) -> str:
    lines = ["```json", _json_dumps(payload), "```"]
    return "\n".join(lines)


def _json_dumps(value: Any) -> str:
    import json

    return json.dumps(value, indent=2, sort_keys=True)


def _extract_source_refs(payload: dict[str, Any]) -> list[dict[str, str]]:
    source_refs_raw = payload.get("source_refs")
    if not isinstance(source_refs_raw, list):
        return []
    source_refs_value = cast(list[object], source_refs_raw)

    refs: list[dict[str, str]] = []
    for raw_item in source_refs_value:
        if not isinstance(raw_item, dict):
            continue

        raw_dict = cast(dict[object, object], raw_item)
        item: dict[str, object] = {}
        for key, value in raw_dict.items():
            if isinstance(key, str):
                item[key] = value

        ref_type = item.get("type")
        ref_id = item.get("id")
        if isinstance(ref_type, str) and isinstance(ref_id, str):
            refs.append({"type": ref_type, "id": ref_id})
    return refs


def _vault_provenance(saved: SavedDocument) -> ProvenanceRef:
    return ProvenanceRef(type="vault_document", id=saved.relative_path)


def _resolve_run_at(payload: dict[str, Any], timezone_name: str) -> datetime:
    resolved_timezone = _resolve_timezone(timezone_name)

    explicit_run_at = _payload_str(payload, "run_at")
    if explicit_run_at is not None:
        parsed = datetime.fromisoformat(explicit_run_at)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=resolved_timezone)
        return parsed.astimezone(resolved_timezone)

    days_from_now = payload.get("days_from_now")
    default_days = _int_or_default(days_from_now, default=0)
    hour = _int_or_default(payload.get("hour"), default=9)
    minute = _int_or_default(payload.get("minute"), default=0)

    now = datetime.now(resolved_timezone)
    target_date = (now + timedelta(days=default_days)).date()
    return datetime.combine(target_date, time(hour=hour, minute=minute), resolved_timezone)


def _int_or_default(value: object, default: int) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default


def _resolve_timezone(timezone_name: str) -> ZoneInfo:
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")
