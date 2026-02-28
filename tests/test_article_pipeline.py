from __future__ import annotations

from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient

from backend.app.dependencies import get_article_pipeline_service


@dataclass(frozen=True)
class _FakeFetchResult:
    html: str | None
    http_status: int | None
    error_message: str | None
    retryable: bool


def test_article_capture_list_read_state_retry_and_delete(client: TestClient) -> None:
    capture_response = client.post(
        "/articles/capture",
        json={
            "url": "https://example.com/articles/personal-knowledge-systems",
            "source": "manual_paste",
        },
    )
    assert capture_response.status_code == 200
    capture_body = capture_response.json()
    assert capture_body["status"] in {"saved", "already_exists"}
    article_id = capture_body["article_id"]
    assert isinstance(article_id, str) and article_id.startswith("article_")

    list_response = client.get("/articles")
    assert list_response.status_code == 200
    list_body = list_response.json()
    assert list_body["count"] >= 1
    assert any(item["article_id"] == article_id for item in list_body["items"])

    update_response = client.patch(
        f"/articles/{article_id}/read-state",
        json={"read_state": "in_progress", "progress_percent": 35},
    )
    assert update_response.status_code == 200
    update_body = update_response.json()
    assert update_body["status"] == "updated"
    assert update_body["article"]["read_state"] == "in_progress"
    assert update_body["article"]["progress_percent"] == 35

    retry_response = client.post(f"/articles/{article_id}/retry")
    assert retry_response.status_code == 200
    assert retry_response.json()["status"] == "queued"

    delete_response = client.delete(f"/articles/{article_id}")
    assert delete_response.status_code == 200
    assert delete_response.json()["status"] == "deleted"

    missing_response = client.get(f"/articles/{article_id}")
    assert missing_response.status_code == 404


