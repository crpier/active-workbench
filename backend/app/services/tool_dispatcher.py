from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from time import perf_counter
from typing import Any, cast
from urllib.parse import parse_qs, urlparse
from uuid import UUID

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
from backend.app.repositories.bucket_repository import BucketItem, BucketRepository
from backend.app.repositories.idempotency_repository import IdempotencyRepository
from backend.app.repositories.memory_repository import MemoryRepository
from backend.app.repositories.youtube_quota_repository import YouTubeQuotaRepository
from backend.app.services.article_pipeline_service import ArticlePipelineService
from backend.app.services.bucket_metadata_service import (
    BucketAddResolution,
    BucketEnrichment,
    BucketMetadataService,
    BucketResolveCandidate,
)
from backend.app.services.youtube_service import (
    YouTubeRateLimitedError,
    YouTubeService,
    YouTubeServiceError,
)
from backend.app.telemetry import TelemetryClient

TOOL_DESCRIPTIONS: dict[ToolName, str] = {
    "youtube.likes.list_recent": (
        "List recently liked YouTube videos from local cache populated by background sync. "
        "Use payload.query/topic and optional payload.cursor/time_scope/cache_miss_policy hints."
    ),
    "youtube.likes.search_recent_content": (
        "Search recent liked videos by content (title/description/transcript) in a recent window."
    ),
    "youtube.transcript.get": (
        "Retrieve transcript for a YouTube video (cache-first, fetch fallback)."
    ),
    "bucket.item.add": (
        "Add or merge a structured bucket item. "
        "payload.domain (or payload.kind) is required. "
        "Movie/TV/Book/Music/Article add requests may return "
        "a clarification response before write; "
        "handle clarifications in normal chat and retry with provider confirmation fields."
    ),
    "bucket.item.update": "Update a structured bucket item.",
    "bucket.item.complete": (
        "Mark a bucket item as completed (hidden from active queries). "
        "Requires payload.item_id (or id/bucket_item_id alias)."
    ),
    "bucket.item.search": "Search bucket items with filters.",
    "bucket.item.recommend": "Recommend best-fit bucket items for the user's constraints.",
    "bucket.health.report": "Generate a bucket health report with stale items and quick wins.",
    "memory.create": "Create a memory record for future retrieval.",
    "memory.list": "List recently saved active memory records.",
    "memory.search": "Search active memory records by text and tags.",
    "memory.delete": "Delete a memory record by id.",
    "memory.undo": "Undo a memory write action.",
}

READY_FOR_USE_TOOLS: frozenset[ToolName] = frozenset(
    {
        "youtube.likes.list_recent",
        "youtube.likes.search_recent_content",
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
    }
)


