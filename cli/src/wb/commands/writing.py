"""Writing workflow commands for Workbench CLI."""

import click
import subprocess
from datetime import datetime
from rich.console import Console
from ..config import Config
from ..vault import Vault

console = Console()


@click.command()
@click.argument("title")
def write(title: str):
    """Create or open a writing draft."""
    config = Config.load()
    vault = Vault(config.vault_path)

    # Sanitize title for filename
    filename = title.replace(" ", "-").lower()
    draft_path = vault.writing / "drafts" / f"{filename}.md"

    if not draft_path.exists():
        template = f"""---
tags: []
---

# {title}

"""
        draft_path.write_text(template)
        console.print(f"[green]Created draft:[/green] {title}")

    subprocess.run([config.editor, str(draft_path)])


@click.command()
def ideas():
    """Open writing ideas file."""
    config = Config.load()
    vault = Vault(config.vault_path)

    ideas_path = vault.writing / "ideas" / "Blog ideas.md"

    if not ideas_path.exists():
        template = """---
tags: []
---

# Blog ideas

-
"""
        ideas_path.write_text(template)

    subprocess.run([config.editor, str(ideas_path)])


@click.command()
@click.argument("title")
def publish(title: str):
    """Move draft to published."""
    config = Config.load()
    vault = Vault(config.vault_path)

    # Find draft
    filename = title.replace(" ", "-").lower()
    draft_path = vault.writing / "drafts" / f"{filename}.md"

    if not draft_path.exists():
        console.print(f"[red]Draft not found: {title}[/red]")
        return

    # Move to published
    month = datetime.now().strftime("%Y-%m")
    published_dir = vault.writing / "published" / month
    published_dir.mkdir(parents=True, exist_ok=True)

    dest_path = published_dir / f"{filename}.md"

    draft_path.rename(dest_path)

    console.print(f"[green]Published {title} to {month}/[/green]")