def test_article_pipeline_processing_exposes_readable(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture_response = client.post(
        "/articles/capture",
        json={
            "url": "https://example.com/articles/deep-work-guide",
            "source": "manual_paste",
            "process_now": False,
        },
    )
    assert capture_response.status_code == 200
    article_id = capture_response.json()["article_id"]
    assert isinstance(article_id, str)

    service = get_article_pipeline_service()
    html_payload = """
    <html>
      <head>
        <title>Deep Work Guide</title>
        <meta property="og:title" content="Deep Work Guide">
        <meta property="og:site_name" content="Example Notes">
        <meta name="author" content="Cal Newport">
      </head>
      <body><p>focus focus focus</p></body>
    </html>
    """.strip()
    markdown_payload = "# Deep Work Guide\n\n" + ("Focus on meaningful tasks. " * 160)

    def _fake_fetch_html(url: str) -> _FakeFetchResult:
        _ = url
        return _FakeFetchResult(
            html=html_payload,
            http_status=200,
            error_message=None,
            retryable=False,
        )

    def _fake_extract_markdown_with_trafilatura(*, html_text: str, source_url: str) -> str:
        _ = (html_text, source_url)
        return markdown_payload

    monkeypatch.setattr(service, "_fetch_html", _fake_fetch_html)
    monkeypatch.setattr(
        service,
        "_extract_markdown_with_trafilatura",
        _fake_extract_markdown_with_trafilatura,
    )

    stats = service.process_due_jobs(limit=10)
    assert stats.attempted >= 1
    assert stats.succeeded >= 1

    readable_response = client.get(f"/articles/{article_id}/readable")
    assert readable_response.status_code == 200
    readable_body = readable_response.json()
    assert readable_body["article"]["status"] == "readable"
    assert "Deep Work Guide" in (readable_body["default_markdown"] or "")

    legacy_redirect = client.get(f"/articles/web/{article_id}", follow_redirects=False)
    assert legacy_redirect.status_code == 308
    assert legacy_redirect.headers.get("location") == f"/app/articles/{article_id}"


def test_article_capture_processes_job_immediately(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = get_article_pipeline_service()
    html_payload = """
    <html>
      <head>
        <title>Immediate Capture Test</title>
        <meta property="og:title" content="Immediate Capture Test">
      </head>
      <body><p>content</p></body>
    </html>
    """.strip()
    markdown_payload = "# Immediate Capture Test\n\n" + ("Signal sentence. " * 180)

    def _fake_fetch_html(url: str) -> _FakeFetchResult:
        _ = url
        return _FakeFetchResult(
            html=html_payload,
            http_status=200,
            error_message=None,
            retryable=False,
        )

    def _fake_extract_markdown_with_trafilatura(*, html_text: str, source_url: str) -> str:
        _ = (html_text, source_url)
        return markdown_payload

    monkeypatch.setattr(service, "_fetch_html", _fake_fetch_html)
    monkeypatch.setattr(
        service,
        "_extract_markdown_with_trafilatura",
        _fake_extract_markdown_with_trafilatura,
    )

    response = client.post(
        "/articles/capture",
        json={
            "url": "https://example.com/articles/immediate-capture",
            "source": "manual_paste",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["article_status"] == "readable"
    article_id = body["article_id"]
    assert isinstance(article_id, str)

    article_response = client.get(f"/articles/{article_id}")
    assert article_response.status_code == 200
    assert article_response.json()["status"] == "readable"


def test_article_capture_process_now_false_leaves_captured(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = get_article_pipeline_service()
    html_payload = """
    <html>
      <head>
        <title>Deferred Capture Test</title>
      </head>
      <body><p>content</p></body>
    </html>
    """.strip()
    markdown_payload = "# Deferred Capture Test\n\n" + ("Signal sentence. " * 180)

    def _fake_fetch_html(url: str) -> _FakeFetchResult:
        _ = url
        return _FakeFetchResult(
            html=html_payload,
            http_status=200,
            error_message=None,
            retryable=False,
        )

    def _fake_extract_markdown_with_trafilatura(*, html_text: str, source_url: str) -> str:
        _ = (html_text, source_url)
        return markdown_payload

    monkeypatch.setattr(service, "_fetch_html", _fake_fetch_html)
    monkeypatch.setattr(
        service,
        "_extract_markdown_with_trafilatura",
        _fake_extract_markdown_with_trafilatura,
    )

    response = client.post(
        "/articles/capture",
        json={
            "url": "https://example.com/articles/deferred-capture",
            "source": "manual_paste",
            "process_now": False,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["article_status"] == "captured"
    article_id = body["article_id"]
    assert isinstance(article_id, str)

    article_response = client.get(f"/articles/{article_id}")
    assert article_response.status_code == 200
    assert article_response.json()["status"] == "captured"


def test_article_pipeline_polishes_readable_markdown(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture_response = client.post(
        "/articles/capture",
        json={
            "url": "https://example.com/articles/polish-readability",
            "source": "manual_paste",
            "process_now": False,
        },
    )
    assert capture_response.status_code == 200
    article_id = capture_response.json()["article_id"]
    assert isinstance(article_id, str)

    service = get_article_pipeline_service()
    html_payload = """
    <html>
      <head>
        <title>Polish Readability</title>
      </head>
      <body><p>content</p></body>
    </html>
    """.strip()
    markdown_payload = """
# Polish Readability

We all know `.env`

files are supposed to be gitignored.
- Someone clones the repo and asks for the
`.env`

file - They sit on disk in plaintext
CLI (`op`

) makes this easier.

```
first command
second command
```
""".strip()

    def _fake_fetch_html(url: str) -> _FakeFetchResult:
        _ = url
        return _FakeFetchResult(
            html=html_payload,
            http_status=200,
            error_message=None,
            retryable=False,
        )

    def _fake_extract_markdown_with_trafilatura(*, html_text: str, source_url: str) -> str:
        _ = (html_text, source_url)
        return markdown_payload

    monkeypatch.setattr(service, "_fetch_html", _fake_fetch_html)
    monkeypatch.setattr(
        service,
        "_extract_markdown_with_trafilatura",
        _fake_extract_markdown_with_trafilatura,
    )

    stats = service.process_due_jobs(limit=10)
    assert stats.succeeded >= 1

    readable_response = client.get(f"/articles/{article_id}/readable")
    assert readable_response.status_code == 200
    readable_body = readable_response.json()
    default_markdown = readable_body["default_markdown"] or ""
    assert "We all know `.env` files are supposed to be gitignored." in default_markdown
    assert "- Someone clones the repo and asks for the `.env` file" in default_markdown
    assert "- They sit on disk in plaintext" in default_markdown
    assert "CLI (`op`) makes this easier." in default_markdown
    assert "first command\nsecond command" in default_markdown
