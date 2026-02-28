from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from structlog.contextvars import bind_contextvars, reset_contextvars

from backend.app.dependencies import get_dispatcher
from backend.app.models.tool_contracts import (
    ToolCatalogEntry,
    ToolName,
    ToolRequest,
    ToolResponse,
)
from backend.app.services.tool_dispatcher import ToolDispatcher

router = APIRouter()


def _default_watch_later_snapshot_videos() -> list[WatchLaterSnapshotVideo]:
    return []


class WatchLaterSnapshotVideo(BaseModel):
    model_config = ConfigDict(extra="ignore")

    video_id: str
    title: str | None = None
    watch_later_added_at: str | None = None
    first_seen_at: str | None = None
    snapshot_position: int | None = None
    video_published_at: str | None = None
    description: str | None = None
    channel_id: str | None = None
    channel_title: str | None = None
    duration_seconds: int | None = None
    category_id: str | None = None
    default_language: str | None = None
    default_audio_language: str | None = None
    caption_available: bool | None = None
    privacy_status: str | None = None
    licensed_content: bool | None = None
    made_for_kids: bool | None = None
    live_broadcast_content: str | None = None
    definition: str | None = None
    dimension: str | None = None
    thumbnails: dict[str, str] | None = None
    topic_categories: list[str] | None = None
    statistics_view_count: int | None = None
    statistics_like_count: int | None = None
    statistics_comment_count: int | None = None
    statistics_fetched_at: str | None = None
    tags: list[str] | None = None


class WatchLaterSnapshotPushRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generated_at_utc: str | None = None
    source_client: str = "unknown"
    videos: list[WatchLaterSnapshotVideo] = Field(
        default_factory=_default_watch_later_snapshot_videos
    )
    allow_empty_snapshot: bool = False


class WatchLaterSnapshotPushResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    result: dict[str, Any]


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
    "/tools/youtube.watch_later.list",
    response_model=ToolResponse,
    tags=["tools"],
    operation_id="youtube_watch_later_list",
)
def youtube_watch_later_list(
    request: ToolRequest,
    dispatcher: Annotated[ToolDispatcher, Depends(get_dispatcher)],
) -> ToolResponse:
    return _handle_tool("youtube.watch_later.list", request, dispatcher)


@router.post(
    "/tools/youtube.watch_later.search_content",
    response_model=ToolResponse,
    tags=["tools"],
    operation_id="youtube_watch_later_search_content",
)
def youtube_watch_later_search_content(
    request: ToolRequest,
    dispatcher: Annotated[ToolDispatcher, Depends(get_dispatcher)],
) -> ToolResponse:
    return _handle_tool("youtube.watch_later.search_content", request, dispatcher)


@router.post(
    "/tools/youtube.watch_later.recommend",
    response_model=ToolResponse,
    tags=["tools"],
    operation_id="youtube_watch_later_recommend",
)
def youtube_watch_later_recommend(
    request: ToolRequest,
    dispatcher: Annotated[ToolDispatcher, Depends(get_dispatcher)],
) -> ToolResponse:
    return _handle_tool("youtube.watch_later.recommend", request, dispatcher)


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
    "/youtube/watch-later/snapshot",
    response_model=WatchLaterSnapshotPushResponse,
    tags=["youtube"],
    operation_id="youtube_watch_later_snapshot_push",
)
def youtube_watch_later_snapshot_push(
    request: WatchLaterSnapshotPushRequest,
    dispatcher: Annotated[ToolDispatcher, Depends(get_dispatcher)],
) -> WatchLaterSnapshotPushResponse:
    if not request.allow_empty_snapshot and not request.videos:
        raise HTTPException(
            status_code=400,
            detail=(
                "Empty watch-later snapshots are blocked by default; "
                "set allow_empty_snapshot=true to force."
            ),
        )
    result = dispatcher.youtube_service.push_watch_later_snapshot(
        video_ids=[video.video_id for video in request.videos],
        source_client=request.source_client,
        generated_at_utc=request.generated_at_utc,
        videos=[video.model_dump(exclude_none=True) for video in request.videos],
    )
    return WatchLaterSnapshotPushResponse(ok=True, result=result)


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
