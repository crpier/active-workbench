from __future__ import annotations

from contextlib import suppress
from typing import Annotated, Literal, cast
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from structlog.contextvars import bind_contextvars, reset_contextvars

from backend.app.dependencies import (
    get_article_pipeline_service,
    get_dispatcher,
    get_mobile_share_rate_limiter,
)
from backend.app.models.article_contracts import (
    ArticleCaptureRequest,
    ArticleCaptureResponse,
    ArticleDeleteResponse,
    ArticleListResponse,
    ArticleReadableResponse,
    ArticleReadStateUpdateRequest,
    ArticleReadStateUpdateResponse,
    ArticleRetryResponse,
    ArticleSummary,
)
from backend.app.models.mobile_contracts import ShareArticleRequest, ShareArticleResponse
from backend.app.models.tool_contracts import (
    ToolCatalogEntry,
    ToolContext,
    ToolName,
    ToolRequest,
    ToolResponse,
)
from backend.app.repositories.article_repository import ArticleRecord
from backend.app.services.article_pipeline_service import ArticlePipelineService
from backend.app.services.rate_limiter import SlidingWindowRateLimiter
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
    article_pipeline_service: Annotated[
        ArticlePipelineService, Depends(get_article_pipeline_service)
    ],
    rate_limiter: Annotated[SlidingWindowRateLimiter, Depends(get_mobile_share_rate_limiter)],
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

    payload: dict[str, object] = {
        "domain": "article",
        "url": request.url,
        "allow_unresolved": True,
    }
    if request.shared_text is not None:
        payload["notes"] = request.shared_text
    if request.source_app is not None:
        payload["source_refs"] = [{"type": "mobile_share_app", "id": request.source_app}]

    tool_response = _handle_tool(
        "bucket.item.add",
        ToolRequest(
            tool="bucket.item.add",
            request_id=uuid4(),
            idempotency_key=request.idempotency_key,
            payload=payload,
            context=ToolContext(
                timezone=request.timezone,
                session_id=request.session_id,
            ),
        ),
        dispatcher,
    )

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

    article_id: str | None = None
    article_status: str | None = None
    readable_available = False
    if response_status in {"saved", "already_exists"} and bucket_item_id is not None and canonical_url:
        try:
            captured = article_pipeline_service.capture_article(
                url=canonical_url,
                bucket_item_id=bucket_item_id,
                source="android_share",
                shared_text=request.shared_text,
            )
        except ValueError:
            message = message or "Saved bucket entry but article URL normalization failed."
        except Exception:
            message = message or "Saved bucket entry but article pipeline capture failed."
        else:
            article_id = captured.article.article_id
            article_status = captured.article.status
            readable_available = captured.article.status == "readable"

    typed_article_status: Literal["captured", "processing", "readable", "failed"] | None = None
    if article_status in {"captured", "processing", "readable", "failed"}:
        typed_article_status = cast(
            Literal["captured", "processing", "readable", "failed"],
            article_status,
        )

    return ShareArticleResponse(
        status=response_status,
        request_id=tool_response.request_id,
        backend_status=backend_status,
        article_id=article_id,
        article_status=typed_article_status,
        readable_available=readable_available,
        bucket_item_id=bucket_item_id,
        title=title,
        canonical_url=canonical_url,
        message=message,
        candidates=candidates,
        error=None if response_status != "failed" else tool_response.error,
    )


