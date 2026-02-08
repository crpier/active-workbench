from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from backend.app.repositories.common import utc_now_iso


@dataclass(frozen=True)
class SavedDocument:
    document_id: str
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


def _slugify(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9]+", "-", value.lower()).strip("-")
    if normalized:
        return normalized[:60]
    return "untitled"
