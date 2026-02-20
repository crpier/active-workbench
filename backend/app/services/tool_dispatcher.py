from __future__ import annotations

import re
from datetime import UTC, datetime, time, timedelta
from typing import Any, cast
from urllib.parse import parse_qs, urlparse
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
from backend.app.repositories.bucket_repository import BucketItem, BucketRepository
from backend.app.repositories.idempotency_repository import IdempotencyRepository
from backend.app.repositories.jobs_repository import JobsRepository, ScheduledJob
from backend.app.repositories.memory_repository import MemoryRepository
from backend.app.repositories.vault_repository import SavedDocument, VaultRepository
from backend.app.repositories.youtube_quota_repository import YouTubeQuotaRepository
from backend.app.services.bucket_metadata_service import BucketMetadataService
from backend.app.services.content_analysis import (
    RecipeExtraction,
    build_routine_review_markdown,
    build_weekly_digest_markdown,
    extract_actions_from_documents,
    extract_actions_from_text,
    extract_recipe_from_transcript,
    extract_summary_from_text,
)
from backend.app.services.youtube_service import (
    YouTubeRateLimitedError,
    YouTubeService,
    YouTubeServiceError,
)

TOOL_DESCRIPTIONS: dict[ToolName, str] = {
    "youtube.likes.list_recent": (
        "List recently liked YouTube videos from local cache populated by background sync. "
        "Use payload.query/topic and optional payload.time_scope/cache_miss_policy hints."
    ),
    "youtube.likes.search_recent_content": (
        "Search recent liked videos by content (title/description/transcript) in a recent window."
    ),
    "youtube.transcript.get": (
        "Retrieve transcript for a YouTube video (cache-first, fetch fallback)."
    ),
    "vault.recipe.save": "Persist a recipe note in markdown.",
    "vault.note.save": "Persist a generic knowledge note in markdown.",
    "vault.bucket_list.add": "Add an item to the bucket list (legacy markdown-compatible flow).",
    "vault.bucket_list.prioritize": "Prioritize active bucket list items for review.",
    "bucket.item.add": "Add or merge a structured bucket item with optional metadata enrichment.",
    "bucket.item.update": "Update a structured bucket item.",
    "bucket.item.complete": "Mark a bucket item as completed (hidden from active queries).",
    "bucket.item.search": "Search bucket items with filters.",
    "bucket.item.recommend": "Recommend best-fit bucket items for the user's constraints.",
    "bucket.health.report": "Generate a bucket health report with stale items and quick wins.",
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

READY_FOR_USE_TOOLS: frozenset[ToolName] = frozenset(
    {
        "youtube.likes.list_recent",
        "youtube.likes.search_recent_content",
        "youtube.transcript.get",
        "vault.bucket_list.add",
        "vault.bucket_list.prioritize",
        "bucket.item.add",
        "bucket.item.update",
        "bucket.item.complete",
        "bucket.item.search",
        "bucket.item.recommend",
        "bucket.health.report",
    }
)


class ToolDispatcher:
    def __init__(
        self,
        *,
        audit_repository: AuditRepository,
        idempotency_repository: IdempotencyRepository,
        memory_repository: MemoryRepository,
        jobs_repository: JobsRepository,
        vault_repository: VaultRepository,
        bucket_repository: BucketRepository,
        bucket_metadata_service: BucketMetadataService,
        youtube_quota_repository: YouTubeQuotaRepository,
        youtube_service: YouTubeService,
        default_timezone: str,
        youtube_daily_quota_limit: int,
        youtube_quota_warning_percent: float,
    ) -> None:
        self._audit_repository = audit_repository
        self._idempotency_repository = idempotency_repository
        self._memory_repository = memory_repository
        self._jobs_repository = jobs_repository
        self._vault_repository = vault_repository
        self._bucket_repository = bucket_repository
        self._bucket_metadata_service = bucket_metadata_service
        self._youtube_quota_repository = youtube_quota_repository
        self._youtube_service = youtube_service
        self._bucket_legacy_synced = False
        self._default_timezone = default_timezone
        self._youtube_daily_quota_limit = max(0, youtube_daily_quota_limit)
        bounded_warning_percent = min(1.0, max(0.0, youtube_quota_warning_percent))
        self._youtube_quota_warning_threshold = int(
            self._youtube_daily_quota_limit * bounded_warning_percent
        )

        self._jobs_repository.ensure_weekly_routine_review(
            run_at=_next_sunday_morning(default_timezone),
            timezone=default_timezone,
        )

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
        due_jobs = self._jobs_repository.list_due_jobs(datetime.now(UTC))
        for job in due_jobs:
            result = self._run_single_job(job)
            if job.recurrence == "weekly":
                self._jobs_repository.reschedule_weekly(job.job_id, job.run_at + timedelta(days=7))
            else:
                self._jobs_repository.mark_completed(job.job_id, result)

    def execute(self, tool_name: ToolName, request: ToolRequest) -> ToolResponse:
        self.run_due_jobs()

        cached = self._load_idempotent_response(tool_name, request.idempotency_key)
        if cached is not None:
            return cached

        response = self._execute_tool(tool_name, request)
        response = self._attach_audit_event(tool_name, request, response)
        self._store_idempotent_response(tool_name, request.idempotency_key, response)
        return response

    def _execute_tool(self, tool_name: ToolName, request: ToolRequest) -> ToolResponse:
        if tool_name == "youtube.likes.list_recent":
            return self._handle_youtube_likes(request)
        if tool_name == "youtube.likes.search_recent_content":
            return self._handle_youtube_likes_search_recent_content(request)
        if tool_name == "youtube.transcript.get":
            return self._handle_youtube_transcript(request)
        if tool_name == "vault.recipe.save":
            return self._handle_vault_save(request, category="recipes")
        if tool_name == "vault.note.save":
            return self._handle_vault_save(request, category="notes")
        if tool_name == "vault.bucket_list.add":
            return self._handle_bucket_item_add(request, legacy_response=True)
        if tool_name == "vault.bucket_list.prioritize":
            return self._handle_bucket_list_prioritize(request)
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
        if tool_name == "memory.undo":
            return self._handle_memory_undo(request)
        if tool_name == "reminder.schedule":
            return self._handle_reminder_schedule(request)
        if tool_name == "context.suggest_for_query":
            return self._handle_context_suggest(request)
        if tool_name == "digest.weekly_learning.generate":
            return self._handle_weekly_digest(request)
        if tool_name == "review.routine.generate":
            return self._handle_routine_review(request)
        if tool_name == "recipe.extract_from_transcript":
            return self._handle_recipe_extract(request)
        if tool_name == "summary.extract_key_ideas":
            return self._handle_summary_extract(request)
        if tool_name == "actions.extract_from_notes":
            return self._handle_actions_extract(request)

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
        limit = _int_or_default(request.payload.get("limit"), default=5)
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
                limit=max(1, min(25, limit)),
                query=query,
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
                "videos": payload_videos,
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

    def _handle_bucket_item_add(
        self,
        request: ToolRequest,
        *,
        legacy_response: bool = False,
    ) -> ToolResponse:
        self._sync_bucket_legacy_documents()

        title = (
            _payload_str(request.payload, "title")
            or _payload_str(request.payload, "name")
            or _payload_str(request.payload, "item")
        )
        if title is None:
            return _tool_error_response(
                request_id=request.request_id,
                tool=request.tool,
                code="invalid_input",
                message="payload.title (or payload.name/payload.item) is required",
            )

        domain = (
            _payload_str(request.payload, "domain")
            or _payload_str(request.payload, "kind")
            or _infer_domain_from_title(title)
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
        external_url = _payload_str(request.payload, "external_url") or _payload_str(
            request.payload, "url"
        )
        confidence = _optional_float(request.payload.get("confidence"))
        metadata = _payload_dict(request.payload.get("metadata"))
        source_refs = _extract_source_refs(request.payload)

        auto_enrich = _bool_or_default(request.payload.get("auto_enrich"), default=True)
        enrichment = None
        if auto_enrich:
            enrichment = self._bucket_metadata_service.enrich(
                title=title,
                domain=domain,
                year=year,
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

        markdown_body = _bucket_item_markdown(item)
        saved = self._vault_repository.save_document(
            category="bucket-list",
            title=item.title,
            body=markdown_body,
            tool_name=request.tool,
            source_refs=item.source_refs,
        )
        self._bucket_repository.create_or_merge_item(
            title=item.title,
            domain=item.domain,
            notes=item.notes,
            year=item.year,
            duration_minutes=item.duration_minutes,
            rating=item.rating,
            popularity=item.popularity,
            genres=item.genres,
            tags=item.tags,
            providers=item.providers,
            metadata=item.metadata,
            source_refs=item.source_refs,
            canonical_id=item.canonical_id,
            external_url=item.external_url,
            confidence=item.confidence,
            legacy_path=saved.relative_path,
            added_at=item.added_at,
            updated_at=item.updated_at,
        )

        refreshed_item = self._bucket_repository.get_item(item.item_id)
        if refreshed_item is None:
            refreshed_item = item

        result: dict[str, Any] = {
            "tool": request.tool,
            "status": "saved" if legacy_response else action,
            "bucket_item": _bucket_item_payload(refreshed_item),
            "enriched": enrichment is not None and enrichment.provider is not None,
            "enrichment_provider": enrichment.provider if enrichment is not None else None,
            "document_id": saved.document_id,
            "path": saved.relative_path,
        }
        if legacy_response:
            result["bucket_item_id"] = refreshed_item.item_id

        provenance = [
            _vault_provenance(saved),
            ProvenanceRef(type="bucket_item", id=refreshed_item.item_id),
        ]
        provenance.extend(_source_ref_provenance(refreshed_item.source_refs))

        return ToolResponse(
            ok=True,
            request_id=request.request_id,
            result=result,
            provenance=provenance,
            error=None,
        )

    def _handle_bucket_item_update(self, request: ToolRequest) -> ToolResponse:
        self._sync_bucket_legacy_documents()
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
        self._sync_bucket_legacy_documents()
        item_id = _payload_str(request.payload, "item_id") or _payload_str(request.payload, "id")
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
        self._sync_bucket_legacy_documents()
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
                "items": [_bucket_item_payload(item) for item in matches],
            },
            provenance=[
                ProvenanceRef(type="bucket_item", id=item.item_id) for item in matches[:30]
            ],
            error=None,
        )

    def _handle_bucket_item_recommend(self, request: ToolRequest) -> ToolResponse:
        self._sync_bucket_legacy_documents()
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

        ranked: list[dict[str, Any]] = []
        now = datetime.now(UTC)
        for candidate in candidates:
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
                "recommendations": recommendations,
            },
            provenance=[
                ProvenanceRef(type="bucket_item", id=item.item_id) for item in selected_items
            ],
            error=None,
        )

    def _handle_bucket_health_report(self, request: ToolRequest) -> ToolResponse:
        self._sync_bucket_legacy_documents()
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

    def _handle_bucket_list_prioritize(self, request: ToolRequest) -> ToolResponse:
        self._sync_bucket_legacy_documents()
        active_items = self._bucket_repository.search_items(
            query=None,
            domain=None,
            statuses={"active"},
            min_duration_minutes=None,
            max_duration_minutes=None,
            genres=[],
            min_rating=None,
            limit=200,
        )
        now = datetime.now(UTC)
        prioritized: list[dict[str, Any]] = []
        for item in active_items:
            prioritized.append(
                {
                    "title": item.title,
                    "path": item.legacy_path,
                    "waiting_days": _waiting_days(item, now),
                    "effort": _metadata_level(item.metadata, "effort"),
                    "cost": _metadata_level(item.metadata, "cost"),
                    "domain": item.domain,
                    "duration_minutes": item.duration_minutes,
                    "rating": item.rating,
                    "item_id": item.item_id,
                }
            )
        prioritized = sorted(
            prioritized,
            key=lambda entry: int(entry.get("waiting_days", 0)),
            reverse=True,
        )

        return ToolResponse(
            ok=True,
            request_id=request.request_id,
            result={"tool": request.tool, "status": "ok", "items": prioritized},
            provenance=[
                ProvenanceRef(type="bucket_item", id=item.item_id) for item in active_items[:50]
            ],
            error=None,
        )

    def _sync_bucket_legacy_documents(self) -> None:
        if self._bucket_legacy_synced:
            return
        documents = self._vault_repository.list_documents("bucket-list", limit=500)
        for document in documents:
            self._bucket_repository.upsert_legacy_document(document)
        self._bucket_legacy_synced = True

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

    def _handle_reminder_schedule(self, request: ToolRequest) -> ToolResponse:
        timezone_name = request.context.timezone or self._default_timezone
        run_at = _resolve_run_at(request.payload, timezone_name)

        payload: dict[str, Any] = dict(request.payload)
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
            result={"tool": request.tool, "status": "ok", "suggestions": suggestions},
            error=None,
        )

    def _handle_weekly_digest(self, request: ToolRequest) -> ToolResponse:
        notes = self._vault_repository.list_documents("notes", limit=200)
        now = datetime.now(UTC)
        title = (
            _payload_str(request.payload, "title")
            or f"Weekly Learning Digest {now.date().isoformat()}"
        )
        markdown = build_weekly_digest_markdown(notes, now)

        source_refs = [{"type": "vault_document", "id": note.relative_path} for note in notes[:50]]
        saved = self._vault_repository.save_document(
            category="digests",
            title=title,
            body=markdown,
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
                "note_count": len(notes),
            },
            provenance=[_vault_provenance(saved)],
            error=None,
        )

    def _handle_routine_review(self, request: ToolRequest) -> ToolResponse:
        now = datetime.now(UTC)
        title = _payload_str(request.payload, "title") or f"Routine Review {now.date().isoformat()}"

        upcoming_items = self._jobs_repository.list_upcoming_reminder_items(limit=10)
        bucket_items = self._vault_repository.list_documents("bucket-list", limit=100)
        recent_notes = self._vault_repository.list_documents("notes", limit=20)

        markdown = build_routine_review_markdown(
            upcoming_items=upcoming_items,
            bucket_items=bucket_items,
            recent_notes=recent_notes,
            now=now,
        )

        source_refs: list[dict[str, str]] = [{"type": "job", "id": "reminder_queue"}]
        source_refs.extend(
            {"type": "vault_document", "id": doc.relative_path} for doc in bucket_items[:20]
        )
        source_refs.extend(
            {"type": "vault_document", "id": doc.relative_path} for doc in recent_notes[:20]
        )

        saved = self._vault_repository.save_document(
            category="reviews",
            title=title,
            body=markdown,
            tool_name=request.tool,
            source_refs=source_refs,
        )

        ensure_schedule = _bool_or_default(request.payload.get("ensure_schedule"), default=True)
        scheduled_job_id: str | None = None
        if ensure_schedule:
            scheduled_job_id = self._jobs_repository.ensure_weekly_routine_review(
                run_at=_next_sunday_morning(self._default_timezone),
                timezone=self._default_timezone,
            )

        provenance = [_vault_provenance(saved)]
        if scheduled_job_id is not None:
            provenance.append(ProvenanceRef(type="job", id=scheduled_job_id))

        return ToolResponse(
            ok=True,
            request_id=request.request_id,
            result={
                "tool": request.tool,
                "status": "saved",
                "document_id": saved.document_id,
                "path": saved.relative_path,
                "scheduled_job_id": scheduled_job_id,
            },
            provenance=provenance,
            error=None,
        )

    def _handle_recipe_extract(self, request: ToolRequest) -> ToolResponse:
        transcript = _payload_str(request.payload, "transcript")
        title = _payload_str(request.payload, "title") or "Extracted Recipe"
        source_video_id = _payload_str(request.payload, "video_id")

        if transcript is None and source_video_id is not None:
            transcript_response = self._youtube_service.get_transcript(source_video_id)
            transcript = transcript_response.transcript
            title = transcript_response.title

        if transcript is None:
            return _tool_error_response(
                request_id=request.request_id,
                tool=request.tool,
                code="invalid_input",
                message="payload.transcript or payload.video_id is required",
            )

        extraction = extract_recipe_from_transcript(transcript, title=title)
        markdown = _recipe_markdown(extraction)

        provenance: list[ProvenanceRef] = []
        if source_video_id is not None:
            provenance.append(ProvenanceRef(type="youtube_video", id=source_video_id))

        return ToolResponse(
            ok=True,
            request_id=request.request_id,
            result={
                "tool": request.tool,
                "status": "ok",
                "title": extraction.title,
                "ingredients": extraction.ingredients,
                "steps": extraction.steps,
                "notes": extraction.notes,
                "markdown": markdown,
            },
            provenance=provenance,
            error=None,
        )

    def _handle_summary_extract(self, request: ToolRequest) -> ToolResponse:
        transcript = _payload_str(request.payload, "transcript")
        source_video_id = _payload_str(request.payload, "video_id")

        if transcript is None and source_video_id is not None:
            transcript_response = self._youtube_service.get_transcript(source_video_id)
            transcript = transcript_response.transcript

        if transcript is None:
            return _tool_error_response(
                request_id=request.request_id,
                tool=request.tool,
                code="invalid_input",
                message="payload.transcript or payload.video_id is required",
            )

        max_points = _int_or_default(request.payload.get("max_points"), default=5)
        summary = extract_summary_from_text(transcript, max_points=max(1, min(10, max_points)))

        provenance: list[ProvenanceRef] = []
        if source_video_id is not None:
            provenance.append(ProvenanceRef(type="youtube_video", id=source_video_id))

        return ToolResponse(
            ok=True,
            request_id=request.request_id,
            result={
                "tool": request.tool,
                "status": "ok",
                "key_ideas": summary.key_ideas,
                "notable_phrases": summary.notable_phrases,
            },
            provenance=provenance,
            error=None,
        )

    def _handle_actions_extract(self, request: ToolRequest) -> ToolResponse:
        notes_payload = request.payload.get("notes")

        actions_payload: list[dict[str, Any]] = []
        provenance: list[ProvenanceRef] = []

        if isinstance(notes_payload, list):
            notes_list = cast(list[object], notes_payload)
            for note in notes_list:
                if isinstance(note, str):
                    for action in extract_actions_from_text(note):
                        actions_payload.append(
                            {
                                "action": action.action,
                                "source_title": action.source_title,
                                "source_path": action.source_path,
                                "priority": "defer_to_agent",
                            }
                        )
        else:
            documents = self._vault_repository.list_documents("notes", limit=100)
            extracted = extract_actions_from_documents(documents)
            for action in extracted:
                actions_payload.append(
                    {
                        "action": action.action,
                        "source_title": action.source_title,
                        "source_path": action.source_path,
                        "priority": "defer_to_agent",
                    }
                )
            provenance = [
                ProvenanceRef(type="vault_document", id=doc.relative_path) for doc in documents
            ]

        return ToolResponse(
            ok=True,
            request_id=request.request_id,
            result={"tool": request.tool, "status": "ok", "actions": actions_payload},
            provenance=provenance,
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

    def _run_single_job(self, job: ScheduledJob) -> dict[str, Any]:
        if job.job_type == "reminder":
            return self._execute_reminder_job(job)

        if job.job_type == "routine_review":
            return self._execute_routine_review_job(job)

        return {"job_id": job.job_id, "status": "skipped", "reason": "unknown_job_type"}

    def _execute_reminder_job(self, job: ScheduledJob) -> dict[str, Any]:
        item = _job_item(job.payload)
        title = f"Reminder: {item}"
        body = (
            f"This reminder was scheduled for {job.run_at.astimezone(UTC).isoformat()} UTC.\n\n"
            f"Item: {item}\n"
            "Action: Handle this before it expires."
        )

        saved = self._vault_repository.save_document(
            category="reviews",
            title=title,
            body=body,
            tool_name="scheduler.reminder",
            source_refs=[{"type": "job", "id": job.job_id}],
        )
        return {"status": "completed", "document_path": saved.relative_path}

    def _execute_routine_review_job(self, job: ScheduledJob) -> dict[str, Any]:
        request = ToolRequest(
            tool="review.routine.generate",
            request_id=UUID("00000000-0000-0000-0000-000000000001"),
            payload={"title": "Scheduled Routine Review", "ensure_schedule": False},
        )
        response = self._handle_routine_review(request)
        return response.result


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


def _infer_domain_from_title(title: str) -> str:
    lowered = title.lower()
    if any(token in lowered for token in ("season", "episode", "series")):
        return "tv"
    return "movie"


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
        "added_at": item.added_at.isoformat(),
        "updated_at": item.updated_at.isoformat(),
        "completed_at": item.completed_at.isoformat() if item.completed_at is not None else None,
        "last_recommended_at": (
            item.last_recommended_at.isoformat() if item.last_recommended_at is not None else None
        ),
        "legacy_path": item.legacy_path,
    }


