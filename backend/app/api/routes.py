from __future__ import annotations

from typing import Annotated, Literal, cast
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from structlog.contextvars import bind_contextvars, reset_contextvars

from backend.app.dependencies import (
    get_bucket_repository,
    get_dispatcher,
    get_mobile_share_rate_limiter,
    get_wallabag_service,
)
from backend.app.models.article_contracts import (
    ArticleCaptureRequest,
    ArticleReadStateRequest,
    ArticleSyncStatusResponse,
)
from backend.app.models.mobile_contracts import ShareArticleRequest, ShareArticleResponse
from backend.app.models.tool_contracts import (
    ToolCatalogEntry,
    ToolContext,
    ToolName,
    ToolRequest,
    ToolResponse,
)
from backend.app.repositories.article_wallabag_repository import ArticleWallabagState
from backend.app.repositories.bucket_repository import BucketRepository
from backend.app.services.rate_limiter import SlidingWindowRateLimiter
from backend.app.services.tool_dispatcher import ToolDispatcher
from backend.app.services.wallabag_service import WallabagService

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


@router.post(
    "/mobile/v1/share/article",
    response_model=ShareArticleResponse,
    tags=["mobile"],
    operation_id="mobile_share_article",
)
def mobile_share_article(
    request: ShareArticleRequest,
    http_request: Request,
    http_response: Response,
    dispatcher: Annotated[ToolDispatcher, Depends(get_dispatcher)],
    rate_limiter: Annotated[SlidingWindowRateLimiter, Depends(get_mobile_share_rate_limiter)],
    wallabag_service: Annotated[WallabagService, Depends(get_wallabag_service)],
) -> ShareArticleResponse:
    client_ip = _resolve_client_ip(http_request)
    client_key = client_ip
    rate_limit = rate_limiter.take(client_key)
    rate_limit_headers = {
        "X-RateLimit-Limit": str(rate_limit.limit),
        "X-RateLimit-Remaining": str(rate_limit.remaining),
        "X-RateLimit-Reset": str(rate_limit.reset_after_seconds),
    }
    if not rate_limit.allowed:
        rate_limit_headers["Retry-After"] = str(rate_limit.retry_after_seconds)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded for mobile share endpoint.",
            headers=rate_limit_headers,
        )
    for header_name, header_value in rate_limit_headers.items():
        http_response.headers[header_name] = header_value

    return _capture_article(
        dispatcher=dispatcher,
        wallabag_service=wallabag_service,
        url=request.url,
        notes=request.shared_text,
        source_ref_type="mobile_share_app",
        source_ref_value=request.source_app,
        idempotency_key=request.idempotency_key,
        timezone=request.timezone,
        session_id=request.session_id,
    )


@router.post(
    "/articles/capture",
    response_model=ShareArticleResponse,
    tags=["articles"],
    operation_id="article_capture",
)
def capture_article(
    request: ArticleCaptureRequest,
    dispatcher: Annotated[ToolDispatcher, Depends(get_dispatcher)],
    wallabag_service: Annotated[WallabagService, Depends(get_wallabag_service)],
) -> ShareArticleResponse:
    return _capture_article(
        dispatcher=dispatcher,
        wallabag_service=wallabag_service,
        url=request.url,
        notes=request.notes,
        source_ref_type="web_capture",
        source_ref_value=request.source,
        idempotency_key=request.idempotency_key,
        timezone=request.timezone,
        session_id=request.session_id,
    )


@router.get(
    "/articles/{bucket_item_id}/sync-status",
    response_model=ArticleSyncStatusResponse,
    tags=["articles"],
    operation_id="article_sync_status",
)
def article_sync_status(
    bucket_item_id: str,
    wallabag_service: Annotated[WallabagService, Depends(get_wallabag_service)],
    bucket_repository: Annotated[BucketRepository, Depends(get_bucket_repository)],
) -> ArticleSyncStatusResponse:
    state = wallabag_service.get_sync_status(bucket_item_id=bucket_item_id)
    if state is None:
        bucket_item = bucket_repository.get_item(bucket_item_id)
        if bucket_item is None:
            raise HTTPException(status_code=404, detail="Article not found.")
        if bucket_item.domain != "article":
            raise HTTPException(status_code=400, detail="Bucket item is not an article.")
        return ArticleSyncStatusResponse(
            bucket_item_id=bucket_item_id,
            sync_status="missing",
        )
    return _to_sync_status_response(state)


