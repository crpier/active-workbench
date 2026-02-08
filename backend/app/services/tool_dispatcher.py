from __future__ import annotations

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
from backend.app.repositories.idempotency_repository import IdempotencyRepository
from backend.app.repositories.jobs_repository import JobsRepository, ScheduledJob
from backend.app.repositories.memory_repository import MemoryRepository
from backend.app.repositories.vault_repository import SavedDocument, VaultRepository
from backend.app.repositories.youtube_quota_repository import YouTubeQuotaRepository
from backend.app.services.content_analysis import (
    RecipeExtraction,
    build_routine_review_markdown,
    build_weekly_digest_markdown,
    extract_actions_from_documents,
    extract_actions_from_text,
    extract_recipe_from_transcript,
    extract_summary_from_text,
    prioritize_bucket_list_items,
)
from backend.app.services.youtube_service import YouTubeService, YouTubeServiceError

TOOL_DESCRIPTIONS: dict[ToolName, str] = {
    "youtube.likes.list_recent": (
        "List recently liked YouTube videos (treat likes as watched-video signal). "
        "Use payload.query or payload.topic to filter by topic."
    ),
    "youtube.transcript.get": "Retrieve transcript for a YouTube video.",
    "vault.recipe.save": "Persist a recipe note in markdown.",
    "vault.note.save": "Persist a generic knowledge note in markdown.",
    "vault.bucket_list.add": "Add an item to the bucket list.",
    "vault.bucket_list.prioritize": "Prioritize bucket list items for review.",
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
        self._youtube_quota_repository = youtube_quota_repository
        self._youtube_service = youtube_service
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
            )
            for name, description in TOOL_DESCRIPTIONS.items()
        ]

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
        if tool_name == "youtube.transcript.get":
            return self._handle_youtube_transcript(request)
        if tool_name == "vault.recipe.save":
            return self._handle_vault_save(request, category="recipes")
        if tool_name == "vault.note.save":
            return self._handle_vault_save(request, category="notes")
        if tool_name == "vault.bucket_list.add":
            return self._handle_vault_save(request, category="bucket-list")
        if tool_name == "vault.bucket_list.prioritize":
            return self._handle_bucket_list_prioritize(request)
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
        estimated_units_this_call = self._estimate_likes_units()

        try:
            videos = self._youtube_service.list_recent(limit=max(1, min(25, limit)), query=query)
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
                estimated_units_this_call=estimated_units_this_call,
            )

        payload_videos = [
            {
                "video_id": item.video_id,
                "title": item.title,
                "published_at": item.published_at,
                "liked_at": item.liked_at,
                "video_published_at": item.video_published_at,
            }
            for item in videos
        ]

        provenance = [ProvenanceRef(type="youtube_video", id=item.video_id) for item in videos]
        response = ToolResponse(
            ok=True,
            request_id=request.request_id,
            result={"tool": request.tool, "status": "ok", "videos": payload_videos},
            provenance=provenance,
            error=None,
        )
        return self._attach_quota_snapshot(
            response,
            tool_name=request.tool,
            estimated_units_this_call=estimated_units_this_call,
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
                recent = self._youtube_service.list_recent(limit=1, query=None)
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
                    estimated_units_this_call=self._estimate_likes_units(),
                )

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
                    estimated_units_this_call=self._estimate_likes_units(),
                )
            video_id = recent[0].video_id

        try:
            transcript = self._youtube_service.get_transcript(video_id)
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
                estimated_units_this_call=self._estimate_transcript_units(
                    transcript_source=None,
                    explicit_video_requested=explicit_video_requested,
                ),
            )

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
            },
            provenance=[ProvenanceRef(type="youtube_video", id=transcript.video_id)],
            error=None,
        )
        return self._attach_quota_snapshot(
            response,
            tool_name=request.tool,
            estimated_units_this_call=self._estimate_transcript_units(
                transcript_source=transcript.source,
                explicit_video_requested=explicit_video_requested,
            ),
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

    def _estimate_likes_units(self) -> int:
        if not self._youtube_service.is_oauth_mode:
            return 0
        return 2

    def _estimate_transcript_units(
        self,
        *,
        transcript_source: str | None,
        explicit_video_requested: bool,
    ) -> int:
        if not self._youtube_service.is_oauth_mode:
            return 0

        units = 1  # videos.list for title lookup
        if not explicit_video_requested:
            units += self._estimate_likes_units()

        if transcript_source == "video_description_fallback" or transcript_source is None:
            units += 1  # videos.list for description fallback path

        return units

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

    def _handle_bucket_list_prioritize(self, request: ToolRequest) -> ToolResponse:
        documents = self._vault_repository.list_documents("bucket-list", limit=100)
        prioritized = prioritize_bucket_list_items(documents)

        return ToolResponse(
            ok=True,
            request_id=request.request_id,
            result={
                "tool": request.tool,
                "status": "ok",
                "items": prioritized,
            },
            provenance=[
                ProvenanceRef(type="vault_document", id=doc.relative_path) for doc in documents
            ],
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
) -> ToolResponse:
    return ToolResponse(
        ok=False,
        request_id=request_id,
        result={"tool": tool, "status": "failed"},
        error=ToolError(code=code, message=message, retryable=False),
    )


def _payload_str(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if isinstance(value, str):
        stripped = value.strip()
        if stripped:
            return stripped
    return None


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
