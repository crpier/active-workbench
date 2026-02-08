from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from backend.app.repositories.vault_repository import VaultDocument

STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "how",
    "i",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "was",
    "with",
    "you",
}

ACTION_PATTERNS = (
    re.compile(r"^\s*(?:-\s*)?(?:todo|task|action)\s*[:\-]\s*(.+)$", re.IGNORECASE),
    re.compile(r"\b(?:need to|should|must|follow up|remember to)\b", re.IGNORECASE),
)

INGREDIENT_PATTERN = re.compile(
    r"\b(\d+\s?/\s?\d+|\d+\.\d+|\d+)\s*(cup|cups|tbsp|tsp|g|kg|ml|l|oz|lb|clove|pinch)\b",
    re.IGNORECASE,
)

STEP_PREFIX_PATTERN = re.compile(r"^\s*(?:\d+[\.)]|-\s+)")


@dataclass(frozen=True)
class RecipeExtraction:
    title: str
    ingredients: list[str]
    steps: list[str]
    notes: list[str]


@dataclass(frozen=True)
class SummaryExtraction:
    key_ideas: list[str]
    notable_phrases: list[str]


@dataclass(frozen=True)
class ActionItem:
    action: str
    source_title: str | None
    source_path: str | None


def extract_recipe_from_transcript(transcript: str, title: str) -> RecipeExtraction:
    lines = [line.strip() for line in transcript.splitlines() if line.strip()]

    ingredients = [line for line in lines if INGREDIENT_PATTERN.search(line)]
    steps = [line for line in lines if _looks_like_step(line)]

    if not ingredients:
        ingredients = _fallback_ingredient_lines(lines)

    if not steps:
        steps = _fallback_steps(lines)

    notes = _take_nonempty(lines, limit=3)

    return RecipeExtraction(
        title=title,
        ingredients=_dedupe_keep_order(ingredients, max_items=15),
        steps=_dedupe_keep_order(steps, max_items=12),
        notes=_dedupe_keep_order(notes, max_items=5),
    )


def extract_summary_from_text(text: str, max_points: int = 5) -> SummaryExtraction:
    sentences = _split_sentences(text)
    if not sentences:
        return SummaryExtraction(key_ideas=[], notable_phrases=[])

    scored = _score_sentences(sentences)
    top = [sentence for sentence, _ in scored[:max_points]]
    phrases = _top_keywords(text, top_n=8)

    return SummaryExtraction(
        key_ideas=top,
        notable_phrases=phrases,
    )


def extract_actions_from_text(text: str, source_title: str | None = None) -> list[ActionItem]:
    actions: list[ActionItem] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        explicit = _extract_explicit_action(line)
        if explicit is not None:
            actions.append(ActionItem(action=explicit, source_title=source_title, source_path=None))
            continue

        if _contains_action_intent(line):
            actions.append(ActionItem(action=line, source_title=source_title, source_path=None))

    return _dedupe_actions(actions, max_items=15)


def extract_actions_from_documents(documents: list[VaultDocument]) -> list[ActionItem]:
    collected: list[ActionItem] = []
    for document in documents:
        for action in extract_actions_from_text(document.body, source_title=document.title):
            collected.append(
                ActionItem(
                    action=action.action,
                    source_title=document.title,
                    source_path=document.relative_path,
                )
            )
    return _dedupe_actions(collected, max_items=20)


def build_weekly_digest_markdown(notes: list[VaultDocument], now: datetime) -> str:
    lookback = now - timedelta(days=7)
    recent_notes = [note for note in notes if note.created_at >= lookback]

    if not recent_notes:
        return "No notes were captured in the last 7 days."

    theme_groups = _group_notes_by_theme(recent_notes)

    lines: list[str] = [
        f"Generated at: {now.astimezone(UTC).isoformat()}",
        "",
        "## Themes",
        "",
    ]

    for theme, theme_notes in theme_groups:
        lines.append(f"### {theme}")
        lines.append("")
        for note in theme_notes:
            lines.append(f"- {note.title} (`{note.relative_path}`)")
        lines.append("")

    highlights = _build_highlights(recent_notes)
    lines.append("## Highlights")
    lines.append("")
    for highlight in highlights:
        lines.append(f"- {highlight}")

    return "\n".join(lines).strip()


def build_routine_review_markdown(
    upcoming_items: list[str],
    bucket_items: list[VaultDocument],
    recent_notes: list[VaultDocument],
    now: datetime,
) -> str:
    lines: list[str] = [
        f"Generated at: {now.astimezone(UTC).isoformat()}",
        "",
        "## Expiring Items",
        "",
    ]

    if upcoming_items:
        for item in upcoming_items:
            lines.append(f"- {item}")
    else:
        lines.append("- No expiring items detected.")

    lines.extend(["", "## Bucket List", ""])
    if bucket_items:
        for item in bucket_items[:15]:
            lines.append(f"- {item.title}")
    else:
        lines.append("- Bucket list is empty.")

    lines.extend(["", "## Notes To Revisit", ""])
    if recent_notes:
        for note in recent_notes[:10]:
            lines.append(f"- {note.title} (`{note.relative_path}`)")
    else:
        lines.append("- No notes to revisit.")

    return "\n".join(lines).strip()