@router.post(
    "/articles/{bucket_item_id}/refresh",
    response_model=ArticleSyncStatusResponse,
    tags=["articles"],
    operation_id="article_refresh_sync",
)
def article_refresh_sync(
    bucket_item_id: str,
    wallabag_service: Annotated[WallabagService, Depends(get_wallabag_service)],
) -> ArticleSyncStatusResponse:
    state = wallabag_service.refresh_article(bucket_item_id=bucket_item_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Article not found.")
    return _to_sync_status_response(state)


@router.patch(
    "/articles/{bucket_item_id}/read-state",
    response_model=ArticleSyncStatusResponse,
    tags=["articles"],
    operation_id="article_update_read_state",
)
def article_update_read_state(
    bucket_item_id: str,
    request: ArticleReadStateRequest,
    wallabag_service: Annotated[WallabagService, Depends(get_wallabag_service)],
) -> ArticleSyncStatusResponse:
    state = wallabag_service.set_read_state(bucket_item_id=bucket_item_id, read=request.read)
    if state is None:
        raise HTTPException(status_code=404, detail="Article not found.")
    return _to_sync_status_response(state)


def _capture_article(
    *,
    dispatcher: ToolDispatcher,
    wallabag_service: WallabagService,
    url: str,
    notes: str | None,
    source_ref_type: str,
    source_ref_value: str | None,
    idempotency_key: UUID | None,
    timezone: str,
    session_id: str | None,
) -> ShareArticleResponse:
    payload: dict[str, object] = {
        "domain": "article",
        "url": url,
        "allow_unresolved": True,
    }
    if notes is not None:
        payload["notes"] = notes
    if source_ref_value is not None:
        payload["source_refs"] = [{"type": source_ref_type, "id": source_ref_value}]

    tool_response = _handle_tool(
        "bucket.item.add",
        ToolRequest(
            tool="bucket.item.add",
            request_id=uuid4(),
            idempotency_key=idempotency_key,
            payload=payload,
            context=ToolContext(
                timezone=timezone,
                session_id=session_id,
            ),
        ),
        dispatcher,
    )

    response = _parse_share_tool_response(tool_response)
    if response.status in {"saved", "already_exists"}:
        bucket_item_id = response.bucket_item_id
        canonical_url = response.canonical_url
        source_url = canonical_url or url
        if bucket_item_id is not None:
            wallabag_state = wallabag_service.track_article_capture(
                bucket_item_id=bucket_item_id,
                source_url=source_url,
                canonical_url=canonical_url,
                eager_sync=True,
            )
            response = response.model_copy(
                update={
                    "wallabag_sync_status": wallabag_state.sync_status,
                    "wallabag_entry_id": wallabag_state.wallabag_entry_id,
                    "wallabag_entry_url": wallabag_state.wallabag_entry_url,
                    "read_state": wallabag_state.read_state,
                    "wallabag_sync_error": wallabag_state.sync_error,
                }
            )

    return response


def _parse_share_tool_response(tool_response: ToolResponse) -> ShareArticleResponse:
    if not tool_response.ok:
        return ShareArticleResponse(
            status="failed",
            request_id=tool_response.request_id,
            backend_status=None,
            message=(
                tool_response.error.message
                if tool_response.error is not None
                else "Share flow failed."
            ),
            error=tool_response.error,
        )

    result: dict[str, object] = {
        key: cast(object, value) for key, value in tool_response.result.items()
    }
    raw_backend_status = result.get("status")
    backend_status = raw_backend_status if isinstance(raw_backend_status, str) else None

    raw_message = result.get("message")
    message = raw_message if isinstance(raw_message, str) else None

    bucket_item_value = _normalize_object_dict(result.get("bucket_item")) or {}
    raw_item_id = bucket_item_value.get("item_id")
    bucket_item_id = raw_item_id if isinstance(raw_item_id, str) else None
    raw_title = bucket_item_value.get("title")
    title = raw_title if isinstance(raw_title, str) else None
    raw_external_url = bucket_item_value.get("external_url")
    canonical_url = raw_external_url if isinstance(raw_external_url, str) else None

    raw_candidates = result.get("candidates")
    candidates: list[dict[str, object]] = []
    if isinstance(raw_candidates, list):
        for raw_candidate in cast(list[object], raw_candidates):
            normalized = _normalize_object_dict(raw_candidate)
            if normalized is not None:
                candidates.append(normalized)

    response_status: Literal["saved", "already_exists", "needs_clarification", "failed"]
    if backend_status in {"created", "merged", "reactivated"}:
        response_status = "saved"
    elif backend_status == "already_exists":
        response_status = "already_exists"
    elif backend_status == "needs_clarification":
        response_status = "needs_clarification"
    else:
        response_status = "failed"
        if message is None:
            message = "Unexpected response status from bucket add."

    return ShareArticleResponse(
        status=response_status,
        request_id=tool_response.request_id,
        backend_status=backend_status,
        bucket_item_id=bucket_item_id,
        title=title,
        canonical_url=canonical_url,
        message=message,
        candidates=candidates,
        error=None if response_status != "failed" else tool_response.error,
    )


def _to_sync_status_response(state: ArticleWallabagState) -> ArticleSyncStatusResponse:
    if state.sync_status not in {"pending", "synced", "failed"}:
        status_value: Literal["pending", "synced", "failed", "missing"] = "failed"
    else:
        status_value = cast(
            Literal["pending", "synced", "failed", "missing"],
            state.sync_status,
        )
    return ArticleSyncStatusResponse(
        bucket_item_id=state.bucket_item_id,
        sync_status=status_value,
        read_state=cast(Literal["unread", "read"] | None, state.read_state),
        wallabag_entry_id=state.wallabag_entry_id,
        wallabag_entry_url=state.wallabag_entry_url,
        sync_error=state.sync_error,
        synced_at=state.synced_at,
        last_push_attempt_at=state.last_push_attempt_at,
        last_pull_attempt_at=state.last_pull_attempt_at,
        updated_at=state.updated_at,
    )


def _normalize_object_dict(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    raw_dict = cast(dict[object, object], value)
    normalized: dict[str, object] = {}
    for key, item_value in raw_dict.items():
        if isinstance(key, str):
            normalized[key] = item_value
    return normalized


def _resolve_client_ip(http_request: Request) -> str:
    forwarded_for = http_request.headers.get("X-Forwarded-For", "")
    if forwarded_for:
        first = forwarded_for.split(",")[0].strip()
        client_ip = first or "unknown"
    elif http_request.client is not None and http_request.client.host:
        client_ip = http_request.client.host
    else:
        client_ip = "unknown"
    return client_ip