class ToolDispatcher:
    def __init__(
        self,
        *,
        audit_repository: AuditRepository,
        idempotency_repository: IdempotencyRepository,
        memory_repository: MemoryRepository,
        bucket_repository: BucketRepository,
        bucket_metadata_service: BucketMetadataService,
        youtube_quota_repository: YouTubeQuotaRepository,
        youtube_service: YouTubeService,
        default_timezone: str,
        youtube_daily_quota_limit: int,
        youtube_quota_warning_percent: float,
        telemetry: TelemetryClient | None = None,
        article_pipeline_service: ArticlePipelineService | None = None,
        article_pipeline_max_jobs_per_tick: int = 5,
    ) -> None:
        self._audit_repository = audit_repository
        self._idempotency_repository = idempotency_repository
        self._memory_repository = memory_repository
        self._bucket_repository = bucket_repository
        self._bucket_metadata_service = bucket_metadata_service
        self._youtube_quota_repository = youtube_quota_repository
        self._youtube_service = youtube_service
        self._telemetry = telemetry if telemetry is not None else TelemetryClient.disabled()
        self._default_timezone = default_timezone
        self._youtube_daily_quota_limit = max(0, youtube_daily_quota_limit)
        bounded_warning_percent = min(1.0, max(0.0, youtube_quota_warning_percent))
        self._youtube_quota_warning_threshold = int(
            self._youtube_daily_quota_limit * bounded_warning_percent
        )
        self._article_pipeline_service = article_pipeline_service
        self._article_pipeline_max_jobs_per_tick = max(1, article_pipeline_max_jobs_per_tick)

    def list_tools(self) -> list[ToolCatalogEntry]:
        return [
            ToolCatalogEntry(
                name=name,
                description=description,
                write_operation=name in WRITE_TOOLS,
                ready_for_use=name in READY_FOR_USE_TOOLS,
                readiness_note=(
                    None
                    if name in READY_FOR_USE_TOOLS
                    else "Not ready for use yet. Keep this tool disabled for now."
                ),
            )
            for name, description in TOOL_DESCRIPTIONS.items()
        ]

    @property
    def youtube_service(self) -> YouTubeService:
        return self._youtube_service

    def run_due_jobs(self) -> None:
        if self._article_pipeline_service is None:
            return
        stats = self._article_pipeline_service.process_due_jobs(
            limit=self._article_pipeline_max_jobs_per_tick
        )
        if stats.attempted > 0:
            self._telemetry.emit(
                "article.jobs.processed",
                attempted=stats.attempted,
                succeeded=stats.succeeded,
                retried=stats.retried,
                failed=stats.failed,
            )

    def run_bucket_annotation_poll(self, *, limit: int = 20) -> dict[str, int]:
        candidates = self._bucket_repository.list_unannotated_active_items(limit=max(1, limit))
        attempted = 0
        annotated = 0
        pending = 0
        failed = 0

        for item in candidates:
            attempted += 1
            attempt_at = datetime.now(UTC).isoformat()
            enrichment = self._bucket_metadata_service.enrich(
                title=item.title,
                domain=item.domain,
                year=item.year,
                article_url=item.external_url,
            )

            metadata_updates: dict[str, Any] = {
                "annotation_last_attempt_at": attempt_at,
            }
            if enrichment.provider is None:
                metadata_updates["annotation_status"] = "pending"
                metadata_updates["annotation_error"] = "no_match"
                updated = self._bucket_repository.update_item(
                    item_id=item.item_id,
                    metadata=metadata_updates,
                )
                if updated is None:
                    failed += 1
                else:
                    pending += 1
                continue

            metadata_updates = _merge_dicts(metadata_updates, enrichment.metadata)
            metadata_updates["annotation_status"] = "annotated"
            metadata_updates["annotation_provider"] = enrichment.provider
            metadata_updates["annotation_updated_at"] = attempt_at
            metadata_updates.pop("annotation_error", None)

            updated = self._bucket_repository.update_item(
                item_id=item.item_id,
                year=enrichment.year if item.year is None else None,
                duration_minutes=(
                    enrichment.duration_minutes if item.duration_minutes is None else None
                ),
                rating=enrichment.rating if item.rating is None else None,
                popularity=enrichment.popularity if item.popularity is None else None,
                genres=enrichment.genres if not item.genres else None,
                tags=enrichment.tags if not item.tags else None,
                providers=enrichment.providers if not item.providers else None,
                metadata=metadata_updates,
                source_refs=enrichment.source_refs,
                canonical_id=enrichment.canonical_id if item.canonical_id is None else None,
                external_url=enrichment.external_url if item.external_url is None else None,
                confidence=enrichment.confidence if item.confidence is None else None,
            )
            if updated is None:
                failed += 1
                continue
            annotated += 1

        result = {
            "attempted": attempted,
            "annotated": annotated,
            "pending": pending,
            "failed": failed,
        }
        return result

    def execute(self, tool_name: ToolName, request: ToolRequest) -> ToolResponse:
        started_at = perf_counter()
        request_id = str(request.request_id)
        self._telemetry.emit(
            "tool.execute.start",
            tool_name=tool_name,
            request_id=request_id,
            write_operation=tool_name in WRITE_TOOLS,
            has_idempotency_key=request.idempotency_key is not None,
        )
        try:
            self.run_due_jobs()

            cached = self._load_idempotent_response(tool_name, request.idempotency_key)
            if cached is not None:
                self._telemetry.emit(
                    "tool.execute.finish",
                    tool_name=tool_name,
                    request_id=request_id,
                    duration_ms=int((perf_counter() - started_at) * 1000),
                    outcome="ok" if cached.ok else "error",
                    idempotency_cache_hit=True,
                )
                return cached

            response = self._execute_tool(tool_name, request)
            response = self._attach_audit_event(tool_name, request, response)
            self._store_idempotent_response(tool_name, request.idempotency_key, response)
            self._telemetry.emit(
                "tool.execute.finish",
                tool_name=tool_name,
                request_id=request_id,
                duration_ms=int((perf_counter() - started_at) * 1000),
                outcome="ok" if response.ok else "error",
                idempotency_cache_hit=False,
            )
            return response
        except Exception as exc:
            self._telemetry.emit(
                "tool.execute.error",
                tool_name=tool_name,
                request_id=request_id,
                duration_ms=int((perf_counter() - started_at) * 1000),
                error_type=type(exc).__name__,
            )
            raise

    def _execute_tool(self, tool_name: ToolName, request: ToolRequest) -> ToolResponse:
        if tool_name == "youtube.likes.list_recent":
            return self._handle_youtube_likes(request)
        if tool_name == "youtube.likes.search_recent_content":
            return self._handle_youtube_likes_search_recent_content(request)
        if tool_name == "youtube.transcript.get":
            return self._handle_youtube_transcript(request)
        if tool_name == "bucket.item.add":
            return self._handle_bucket_item_add(request)
        if tool_name == "bucket.item.update":
            return self._handle_bucket_item_update(request)
        if tool_name == "bucket.item.complete":
            return self._handle_bucket_item_complete(request)
        if tool_name == "bucket.item.search":
            return self._handle_bucket_item_search(request)
        if tool_name == "bucket.item.recommend":
            return self._handle_bucket_item_recommend(request)
        if tool_name == "bucket.health.report":
            return self._handle_bucket_health_report(request)
        if tool_name == "memory.create":
            return self._handle_memory_create(request)
        if tool_name == "memory.list":
            return self._handle_memory_list(request)
        if tool_name == "memory.search":
            return self._handle_memory_search(request)
        if tool_name == "memory.delete":
            return self._handle_memory_delete(request)
        if tool_name == "memory.undo":
            return self._handle_memory_undo(request)

        return self._placeholder_response(tool_name, request)

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

    def _handle_youtube_likes(self, request: ToolRequest) -> ToolResponse:
        requested_limit = _int_or_default(request.payload.get("limit"), default=5)
        applied_limit = max(1, min(100, requested_limit))
        raw_cursor = request.payload.get("cursor")
        if raw_cursor is None:
            raw_cursor = request.payload.get("offset")
        requested_cursor = _optional_int(raw_cursor)
        cursor = max(0, requested_cursor or 0)
        compact = _bool_or_default(request.payload.get("compact"), default=False)
        query = _payload_str(request.payload, "query") or _payload_str(request.payload, "topic")
        time_scope = _normalize_time_scope(request.payload.get("time_scope"))
        cache_miss_policy = _normalize_cache_miss_policy(request.payload.get("cache_miss_policy"))
        recent_probe_pages = max(
            1, min(3, _int_or_default(request.payload.get("recent_probe_pages"), default=1))
        )

        if cache_miss_policy is not None:
            probe_recent_on_miss = cache_miss_policy == "probe_recent"
            resolved_time_scope = time_scope
            resolved_cache_miss_policy = cache_miss_policy
        else:
            inferred_time_scope = (
                time_scope if time_scope != "auto" else _infer_query_time_scope(query)
            )
            resolved_time_scope = inferred_time_scope
            resolved_cache_miss_policy = (
                "probe_recent" if inferred_time_scope == "recent" else "none"
            )
            probe_recent_on_miss = resolved_cache_miss_policy == "probe_recent"

        try:
            likes_result = self._youtube_service.list_recent_cached_only_with_metadata(
                limit=applied_limit,
                query=query,
                cursor=cursor,
                probe_recent_on_miss=probe_recent_on_miss,
                recent_probe_pages=recent_probe_pages,
            )
        except YouTubeRateLimitedError as exc:
            error_response = _youtube_rate_limited_error_response(
                request_id=request.request_id,
                tool=request.tool,
                message=str(exc),
                scope=exc.scope,
                retry_after_seconds=exc.retry_after_seconds,
            )
            return self._attach_quota_snapshot(
                error_response,
                tool_name=request.tool,
                estimated_units_this_call=0,
            )
        except YouTubeServiceError as exc:
            error_response = _tool_error_response(
                request_id=request.request_id,
                tool=request.tool,
                code="youtube_unavailable",
                message=str(exc),
            )
            return self._attach_quota_snapshot(
                error_response,
                tool_name=request.tool,
                estimated_units_this_call=0,
            )

        if compact:
            payload_videos = [
                {
                    "video_id": item.video_id,
                    "title": item.title,
                    "liked_at": item.liked_at,
                    "video_published_at": item.video_published_at,
                    "channel_title": item.channel_title,
                    "duration_seconds": item.duration_seconds,
                    "topic_categories": list(item.topic_categories),
                    "tags": list(item.tags),
                }
                for item in likes_result.videos
            ]
        else:
            payload_videos = [
                {
                    "video_id": item.video_id,
                    "title": item.title,
                    "published_at": item.published_at,
                    "liked_at": item.liked_at,
                    "video_published_at": item.video_published_at,
                    "description": item.description,
                    "channel_id": item.channel_id,
                    "channel_title": item.channel_title,
                    "duration_seconds": item.duration_seconds,
                    "category_id": item.category_id,
                    "default_language": item.default_language,
                    "default_audio_language": item.default_audio_language,
                    "caption_available": item.caption_available,
                    "privacy_status": item.privacy_status,
                    "licensed_content": item.licensed_content,
                    "made_for_kids": item.made_for_kids,
                    "live_broadcast_content": item.live_broadcast_content,
                    "definition": item.definition,
                    "dimension": item.dimension,
                    "thumbnails": item.thumbnails or {},
                    "topic_categories": list(item.topic_categories),
                    "statistics_view_count": item.statistics_view_count,
                    "statistics_like_count": item.statistics_like_count,
                    "statistics_comment_count": item.statistics_comment_count,
                    "statistics_fetched_at": item.statistics_fetched_at,
                    "tags": list(item.tags),
                }
                for item in likes_result.videos
            ]

        provenance = [
            ProvenanceRef(type="youtube_video", id=item.video_id) for item in likes_result.videos
        ]
        response = ToolResponse(
            ok=True,
            request_id=request.request_id,
            result={
                "tool": request.tool,
                "status": "ok",
                "compact": compact,
                "videos": payload_videos,
                "requested_limit": requested_limit,
                "applied_limit": likes_result.applied_limit,
                "requested_cursor": cursor,
                "cursor": likes_result.cursor,
                "next_cursor": likes_result.next_cursor,
                "has_more": likes_result.has_more,
                "total_matches": likes_result.total_matches,
                "truncated": likes_result.has_more,
                "cache": {
                    "hit": likes_result.cache_hit,
                    "refreshed": likes_result.refreshed,
                    "miss": likes_result.cache_miss,
                    "time_scope": resolved_time_scope,
                    "miss_policy": resolved_cache_miss_policy,
                    "miss_policy_applied": likes_result.cache_miss
                    and likes_result.recent_probe_applied,
                    "recent_probe": {
                        "applied": likes_result.recent_probe_applied,
                        "pages_requested": recent_probe_pages
                        if resolved_cache_miss_policy == "probe_recent"
                        else 0,
                        "pages_used": likes_result.recent_probe_pages_used,
                    },
                },
            },
            provenance=provenance,
            error=None,
        )
        return self._attach_quota_snapshot(
            response,
            tool_name=request.tool,
            estimated_units_this_call=likes_result.estimated_api_units,
        )

    def _handle_youtube_transcript(self, request: ToolRequest) -> ToolResponse:
        raw_video = (
            _payload_str(request.payload, "video_id")
            or _payload_str(request.payload, "videoId")
            or _payload_str(request.payload, "id")
            or _payload_str(request.payload, "url")
            or _payload_str(request.payload, "video_url")
            or _payload_str(request.payload, "videoUrl")
        )
        explicit_video_requested = raw_video is not None
        video_id = _extract_youtube_video_id(raw_video) if explicit_video_requested else None

        if raw_video is not None and video_id is None:
            return _tool_error_response(
                request_id=request.request_id,
                tool=request.tool,
                code="invalid_input",
                message=(
                    "Could not extract a valid YouTube video ID from payload. "
                    "Provide payload.video_id or a valid YouTube URL."
                ),
            )

        if video_id is None:
            try:
                recent_result = self._youtube_service.list_recent_cached_only_with_metadata(
                    limit=1,
                    query=None,
                )
            except YouTubeServiceError as exc:
                error_response = _tool_error_response(
                    request_id=request.request_id,
                    tool=request.tool,
                    code="youtube_unavailable",
                    message=str(exc),
                )
                return self._attach_quota_snapshot(
                    error_response,
                    tool_name=request.tool,
                    estimated_units_this_call=0,
                )

            recent = recent_result.videos
            if not recent:
                error_response = _tool_error_response(
                    request_id=request.request_id,
                    tool=request.tool,
                    code="not_found",
                    message="No recently liked videos available",
                )
                return self._attach_quota_snapshot(
                    error_response,
                    tool_name=request.tool,
                    estimated_units_this_call=recent_result.estimated_api_units,
                )
            video_id = recent[0].video_id
            likes_units_used = recent_result.estimated_api_units
        else:
            likes_units_used = 0

        try:
            transcript_result = self._youtube_service.get_transcript_with_metadata(video_id)
        except YouTubeServiceError as exc:
            error_response = _tool_error_response(
                request_id=request.request_id,
                tool=request.tool,
                code="transcript_unavailable",
                message=str(exc),
            )
            return self._attach_quota_snapshot(
                error_response,
                tool_name=request.tool,
                estimated_units_this_call=likes_units_used
                + self._estimate_transcript_error_units(
                    explicit_video_requested=explicit_video_requested
                ),
            )
        transcript = transcript_result.transcript

        response = ToolResponse(
            ok=True,
            request_id=request.request_id,
            result={
                "tool": request.tool,
                "status": "ok",
                "video_id": transcript.video_id,
                "title": transcript.title,
                "transcript": transcript.transcript,
                "source": transcript.source,
                "segments": transcript.segments,
                "cache": {"hit": transcript_result.cache_hit},
            },
            provenance=[ProvenanceRef(type="youtube_video", id=transcript.video_id)],
            error=None,
        )
        return self._attach_quota_snapshot(
            response,
            tool_name=request.tool,
            estimated_units_this_call=likes_units_used + transcript_result.estimated_api_units,
        )

    def _handle_youtube_likes_search_recent_content(self, request: ToolRequest) -> ToolResponse:
        query = _payload_str(request.payload, "query") or _payload_str(request.payload, "topic")
        if query is None:
            return _tool_error_response(
                request_id=request.request_id,
                tool=request.tool,
                code="invalid_input",
                message="payload.query is required",
            )

        requested_window_days = _optional_int(request.payload.get("window_days"))
        window_days = (
            None if requested_window_days is None else max(1, min(30, requested_window_days))
        )
        limit = max(1, min(25, _int_or_default(request.payload.get("limit"), default=5)))
        recent_probe_pages = max(
            1, min(3, _int_or_default(request.payload.get("recent_probe_pages"), default=2))
        )
        cache_miss_policy = (
            _normalize_cache_miss_policy(request.payload.get("cache_miss_policy")) or "probe_recent"
        )
        probe_recent_on_miss = cache_miss_policy == "probe_recent"

        try:
            search_result = self._youtube_service.search_recent_content_with_metadata(
                query=query,
                window_days=window_days,
                limit=limit,
                probe_recent_on_miss=probe_recent_on_miss,
                recent_probe_pages=recent_probe_pages,
            )
        except YouTubeRateLimitedError as exc:
            error_response = _youtube_rate_limited_error_response(
                request_id=request.request_id,
                tool=request.tool,
                message=str(exc),
                scope=exc.scope,
                retry_after_seconds=exc.retry_after_seconds,
            )
            return self._attach_quota_snapshot(
                error_response,
                tool_name=request.tool,
                estimated_units_this_call=0,
            )
        except YouTubeServiceError as exc:
            error_response = _tool_error_response(
                request_id=request.request_id,
                tool=request.tool,
                code="youtube_unavailable",
                message=str(exc),
            )
            return self._attach_quota_snapshot(
                error_response,
                tool_name=request.tool,
                estimated_units_this_call=0,
            )

        matches = [
            {
                "video_id": match.video.video_id,
                "title": match.video.title,
                "liked_at": match.video.liked_at,
                "video_published_at": match.video.video_published_at,
                "score": match.score,
                "matched_in": list(match.matched_in),
                "snippet": match.snippet,
            }
            for match in search_result.matches
        ]
        response = ToolResponse(
            ok=True,
            request_id=request.request_id,
            result={
                "tool": request.tool,
                "status": "ok",
                "query": query,
                "window_days": window_days,
                "matches": matches,
                "coverage": {
                    "recent_videos_count": search_result.recent_videos_count,
                    "transcripts_available_count": search_result.transcripts_available_count,
                    "transcript_coverage_percent": search_result.transcript_coverage_percent,
                },
                "cache": {
                    "miss": search_result.cache_miss,
                    "miss_policy": cache_miss_policy,
                    "miss_policy_applied": search_result.cache_miss
                    and search_result.recent_probe_applied,
                    "recent_probe": {
                        "applied": search_result.recent_probe_applied,
                        "pages_requested": recent_probe_pages
                        if cache_miss_policy == "probe_recent"
                        else 0,
                        "pages_used": search_result.recent_probe_pages_used,
                    },
                },
            },
            provenance=[
                ProvenanceRef(type="youtube_video", id=match.video.video_id)
                for match in search_result.matches
            ],
            error=None,
        )
        return self._attach_quota_snapshot(
            response,
            tool_name=request.tool,
            estimated_units_this_call=search_result.estimated_api_units,
        )

    def _attach_quota_snapshot(
        self,
        response: ToolResponse,
        *,
        tool_name: ToolName,
        estimated_units_this_call: int,
    ) -> ToolResponse:
        snapshot = self._youtube_quota_repository.record_and_snapshot(
            tool_name=tool_name,
            estimated_units_this_call=estimated_units_this_call,
            daily_limit=self._youtube_daily_quota_limit,
            warning_threshold=self._youtube_quota_warning_threshold,
        )
        quota_payload: dict[str, Any] = {
            "date_utc": snapshot.date_utc,
            "estimated_units_this_call": snapshot.estimated_units_this_call,
            "estimated_units_today": snapshot.estimated_units_today,
            "estimated_calls_today": snapshot.estimated_calls_today,
            "daily_limit": snapshot.daily_limit,
            "warning_threshold": snapshot.warning_threshold,
            "warning": snapshot.warning,
        }

        if snapshot.warning and snapshot.daily_limit > 0:
            quota_payload["warning_message"] = (
                "Estimated YouTube API quota usage is above warning threshold "
                f"({snapshot.estimated_units_today}/{snapshot.daily_limit})."
            )

        result = dict(response.result)
        result["quota"] = quota_payload
        return response.model_copy(update={"result": result})

    def _estimate_likes_units(self, *, has_query: bool) -> int:
        if not self._youtube_service.is_oauth_mode:
            return 0
        # channels.list + playlistItems.list
        # (+ videos.list metadata enrichment when query is present)
        return 3 if has_query else 2

    def _estimate_transcript_error_units(self, *, explicit_video_requested: bool) -> int:
        if not self._youtube_service.is_oauth_mode:
            return 0

        _ = explicit_video_requested
        return 1

    def _handle_bucket_item_add(self, request: ToolRequest) -> ToolResponse:
        domain = _payload_str(request.payload, "domain") or _payload_str(request.payload, "kind")
        if domain is None:
            return _tool_error_response(
                request_id=request.request_id,
                tool=request.tool,
                code="invalid_input",
                message="payload.domain (or payload.kind) is required",
            )
        external_url = _payload_str(request.payload, "external_url") or _payload_str(
            request.payload, "url"
        )
        media_domain = _normalize_bucket_media_domain(domain)
        title = (
            _payload_str(request.payload, "title")
            or _payload_str(request.payload, "name")
            or _payload_str(request.payload, "item")
        )
        title_provided = title is not None
        if title is None and media_domain == "article":
            title = _article_title_from_url(external_url)
        if title is None:
            return _tool_error_response(
                request_id=request.request_id,
                tool=request.tool,
                code="invalid_input",
                message="payload.title (or payload.name/payload.item) is required",
            )

        notes = (
            _payload_str(request.payload, "notes")
            or _payload_str(request.payload, "body")
            or _payload_str(request.payload, "description")
            or ""
        )
        year = _optional_int(request.payload.get("year"))
        duration_minutes = _optional_int(
            request.payload.get("duration_minutes") or request.payload.get("duration")
        )
        rating = _optional_float(request.payload.get("rating") or request.payload.get("score"))
        popularity = _optional_float(request.payload.get("popularity"))
        genres = _payload_str_list(request.payload.get("genres") or request.payload.get("genre"))
        tags = _payload_str_list(request.payload.get("tags") or request.payload.get("tag"))
        providers = _payload_str_list(
            request.payload.get("providers")
            or request.payload.get("provider")
            or request.payload.get("platforms")
        )
        canonical_id = _payload_str(request.payload, "canonical_id")
        confidence = _optional_float(request.payload.get("confidence"))
        metadata = _payload_dict(request.payload.get("metadata"))
        source_refs = _extract_source_refs(request.payload)
        auto_enrich = _bool_or_default(request.payload.get("auto_enrich"), default=False)
        allow_unresolved = _bool_or_default(request.payload.get("allow_unresolved"), default=False)

        local_match = self._bucket_repository.find_confident_active_match(
            title=title,
            domain=domain,
            year=year,
            canonical_id=canonical_id,
        )
        if local_match is not None:
            result: dict[str, Any] = {
                "tool": request.tool,
                "status": "already_exists",
                "bucket_item": _bucket_item_payload(local_match),
                "write_performed": False,
                "enriched": False,
                "enrichment_provider": None,
                "resolution_status": "local_duplicate",
                "resolution_reason": "local_active_match",
                "selected_candidate": None,
            }
            provenance = [ProvenanceRef(type="bucket_item", id=local_match.item_id)]
            provenance.extend(_source_ref_provenance(local_match.source_refs))
            return ToolResponse(
                ok=True,
                request_id=request.request_id,
                result=result,
                provenance=provenance,
                error=None,
            )

        tmdb_id = _payload_tmdb_id(
            request.payload.get("tmdb_id"),
            canonical_id=canonical_id,
        )
        bookwyrm_key = _payload_bookwyrm_key(
            request.payload.get("bookwyrm_key"),
            canonical_id=canonical_id,
        )
        musicbrainz_release_group_id = _payload_musicbrainz_release_group_id(
            request.payload.get("musicbrainz_release_group_id"),
            canonical_id=canonical_id,
        )
        music_artist_hint = _payload_str(request.payload, "artist") or _extract_music_artist_hint(
            title=title,
            notes=notes,
            domain=domain,
        )

        enrichment = None
        add_resolution: BucketAddResolution | None = None
        if media_domain is not None:
            add_resolution = self._bucket_metadata_service.resolve_for_bucket_add(
                title=title,
                domain=domain,
                year=year,
                article_url=external_url,
                artist_hint=music_artist_hint,
                tmdb_id=tmdb_id,
                bookwyrm_key=bookwyrm_key,
                musicbrainz_release_group_id=musicbrainz_release_group_id,
                max_candidates=5,
            )
            self._telemetry.emit(
                "bucket.item.add.resolve",
                request_id=str(request.request_id),
                domain=domain,
                status=add_resolution.status,
                reason=add_resolution.reason,
                candidates=len(add_resolution.candidates),
                tmdb_id=tmdb_id,
                bookwyrm_key=bookwyrm_key,
                musicbrainz_release_group_id=musicbrainz_release_group_id,
                music_artist_hint=music_artist_hint,
                article_url_provided=external_url is not None,
            )
            if (
                add_resolution.status in {"ambiguous", "no_match", "rate_limited"}
                and not allow_unresolved
            ):
                candidates = [
                    _bucket_resolve_candidate_payload(c) for c in add_resolution.candidates
                ]
                selected_candidate = (
                    _bucket_resolve_candidate_payload(add_resolution.selected_candidate)
                    if add_resolution.selected_candidate is not None
                    else None
                )
                result: dict[str, Any] = {
                    "tool": request.tool,
                    "status": "needs_clarification",
                    "write_performed": False,
                    "resolution_status": add_resolution.status,
                    "resolution_reason": add_resolution.reason,
                    "message": _bucket_add_resolution_message(add_resolution),
                    "follow_up_mode": "chat",
                    "assistant_follow_up": _bucket_add_follow_up_instruction(add_resolution),
                    "candidates": candidates,
                    "selected_candidate": selected_candidate,
                    "retry_after_seconds": add_resolution.retry_after_seconds,
                }
                provenance: list[ProvenanceRef] = []
                for candidate in add_resolution.candidates[:5]:
                    provenance.append(ProvenanceRef(type="external_api", id=candidate.canonical_id))
                return ToolResponse(
                    ok=True,
                    request_id=request.request_id,
                    result=result,
                    provenance=provenance,
                    error=None,
                )
            if add_resolution.status == "resolved":
                enrichment = add_resolution.enrichment
                if add_resolution.selected_candidate is not None:
                    canonical_id = canonical_id or add_resolution.selected_candidate.canonical_id
                    if year is None:
                        year = add_resolution.selected_candidate.year
                if not title_provided and enrichment is not None:
                    title = _title_from_article_enrichment(enrichment, fallback=title)
            elif auto_enrich:
                enrichment = self._bucket_metadata_service.enrich(
                    title=title,
                    domain=domain,
                    year=year,
                    article_url=external_url,
                )
        elif auto_enrich:
            enrichment = self._bucket_metadata_service.enrich(
                title=title,
                domain=domain,
                year=year,
                article_url=external_url,
            )

        if enrichment is not None:
            year = year if year is not None else enrichment.year
            duration_minutes = (
                duration_minutes if duration_minutes is not None else enrichment.duration_minutes
            )
            rating = rating if rating is not None else enrichment.rating
            popularity = popularity if popularity is not None else enrichment.popularity
            if not genres:
                genres = list(enrichment.genres)
            if not tags:
                tags = list(enrichment.tags)
            if not providers:
                providers = list(enrichment.providers)
            canonical_id = canonical_id or enrichment.canonical_id
            if media_domain == "article" and enrichment.external_url is not None:
                external_url = enrichment.external_url
            else:
                external_url = external_url or enrichment.external_url
            confidence = confidence if confidence is not None else enrichment.confidence
            metadata = _merge_dicts(metadata, enrichment.metadata)
            source_refs = _merge_source_refs(source_refs, enrichment.source_refs)

        item, action = self._bucket_repository.create_or_merge_item(
            title=title,
            domain=domain,
            notes=notes,
            year=year,
            duration_minutes=duration_minutes,
            rating=rating,
            popularity=popularity,
            genres=genres,
            tags=tags,
            providers=providers,
            metadata=metadata,
            source_refs=source_refs,
            canonical_id=canonical_id,
            external_url=external_url,
            confidence=confidence,
        )

        refreshed_item = self._bucket_repository.get_item(item.item_id)
        if refreshed_item is None:
            refreshed_item = item

        article_capture_payload: dict[str, Any] | None = None
        if (
            self._article_pipeline_service is not None
            and media_domain == "article"
            and refreshed_item.external_url is not None
        ):
            try:
                article_capture = self._article_pipeline_service.capture_article(
                    url=refreshed_item.external_url,
                    bucket_item_id=refreshed_item.item_id,
                    source="bucket_tool",
                    shared_text=notes,
                )
            except ValueError as exc:
                self._telemetry.emit(
                    "article.capture.invalid_input",
                    request_id=str(request.request_id),
                    reason=str(exc),
                )
            except Exception as exc:
                self._telemetry.emit(
                    "article.capture.error",
                    request_id=str(request.request_id),
                    error_type=type(exc).__name__,
                )
            else:
                refreshed_after_capture = self._bucket_repository.get_item(refreshed_item.item_id)
                if refreshed_after_capture is not None:
                    refreshed_item = refreshed_after_capture
                article_capture_payload = {
                    "article_id": article_capture.article.article_id,
                    "article_status": article_capture.article.status,
                    "readable_available": article_capture.article.status == "readable",
                    "job_status": article_capture.job_status,
                    "deduped": article_capture.deduped,
                }

        result: dict[str, Any] = {
            "tool": request.tool,
            "status": action,
            "bucket_item": _bucket_item_payload(refreshed_item),
            "write_performed": action in {"created", "merged", "reactivated"},
            "enriched": enrichment is not None and enrichment.provider is not None,
            "enrichment_provider": enrichment.provider if enrichment is not None else None,
            "resolution_status": add_resolution.status if add_resolution is not None else None,
            "resolution_reason": add_resolution.reason if add_resolution is not None else None,
            "selected_candidate": (
                _bucket_resolve_candidate_payload(add_resolution.selected_candidate)
                if add_resolution is not None and add_resolution.selected_candidate is not None
                else None
            ),
        }
        if article_capture_payload is not None:
            result["article"] = article_capture_payload

        provenance = [ProvenanceRef(type="bucket_item", id=refreshed_item.item_id)]
        provenance.extend(_source_ref_provenance(refreshed_item.source_refs))

        return ToolResponse(
            ok=True,
            request_id=request.request_id,
            result=result,
            provenance=provenance,
            error=None,
        )

    def _handle_bucket_item_update(self, request: ToolRequest) -> ToolResponse:
        item_id = _payload_str(request.payload, "item_id") or _payload_str(request.payload, "id")
        if item_id is None:
            return _tool_error_response(
                request_id=request.request_id,
                tool=request.tool,
                code="invalid_input",
                message="payload.item_id is required",
            )

        metadata = (
            _payload_dict(request.payload.get("metadata"))
            if "metadata" in request.payload
            else None
        )
        source_refs = (
            _extract_source_refs(request.payload) if "source_refs" in request.payload else None
        )
        updated = self._bucket_repository.update_item(
            item_id=item_id,
            title=_payload_str(request.payload, "title"),
            domain=_payload_str(request.payload, "domain") or _payload_str(request.payload, "kind"),
            notes=_payload_str(request.payload, "notes")
            or _payload_str(request.payload, "body")
            or _payload_str(request.payload, "description"),
            year=_optional_int(request.payload.get("year")),
            duration_minutes=_optional_int(
                request.payload.get("duration_minutes") or request.payload.get("duration")
            ),
            rating=_optional_float(request.payload.get("rating") or request.payload.get("score")),
            popularity=_optional_float(request.payload.get("popularity")),
            genres=_payload_optional_str_list(
                request.payload.get("genres") or request.payload.get("genre")
            ),
            tags=_payload_optional_str_list(
                request.payload.get("tags") or request.payload.get("tag")
            ),
            providers=_payload_optional_str_list(
                request.payload.get("providers")
                or request.payload.get("provider")
                or request.payload.get("platforms")
            ),
            metadata=metadata,
            source_refs=source_refs,
            canonical_id=_payload_str(request.payload, "canonical_id"),
            external_url=_payload_str(request.payload, "external_url")
            or _payload_str(request.payload, "url"),
            confidence=_optional_float(request.payload.get("confidence")),
        )
        if updated is None:
            return _tool_error_response(
                request_id=request.request_id,
                tool=request.tool,
                code="not_found",
                message=f"Bucket item was not found: {item_id}",
            )

        return ToolResponse(
            ok=True,
            request_id=request.request_id,
            result={
                "tool": request.tool,
                "status": "updated",
                "bucket_item": _bucket_item_payload(updated),
            },
            provenance=[ProvenanceRef(type="bucket_item", id=updated.item_id)],
            error=None,
        )

    def _handle_bucket_item_complete(self, request: ToolRequest) -> ToolResponse:
        item_id = (
            _payload_str(request.payload, "item_id")
            or _payload_str(request.payload, "id")
            or _payload_str(request.payload, "bucket_item_id")
        )
        if item_id is None:
            return _tool_error_response(
                request_id=request.request_id,
                tool=request.tool,
                code="invalid_input",
                message="payload.item_id is required",
            )

        completed = self._bucket_repository.mark_completed(item_id)
        if completed is None:
            return _tool_error_response(
                request_id=request.request_id,
                tool=request.tool,
                code="not_found",
                message=f"Bucket item was not found: {item_id}",
            )

        return ToolResponse(
            ok=True,
            request_id=request.request_id,
            result={
                "tool": request.tool,
                "status": "completed",
                "bucket_item": _bucket_item_payload(completed),
            },
            provenance=[ProvenanceRef(type="bucket_item", id=completed.item_id)],
            error=None,
        )

    def _handle_bucket_item_search(self, request: ToolRequest) -> ToolResponse:
        query = _payload_str(request.payload, "query")
        domain = _payload_str(request.payload, "domain") or _payload_str(request.payload, "kind")
        statuses = _bucket_statuses_from_payload(request.payload)
        min_duration = _optional_int(request.payload.get("min_duration_minutes"))
        max_duration = _optional_int(
            request.payload.get("max_duration_minutes") or request.payload.get("max_duration")
        )
        genres = _payload_str_list(request.payload.get("genres") or request.payload.get("genre"))
        min_rating = _optional_float(request.payload.get("min_rating"))
        limit = _int_or_default(request.payload.get("limit"), default=10)

        matches = self._bucket_repository.search_items(
            query=query,
            domain=domain,
            statuses=statuses,
            min_duration_minutes=min_duration,
            max_duration_minutes=max_duration,
            genres=genres,
            min_rating=min_rating,
            limit=max(1, min(100, limit)),
        )

        return ToolResponse(
            ok=True,
            request_id=request.request_id,
            result={
                "tool": request.tool,
                "status": "ok",
                "count": len(matches),
                "annotated_count": sum(1 for item in matches if item.is_annotated),
                "unannotated_count": sum(1 for item in matches if not item.is_annotated),
                "items": [_bucket_item_payload(item) for item in matches],
            },
            provenance=[
                ProvenanceRef(type="bucket_item", id=item.item_id) for item in matches[:30]
            ],
            error=None,
        )

    def _handle_bucket_item_recommend(self, request: ToolRequest) -> ToolResponse:
        query = _payload_str(request.payload, "query")
        domain = _payload_str(request.payload, "domain") or _payload_str(request.payload, "kind")
        statuses = _bucket_statuses_from_payload(request.payload)
        min_duration = _optional_int(request.payload.get("min_duration_minutes"))
        max_duration = _optional_int(
            request.payload.get("max_duration_minutes") or request.payload.get("max_duration")
        )
        target_duration = _optional_int(
            request.payload.get("target_duration_minutes")
            or request.payload.get("duration_minutes")
        )
        genres = _payload_str_list(request.payload.get("genres") or request.payload.get("genre"))
        min_rating = _optional_float(request.payload.get("min_rating"))
        limit = max(1, min(20, _int_or_default(request.payload.get("limit"), default=3)))

        candidates = self._bucket_repository.search_items(
            query=query,
            domain=domain,
            statuses=statuses,
            min_duration_minutes=min_duration,
            max_duration_minutes=max_duration,
            genres=genres,
            min_rating=min_rating,
            limit=100,
        )
        annotated_candidates = [item for item in candidates if item.is_annotated]
        skipped_unannotated_count = len(candidates) - len(annotated_candidates)

        ranked: list[dict[str, Any]] = []
        now = datetime.now(UTC)
        for candidate in annotated_candidates:
            score, reasons = _bucket_recommendation_score(
                candidate,
                now=now,
                query=query,
                domain=domain,
                genres=genres,
                target_duration_minutes=target_duration,
                min_duration_minutes=min_duration,
                max_duration_minutes=max_duration,
            )
            if score <= 0:
                continue
            ranked.append(
                {
                    "item": candidate,
                    "score": round(score, 4),
                    "reasons": reasons,
                }
            )

        ranked.sort(
            key=lambda entry: (
                float(entry["score"]),
                _waiting_days(cast(BucketItem, entry["item"]), now),
            ),
            reverse=True,
        )
        selected = ranked[:limit]
        selected_items = [cast(BucketItem, entry["item"]) for entry in selected]
        self._bucket_repository.track_recommendations([item.item_id for item in selected_items])

        recommendations: list[dict[str, Any]] = []
        for entry in selected:
            item = cast(BucketItem, entry["item"])
            recommendations.append(
                {
                    "bucket_item": _bucket_item_payload(item),
                    "score": entry["score"],
                    "reasons": entry["reasons"],
                }
            )

        return ToolResponse(
            ok=True,
            request_id=request.request_id,
            result={
                "tool": request.tool,
                "status": "ok",
                "count": len(recommendations),
                "skipped_unannotated_count": skipped_unannotated_count,
                "recommendations": recommendations,
            },
            provenance=[
                ProvenanceRef(type="bucket_item", id=item.item_id) for item in selected_items
            ],
            error=None,
        )

    def _handle_bucket_health_report(self, request: ToolRequest) -> ToolResponse:
        stale_after_days = max(
            1, _int_or_default(request.payload.get("stale_after_days"), default=60)
        )
        quick_win_max_minutes = max(
            15,
            _int_or_default(request.payload.get("quick_win_max_minutes"), default=100),
        )
        quick_win_min_rating = _optional_float(request.payload.get("quick_win_min_rating")) or 7.0
        limit = max(1, min(50, _int_or_default(request.payload.get("limit"), default=10)))

        report = self._bucket_repository.build_health_report(
            stale_after_days=stale_after_days,
            quick_win_max_minutes=quick_win_max_minutes,
            quick_win_min_rating=quick_win_min_rating,
            limit=limit,
        )
        return ToolResponse(
            ok=True,
            request_id=request.request_id,
            result={"tool": request.tool, "status": "ok", "report": report},
            error=None,
        )

    def _handle_memory_create(self, request: ToolRequest) -> ToolResponse:
        source_refs = _extract_source_refs(request.payload)
        content = _normalize_memory_content(request.payload, session_id=request.context.session_id)
        if content is None:
            return _tool_error_response(
                request_id=request.request_id,
                tool=request.tool,
                code="invalid_input",
                message=(
                    "Memory payload must include meaningful content. "
                    "Provide payload.text or payload.fact."
                ),
            )

        memory_id, undo_token = self._memory_repository.create_entry(content, source_refs)

        return ToolResponse(
            ok=True,
            request_id=request.request_id,
            result={
                "tool": request.tool,
                "status": "created",
                "memory_id": memory_id,
                "memory": content,
            },
            provenance=[ProvenanceRef(type="memory_entry", id=memory_id)],
            undo_token=undo_token,
            error=None,
        )

    def _handle_memory_list(self, request: ToolRequest) -> ToolResponse:
        limit = max(1, min(200, _int_or_default(request.payload.get("limit"), default=20)))
        entries = self._memory_repository.list_active_entries(limit=limit)
        return ToolResponse(
            ok=True,
            request_id=request.request_id,
            result={
                "tool": request.tool,
                "status": "ok",
                "count": len(entries),
                "entries": entries,
            },
            provenance=[
                ProvenanceRef(type="memory_entry", id=str(entry["id"])) for entry in entries
            ],
            error=None,
        )

    def _handle_memory_search(self, request: ToolRequest) -> ToolResponse:
        query = _payload_str(request.payload, "query")
        tags = _payload_str_list(request.payload.get("tags") or request.payload.get("tag"))
        limit = max(1, min(100, _int_or_default(request.payload.get("limit"), default=10)))
        scan_limit = max(limit, min(1000, _int_or_default(request.payload.get("scan_limit"), 300)))

        if query is None and not tags:
            return _tool_error_response(
                request_id=request.request_id,
                tool=request.tool,
                code="invalid_input",
                message="payload.query or payload.tags is required",
            )

        entries = self._memory_repository.search_active_entries(
            query=query,
            tags=tags,
            limit=limit,
            scan_limit=scan_limit,
        )
        return ToolResponse(
            ok=True,
            request_id=request.request_id,
            result={
                "tool": request.tool,
                "status": "ok",
                "count": len(entries),
                "query": query,
                "tags": tags,
                "entries": entries,
            },
            provenance=[
                ProvenanceRef(type="memory_entry", id=str(entry["id"])) for entry in entries
            ],
            error=None,
        )

    def _handle_memory_delete(self, request: ToolRequest) -> ToolResponse:
        memory_id = _payload_str(request.payload, "memory_id") or _payload_str(
            request.payload,
            "id",
        )
        if memory_id is None:
            return _tool_error_response(
                request_id=request.request_id,
                tool=request.tool,
                code="invalid_input",
                message="payload.memory_id is required",
            )

        deleted = self._memory_repository.delete_entry(memory_id)
        if not deleted:
            return _tool_error_response(
                request_id=request.request_id,
                tool=request.tool,
                code="not_found",
                message="Memory entry was not found or already deleted",
            )

        return ToolResponse(
            ok=True,
            request_id=request.request_id,
            result={"tool": request.tool, "status": "deleted", "memory_id": memory_id},
            provenance=[ProvenanceRef(type="memory_entry", id=memory_id)],
            error=None,
        )

    def _handle_memory_undo(self, request: ToolRequest) -> ToolResponse:
        undo_token = _payload_str(request.payload, "undo_token")
        if undo_token is None:
            return _tool_error_response(
                request_id=request.request_id,
                tool=request.tool,
                code="invalid_input",
                message="payload.undo_token is required",
            )

        memory_id = self._memory_repository.undo(undo_token)
        if memory_id is None:
            return _tool_error_response(
                request_id=request.request_id,
                tool=request.tool,
                code="not_found",
                message="Undo token was not found or already consumed",
            )

        return ToolResponse(
            ok=True,
            request_id=request.request_id,
            result={"tool": request.tool, "status": "undone", "memory_id": memory_id},
            provenance=[ProvenanceRef(type="memory_entry", id=memory_id)],
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
            error=None,
        )


