from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from backend.app.dependencies import get_dispatcher
from backend.app.models.tool_contracts import ToolCatalogEntry, ToolName, ToolRequest, ToolResponse
from backend.app.services.tool_dispatcher import ToolDispatcher

router = APIRouter()


def _validate_tool_name(expected_tool: ToolName, request: ToolRequest) -> None:
    if request.tool != expected_tool:
        raise HTTPException(
            status_code=400,
            detail=(
                "Request tool does not match endpoint. "
                f"expected={expected_tool} actual={request.tool}"
            ),
        )


def _handle_tool(
    expected_tool: ToolName,
    request: ToolRequest,
    dispatcher: ToolDispatcher,
) -> ToolResponse:
    _validate_tool_name(expected_tool, request)
    return dispatcher.execute(expected_tool, request)


@router.get(
    "/tools", response_model=list[ToolCatalogEntry], tags=["tools"], operation_id="list_tools"
)
def list_tools(
    dispatcher: Annotated[ToolDispatcher, Depends(get_dispatcher)],
) -> list[ToolCatalogEntry]:
    return dispatcher.list_tools()


@router.post(
    "/tools/youtube.likes.list_recent",
    response_model=ToolResponse,
    tags=["tools"],
    operation_id="youtube_likes_list_recent",
)
def youtube_likes_list_recent(
    request: ToolRequest,
    dispatcher: Annotated[ToolDispatcher, Depends(get_dispatcher)],
) -> ToolResponse:
    return _handle_tool("youtube.likes.list_recent", request, dispatcher)


@router.post(
    "/tools/youtube.likes.search_recent_content",
    response_model=ToolResponse,
    tags=["tools"],
    operation_id="youtube_likes_search_recent_content",
)
def youtube_likes_search_recent_content(
    request: ToolRequest,
    dispatcher: Annotated[ToolDispatcher, Depends(get_dispatcher)],
) -> ToolResponse:
    return _handle_tool("youtube.likes.search_recent_content", request, dispatcher)


@router.post(
    "/tools/youtube.transcript.get",
    response_model=ToolResponse,
    tags=["tools"],
    operation_id="youtube_transcript_get",
)
def youtube_transcript_get(
    request: ToolRequest,
    dispatcher: Annotated[ToolDispatcher, Depends(get_dispatcher)],
) -> ToolResponse:
    return _handle_tool("youtube.transcript.get", request, dispatcher)


@router.post(
    "/tools/vault.recipe.save",
    response_model=ToolResponse,
    tags=["tools"],
    operation_id="vault_recipe_save",
)
def vault_recipe_save(
    request: ToolRequest,
    dispatcher: Annotated[ToolDispatcher, Depends(get_dispatcher)],
) -> ToolResponse:
    return _handle_tool("vault.recipe.save", request, dispatcher)


@router.post(
    "/tools/vault.note.save",
    response_model=ToolResponse,
    tags=["tools"],
    operation_id="vault_note_save",
)
def vault_note_save(
    request: ToolRequest,
    dispatcher: Annotated[ToolDispatcher, Depends(get_dispatcher)],
) -> ToolResponse:
    return _handle_tool("vault.note.save", request, dispatcher)


@router.post(
    "/tools/vault.bucket_list.add",
    response_model=ToolResponse,
    tags=["tools"],
    operation_id="vault_bucket_list_add",
)
def vault_bucket_list_add(
    request: ToolRequest,
    dispatcher: Annotated[ToolDispatcher, Depends(get_dispatcher)],
) -> ToolResponse:
    return _handle_tool("vault.bucket_list.add", request, dispatcher)


@router.post(
    "/tools/vault.bucket_list.prioritize",
    response_model=ToolResponse,
    tags=["tools"],
    operation_id="bucket_list_prioritize",
)
def bucket_list_prioritize(
    request: ToolRequest,
    dispatcher: Annotated[ToolDispatcher, Depends(get_dispatcher)],
) -> ToolResponse:
    return _handle_tool("vault.bucket_list.prioritize", request, dispatcher)


@router.post(
    "/tools/memory.create",
    response_model=ToolResponse,
    tags=["tools"],
    operation_id="memory_create",
)
def memory_create(
    request: ToolRequest,
    dispatcher: Annotated[ToolDispatcher, Depends(get_dispatcher)],
) -> ToolResponse:
    return _handle_tool("memory.create", request, dispatcher)


@router.post(
    "/tools/memory.undo",
    response_model=ToolResponse,
    tags=["tools"],
    operation_id="memory_undo",
)
def memory_undo(
    request: ToolRequest,
    dispatcher: Annotated[ToolDispatcher, Depends(get_dispatcher)],
) -> ToolResponse:
    return _handle_tool("memory.undo", request, dispatcher)


@router.post(
    "/tools/reminder.schedule",
    response_model=ToolResponse,
    tags=["tools"],
    operation_id="reminder_schedule",
)
def reminder_schedule(
    request: ToolRequest,
    dispatcher: Annotated[ToolDispatcher, Depends(get_dispatcher)],
) -> ToolResponse:
    return _handle_tool("reminder.schedule", request, dispatcher)


@router.post(
    "/tools/context.suggest_for_query",
    response_model=ToolResponse,
    tags=["tools"],
    operation_id="context_suggest_for_query",
)
def context_suggest_for_query(
    request: ToolRequest,
    dispatcher: Annotated[ToolDispatcher, Depends(get_dispatcher)],
) -> ToolResponse:
    return _handle_tool("context.suggest_for_query", request, dispatcher)


@router.post(
    "/tools/digest.weekly_learning.generate",
    response_model=ToolResponse,
    tags=["tools"],
    operation_id="digest_weekly_learning_generate",
)
def digest_weekly_learning_generate(
    request: ToolRequest,
    dispatcher: Annotated[ToolDispatcher, Depends(get_dispatcher)],
) -> ToolResponse:
    return _handle_tool("digest.weekly_learning.generate", request, dispatcher)


@router.post(
    "/tools/review.routine.generate",
    response_model=ToolResponse,
    tags=["tools"],
    operation_id="review_routine_generate",
)
def review_routine_generate(
    request: ToolRequest,
    dispatcher: Annotated[ToolDispatcher, Depends(get_dispatcher)],
) -> ToolResponse:
    return _handle_tool("review.routine.generate", request, dispatcher)


@router.post(
    "/tools/recipe.extract_from_transcript",
    response_model=ToolResponse,
    tags=["tools"],
    operation_id="recipe_extract_from_transcript",
)
def recipe_extract_from_transcript(
    request: ToolRequest,
    dispatcher: Annotated[ToolDispatcher, Depends(get_dispatcher)],
) -> ToolResponse:
    return _handle_tool("recipe.extract_from_transcript", request, dispatcher)


@router.post(
    "/tools/summary.extract_key_ideas",
    response_model=ToolResponse,
    tags=["tools"],
    operation_id="summary_extract_key_ideas",
)
def summary_extract_key_ideas(
    request: ToolRequest,
    dispatcher: Annotated[ToolDispatcher, Depends(get_dispatcher)],
) -> ToolResponse:
    return _handle_tool("summary.extract_key_ideas", request, dispatcher)


@router.post(
    "/tools/actions.extract_from_notes",
    response_model=ToolResponse,
    tags=["tools"],
    operation_id="actions_extract_from_notes",
)
def actions_extract_from_notes(
    request: ToolRequest,
    dispatcher: Annotated[ToolDispatcher, Depends(get_dispatcher)],
) -> ToolResponse:
    return _handle_tool("actions.extract_from_notes", request, dispatcher)