def _bucket_item_markdown(item: BucketItem) -> str:
    lines = [
        f"domain: {item.domain}",
        f"status: {item.status}",
    ]
    if item.year is not None:
        lines.append(f"year: {item.year}")
    if item.duration_minutes is not None:
        lines.append(f"duration_minutes: {item.duration_minutes}")
    if item.rating is not None:
        lines.append(f"rating: {item.rating}")
    if item.genres:
        lines.append(f"genres: {', '.join(item.genres)}")
    if item.providers:
        lines.append(f"providers: {', '.join(item.providers)}")
    if item.external_url is not None:
        lines.append(f"url: {item.external_url}")
    if item.notes:
        lines.extend(["", item.notes.strip()])
    return "\n".join(lines).strip()


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


def _metadata_level(metadata: dict[str, Any], key: str) -> str | None:
    value = metadata.get(key)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"low", "medium", "high"}:
            return normalized
    return None


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

    days_from_now = _int_or_default(payload.get("days_from_now"), default=0)
    hour = _int_or_default(payload.get("hour"), default=9)
    minute = _int_or_default(payload.get("minute"), default=0)

    now = datetime.now(resolved_timezone)
    target_date = (now + timedelta(days=days_from_now)).date()
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


def _resolve_timezone(timezone_name: str) -> ZoneInfo:
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def _next_sunday_morning(timezone_name: str) -> datetime:
    timezone = _resolve_timezone(timezone_name)
    now = datetime.now(timezone)
    days_until_sunday = (6 - now.weekday()) % 7
    if days_until_sunday == 0 and now.time() >= time(hour=9, minute=0):
        days_until_sunday = 7

    target_date = (now + timedelta(days=days_until_sunday)).date()
    return datetime.combine(target_date, time(hour=9, minute=0), timezone)


def _job_item(payload: dict[str, Any]) -> str:
    for key in ("item", "ingredient", "name", "title"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "scheduled task"


def _recipe_markdown(extraction: RecipeExtraction) -> str:
    lines: list[str] = [f"# {extraction.title}", "", "## Ingredients", ""]
    for ingredient in extraction.ingredients:
        lines.append(f"- {ingredient}")

    lines.extend(["", "## Steps", ""])
    for index, step in enumerate(extraction.steps, start=1):
        lines.append(f"{index}. {step}")

    if extraction.notes:
        lines.extend(["", "## Notes", ""])
        for note in extraction.notes:
            lines.append(f"- {note}")

    return "\n".join(lines)
