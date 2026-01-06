"""Vault operations for Workbench."""

from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Optional


class Vault:
    """Represents the vault directory and provides operations on it."""

    def __init__(self, vault_path: Path):
        self.path = vault_path
        self.daybook = vault_path / "daybook"
        self.projects = vault_path / "projects"
        self.writing = vault_path / "writing"
        self.limbo = vault_path / "limbo"
        self.templates = vault_path / "templates"

    def ensure_structure(self):
        """Create vault directory structure if it doesn't exist."""
        self.daybook.mkdir(parents=True, exist_ok=True)
        (self.projects / "personal" / "ongoing").mkdir(parents=True, exist_ok=True)
        (self.projects / "personal" / "solved").mkdir(parents=True, exist_ok=True)
        (self.projects / "life" / "ongoing").mkdir(parents=True, exist_ok=True)
        (self.projects / "life" / "solved").mkdir(parents=True, exist_ok=True)
        (self.projects / "hiatus").mkdir(parents=True, exist_ok=True)
        (self.writing / "ideas").mkdir(parents=True, exist_ok=True)
        (self.writing / "drafts").mkdir(parents=True, exist_ok=True)
        (self.writing / "published").mkdir(parents=True, exist_ok=True)
        self.limbo.mkdir(parents=True, exist_ok=True)
        self.templates.mkdir(parents=True, exist_ok=True)

    def get_daybook_path(self, date: Optional[datetime] = None) -> Path:
        """Get path to daybook for given date (or today)."""
        if date is None:
            date = datetime.now()

        year_month = date.strftime("%Y-%m")
        filename = date.strftime("%Y-%m-%d.md")

        daybook_dir = self.daybook / year_month
        daybook_dir.mkdir(parents=True, exist_ok=True)

        return daybook_dir / filename

    def create_daybook_from_template(self, path: Path):
        """Create new daybook from template."""
        date = datetime.now()

        template = f"""---
tags: []
---

# {date.strftime("%Y-%m-%d")}

## Standup
- **Yesterday**:
- **Today**:
- **Blockers**:

## Priority Tasks
- [ ]

## Engineering Log (UTC)
- {date.strftime("%H:%M")}

## Code Reviews / PRs
- [ ]

## Notes & Links
-
"""
        path.write_text(template)

    def list_projects(self, status: str = "ongoing") -> List[Path]:
        """List projects by status (ongoing, hiatus, solved)."""
        if status == "ongoing":
            personal = list((self.projects / "personal" / "ongoing").glob("*.md"))
            life = list((self.projects / "life" / "ongoing").glob("*.md"))
            return personal + life
        elif status == "hiatus":
            return list((self.projects / "hiatus").glob("*.md"))
        elif status == "solved":
            personal = list((self.projects / "personal" / "solved").rglob("*.md"))
            life = list((self.projects / "life" / "solved").rglob("*.md"))
            return personal + life
        return []

    def find_project(self, name: str) -> Optional[Path]:
        """Find a project file by name, checking ongoing and hiatus."""
        # Check personal/ongoing
        path = self.projects / "personal" / "ongoing" / f"{name}.md"
        if path.exists():
            return path

        # Check life/ongoing
        path = self.projects / "life" / "ongoing" / f"{name}.md"
        if path.exists():
            return path

        # Check hiatus
        path = self.projects / "hiatus" / f"{name}.md"
        if path.exists():
            return path

        return None

    def create_project(self, name: str, category: str = "personal") -> Path:
        """Create new project file."""
        date = datetime.now().strftime("%Y-%m-%d")
        project_path = self.projects / category / "ongoing" / f"{name}.md"

        if project_path.exists():
            return project_path

        template = f"""# {name}

**Started:** {date}
**Status:** ongoing
**Goal:**
**Last updated:** {date}

---

## Compiled Log

(No entries yet. Run: wb compile {name})

---

## Key Insights

"""
        project_path.write_text(template)
        return project_path

    def compile_project(self, project_name: str) -> int:
        """Extract [project_name] entries from daybook and append to project log."""
        # Find project file
        project_path = self.find_project(project_name)

        if not project_path:
            raise FileNotFoundError(f"Project not found: {project_name}")

        # Search daybook files for [project_name] entries
        entries = []

        for daybook_file in self.daybook.rglob("*.md"):
            if not daybook_file.is_file():
                continue

            content = daybook_file.read_text()
            lines = content.split("\n")

            # Extract date from filename
            date = daybook_file.stem

            # Find lines with [project_name] tag
            i = 0
            while i < len(lines):
                line = lines[i]
                if f"[{project_name}]" in line:
                    # Extract the entry (current line and following indented lines)
                    entry_lines = [line]

                    # Get following indented lines
                    j = i + 1
                    while j < len(lines):
                        next_line = lines[j]
                        # Stop if we hit a non-indented line or another timestamp entry
                        if next_line and not next_line.startswith(("  ", "\t")) and not next_line.strip() == "":
                            break
                        entry_lines.append(next_line)
                        j += 1

                    entry_text = "\n".join(entry_lines)
                    entries.append((date, entry_text))
                    i = j
                else:
                    i += 1

        if not entries:
            return 0

        # Read current project content
        content = project_path.read_text()

        # Find where to insert (before "## Key Insights" if it exists)
        if "## Key Insights" in content:
            parts = content.split("## Key Insights")
            before = parts[0]
            after = "## Key Insights" + parts[1]
        else:
            before = content
            after = ""

        # Append entries
        new_content = before.rstrip() + "\n\n"
        for date, entry in entries:
            new_content += f"### {date}\n\n"
            new_content += f"{entry}\n\n"
            new_content += "---\n\n"

        if after:
            new_content += "\n" + after

        # Update "Last updated" date
        today = datetime.now().strftime("%Y-%m-%d")
        new_content = new_content.replace(
            f"**Last updated:** {content.split('**Last updated:** ')[1].split('\n')[0] if '**Last updated:**' in content else date}",
            f"**Last updated:** {today}"
        )

        project_path.write_text(new_content)

        return len(entries)

    def get_project_category(self, project_path: Path) -> str:
        """Determine category (personal/life) from project path."""
        if "personal" in str(project_path):
            return "personal"
        elif "life" in str(project_path):
            return "life"
        return "personal"