@router.post(
    "/articles/capture",
    response_model=ArticleCaptureResponse,
    tags=["articles"],
    operation_id="article_capture",
)
def article_capture(
    request: ArticleCaptureRequest,
    dispatcher: Annotated[ToolDispatcher, Depends(get_dispatcher)],
    article_pipeline_service: Annotated[
        ArticlePipelineService, Depends(get_article_pipeline_service)
    ],
) -> ArticleCaptureResponse:
    tool_response = _handle_tool(
        "bucket.item.add",
        ToolRequest(
            tool="bucket.item.add",
            request_id=uuid4(),
            idempotency_key=request.idempotency_key,
            payload={
                "domain": "article",
                "url": request.url,
                "notes": request.shared_text,
                "allow_unresolved": True,
            },
            context=ToolContext(
                timezone=request.timezone,
                session_id=request.session_id,
            ),
        ),
        dispatcher,
    )
    if not tool_response.ok:
        return ArticleCaptureResponse(
            status="failed",
            request_id=tool_response.request_id,
            message=(
                tool_response.error.message
                if tool_response.error is not None
                else "Article capture failed."
            ),
            error=tool_response.error,
        )

    result: dict[str, object] = {
        key: cast(object, value) for key, value in tool_response.result.items()
    }
    raw_backend_status = result.get("status")
    backend_status = raw_backend_status if isinstance(raw_backend_status, str) else None
    bucket_item_value = _normalize_object_dict(result.get("bucket_item")) or {}
    raw_item_id = bucket_item_value.get("item_id")
    bucket_item_id = raw_item_id if isinstance(raw_item_id, str) else None
    raw_title = bucket_item_value.get("title")
    title = raw_title if isinstance(raw_title, str) else None
    raw_external_url = bucket_item_value.get("external_url")
    canonical_url = raw_external_url if isinstance(raw_external_url, str) else None

    if bucket_item_id is None or canonical_url is None:
        return ArticleCaptureResponse(
            status="failed",
            request_id=tool_response.request_id,
            backend_status=backend_status,
            message="Bucket add completed but article identifiers were missing.",
        )

    try:
        captured = article_pipeline_service.capture_article(
            url=canonical_url,
            bucket_item_id=bucket_item_id,
            source=request.source,
            shared_text=request.shared_text,
        )
    except ValueError as exc:
        return ArticleCaptureResponse(
            status="failed",
            request_id=tool_response.request_id,
            backend_status=backend_status,
            message=str(exc),
        )

    response_status: Literal["saved", "already_exists", "failed"]
    if captured.deduped or backend_status == "already_exists":
        response_status = "already_exists"
    else:
        response_status = "saved"

    returned_article_status = cast(
        Literal["captured", "processing", "readable", "failed"],
        captured.article.status,
    )
    readable_available = captured.article.status == "readable"
    if request.process_now and response_status in {"saved", "already_exists"}:
        with suppress(Exception):
            article_pipeline_service.process_due_jobs(limit=1)
        refreshed = article_pipeline_service.get_article(captured.article.article_id)
        if refreshed is not None:
            returned_article_status = cast(
                Literal["captured", "processing", "readable", "failed"],
                refreshed.status,
            )
            readable_available = refreshed.status == "readable"

    return ArticleCaptureResponse(
        status=response_status,
        request_id=tool_response.request_id,
        backend_status=backend_status,
        article_id=captured.article.article_id,
        article_status=returned_article_status,
        readable_available=readable_available,
        bucket_item_id=bucket_item_id,
        title=title,
        canonical_url=canonical_url,
        message=None,
        error=None,
    )


@router.get(
    "/articles",
    response_model=ArticleListResponse,
    tags=["articles"],
    operation_id="article_list",
)
def article_list(
    article_pipeline_service: Annotated[
        ArticlePipelineService, Depends(get_article_pipeline_service)
    ],
    status_filter: str | None = Query(default=None, alias="status"),
    read_state_filter: str | None = Query(default=None, alias="read_state"),
    domain_host: str | None = Query(default=None),
    limit: int = Query(default=30, ge=1, le=200),
    cursor: int = Query(default=0, ge=0),
) -> ArticleListResponse:
    statuses: set[str] = (
        {part.strip().lower() for part in status_filter.split(",") if part.strip()}
        if isinstance(status_filter, str)
        else set()
    )
    read_states: set[str] = (
        {part.strip().lower() for part in read_state_filter.split(",") if part.strip()}
        if isinstance(read_state_filter, str)
        else set()
    )
    articles = article_pipeline_service.list_articles(
        statuses=statuses or None,
        read_states=read_states or None,
        domain_host=domain_host,
        limit=limit,
        cursor=cursor,
    )
    next_cursor = cursor + len(articles) if len(articles) == limit else None
    return ArticleListResponse(
        count=len(articles),
        items=[_article_summary_payload(article) for article in articles],
        cursor=cursor,
        next_cursor=next_cursor,
    )


@router.get("/articles/web", include_in_schema=False)
def article_web_legacy_redirect(request: Request) -> RedirectResponse:
    destination = "/app/articles"
    if request.url.query:
        destination = f"{destination}?{request.url.query}"
    return RedirectResponse(url=destination, status_code=status.HTTP_308_PERMANENT_REDIRECT)


@router.get("/articles/web/{article_id}", include_in_schema=False)
def article_web_legacy_reader_redirect(
    request: Request,
    article_id: str = Path(pattern=r"^article_[A-Za-z0-9]+$"),
) -> RedirectResponse:
    destination = f"/app/articles/{article_id}"
    if request.url.query:
        destination = f"{destination}?{request.url.query}"
    return RedirectResponse(url=destination, status_code=status.HTTP_308_PERMANENT_REDIRECT)


