"""Project management commands for Workbench CLI."""

import click
import subprocess
from rich.console import Console
from datetime import datetime
from ..config import Config
from ..vault import Vault

console = Console()


@click.command()
@click.argument("name")
@click.option("--category", "-c", default="personal", help="Project category (personal/life)")
def new(name: str, category: str):
    """Create a new project."""
    config = Config.load()
    vault = Vault(config.vault_path)

    project_path = vault.create_project(name, category)

    if project_path.exists():
        console.print(f"[green]Created project:[/green] {name}")
        subprocess.run([config.editor, str(project_path)])
    else:
        console.print(f"[yellow]Project already exists:[/yellow] {name}")
        subprocess.run([config.editor, str(project_path)])


@click.command(name="list")
def list_projects():
    """List all active projects."""
    config = Config.load()
    vault = Vault(config.vault_path)

    console.print("\n[bold]ONGOING[/bold]")
    ongoing = vault.list_projects("ongoing")

    if ongoing:
        for project_path in ongoing:
            name = project_path.stem

            # Extract started date from file
            content = project_path.read_text()
            started = "unknown"
            for line in content.split("\n"):
                if line.startswith("**Started:**"):
                    started = line.split("**Started:**")[1].strip()
                    break

            console.print(f"  - {name} (started {started})")
    else:
        console.print("  (none)")

    console.print("\n[bold]HIATUS[/bold]")
    hiatus = vault.list_projects("hiatus")

    if hiatus:
        for project_path in hiatus:
            console.print(f"  - {project_path.stem}")
    else:
        console.print("  (none)")

    console.print()


@click.command()
@click.argument("name")
def compile_project(name: str):
    """Compile project log from daybook entries."""
    config = Config.load()
    vault = Vault(config.vault_path)

    try:
        count = vault.compile_project(name)

        if count > 0:
            console.print(f"[green]Added {count} entries to {name}[/green]")
        else:
            console.print(f"[yellow]No entries found for [{name}][/yellow]")

    except FileNotFoundError as e:
        console.print(f"[red]Error: {e}[/red]")
        console.print(f"\nCreate it first: [cyan]wb new {name}[/cyan]")


@click.command()
@click.argument("name", required=False)
def solve(name: str):
    """Mark project as solved."""
    config = Config.load()
    vault = Vault(config.vault_path)

    if not name:
        # Interactive mode
        ongoing = vault.list_projects("ongoing")

        if not ongoing:
            console.print("[yellow]No ongoing projects to solve[/yellow]")
            return

        console.print("Select project to mark as solved:")
        for i, project_path in enumerate(ongoing, 1):
            console.print(f"  {i}. {project_path.stem}")

        choice = click.prompt("Enter number", type=int)

        if 1 <= choice <= len(ongoing):
            project_path = ongoing[choice - 1]
            name = project_path.stem
        else:
            console.print("[red]Invalid choice[/red]")
            return
    else:
        project_path = vault.find_project(name)
        if not project_path:
            console.print(f"[red]Project not found: {name}[/red]")
            return

    # Determine category
    category = vault.get_project_category(project_path)

    # Move to solved
    month = datetime.now().strftime("%Y-%m")
    solved_dir = vault.projects / category / "solved" / month
    solved_dir.mkdir(parents=True, exist_ok=True)

    dest_path = solved_dir / f"{name}.md"

    # Update status in file
    content = project_path.read_text()
    content = content.replace("**Status:** ongoing", "**Status:** solved")
    project_path.write_text(content)

    # Move file
    project_path.rename(dest_path)

    console.print(f"[green]Moved {name} to solved/{month}/[/green]")


@click.command()
@click.argument("name", required=False)
def block(name: str):
    """Move project to hiatus."""
    config = Config.load()
    vault = Vault(config.vault_path)

    if not name:
        # Interactive mode
        ongoing = vault.list_projects("ongoing")

        if not ongoing:
            console.print("[yellow]No ongoing projects to block[/yellow]")
            return

        console.print("Select project to move to hiatus:")
        for i, project_path in enumerate(ongoing, 1):
            console.print(f"  {i}. {project_path.stem}")

        choice = click.prompt("Enter number", type=int)

        if 1 <= choice <= len(ongoing):
            project_path = ongoing[choice - 1]
            name = project_path.stem
        else:
            console.print("[red]Invalid choice[/red]")
            return
    else:
        project_path = vault.find_project(name)
        if not project_path:
            console.print(f"[red]Project not found: {name}[/red]")
            return

    # Move to hiatus
    dest_path = vault.projects / "hiatus" / f"{name}.md"

    # Update status
    content = project_path.read_text()
    content = content.replace("**Status:** ongoing", "**Status:** hiatus")
    project_path.write_text(content)

    project_path.rename(dest_path)

    console.print(f"[green]Moved {name} to hiatus/[/green]")


@click.command()
@click.argument("name")
def resume(name: str):
    """Move project from hiatus back to ongoing."""
    config = Config.load()
    vault = Vault(config.vault_path)

    # Find in hiatus
    hiatus_path = vault.projects / "hiatus" / f"{name}.md"

    if not hiatus_path.exists():
        console.print(f"[red]Project not found in hiatus: {name}[/red]")
        return

    # Determine original category from content or default to personal
    category = "personal"

    # Move back to ongoing
    dest_path = vault.projects / category / "ongoing" / f"{name}.md"

    # Update status
    content = hiatus_path.read_text()
    content = content.replace("**Status:** hiatus", "**Status:** ongoing")
    hiatus_path.write_text(content)

    hiatus_path.rename(dest_path)

    console.print(f"[green]Moved {name} back to ongoing/[/green]")
