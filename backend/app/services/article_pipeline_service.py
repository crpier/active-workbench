from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from html import escape, unescape
from html.parser import HTMLParser
from importlib import import_module
from typing import Any, cast
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse
from urllib.request import Request, urlopen

from backend.app.repositories.article_repository import (
    ARTICLE_JOB_STATUS_QUEUED,
    ArticleJob,
    ArticleRecord,
    ArticleRepository,
)
from backend.app.repositories.bucket_repository import BucketRepository
from backend.app.telemetry import TelemetryClient

LOGGER = logging.getLogger("active_workbench.article_pipeline")

ARTICLE_JOB_TYPE_INGEST = "ingest"
ARTICLE_JOB_TYPE_RETRY = "retry"

TRACKING_QUERY_PARAMS: frozenset[str] = frozenset(
    {
        "fbclid",
        "gclid",
        "igshid",
        "mc_cid",
        "mc_eid",
        "mkt_tok",
        "ref_src",
        "spm",
        "utm_campaign",
        "utm_content",
        "utm_id",
        "utm_medium",
        "utm_name",
        "utm_source",
        "utm_term",
    }
)


@dataclass(frozen=True)
class ArticleCaptureResult:
    article: ArticleRecord
    job_status: str
    deduped: bool


@dataclass(frozen=True)
class ArticleReadableResult:
    article: ArticleRecord
    source_markdown: str | None
    llm_markdown: str | None
    default_markdown: str | None


@dataclass(frozen=True)
class ArticleProcessingStats:
    attempted: int
    succeeded: int
    retried: int
    failed: int


class _RetryablePipelineError(Exception):
    def __init__(self, message: str, *, retry_after_seconds: int) -> None:
        super().__init__(message)
        self.retry_after_seconds = max(1, retry_after_seconds)


class _TerminalPipelineError(Exception):
    pass


