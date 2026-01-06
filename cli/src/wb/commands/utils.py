"""Utility commands for Workbench CLI."""

import click
import subprocess
from rich.console import Console
from ..config import Config
from ..vault import Vault

console = Console()


@click.command()
def inbox():
    """Open inbox file."""
    config = Config.load()
    vault = Vault(config.vault_path)

    inbox_path = vault.limbo / "Inbox.md"

    if not inbox_path.exists():
        template = """---
tags: []
---

# Inbox

## Articles

## Books

## Research bucket

"""
        inbox_path.write_text(template)

    subprocess.run([config.editor, str(inbox_path)])


@click.command()
def triage():
    """Open limbo directory for triage."""
    config = Config.load()
    vault = Vault(config.vault_path)

    # Open directory in editor
    subprocess.run([config.editor, str(vault.limbo)])


@click.command()
@click.argument("term")
def search(term: str):
    """Search across daybook entries."""
    config = Config.load()
    vault = Vault(config.vault_path)

    console.print(f"Searching for: [cyan]{term}[/cyan]\n")

    # Use grep to search
    try:
        result = subprocess.run(
            ["grep", "-r", "-n", term, str(vault.daybook)],
            capture_output=True,
            text=True
        )

        if result.stdout:
            console.print(result.stdout)
        else:
            console.print("[yellow]No results found[/yellow]")

    except FileNotFoundError:
        console.print("[red]grep command not found[/red]")


@click.command()
def status():
    """Show dashboard with current status."""
    config = Config.load()
    vault = Vault(config.vault_path)

    console.print("\n[bold cyan]Workbench Status[/bold cyan]\n")

    # Projects
    ongoing = vault.list_projects("ongoing")
    hiatus = vault.list_projects("hiatus")

    console.print(f"[bold]Projects:[/bold]")
    console.print(f"  Ongoing: {len(ongoing)}")
    console.print(f"  Hiatus: {len(hiatus)}")

    # Limbo
    limbo_notes = list(vault.limbo.glob("*.md"))
    limbo_notes = [n for n in limbo_notes if n.name != "Inbox.md"]

    console.print(f"\n[bold]Triage:[/bold]")
    console.print(f"  Notes in limbo: {len(limbo_notes)}")

    # Writing
    drafts = list((vault.writing / "drafts").glob("*.md"))

    console.print(f"\n[bold]Writing:[/bold]")
    console.print(f"  Drafts in progress: {len(drafts)}")

    console.print()
