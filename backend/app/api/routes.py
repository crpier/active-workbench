from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.app.models.tool_contracts import ToolCatalogEntry, ToolName, ToolRequest, ToolResponse
from backend.app.services.tool_dispatcher import ToolDispatcher

router = APIRouter()
_dispatcher = ToolDispatcher()


def _validate_tool_name(expected_tool: ToolName, request: ToolRequest) -> None:
    if request.tool != expected_tool:
        raise HTTPException(
            status_code=400,
            detail=(
                "Request tool does not match endpoint. "
                f"expected={expected_tool} actual={request.tool}"
            ),
        )


def _handle_tool(expected_tool: ToolName, request: ToolRequest) -> ToolResponse:
    _validate_tool_name(expected_tool, request)
    return _dispatcher.execute(expected_tool, request)


@router.get(
    "/tools", response_model=list[ToolCatalogEntry], tags=["tools"], operation_id="list_tools"
)
def list_tools() -> list[ToolCatalogEntry]:
    return _dispatcher.list_tools()


@router.post(
    "/tools/youtube.history.list_recent",
    response_model=ToolResponse,
    tags=["tools"],
    operation_id="youtube_history_list_recent",
)
def youtube_history_list_recent(request: ToolRequest) -> ToolResponse:
    return _handle_tool("youtube.history.list_recent", request)


@router.post(
    "/tools/youtube.transcript.get",
    response_model=ToolResponse,
    tags=["tools"],
    operation_id="youtube_transcript_get",
)
def youtube_transcript_get(request: ToolRequest) -> ToolResponse:
    return _handle_tool("youtube.transcript.get", request)


@router.post(
    "/tools/vault.recipe.save",
    response_model=ToolResponse,
    tags=["tools"],
    operation_id="vault_recipe_save",
)
def vault_recipe_save(request: ToolRequest) -> ToolResponse:
    return _handle_tool("vault.recipe.save", request)


@router.post(
    "/tools/vault.note.save",
    response_model=ToolResponse,
    tags=["tools"],
    operation_id="vault_note_save",
)
def vault_note_save(request: ToolRequest) -> ToolResponse:
    return _handle_tool("vault.note.save", request)


@router.post(
    "/tools/vault.bucket_list.add",
    response_model=ToolResponse,
    tags=["tools"],
    operation_id="vault_bucket_list_add",
)
def vault_bucket_list_add(request: ToolRequest) -> ToolResponse:
    return _handle_tool("vault.bucket_list.add", request)


@router.post(
    "/tools/memory.create",
    response_model=ToolResponse,
    tags=["tools"],
    operation_id="memory_create",
)
def memory_create(request: ToolRequest) -> ToolResponse:
    return _handle_tool("memory.create", request)


@router.post(
    "/tools/memory.undo",
    response_model=ToolResponse,
    tags=["tools"],
    operation_id="memory_undo",
)
def memory_undo(request: ToolRequest) -> ToolResponse:
    return _handle_tool("memory.undo", request)


@router.post(
    "/tools/reminder.schedule",
    response_model=ToolResponse,
    tags=["tools"],
    operation_id="reminder_schedule",
)
def reminder_schedule(request: ToolRequest) -> ToolResponse:
    return _handle_tool("reminder.schedule", request)


@router.post(
    "/tools/context.suggest_for_query",
    response_model=ToolResponse,
    tags=["tools"],
    operation_id="context_suggest_for_query",
)
def context_suggest_for_query(request: ToolRequest) -> ToolResponse:
    return _handle_tool("context.suggest_for_query", request)


@router.post(
    "/tools/digest.weekly_learning.generate",
    response_model=ToolResponse,
    tags=["tools"],
    operation_id="digest_weekly_learning_generate",
)
def digest_weekly_learning_generate(request: ToolRequest) -> ToolResponse:
    return _handle_tool("digest.weekly_learning.generate", request)


@router.post(
    "/tools/review.routine.generate",
    response_model=ToolResponse,
    tags=["tools"],
    operation_id="review_routine_generate",
)
def review_routine_generate(request: ToolRequest) -> ToolResponse:
    return _handle_tool("review.routine.generate", request)


@router.post(
    "/tools/recipe.extract_from_transcript",
    response_model=ToolResponse,
    tags=["tools"],
    operation_id="recipe_extract_from_transcript",
)
def recipe_extract_from_transcript(request: ToolRequest) -> ToolResponse:
    return _handle_tool("recipe.extract_from_transcript", request)


@router.post(
    "/tools/summary.extract_key_ideas",
    response_model=ToolResponse,
    tags=["tools"],
    operation_id="summary_extract_key_ideas",
)
def summary_extract_key_ideas(request: ToolRequest) -> ToolResponse:
    return _handle_tool("summary.extract_key_ideas", request)


@router.post(
    "/tools/actions.extract_from_notes",
    response_model=ToolResponse,
    tags=["tools"],
    operation_id="actions_extract_from_notes",
)
def actions_extract_from_notes(request: ToolRequest) -> ToolResponse:
    return _handle_tool("actions.extract_from_notes", request)