def prioritize_bucket_list_items(bucket_items: list[VaultDocument]) -> list[dict[str, Any]]:
    prioritized: list[dict[str, Any]] = []
    now = datetime.now(UTC)

    for item in bucket_items:
        waiting_days = max(0, int((now - item.created_at).days))
        effort = _extract_keyword_level(item.body, keyword="effort")
        cost = _extract_keyword_level(item.body, keyword="cost")

        prioritized.append(
            {
                "title": item.title,
                "path": item.relative_path,
                "waiting_days": waiting_days,
                "effort": effort,
                "cost": cost,
            }
        )

    def sort_key(entry: dict[str, Any]) -> tuple[int]:
        waiting = entry.get("waiting_days")
        return (int(waiting) if isinstance(waiting, int) else 0,)

    return sorted(prioritized, key=sort_key, reverse=True)


def _build_highlights(notes: list[VaultDocument]) -> list[str]:
    merged_text = "\n".join(note.body for note in notes)
    summary = extract_summary_from_text(merged_text, max_points=5)
    return summary.key_ideas


def _group_notes_by_theme(notes: list[VaultDocument]) -> list[tuple[str, list[VaultDocument]]]:
    categories: dict[str, list[VaultDocument]] = {
        "Architecture": [],
        "Food & Recipes": [],
        "Productivity": [],
        "General": [],
    }

    for note in notes:
        lower_text = f"{note.title}\n{note.body}".lower()
        if any(
            keyword in lower_text for keyword in ("service", "api", "microservice", "architecture")
        ):
            categories["Architecture"].append(note)
        elif any(keyword in lower_text for keyword in ("recipe", "cook", "ingredient", "food")):
            categories["Food & Recipes"].append(note)
        elif any(keyword in lower_text for keyword in ("task", "todo", "habit", "plan")):
            categories["Productivity"].append(note)
        else:
            categories["General"].append(note)

    return [(name, docs) for name, docs in categories.items() if docs]


def _split_sentences(text: str) -> list[str]:
    raw = re.split(r"(?<=[.!?])\s+", text)
    return [sentence.strip() for sentence in raw if len(sentence.strip()) > 25]


def _score_sentences(sentences: list[str]) -> list[tuple[str, float]]:
    word_counts = Counter(
        word
        for sentence in sentences
        for word in re.findall(r"[a-zA-Z]{3,}", sentence.lower())
        if word not in STOP_WORDS
    )

    if not word_counts:
        return [(sentence, 0.0) for sentence in sentences]

    max_freq = max(word_counts.values())
    normalized = {word: count / max_freq for word, count in word_counts.items()}

    scores: list[tuple[str, float]] = []
    for sentence in sentences:
        words = re.findall(r"[a-zA-Z]{3,}", sentence.lower())
        score = sum(normalized.get(word, 0.0) for word in words)
        scores.append((sentence, score))

    scores.sort(key=lambda item: item[1], reverse=True)
    return scores


def _top_keywords(text: str, top_n: int) -> list[str]:
    counts = Counter(
        word for word in re.findall(r"[a-zA-Z]{4,}", text.lower()) if word not in STOP_WORDS
    )
    return [word for word, _ in counts.most_common(top_n)]


def _looks_like_step(line: str) -> bool:
    if STEP_PREFIX_PATTERN.match(line):
        return True

    leading = line.lower().split(" ", 1)[0]
    return leading in {
        "add",
        "mix",
        "cook",
        "stir",
        "bake",
        "boil",
        "chop",
        "slice",
        "serve",
        "heat",
        "saute",
    }


def _fallback_ingredient_lines(lines: list[str]) -> list[str]:
    candidates = [line for line in lines if "," in line and len(line) < 120]
    if candidates:
        return candidates[:8]
    return lines[:6]


def _fallback_steps(lines: list[str]) -> list[str]:
    selected = [line for line in lines if len(line.split()) > 6]
    return selected[:8]


def _take_nonempty(lines: list[str], limit: int) -> list[str]:
    return [line for line in lines[:limit] if line]


def _dedupe_keep_order(items: list[str], max_items: int) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        normalized = item.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
        if len(result) >= max_items:
            break
    return result


def _extract_explicit_action(line: str) -> str | None:
    for pattern in ACTION_PATTERNS[:1]:
        match = pattern.search(line)
        if match:
            return match.group(1).strip()
    return None


def _contains_action_intent(line: str) -> bool:
    return any(pattern.search(line) for pattern in ACTION_PATTERNS[1:])


def _dedupe_actions(items: list[ActionItem], max_items: int) -> list[ActionItem]:
    seen: set[str] = set()
    deduped: list[ActionItem] = []
    for item in items:
        key = item.action.lower().strip()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(item)
        if len(deduped) >= max_items:
            break
    return deduped


def _extract_keyword_level(text: str, keyword: str) -> str | None:
    match = re.search(rf"{keyword}\s*[:\-]\s*(low|medium|high)", text, re.IGNORECASE)
    if match:
        return match.group(1).lower()
    return None