@router.get(
    "/articles/{article_id}",
    response_model=ArticleSummary,
    tags=["articles"],
    operation_id="article_get",
)
def article_get(
    article_pipeline_service: Annotated[
        ArticlePipelineService, Depends(get_article_pipeline_service)
    ],
    article_id: str = Path(pattern=r"^article_[A-Za-z0-9]+$"),
) -> ArticleSummary:
    article = article_pipeline_service.get_article(article_id)
    if article is None:
        raise HTTPException(status_code=404, detail="Article not found.")
    return _article_summary_payload(article)


@router.get(
    "/articles/{article_id}/readable",
    response_model=ArticleReadableResponse,
    tags=["articles"],
    operation_id="article_readable_get",
)
def article_readable_get(
    article_pipeline_service: Annotated[
        ArticlePipelineService, Depends(get_article_pipeline_service)
    ],
    article_id: str = Path(pattern=r"^article_[A-Za-z0-9]+$"),
) -> ArticleReadableResponse:
    readable = article_pipeline_service.get_readable(article_id=article_id)
    if readable is None:
        raise HTTPException(status_code=404, detail="Article not found.")
    return ArticleReadableResponse(
        article=_article_summary_payload(readable.article),
        source_markdown=readable.source_markdown,
        llm_markdown=readable.llm_markdown,
        default_markdown=readable.default_markdown,
    )


@router.post(
    "/articles/{article_id}/retry",
    response_model=ArticleRetryResponse,
    tags=["articles"],
    operation_id="article_retry",
)
def article_retry(
    article_pipeline_service: Annotated[
        ArticlePipelineService, Depends(get_article_pipeline_service)
    ],
    article_id: str = Path(pattern=r"^article_[A-Za-z0-9]+$"),
) -> ArticleRetryResponse:
    article = article_pipeline_service.retry_article(article_id=article_id)
    if article is None:
        raise HTTPException(status_code=404, detail="Article not found.")
    return ArticleRetryResponse(
        status="queued",
        article_id=article.article_id,
        article_status=cast(Literal["captured", "processing", "readable", "failed"], article.status),
    )


@router.patch(
    "/articles/{article_id}/read-state",
    response_model=ArticleReadStateUpdateResponse,
    tags=["articles"],
    operation_id="article_read_state_update",
)
def article_read_state_update(
    request: ArticleReadStateUpdateRequest,
    article_pipeline_service: Annotated[
        ArticlePipelineService, Depends(get_article_pipeline_service)
    ],
    article_id: str = Path(pattern=r"^article_[A-Za-z0-9]+$"),
) -> ArticleReadStateUpdateResponse:
    updated = article_pipeline_service.update_read_state(
        article_id=article_id,
        read_state=request.read_state,
        progress_percent=request.progress_percent,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Article not found.")
    return ArticleReadStateUpdateResponse(
        status="updated",
        article=_article_summary_payload(updated),
    )


@router.delete(
    "/articles/{article_id}",
    response_model=ArticleDeleteResponse,
    tags=["articles"],
    operation_id="article_delete",
)
def article_delete(
    article_pipeline_service: Annotated[
        ArticlePipelineService, Depends(get_article_pipeline_service)
    ],
    article_id: str = Path(pattern=r"^article_[A-Za-z0-9]+$"),
) -> ArticleDeleteResponse:
    deleted = article_pipeline_service.delete_article(article_id=article_id)
    if deleted is None:
        raise HTTPException(status_code=404, detail="Article not found.")
    return ArticleDeleteResponse(status="deleted", article_id=deleted.article_id)


def _normalize_object_dict(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    raw_dict = cast(dict[object, object], value)
    normalized: dict[str, object] = {}
    for key, item_value in raw_dict.items():
        if isinstance(key, str):
            normalized[key] = item_value
    return normalized


def _article_summary_payload(article: ArticleRecord) -> ArticleSummary:
    return ArticleSummary(
        article_id=article.article_id,
        bucket_item_id=article.bucket_item_id,
        source_url=article.source_url,
        canonical_url=article.canonical_url,
        title=article.title,
        author=article.author,
        site_name=article.site_name,
        published_at=article.published_at,
        status=cast(Literal["captured", "processing", "readable", "failed"], article.status),
        read_state=cast(Literal["unread", "in_progress", "read"], article.read_state),
        estimated_read_minutes=article.estimated_read_minutes,
        progress_percent=article.progress_percent,
        extraction_method=article.extraction_method,
        llm_polished=article.llm_polished,
        captured_at=article.captured_at.isoformat(),
        updated_at=article.updated_at.isoformat(),
        last_error_code=article.last_error_code,
        last_error_message=article.last_error_message,
    )


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
