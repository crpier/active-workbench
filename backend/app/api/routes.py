from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from structlog.contextvars import bind_contextvars, reset_contextvars

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
    context_tokens = bind_contextvars(
        tool_name=expected_tool,
        tool_request_id=str(request.request_id),
    )
    try:
        return dispatcher.execute(expected_tool, request)
    finally:
        reset_contextvars(**context_tokens)


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
    "/tools/bucket.item.add",
    response_model=ToolResponse,
    tags=["tools"],
    operation_id="bucket_item_add",
)
def bucket_item_add(
    request: ToolRequest,
    dispatcher: Annotated[ToolDispatcher, Depends(get_dispatcher)],
) -> ToolResponse:
    return _handle_tool("bucket.item.add", request, dispatcher)


@router.post(
    "/tools/bucket.item.update",
    response_model=ToolResponse,
    tags=["tools"],
    operation_id="bucket_item_update",
)
def bucket_item_update(
    request: ToolRequest,
    dispatcher: Annotated[ToolDispatcher, Depends(get_dispatcher)],
) -> ToolResponse:
    return _handle_tool("bucket.item.update", request, dispatcher)


@router.post(
    "/tools/bucket.item.complete",
    response_model=ToolResponse,
    tags=["tools"],
    operation_id="bucket_item_complete",
)
def bucket_item_complete(
    request: ToolRequest,
    dispatcher: Annotated[ToolDispatcher, Depends(get_dispatcher)],
) -> ToolResponse:
    return _handle_tool("bucket.item.complete", request, dispatcher)


@router.post(
    "/tools/bucket.item.search",
    response_model=ToolResponse,
    tags=["tools"],
    operation_id="bucket_item_search",
)
def bucket_item_search(
    request: ToolRequest,
    dispatcher: Annotated[ToolDispatcher, Depends(get_dispatcher)],
) -> ToolResponse:
    return _handle_tool("bucket.item.search", request, dispatcher)


@router.post(
    "/tools/bucket.item.recommend",
    response_model=ToolResponse,
    tags=["tools"],
    operation_id="bucket_item_recommend",
)
def bucket_item_recommend(
    request: ToolRequest,
    dispatcher: Annotated[ToolDispatcher, Depends(get_dispatcher)],
) -> ToolResponse:
    return _handle_tool("bucket.item.recommend", request, dispatcher)


@router.post(
    "/tools/bucket.health.report",
    response_model=ToolResponse,
    tags=["tools"],
    operation_id="bucket_health_report",
)
def bucket_health_report(
    request: ToolRequest,
    dispatcher: Annotated[ToolDispatcher, Depends(get_dispatcher)],
) -> ToolResponse:
    return _handle_tool("bucket.health.report", request, dispatcher)


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
    "/tools/memory.list",
    response_model=ToolResponse,
    tags=["tools"],
    operation_id="memory_list",
)
def memory_list(
    request: ToolRequest,
    dispatcher: Annotated[ToolDispatcher, Depends(get_dispatcher)],
) -> ToolResponse:
    return _handle_tool("memory.list", request, dispatcher)


@router.post(
    "/tools/memory.search",
    response_model=ToolResponse,
    tags=["tools"],
    operation_id="memory_search",
)
def memory_search(
    request: ToolRequest,
    dispatcher: Annotated[ToolDispatcher, Depends(get_dispatcher)],
) -> ToolResponse:
    return _handle_tool("memory.search", request, dispatcher)


@router.post(
    "/tools/memory.delete",
    response_model=ToolResponse,
    tags=["tools"],
    operation_id="memory_delete",
)
def memory_delete(
    request: ToolRequest,
    dispatcher: Annotated[ToolDispatcher, Depends(get_dispatcher)],
) -> ToolResponse:
    return _handle_tool("memory.delete", request, dispatcher)


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