def _tool_error_response(
    *,
    request_id: UUID,
    tool: ToolName,
    code: str,
    message: str,
    retryable: bool = False,
    result_updates: dict[str, Any] | None = None,
) -> ToolResponse:
    result: dict[str, Any] = {"tool": tool, "status": "failed"}
    if result_updates:
        result.update(result_updates)
    return ToolResponse(
        ok=False,
        request_id=request_id,
        result=result,
        error=ToolError(code=code, message=message, retryable=retryable),
    )


def _youtube_rate_limited_error_response(
    *,
    request_id: UUID,
    tool: ToolName,
    message: str,
    scope: str,
    retry_after_seconds: int,
) -> ToolResponse:
    now = datetime.now(UTC)
    retry_at = now + timedelta(seconds=max(1, retry_after_seconds))
    return _tool_error_response(
        request_id=request_id,
        tool=tool,
        code="youtube_rate_limited",
        message=message,
        retryable=True,
        result_updates={
            "rate_limit": {
                "scope": scope,
                "retry_after_seconds": max(1, retry_after_seconds),
                "retry_after_utc": retry_at.isoformat(),
                "action": "wait_and_retry",
            }
        },
    )


def _payload_str(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if isinstance(value, str):
        stripped = value.strip()
        if stripped:
            return stripped
    return None


def _payload_dict(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    raw_dict = cast(dict[object, object], value)
    normalized: dict[str, Any] = {}
    for key, raw_value in raw_dict.items():
        if isinstance(key, str):
            normalized[key] = raw_value
    return normalized


def _payload_str_list(value: object) -> list[str]:
    if isinstance(value, str):
        return _split_str_values([part.strip() for part in value.split(",")])
    if isinstance(value, list):
        raw_list = cast(list[object], value)
        str_items = [item for item in raw_list if isinstance(item, str)]
        return _split_str_values(str_items)
    return []


def _payload_optional_str_list(value: object) -> list[str] | None:
    if value is None:
        return None
    return _payload_str_list(value)


def _split_str_values(values: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = value.strip()
        if not normalized:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(normalized)
    return deduped


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            return int(stripped)
        except ValueError:
            return None
    return None


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, float):
        return value
    if isinstance(value, int):
        return float(value)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            return float(stripped)
        except ValueError:
            return None
    return None


def _normalize_bucket_media_domain(domain: str) -> str | None:
    normalized = domain.strip().lower()
    if normalized == "movie":
        return "movie"
    if normalized in {"tv", "show"}:
        return "tv"
    if normalized == "book":
        return "book"
    if normalized in {"music", "album"}:
        return "music"
    if normalized == "article":
        return "article"
    return None


def _extract_music_artist_hint(*, title: str, notes: str, domain: str) -> str | None:
    if _normalize_bucket_media_domain(domain) != "music":
        return None
    return _extract_artist_name(notes) or _extract_artist_name(title)


def _article_title_from_url(value: str | None) -> str | None:
    if value is None:
        return None
    parsed = urlparse(value.strip())
    path = parsed.path.rstrip("/")
    slug = path.rsplit("/", 1)[-1].strip()
    if not slug:
        host = (parsed.hostname or "").strip()
        if not host:
            return None
        return f"Article from {host}"
    slug = re.sub(r"\.[a-z0-9]{2,4}$", "", slug, flags=re.IGNORECASE)
    words = [word for word in re.split(r"[-_]+", slug) if word]
    if not words:
        return None
    return " ".join(words).title()


def _title_from_article_enrichment(enrichment: BucketEnrichment, *, fallback: str) -> str:
    metadata = enrichment.metadata
    enriched_title = _payload_str(metadata, "title") or _payload_str(metadata, "article_title")
    if enriched_title is not None:
        return enriched_title
    return fallback


def _extract_artist_name(value: str) -> str | None:
    normalized = value.strip()
    if not normalized:
        return None

    patterns = (
        r"\bby\s+([A-Za-z0-9][A-Za-z0-9 '&\.-]{1,80})",
        r"\bartist\s*[:\-]\s*([A-Za-z0-9][A-Za-z0-9 '&\.-]{1,80})",
    )
    for pattern in patterns:
        match = re.search(pattern, normalized, flags=re.IGNORECASE)
        if match is None:
            continue
        candidate = re.split(r"[,\.;\)\]]", match.group(1), maxsplit=1)[0].strip()
        cleaned = re.sub(r"\s+", " ", candidate).strip()
        if len(cleaned) >= 2:
            return cleaned
    return None


def _payload_tmdb_id(raw_value: object, *, canonical_id: str | None) -> int | None:
    parsed_from_payload = _optional_int(raw_value)
    if parsed_from_payload is not None and parsed_from_payload > 0:
        return parsed_from_payload
    if canonical_id is None:
        return None
    match = re.fullmatch(r"tmdb:(movie|tv):(\d+)", canonical_id.strip().lower())
    if match is None:
        return None
    return int(match.group(2))


def _payload_bookwyrm_key(raw_value: object, *, canonical_id: str | None) -> str | None:
    parsed_from_payload = _payload_str({"value": raw_value}, "value")
    if parsed_from_payload is not None and parsed_from_payload.startswith(("http://", "https://")):
        return parsed_from_payload.rstrip("/")
    if canonical_id is None:
        return None
    prefix = "bookwyrm:"
    if not canonical_id.lower().startswith(prefix):
        return None
    candidate = canonical_id[len(prefix) :].strip()
    if candidate.startswith(("http://", "https://")):
        return candidate.rstrip("/")
    return None


def _payload_musicbrainz_release_group_id(
    raw_value: object,
    *,
    canonical_id: str | None,
) -> str | None:
    parsed_from_payload = _payload_str({"value": raw_value}, "value")
    normalized = _normalize_musicbrainz_release_group_id(parsed_from_payload)
    if normalized is not None:
        return normalized
    return _normalize_musicbrainz_release_group_id(canonical_id)


def _normalize_musicbrainz_release_group_id(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().rstrip("/")
    if not normalized:
        return None

    candidate = normalized
    if normalized.lower().startswith("musicbrainz:release-group:"):
        candidate = normalized[len("musicbrainz:release-group:") :]
    elif normalized.startswith(("http://", "https://")):
        parsed = urlparse(normalized)
        path = parsed.path.rstrip("/")
        match = re.search(r"/release-group/([0-9a-fA-F-]+)$", path)
        if match is None:
            return None
        candidate = match.group(1)

    lowered = candidate.strip().lower()
    if (
        re.fullmatch(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
            lowered,
        )
        is None
    ):
        return None
    return lowered


def _bucket_resolve_candidate_payload(candidate: BucketResolveCandidate) -> dict[str, Any]:
    return {
        "provider": candidate.provider,
        "canonical_id": candidate.canonical_id,
        "tmdb_id": candidate.tmdb_id,
        "media_type": candidate.media_type,
        "bookwyrm_key": candidate.bookwyrm_key,
        "musicbrainz_release_group_id": candidate.musicbrainz_release_group_id,
        "author": candidate.author,
        "artist": candidate.artist,
        "title": candidate.title,
        "year": candidate.year,
        "confidence": candidate.confidence,
        "popularity": candidate.popularity,
        "vote_count": candidate.vote_count,
        "external_url": candidate.external_url,
    }


def _bucket_add_resolution_message(resolution: BucketAddResolution) -> str:
    provider = "tmdb"
    if resolution.selected_candidate is not None:
        provider = resolution.selected_candidate.provider
    elif resolution.candidates:
        provider = resolution.candidates[0].provider
    elif isinstance(resolution.reason, str) and resolution.reason.startswith("bookwyrm_"):
        provider = "bookwyrm"
    elif isinstance(resolution.reason, str) and resolution.reason.startswith("musicbrainz_"):
        provider = "musicbrainz"
    elif isinstance(resolution.reason, str) and resolution.reason.startswith("article_"):
        provider = "article"
    if resolution.status == "ambiguous":
        if provider == "bookwyrm":
            return (
                "Multiple BookWyrm matches were found for this title. "
                "Please choose by option number or by author/year, then retry bucket.item.add."
            )
        if provider == "musicbrainz":
            return (
                "Multiple MusicBrainz album matches were found for this title. "
                "Please choose by option number or by artist name (year optional), then retry "
                "bucket.item.add."
            )
        return (
            "Multiple TMDb matches were found for this title. "
            "Please choose by option number or by release year, then retry bucket.item.add."
        )
    if resolution.status == "no_match":
        if provider == "bookwyrm":
            return (
                "No confident BookWyrm match was found. "
                "Please provide a more specific title, author name, or release year."
            )
        if provider == "musicbrainz":
            return (
                "No confident MusicBrainz album match was found. "
                "Please provide a more specific title, artist name, or release year."
            )
        if provider == "article":
            if resolution.reason == "article_url_required":
                return "Article URL is required for article adds. Please provide the article link."
            if resolution.reason == "article_fetch_unavailable":
                return (
                    "Couldn't fetch article metadata from that URL right now. "
                    "Please retry or provide a different link."
                )
            return "No article metadata could be resolved from that URL."
        return (
            "No confident TMDb match was found. "
            "Please provide a more specific title or release year."
        )
    if resolution.status == "rate_limited":
        if provider == "bookwyrm":
            return "BookWyrm enrichment is currently rate limited. Please retry shortly."
        if provider == "musicbrainz":
            return "MusicBrainz enrichment is currently rate limited. Please retry shortly."
        return "TMDb enrichment is currently rate limited. Please retry shortly."
    return "Resolution skipped."


def _bucket_add_follow_up_instruction(resolution: BucketAddResolution) -> str:
    if resolution.reason == "article_url_required":
        return (
            "Ask the user for the article URL in normal chat, then retry bucket.item.add "
            "with payload.url."
        )
    return (
        "Ask the user to choose the intended candidate by option number "
        "or by creator clues in normal chat, then retry with the matching "
        "provider identifier."
    )


def _merge_dicts(first: dict[str, Any], second: dict[str, Any]) -> dict[str, Any]:
    merged = dict(first)
    merged.update(second)
    return merged


def _merge_source_refs(
    first: list[dict[str, str]],
    second: list[dict[str, str]],
) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for source_ref in [*first, *second]:
        ref_type = source_ref.get("type")
        ref_id = source_ref.get("id")
        if not isinstance(ref_type, str) or not isinstance(ref_id, str):
            continue
        key = (ref_type.strip(), ref_id.strip())
        if not key[0] or not key[1] or key in seen:
            continue
        seen.add(key)
        refs.append({"type": key[0], "id": key[1]})
    return refs


def _source_ref_provenance(source_refs: list[dict[str, str]]) -> list[ProvenanceRef]:
    return [
        ProvenanceRef(type=source_ref["type"], id=source_ref["id"])
        for source_ref in source_refs
        if source_ref.get("type") and source_ref.get("id")
    ]


def _bucket_statuses_from_payload(payload: dict[str, Any]) -> set[str]:
    include_completed = _bool_or_default(payload.get("include_completed"), default=False)
    statuses_raw = payload.get("statuses") or payload.get("status")
    statuses = {"active"}
    if isinstance(statuses_raw, str):
        statuses = {statuses_raw.strip().lower()}
    elif isinstance(statuses_raw, list):
        parsed = {
            item.strip().lower()
            for item in cast(list[object], statuses_raw)
            if isinstance(item, str) and item.strip()
        }
        if parsed:
            statuses = parsed
    if include_completed:
        statuses.add("completed")
    return statuses


def _bucket_item_payload(item: BucketItem) -> dict[str, Any]:
    return {
        "item_id": item.item_id,
        "title": item.title,
        "domain": item.domain,
        "status": item.status,
        "year": item.year,
        "duration_minutes": item.duration_minutes,
        "rating": item.rating,
        "popularity": item.popularity,
        "genres": item.genres,
        "tags": item.tags,
        "providers": item.providers,
        "notes": item.notes,
        "canonical_id": item.canonical_id,
        "external_url": item.external_url,
        "confidence": item.confidence,
        "metadata": item.metadata,
        "source_refs": item.source_refs,
        "annotation_status": item.annotation_status,
        "annotated": item.is_annotated,
        "annotation_provider": item.annotation_provider,
        "annotation_last_attempt_at": item.annotation_last_attempt_at,
        "added_at": item.added_at.isoformat(),
        "updated_at": item.updated_at.isoformat(),
        "completed_at": item.completed_at.isoformat() if item.completed_at is not None else None,
        "last_recommended_at": (
            item.last_recommended_at.isoformat() if item.last_recommended_at is not None else None
        ),
    }


def _bucket_recommendation_score(
    item: BucketItem,
    *,
    now: datetime,
    query: str | None,
    domain: str | None,
    genres: list[str],
    target_duration_minutes: int | None,
    min_duration_minutes: int | None,
    max_duration_minutes: int | None,
) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []
    lowered_title = item.title.lower()

    if query is not None:
        for token in re.findall(r"[a-z0-9]+", query.lower()):
            if token and token in lowered_title:
                score += 2.0
        if score > 0:
            reasons.append("matches title/query intent")

    if domain is not None and domain.strip().lower() == item.domain:
        score += 3.0
        reasons.append(f"matches domain ({item.domain})")

    normalized_genres = {genre.lower().strip() for genre in genres if genre.strip()}
    if normalized_genres:
        item_genres = {genre.lower().strip() for genre in item.genres}
        overlap = sorted(normalized_genres & item_genres)
        if overlap:
            score += 4.0 + float(len(overlap))
            reasons.append(f"matches genres: {', '.join(overlap)}")

    if target_duration_minutes is not None and item.duration_minutes is not None:
        distance = abs(item.duration_minutes - target_duration_minutes)
        duration_score = max(0.0, 8.0 - (distance / 10.0))
        score += duration_score
        reasons.append(
            f"close to target duration ({item.duration_minutes}m vs {target_duration_minutes}m)"
        )
    elif (
        min_duration_minutes is not None
        and max_duration_minutes is not None
        and item.duration_minutes is not None
    ):
        if min_duration_minutes <= item.duration_minutes <= max_duration_minutes:
            score += 5.0
            reasons.append("fits requested duration range")

    if item.rating is not None:
        score += item.rating / 2.0
        reasons.append(f"quality score {item.rating}")
    if item.popularity is not None:
        score += min(4.0, item.popularity / 10000.0)

    wait_days = _waiting_days(item, now)
    score += min(6.0, wait_days / 10.0)

    if item.last_recommended_at is not None:
        days_since_recommended = max(0, int((now - item.last_recommended_at).days))
        if days_since_recommended < 2:
            score -= 3.0
        elif days_since_recommended < 7:
            score -= 1.0

    if not reasons:
        reasons.append("strong overall fit")
    return score, reasons


def _waiting_days(item: BucketItem, now: datetime) -> int:
    return max(0, int((now - item.added_at.astimezone(UTC)).days))


def _normalize_time_scope(value: object) -> str:
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"recent", "historical", "auto"}:
            return normalized
    return "auto"


def _normalize_cache_miss_policy(value: object) -> str | None:
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"probe_recent", "none"}:
            return normalized
    return None


def _infer_query_time_scope(query: str | None) -> str:
    if query is None:
        return "recent"

    tokens = set(re.findall(r"[a-z0-9]+", query.lower()))
    if tokens & {"recent", "recently", "latest", "new", "just", "last"}:
        return "recent"
    if tokens & {"ago", "before", "older", "old", "past", "historical"}:
        return "historical"
    return "recent"


def _extract_youtube_video_id(value: str | None) -> str | None:
    if value is None:
        return None

    candidate = value.strip()
    if not candidate:
        return None

    if "://" not in candidate and "/" not in candidate and "?" not in candidate:
        return candidate

    parsed = urlparse(candidate)
    host = parsed.netloc.lower()
    path = parsed.path.strip("/")

    if host in {"youtu.be", "www.youtu.be", "m.youtu.be"}:
        first = path.split("/", maxsplit=1)[0]
        return first or None

    if host.endswith("youtube.com") or host.endswith("youtube-nocookie.com"):
        query_video = parse_qs(parsed.query).get("v")
        if query_video:
            value = query_video[0].strip()
            if value:
                return value

        for prefix in ("shorts/", "embed/", "live/"):
            if path.startswith(prefix):
                remainder = path[len(prefix) :]
                first = remainder.split("/", maxsplit=1)[0].strip()
                if first:
                    return first

    return None


def _normalize_memory_content(
    payload: dict[str, Any],
    *,
    session_id: str | None,
) -> dict[str, object] | None:
    normalized: dict[str, object] = {}

    memory_type = _payload_str(payload, "type") or _payload_str(payload, "kind") or "note"
    normalized["type"] = memory_type

    text = (
        _payload_str(payload, "text")
        or _payload_str(payload, "fact")
        or _payload_str(payload, "note")
        or _payload_str(payload, "summary")
        or _payload_str(payload, "message")
    )
    if text is not None:
        normalized["text"] = text

    title = _payload_str(payload, "title")
    if title is not None:
        normalized["title"] = title

    tags = _payload_str_list(payload.get("tags") or payload.get("tag"))
    if tags:
        normalized["tags"] = tags

    priority = _payload_str(payload, "priority")
    if priority is not None:
        normalized["priority"] = priority

    if session_id:
        normalized["session_id"] = session_id

    if "text" not in normalized:
        extracted = _flatten_memory_payload_text(payload)
        if extracted:
            normalized["text"] = extracted

    return normalized if "text" in normalized else None


def _flatten_memory_payload_text(payload: dict[str, Any]) -> str | None:
    chunks: list[str] = []
    for key, value in payload.items():
        if key in {"source_refs", "tags", "tag", "type", "kind"}:
            continue
        if isinstance(value, str):
            stripped = value.strip()
            if stripped:
                chunks.append(f"{key}: {stripped}")
        elif isinstance(value, (int, float, bool)):
            chunks.append(f"{key}: {value}")
    if not chunks:
        return None
    return "; ".join(chunks)


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


def _int_or_default(value: object, default: int) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default


def _bool_or_default(value: object, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
    return default
