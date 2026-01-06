"""Daybook commands for Workbench CLI."""

import click
import subprocess
from datetime import datetime, timedelta
from ..config import Config
from ..vault import Vault


@click.command()
def today():
    """Open today's daybook."""
    config = Config.load()
    vault = Vault(config.vault_path)

    daybook_path = vault.get_daybook_path()

    if not daybook_path.exists():
        vault.create_daybook_from_template(daybook_path)

    subprocess.run([config.editor, str(daybook_path)])


@click.command()
def yesterday():
    """Open yesterday's daybook."""
    config = Config.load()
    vault = Vault(config.vault_path)

    yesterday_date = datetime.now() - timedelta(days=1)
    daybook_path = vault.get_daybook_path(yesterday_date)

    if not daybook_path.exists():
        click.echo(f"Yesterday's daybook doesn't exist: {daybook_path}")
        return

    subprocess.run([config.editor, str(daybook_path)])
