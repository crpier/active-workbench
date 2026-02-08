from __future__ import annotations

from datetime import UTC, datetime, timedelta

from backend.app.repositories.vault_repository import VaultDocument
from backend.app.services.content_analysis import (
    build_routine_review_markdown,
    build_weekly_digest_markdown,
    extract_actions_from_documents,
    extract_actions_from_text,
    extract_recipe_from_transcript,
    extract_summary_from_text,
    prioritize_bucket_list_items,
)


def _doc(title: str, body: str, days_ago: int = 0, category: str = "notes") -> VaultDocument:
    created = datetime.now(UTC) - timedelta(days=days_ago)
    return VaultDocument(
        document_id=f"doc-{title}",
        title=title,
        tool="vault.note.save",
        created_at=created,
        updated_at=created,
        source_refs=[],
        body=body,
        relative_path=f"vault/{category}/{title}.md",
    )


def test_extract_recipe_from_transcript() -> None:
    transcript = """
Ingredients: 2 leeks, 1 cup cream
Chop the leeks.
Cook for 10 minutes.
Serve warm.
"""
    recipe = extract_recipe_from_transcript(transcript, title="Leek Dish")
    assert recipe.title == "Leek Dish"
    assert recipe.ingredients
    assert recipe.steps


def test_extract_summary_from_text() -> None:
    text = (
        "Microservices allow independent deployments. "
        "Observability must include traces and metrics. "
        "Retries need limits to avoid cascading failures."
    )
    summary = extract_summary_from_text(text, max_points=2)
    assert len(summary.key_ideas) == 2
    assert summary.notable_phrases


def test_extract_actions_from_text_and_documents() -> None:
    text = "TODO: Define boundaries\nWe should improve tracing"
    actions = extract_actions_from_text(text, source_title="Note")
    assert actions

    documents = [_doc("actions", text)]
    from_docs = extract_actions_from_documents(documents)
    assert from_docs
    assert from_docs[0].source_path is not None


def test_weekly_digest_and_routine_review_builders() -> None:
    notes = [
        _doc("microservices", "service boundaries and architecture", days_ago=1),
        _doc("recipe", "cook leeks with olive oil", days_ago=2),
    ]
    digest = build_weekly_digest_markdown(notes, now=datetime.now(UTC))
    assert "Themes" in digest
    assert "Highlights" in digest

    review = build_routine_review_markdown(
        upcoming_items=["leeks"],
        bucket_items=[_doc("andor", "watch this", category="bucket-list")],
        recent_notes=notes,
        now=datetime.now(UTC),
    )
    assert "Expiring Items" in review
    assert "Bucket List" in review


def test_prioritize_bucket_list_items() -> None:
    items = [
        _doc("older", "effort: low\ncost: medium", days_ago=5, category="bucket-list"),
        _doc("newer", "effort: high\ncost: low", days_ago=1, category="bucket-list"),
    ]
    prioritized = prioritize_bucket_list_items(items)
    assert prioritized
    assert prioritized[0]["title"] == "older"
