"""Service for writing notes to vault."""

from pathlib import Path
from datetime import datetime
import re


class VaultWriter:
    """Handles writing voice notes to the vault."""

    def __init__(self, vault_path: Path):
        self.vault_path = vault_path
        self.limbo_path = vault_path / "limbo"
        self.limbo_path.mkdir(parents=True, exist_ok=True)

    def create_voice_note(self, text: str, timestamp: datetime) -> Path:
        """Create individual note in limbo/ from voice capture.

        Args:
            text: The voice note text
            timestamp: When the note was captured

        Returns:
            Path to the created note file
        """
        # Generate filename from content (first 50 chars, sanitized)
        title = self._generate_title(text)
        filename = f"{timestamp.strftime('%Y-%m-%d-%H%M%S')}-{title}.md"

        note_path = self.limbo_path / filename

        # Ensure unique filename
        counter = 1
        while note_path.exists():
            filename = f"{timestamp.strftime('%Y-%m-%d-%H%M%S')}-{title}-{counter}.md"
            note_path = self.limbo_path / filename
            counter += 1

        # Create note with frontmatter
        content = self._format_note(text, timestamp)
        note_path.write_text(content)

        return note_path

    def _generate_title(self, text: str) -> str:
        """Generate filename-safe title from text.

        Takes first 50 chars, removes special characters, replaces spaces with hyphens.
        """
        # Take first 50 chars
        title = text[:50]

        # Remove special characters, replace spaces with hyphens
        title = re.sub(r'[^\w\s-]', '', title)
        title = re.sub(r'[\s]+', '-', title)
        title = title.strip('-').lower()

        return title or "voice-note"

    def _format_note(self, text: str, timestamp: datetime) -> str:
        """Format note with frontmatter."""
        return f"""---
tags: []
captured: {timestamp.isoformat()}
source: voice
status: needs-triage
---

# Voice Note

{text}
"""
