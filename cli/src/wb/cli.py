"""Main CLI entry point for Workbench."""

import click
from .commands import daybook, projects, writing, utils


@click.group()
@click.version_option(version="0.1.0")
def main():
    """Workbench - Knowledge management CLI for active work."""
    pass


# Daybook commands
main.add_command(daybook.today)
main.add_command(daybook.yesterday)

# Project commands
main.add_command(projects.new)
main.add_command(projects.list_projects)
main.add_command(projects.compile_project, name="compile")
main.add_command(projects.solve)
main.add_command(projects.block)
main.add_command(projects.resume)

# Writing commands
main.add_command(writing.write)
main.add_command(writing.ideas)
main.add_command(writing.publish)

# Utility commands
main.add_command(utils.inbox)
main.add_command(utils.triage)
main.add_command(utils.search)
main.add_command(utils.status)


if __name__ == "__main__":
    main()