class ArticlePipelineService:
    def __init__(
        self,
        *,
        article_repository: ArticleRepository,
        bucket_repository: BucketRepository,
        telemetry: TelemetryClient | None = None,
        enabled: bool = True,
        fetch_timeout_seconds: float = 12.0,
        user_agent: str = "active-workbench/0.1 (+https://github.com/crpier/active-workbench)",
        quality_min_chars: int = 900,
        supadata_api_key: str | None = None,
        supadata_base_url: str = "https://api.supadata.ai/v1",
        supadata_timeout_seconds: float = 30.0,
        supadata_fallback_enabled: bool = True,
        llm_polish_enabled: bool = True,
        domain_backoff_base_seconds: int = 120,
        domain_backoff_max_seconds: int = 3600,
    ) -> None:
        self._article_repository = article_repository
        self._bucket_repository = bucket_repository
        self._telemetry = telemetry if telemetry is not None else TelemetryClient.disabled()
        self._enabled = enabled
        self._fetch_timeout_seconds = max(1.0, fetch_timeout_seconds)
        self._user_agent = user_agent.strip() or "active-workbench/0.1"
        self._quality_min_chars = max(150, quality_min_chars)
        self._supadata_api_key = _normalize_optional_text(supadata_api_key)
        self._supadata_base_url = supadata_base_url.rstrip("/")
        self._supadata_timeout_seconds = max(1.0, supadata_timeout_seconds)
        self._supadata_fallback_enabled = supadata_fallback_enabled
        self._llm_polish_enabled = llm_polish_enabled
        self._domain_backoff_base_seconds = max(10, domain_backoff_base_seconds)
        self._domain_backoff_max_seconds = max(
            self._domain_backoff_base_seconds,
            domain_backoff_max_seconds,
        )

    @property
    def enabled(self) -> bool:
        return self._enabled

    def capture_article(
        self,
        *,
        url: str,
        bucket_item_id: str,
        source: str,
        shared_text: str | None = None,
    ) -> ArticleCaptureResult:
        normalized_url = normalize_article_url(url)
        if normalized_url is None:
            raise ValueError("Article URL must be an absolute http/https URL")

        existing_bucket = self._article_repository.get_article_by_bucket_item_id(bucket_item_id)
        if existing_bucket is not None:
            self._article_repository.enqueue_job(
                article_id=existing_bucket.article_id,
                job_type=ARTICLE_JOB_TYPE_INGEST,
            )
            self._sync_bucket_item(existing_bucket)
            return ArticleCaptureResult(
                article=existing_bucket,
                job_status=ARTICLE_JOB_STATUS_QUEUED,
                deduped=True,
            )

        existing_url = self._article_repository.find_active_by_url(normalized_url)
        if existing_url is not None:
            self._sync_bucket_item(existing_url)
            return ArticleCaptureResult(
                article=existing_url,
                job_status=ARTICLE_JOB_STATUS_QUEUED,
                deduped=True,
            )

        created = self._article_repository.create_article(
            bucket_item_id=bucket_item_id,
            source_url=normalized_url,
            canonical_url=normalized_url,
            title=None,
            provenance={
                "capture_source": source.strip().lower(),
                "capture_url": normalized_url,
                "captured_at": datetime.now(UTC).isoformat(),
                "shared_text_present": bool(_normalize_optional_text(shared_text)),
            },
        )
        self._article_repository.enqueue_job(
            article_id=created.article_id,
            job_type=ARTICLE_JOB_TYPE_INGEST,
        )
        self._sync_bucket_item(created)
        return ArticleCaptureResult(
            article=created,
            job_status=ARTICLE_JOB_STATUS_QUEUED,
            deduped=False,
        )

    def retry_article(self, *, article_id: str) -> ArticleRecord | None:
        article = self._article_repository.get_article(article_id)
        if article is None:
            return None
        self._article_repository.enqueue_job(
            article_id=article.article_id,
            job_type=ARTICLE_JOB_TYPE_RETRY,
        )
        return article

    def process_due_jobs(self, *, limit: int) -> ArticleProcessingStats:
        if not self._enabled:
            return ArticleProcessingStats(attempted=0, succeeded=0, retried=0, failed=0)

        claimed = self._article_repository.claim_due_jobs(limit=max(1, limit))
        attempted = len(claimed)
        succeeded = 0
        retried = 0
        failed = 0
        for job in claimed:
            try:
                self._process_single_job(job)
            except _RetryablePipelineError as exc:
                if job.attempts >= 5:
                    self._article_repository.mark_job_failed(
                        job_id=job.job_id,
                        last_error=f"retry_exhausted: {exc}",
                    )
                    self._article_repository.update_article_failed(
                        article_id=job.article_id,
                        error_code="retry_exhausted",
                        error_message=str(exc),
                    )
                    failed += 1
                    continue
                self._article_repository.mark_job_retry(
                    job_id=job.job_id,
                    retry_after_seconds=exc.retry_after_seconds,
                    last_error=str(exc),
                )
                retried += 1
            except _TerminalPipelineError as exc:
                self._article_repository.mark_job_failed(job_id=job.job_id, last_error=str(exc))
                self._article_repository.update_article_failed(
                    article_id=job.article_id,
                    error_code="pipeline_terminal_error",
                    error_message=str(exc),
                )
                failed += 1
            else:
                self._article_repository.mark_job_succeeded(job_id=job.job_id)
                succeeded += 1

        return ArticleProcessingStats(
            attempted=attempted,
            succeeded=succeeded,
            retried=retried,
            failed=failed,
        )

    def get_article(self, article_id: str) -> ArticleRecord | None:
        return self._article_repository.get_article(article_id)

    def list_articles(
        self,
        *,
        statuses: set[str] | None,
        read_states: set[str] | None,
        domain_host: str | None,
        limit: int,
        cursor: int,
    ) -> list[ArticleRecord]:
        return self._article_repository.list_articles(
            statuses=statuses,
            read_states=read_states,
            domain_host=domain_host,
            limit=limit,
            cursor=cursor,
        )

    def get_readable(self, *, article_id: str) -> ArticleReadableResult | None:
        article = self._article_repository.get_article(article_id)
        if article is None:
            return None
        source = self._article_repository.get_latest_snapshot(
            article_id=article.article_id,
            snapshot_type="source_markdown",
        )
        llm = self._article_repository.get_latest_snapshot(
            article_id=article.article_id,
            snapshot_type="llm_markdown",
        )
        default_markdown: str | None = None
        if llm is not None and _normalize_optional_text(llm.content_text) is not None:
            default_markdown = llm.content_text
        elif source is not None and _normalize_optional_text(source.content_text) is not None:
            default_markdown = source.content_text
        return ArticleReadableResult(
            article=article,
            source_markdown=source.content_text if source is not None else None,
            llm_markdown=llm.content_text if llm is not None else None,
            default_markdown=default_markdown,
        )

    def update_read_state(
        self,
        *,
        article_id: str,
        read_state: str,
        progress_percent: int | None,
    ) -> ArticleRecord | None:
        updated = self._article_repository.update_read_state(
            article_id=article_id,
            read_state=read_state,
            progress_percent=progress_percent,
        )
        if updated is not None:
            self._sync_bucket_item(updated)
        return updated

    def delete_article(self, *, article_id: str) -> ArticleRecord | None:
        article = self._article_repository.mark_deleted(article_id)
        if article is not None:
            self._sync_bucket_item(article)
        return article

    def _process_single_job(self, job: ArticleJob) -> None:
        article = self._article_repository.get_article(job.article_id)
        if article is None:
            raise _TerminalPipelineError("article_missing")

        self._article_repository.update_article_processing_status(article.article_id)
        domain = article.domain_host
        if domain is not None:
            throttle = self._article_repository.get_domain_throttle(domain=domain)
            if throttle is not None and throttle.next_allowed_at > datetime.now(UTC):
                retry_seconds = max(
                    1,
                    int((throttle.next_allowed_at - datetime.now(UTC)).total_seconds()),
                )
                raise _RetryablePipelineError(
                    f"domain_throttled:{domain}",
                    retry_after_seconds=retry_seconds,
                )
            if throttle is not None:
                self._article_repository.clear_domain_throttle(domain=domain)

        fetched = self._fetch_html(article.source_url)
        if fetched.html is None:
            error_message = fetched.error_message or "fetch_failed"
            if fetched.retryable:
                self._apply_domain_backoff(
                    domain=domain,
                    http_status=fetched.http_status,
                )
                self._article_repository.update_article_failed(
                    article_id=article.article_id,
                    error_code="fetch_retryable_error",
                    error_message=error_message,
                )
                raise _RetryablePipelineError(
                    error_message,
                    retry_after_seconds=self._domain_backoff_base_seconds,
                )
            raise _TerminalPipelineError(error_message)

        html_text = fetched.html
        raw_hash = sha256(html_text.encode("utf-8")).hexdigest()
        self._article_repository.add_snapshot(
            article_id=article.article_id,
            snapshot_type="raw_html",
            content_text=html_text,
            content_hash=raw_hash,
            extractor="url_fetch",
            extractor_version=None,
        )

        metadata = _extract_article_metadata(article.source_url, html_text)
        canonical_url = metadata.canonical_url or article.canonical_url
        source_markdown = self._extract_markdown_with_trafilatura(
            html_text=html_text,
            source_url=canonical_url,
        )
        if source_markdown is not None:
            source_markdown = _heuristic_markdown_polish(source_markdown)
        chosen_markdown = source_markdown
        extraction_method = "trafilatura"
        llm_polished = False

        if source_markdown is not None:
            self._article_repository.add_snapshot(
                article_id=article.article_id,
                snapshot_type="source_markdown",
                content_text=source_markdown,
                content_hash=sha256(source_markdown.encode("utf-8")).hexdigest(),
                extractor="trafilatura",
                extractor_version=None,
            )

        if not self._is_markdown_quality_ok(source_markdown):
            fallback_markdown = self._extract_markdown_with_supadata(canonical_url)
            if fallback_markdown is not None:
                fallback_markdown = _heuristic_markdown_polish(fallback_markdown)
                extraction_method = "supadata"
                chosen_markdown = fallback_markdown
                self._article_repository.add_snapshot(
                    article_id=article.article_id,
                    snapshot_type="source_markdown",
                    content_text=fallback_markdown,
                    content_hash=sha256(fallback_markdown.encode("utf-8")).hexdigest(),
                    extractor="supadata",
                    extractor_version=None,
                )

            if self._llm_polish_enabled and chosen_markdown is not None:
                polished = self._polish_markdown_with_llm(
                    source_markdown=chosen_markdown,
                    source_url=canonical_url,
                )
                if polished is not None:
                    polished = _heuristic_markdown_polish(polished)
                    llm_polished = True
                    extraction_method = f"{extraction_method}+llm"
                    chosen_markdown = polished
                    self._article_repository.add_snapshot(
                        article_id=article.article_id,
                        snapshot_type="llm_markdown",
                        content_text=polished,
                        content_hash=sha256(polished.encode("utf-8")).hexdigest(),
                        extractor="llm_polish",
                        extractor_version=None,
                    )

        if _normalize_optional_text(chosen_markdown) is None:
            self._article_repository.update_article_failed(
                article_id=article.article_id,
                error_code="extraction_empty",
                error_message="Could not produce readable markdown.",
            )
            raise _TerminalPipelineError("extraction_empty")
        assert chosen_markdown is not None

        estimated_read_minutes = _estimate_read_minutes(chosen_markdown)
        final_title = (
            _normalize_optional_text(metadata.title)
            or _normalize_optional_text(article.title)
            or _title_from_url(canonical_url)
        )
        provenance = dict(article.provenance)
        provenance.update(
            {
                "source_url": article.source_url,
                "canonical_url": canonical_url,
                "fetched_at": datetime.now(UTC).isoformat(),
                "extraction_method": extraction_method,
                "llm_polished": llm_polished,
            }
        )

        updated = self._article_repository.update_article_readable(
            article_id=article.article_id,
            canonical_url=canonical_url,
            title=final_title,
            author=metadata.author,
            site_name=metadata.site_name,
            published_at=metadata.published_at,
            extraction_method=extraction_method,
            llm_polished=llm_polished,
            estimated_read_minutes=estimated_read_minutes,
            provenance=provenance,
        )
        if updated is None:
            raise _TerminalPipelineError("article_update_missing")

        self._telemetry.emit(
            "article.pipeline.processed",
            article_id=updated.article_id,
            status=updated.status,
            extraction_method=updated.extraction_method,
            llm_polished=updated.llm_polished,
        )
        self._sync_bucket_item(updated)

    def _sync_bucket_item(self, article: ArticleRecord) -> None:
        self._bucket_repository.update_item(
            item_id=article.bucket_item_id,
            metadata={
                "article_id": article.article_id,
                "article_status": article.status,
                "read_state": article.read_state,
                "estimated_read_minutes": article.estimated_read_minutes,
                "article_progress_percent": article.progress_percent,
                "article_last_error_code": article.last_error_code,
                "article_last_error_message": article.last_error_message,
                "canonical_url": article.canonical_url,
            },
            external_url=article.canonical_url,
        )

    def _fetch_html(self, url: str) -> _FetchResult:
        request = Request(
            url,
            headers={
                "Accept": "text/html,application/xhtml+xml",
                "User-Agent": self._user_agent,
            },
            method="GET",
        )
        try:
            with urlopen(request, timeout=self._fetch_timeout_seconds) as response:
                charset = response.headers.get_content_charset() or "utf-8"
                body = response.read().decode(charset, errors="replace")
                return _FetchResult(
                    html=body,
                    http_status=getattr(response, "status", None),
                    error_message=None,
                    retryable=False,
                )
        except HTTPError as exc:
            status_code = int(exc.code)
            retryable = status_code in {408, 425, 429, 500, 502, 503, 504}
            return _FetchResult(
                html=None,
                http_status=status_code,
                error_message=f"http_{status_code}",
                retryable=retryable,
            )
        except (URLError, TimeoutError, OSError) as exc:
            return _FetchResult(
                html=None,
                http_status=None,
                error_message=f"network_error:{type(exc).__name__}",
                retryable=True,
            )

    def _extract_markdown_with_trafilatura(
        self,
        *,
        html_text: str,
        source_url: str,
    ) -> str | None:
        try:
            module = import_module("trafilatura")
        except ModuleNotFoundError:
            return None

        extract = getattr(module, "extract", None)
        if not callable(extract):
            return None
        extracted = extract(
            html_text,
            url=source_url,
            output_format="markdown",
            favor_precision=True,
            include_comments=False,
            include_tables=False,
        )
        return _normalize_optional_text(extracted)

    def _extract_markdown_with_supadata(self, source_url: str) -> str | None:
        if not self._supadata_fallback_enabled or self._supadata_api_key is None:
            return None
        payload = {
            "url": source_url,
            "format": "markdown",
            "mode": "readable",
        }
        response = self._post_supadata_json(path="/scrape", payload=payload)
        if response is None:
            return None
        return _extract_markdown_from_payload(response)

    def _polish_markdown_with_llm(
        self,
        *,
        source_markdown: str,
        source_url: str,
    ) -> str | None:
        if _normalize_optional_text(source_markdown) is None:
            return None

        if self._supadata_api_key is not None:
            payload = {
                "url": source_url,
                "input_markdown": source_markdown,
                "format": "markdown",
                "polish": "llm",
            }
            response = self._post_supadata_json(path="/scrape", payload=payload)
            extracted = _extract_markdown_from_payload(response) if response is not None else None
            if extracted is not None:
                return extracted

        polished = _heuristic_markdown_polish(source_markdown)
        return polished if _normalize_optional_text(polished) is not None else None

    def _post_supadata_json(self, *, path: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        if self._supadata_api_key is None:
            return None

        request = Request(
            f"{self._supadata_base_url}{path}",
            data=json.dumps(payload, ensure_ascii=True).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "X-Api-Key": self._supadata_api_key,
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self._supadata_timeout_seconds) as response:
                raw = response.read().decode("utf-8", errors="replace")
        except (HTTPError, URLError, TimeoutError, OSError):
            return None

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return None
        if not isinstance(parsed, dict):
            return None
        raw_dict = cast(dict[object, object], parsed)
        response_dict: dict[str, Any] = {}
        for key, value in raw_dict.items():
            if isinstance(key, str):
                response_dict[key] = value
        return response_dict

    def _is_markdown_quality_ok(self, markdown_text: str | None) -> bool:
        normalized = _normalize_optional_text(markdown_text)
        if normalized is None:
            return False
        text = re.sub(r"\s+", " ", normalized)
        if len(text) < self._quality_min_chars:
            return False
        lines = [line.strip() for line in normalized.splitlines() if line.strip()]
        return len(lines) >= 5

    def _apply_domain_backoff(self, *, domain: str | None, http_status: int | None) -> None:
        if domain is None:
            return
        existing = self._article_repository.get_domain_throttle(domain=domain)
        next_level = 1 if existing is None else max(1, existing.backoff_level + 1)
        seconds = min(
            self._domain_backoff_max_seconds,
            self._domain_backoff_base_seconds * (2 ** (next_level - 1)),
        )
        next_allowed_at = datetime.now(UTC) + timedelta(seconds=seconds)
        self._article_repository.upsert_domain_throttle(
            domain=domain,
            next_allowed_at=next_allowed_at,
            backoff_level=next_level,
            last_http_status=http_status,
        )
        LOGGER.info(
            "article domain backoff applied domain=%s backoff_level=%s wait_seconds=%s http_status=%s",
            domain,
            next_level,
            seconds,
            http_status,
        )


@dataclass(frozen=True)
class _FetchResult:
    html: str | None
    http_status: int | None
    error_message: str | None
    retryable: bool


@dataclass(frozen=True)
class _ArticleMetadata:
    canonical_url: str | None
    title: str | None
    author: str | None
    site_name: str | None
    published_at: str | None


class _ArticleMetadataParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._meta: dict[str, str] = {}
        self._title_parts: list[str] = []
        self._capture_title = False
        self.canonical_href: str | None = None

    @property
    def title_text(self) -> str | None:
        if not self._title_parts:
            return None
        return _normalize_optional_text("".join(self._title_parts))

    def meta_value(self, key: str) -> str | None:
        return _normalize_optional_text(self._meta.get(key.lower()))

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_name = tag.lower()
        attrs_map = {name.lower(): (value or "").strip() for name, value in attrs}
        if tag_name == "title":
            self._capture_title = True
            return
        if tag_name == "link":
            rel = attrs_map.get("rel", "").lower()
            href = attrs_map.get("href")
            if "canonical" in rel and _normalize_optional_text(href) is not None:
                self.canonical_href = cast(str, href)
            return
        if tag_name != "meta":
            return
        key = (
            attrs_map.get("property")
            or attrs_map.get("name")
            or attrs_map.get("itemprop")
            or attrs_map.get("http-equiv")
        )
        value = attrs_map.get("content")
        normalized_key = _normalize_optional_text(key)
        normalized_value = _normalize_optional_text(unescape(value or ""))
        if normalized_key is None or normalized_value is None:
            return
        lowered = normalized_key.lower()
        if lowered not in self._meta:
            self._meta[lowered] = normalized_value

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self._capture_title = False

    def handle_data(self, data: str) -> None:
        if self._capture_title:
            self._title_parts.append(unescape(data))


def _extract_article_metadata(source_url: str, html_text: str) -> _ArticleMetadata:
    parser = _ArticleMetadataParser()
    parser.feed(html_text)
    parser.close()
    canonical_candidate = parser.canonical_href or parser.meta_value("og:url")
    canonical_url = normalize_article_url(urljoin(source_url, canonical_candidate or ""))
    title = (
        parser.meta_value("og:title")
        or parser.meta_value("twitter:title")
        or parser.meta_value("title")
        or parser.title_text
    )
    author = (
        parser.meta_value("article:author")
        or parser.meta_value("author")
        or parser.meta_value("parsely-author")
        or parser.meta_value("dc.creator")
    )
    site_name = (
        parser.meta_value("og:site_name")
        or parser.meta_value("application-name")
        or parser.meta_value("publisher")
    )
    published_at = (
        parser.meta_value("article:published_time")
        or parser.meta_value("og:published_time")
        or parser.meta_value("publish_date")
        or parser.meta_value("pubdate")
        or parser.meta_value("date")
        or parser.meta_value("parsely-pub-date")
    )
    return _ArticleMetadata(
        canonical_url=canonical_url,
        title=title,
        author=author,
        site_name=site_name,
        published_at=published_at,
    )


def normalize_article_url(value: str | None) -> str | None:
    normalized = _normalize_optional_text(value)
    if normalized is None:
        return None
    parsed = urlparse(normalized)
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"}:
        return None
    host = (parsed.hostname or "").lower().strip()
    if not host:
        return None

    port = parsed.port
    netloc = host
    is_default_port = (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    if port is not None and not is_default_port:
        netloc = f"{host}:{port}"

    path = parsed.path or "/"
    path = re.sub(r"/{2,}", "/", path)
    if path != "/":
        path = path.rstrip("/")
    if not path:
        path = "/"

    kept_query: list[tuple[str, str]] = []
    for key, query_value in parse_qsl(parsed.query, keep_blank_values=False):
        normalized_key = key.lower().strip()
        if not normalized_key:
            continue
        if normalized_key.startswith("utm_") or normalized_key in TRACKING_QUERY_PARAMS:
            continue
        kept_query.append((key.strip(), query_value.strip()))
    kept_query.sort(key=lambda item: (item[0].lower(), item[1]))
    query = urlencode(kept_query, doseq=True)
    return urlunparse((scheme, netloc, path, "", query, ""))


def _extract_markdown_from_payload(payload: dict[str, Any] | None) -> str | None:
    if payload is None:
        return None
    direct_candidates: list[object] = [
        payload.get("markdown"),
        payload.get("content"),
        payload.get("text"),
        payload.get("result"),
    ]
    nested = payload.get("data")
    if isinstance(nested, dict):
        nested_dict = cast(dict[object, object], nested)
        direct_candidates.extend(
            [
                nested_dict.get("markdown"),
                nested_dict.get("content"),
                nested_dict.get("text"),
            ]
        )

    for candidate in direct_candidates:
        normalized = _normalize_optional_text(candidate)
        if normalized is not None:
            return normalized
    return None


def _heuristic_markdown_polish(source_markdown: str) -> str:
    lines = [line.rstrip() for line in source_markdown.splitlines()]
    cleaned: list[str] = []
    in_code_block = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code_block = not in_code_block
            cleaned.append(stripped)
            continue
        if in_code_block:
            cleaned.append(line.rstrip())
            continue
        cleaned.append(re.sub(r"\s+", " ", stripped))

    polished: list[str] = []
    in_code_block = False
    for idx, line in enumerate(cleaned):
        stripped_line = line.strip()
        if stripped_line.startswith("```"):
            in_code_block = not in_code_block
            polished.append(stripped_line)
            continue
        if in_code_block:
            polished.append(line)
            continue

        if not line:
            prev_line = polished[-1] if polished else ""
            next_line = _next_nonempty(cleaned, idx + 1)
            if (
                prev_line
                and next_line is not None
                and _can_merge_markdown_lines(prev_line, next_line)
            ):
                continue
            if polished and polished[-1] == "":
                continue
            polished.append("")
            continue

        if polished and _can_merge_markdown_lines(polished[-1], line):
            joiner = "" if line[:1] in {".", ",", ";", ":", "!", "?", ")", "]", "}"} else " "
            polished[-1] = f"{polished[-1]}{joiner}{line}".strip()
            continue
        polished.append(line)

    polished = _split_merged_bullet_lines(polished)
    return "\n".join(polished).strip()


def _next_nonempty(lines: list[str], start_index: int) -> str | None:
    for idx in range(start_index, len(lines)):
        if lines[idx]:
            return lines[idx]
    return None


def _can_merge_markdown_lines(previous_line: str, current_line: str) -> bool:
    prev = previous_line.strip()
    curr = current_line.strip()
    if not prev or not curr:
        return False
    if _is_list_item_line(prev):
        return _is_list_continuation_line(curr)
    if _is_structural_markdown_line(prev) or _is_structural_markdown_line(curr):
        return False

    if len(curr) <= 3:
        return True
    if curr[0].islower():
        return True
    if curr[0] in {".", ",", ";", ":", "!", "?", ")", "]", "}", "`", "'"}:
        return True
    if prev.endswith(("`", "(", "[", "{", "/", "-")):
        return True
    return bool(not prev.endswith((".", "!", "?")))


def _is_list_item_line(line: str) -> bool:
    stripped = line.strip()
    return bool(re.match(r"^([-*+]\s+|\d+\.\s+)", stripped))


def _is_list_continuation_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if _is_structural_markdown_line(stripped):
        return False
    if len(stripped) <= 3:
        return True
    if stripped[0].islower():
        return True
    return bool(stripped[0] in {".", ",", ";", ":", "!", "?", ")", "]", "}", "`", "'", "("})


def _is_structural_markdown_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return True
    if stripped.startswith("```"):
        return True
    if re.match(r"^#{1,6}\s+", stripped):
        return True
    if re.match(r"^[-*+]\s+", stripped):
        return True
    if re.match(r"^\d+\.\s+", stripped):
        return True
    if stripped.startswith(">"):
        return True
    return bool(stripped.startswith("|"))


def _split_merged_bullet_lines(lines: list[str]) -> list[str]:
    split_lines: list[str] = []
    for line in lines:
        match = re.match(r"^(-\s.+?)\s-\s([A-Z][^\n]+)$", line)
        if match is None:
            split_lines.append(line)
            continue
        split_lines.append(match.group(1))
        split_lines.append(f"- {match.group(2)}")
    return split_lines


def _estimate_read_minutes(markdown_text: str) -> int:
    words = re.findall(r"[A-Za-z0-9]+", markdown_text)
    if not words:
        return 1
    minutes = max(1, round(len(words) / 220.0))
    return int(minutes)


def _title_from_url(value: str) -> str:
    parsed = urlparse(value)
    slug = parsed.path.rsplit("/", 1)[-1].strip()
    if not slug:
        host = parsed.hostname or "article"
        return f"Article from {host}"
    slug = re.sub(r"\.[a-z0-9]{2,4}$", "", slug, flags=re.IGNORECASE)
    words = re.split(r"[-_]+", slug)
    cleaned = " ".join(word for word in words if word)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        host = parsed.hostname or "article"
        return f"Article from {host}"
    return cleaned.title()


def _normalize_optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized:
        return None
    return normalized


def markdown_to_html(markdown_text: str) -> str:
    escaped_lines: list[str] = []
    in_code_block = False
    for raw_line in markdown_text.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if stripped.startswith("```"):
            if in_code_block:
                escaped_lines.append("</code></pre>")
                in_code_block = False
            else:
                escaped_lines.append("<pre><code>")
                in_code_block = True
            continue
        if in_code_block:
            escaped_lines.append(escape(line))
            continue
        if not stripped:
            escaped_lines.append("")
            continue
        heading_match = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if heading_match is not None:
            level = len(heading_match.group(1))
            text = escape(heading_match.group(2).strip())
            escaped_lines.append(f"<h{level}>{text}</h{level}>")
            continue
        escaped_lines.append(f"<p>{escape(stripped)}</p>")
    if in_code_block:
        escaped_lines.append("</code></pre>")
    return "\n".join(escaped_lines)
