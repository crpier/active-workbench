from __future__ import annotations

import secrets
from typing import Annotated, Literal, cast
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from structlog.contextvars import bind_contextvars, reset_contextvars

from backend.app.config import AppSettings
from backend.app.dependencies import (
    get_dispatcher,
    get_mobile_api_key_repository,
    get_mobile_share_rate_limiter,
    get_settings,
)
from backend.app.models.mobile_contracts import ShareArticleRequest, ShareArticleResponse
from backend.app.models.tool_contracts import (
    ToolCatalogEntry,
    ToolContext,
    ToolName,
    ToolRequest,
    ToolResponse,
)
from backend.app.repositories.mobile_api_key_repository import MobileApiKeyRepository
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
    settings: Annotated[AppSettings, Depends(get_settings)],
    mobile_key_repository: Annotated[
        MobileApiKeyRepository,
        Depends(get_mobile_api_key_repository),
    ],
    rate_limiter: Annotated[SlidingWindowRateLimiter, Depends(get_mobile_share_rate_limiter)],
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> ShareArticleResponse:
    client_ip = _resolve_client_ip(http_request)
    auth_principal = _authenticate_mobile_request(
        authorization=authorization,
        settings=settings,
        mobile_key_repository=mobile_key_repository,
        client_ip=client_ip,
    )
    client_key = _resolve_client_key(client_ip=client_ip, auth_principal=auth_principal)
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


def _normalize_object_dict(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    raw_dict = cast(dict[object, object], value)
    normalized: dict[str, object] = {}
    for key, item_value in raw_dict.items():
        if isinstance(key, str):
            normalized[key] = item_value
    return normalized


def _extract_bearer_token(authorization: str | None) -> str | None:
    if authorization is None:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.strip().lower() != "bearer":
        return None
    normalized = token.strip()
    return normalized or None


def _authenticate_mobile_request(
    *,
    authorization: str | None,
    settings: AppSettings,
    mobile_key_repository: MobileApiKeyRepository,
    client_ip: str,
) -> str | None:
    raw_token = _extract_bearer_token(authorization)
    has_active_device_keys = mobile_key_repository.has_active_keys()
    legacy_api_key = settings.mobile_api_key
    auth_required = has_active_device_keys or legacy_api_key is not None

    if not auth_required:
        if raw_token is not None:
            _raise_mobile_unauthorized()
        return None
    if raw_token is None:
        _raise_mobile_unauthorized()

    parsed_device_token = _parse_device_token(raw_token)
    if parsed_device_token is not None:
        key_id, secret = parsed_device_token
        if mobile_key_repository.verify_active_token(key_id=key_id, secret=secret):
            mobile_key_repository.mark_used(key_id=key_id, client_ip=client_ip)
            return f"device:{key_id}"

    if legacy_api_key is not None and secrets.compare_digest(legacy_api_key, raw_token):
        return "legacy"

    _raise_mobile_unauthorized()


def _raise_mobile_unauthorized() -> None:
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Unauthorized mobile share request.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _parse_device_token(token: str) -> tuple[str, str] | None:
    key_id, separator, secret = token.partition(".")
    if separator != ".":
        return None
    normalized_key_id = key_id.strip()
    normalized_secret = secret.strip()
    if not normalized_key_id.startswith("mkey_"):
        return None
    if len(normalized_secret) < 16:
        return None
    return normalized_key_id, normalized_secret


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


def _resolve_client_key(*, client_ip: str, auth_principal: str | None) -> str:
    if auth_principal is None:
        return client_ip
    return f"{client_ip}:{auth_principal}"
