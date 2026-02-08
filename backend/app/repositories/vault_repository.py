from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from uuid import uuid4

from backend.app.repositories.common import utc_now_iso


@dataclass(frozen=True)
class SavedDocument:
    document_id: str
    relative_path: str


@dataclass(frozen=True)
class VaultDocument:
    document_id: str
    title: str
    tool: str
    created_at: datetime
    updated_at: datetime
    source_refs: list[dict[str, str]]
    body: str
    relative_path: str


class VaultRepository:
    def __init__(self, vault_dir: Path) -> None:
        self._vault_dir = vault_dir

    def save_document(
        self,
        category: str,
        title: str,
        body: str,
        tool_name: str,
        source_refs: list[dict[str, str]],
    ) -> SavedDocument:
        category_dir = self._vault_dir / category
        category_dir.mkdir(parents=True, exist_ok=True)

        document_id = f"doc_{uuid4().hex}"
        timestamp = utc_now_iso()
        slug = _slugify(title)
        file_name = f"{timestamp[:10]}-{slug}-{document_id[-8:]}.md"
        document_path = category_dir / file_name

        frontmatter_lines = [
            "---",
            f"id: {document_id}",
            f"created_at: {timestamp}",
            f"updated_at: {timestamp}",
            f"tool: {tool_name}",
            f"title: {title}",
            f"source_refs: {json.dumps(source_refs, ensure_ascii=True)}",
            "---",
            "",
            f"# {title}",
            "",
            body.strip() or "No content provided.",
            "",
        ]
        document_path.write_text("\n".join(frontmatter_lines), encoding="utf-8")

        relative_path = document_path.relative_to(self._vault_dir.parent).as_posix()
        return SavedDocument(document_id=document_id, relative_path=relative_path)

    def list_documents(self, category: str, limit: int = 50) -> list[VaultDocument]:
        category_dir = self._vault_dir / category
        if not category_dir.exists():
            return []

        markdown_files = sorted(
            [path for path in category_dir.glob("*.md") if path.is_file()],
            key=lambda file_path: file_path.stat().st_mtime,
            reverse=True,
        )

        documents: list[VaultDocument] = []
        for path in markdown_files[:limit]:
            parsed = _parse_markdown_document(path, root=self._vault_dir.parent)
            if parsed is not None:
                documents.append(parsed)

        return documents


def _parse_markdown_document(path: Path, *, root: Path) -> VaultDocument | None:
    raw = path.read_text(encoding="utf-8")
    frontmatter, body = _split_frontmatter(raw)
    if frontmatter is None:
        return None

    document_id = frontmatter.get("id") or f"doc_{uuid4().hex}"
    title = frontmatter.get("title") or path.stem
    tool = frontmatter.get("tool") or "unknown"
    created_at = _parse_datetime(frontmatter.get("created_at"))
    updated_at = _parse_datetime(frontmatter.get("updated_at"))
    source_refs = _parse_source_refs(frontmatter.get("source_refs"))

    return VaultDocument(
        document_id=document_id,
        title=title,
        tool=tool,
        created_at=created_at,
        updated_at=updated_at,
        source_refs=source_refs,
        body=body.strip(),
        relative_path=path.relative_to(root).as_posix(),
    )


def _split_frontmatter(raw: str) -> tuple[dict[str, str] | None, str]:
    if not raw.startswith("---\n"):
        return None, raw

    parts = raw.split("\n---\n", maxsplit=1)
    if len(parts) != 2:
        return None, raw

    frontmatter_with_marker, remainder = parts
    if not frontmatter_with_marker.startswith("---\n"):
        return None, raw

    frontmatter_block = frontmatter_with_marker[len("---\n") :]

    frontmatter: dict[str, str] = {}
    for line in frontmatter_block.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        frontmatter[key.strip()] = value.strip()

    return frontmatter, remainder


def _parse_datetime(value: str | None) -> datetime:
    if value is None:
        return datetime.now(UTC)

    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return datetime.now(UTC)

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _parse_source_refs(value: str | None) -> list[dict[str, str]]:
    if value is None:
        return []

    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []

    if not isinstance(parsed, list):
        return []
    parsed_items = cast(list[object], parsed)

    refs: list[dict[str, str]] = []
    for raw_item in parsed_items:
        if not isinstance(raw_item, dict):
            continue

        item = cast(dict[object, object], raw_item)
        raw_type = item.get("type")
        raw_id = item.get("id")
        if isinstance(raw_type, str) and isinstance(raw_id, str):
            refs.append({"type": raw_type, "id": raw_id})
    return refs


def _slugify(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9]+", "-", value.lower()).strip("-")
    if normalized:
        return normalized[:60]
    return "untitled"
