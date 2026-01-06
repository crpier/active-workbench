# Workbench CLI - Quick Start

## Installation

The CLI is already installed! It's located at:
```
~/Projects/active-workbench/cli/
```

A symlink has been created at `~/bin/wb`. After restarting your terminal (or running `source ~/.bashrc`), you can use `wb` from anywhere.

For now, use the full path:
```bash
~/bin/wb <command>
```

## Available Commands

### Daily Workflow

```bash
wb today              # Open today's daybook (creates from template if needed)
wb yesterday          # Open yesterday's daybook
```

### Project Management

```bash
wb new <project-name>         # Create new project
wb list                       # Show all ongoing and hiatus projects
wb compile <project-name>     # Extract [project-name] entries from daybook
wb solve [project-name]       # Mark project as solved (interactive if no name)
wb block [project-name]       # Move project to hiatus (interactive if no name)
wb resume <project-name>      # Move project from hiatus back to ongoing
```

### Writing Workflow

```bash
wb write <title>      # Create/open draft in writing/drafts/
wb ideas              # Open writing ideas file
wb publish <title>    # Move draft to writing/published/YYYY-MM/
```

### Utilities

```bash
wb inbox              # Open limbo/Inbox.md
wb triage             # Open limbo/ directory for processing voice notes
wb search <term>      # Search across all daybook entries
wb status             # Show dashboard (projects, limbo notes, drafts)
```

## Quick Workflow Example

### Start your day:
```bash
wb today
```

This opens today's daybook. Start logging your work:

```markdown
## Engineering Log (UTC)
- 10:30 [learn-keyboard]
  Started practicing keyboard. Finger positioning is tricky.

- 14:00 [fix-auth-bug]
  Production bug: users getting logged out randomly.
  Checking server logs...
```

### Create a project:
```bash
wb new learn-keyboard
```

This creates `projects/personal/ongoing/learn-keyboard.md`.

### Compile your work:
```bash
wb compile learn-keyboard
```

This extracts all `[learn-keyboard]` entries from your daybook and appends them to the project log.

### Review your projects:
```bash
wb list
```

Shows:
```
ONGOING
  - learn-keyboard (started 2026-01-04)

HIATUS
  (none)
```

### When done:
```bash
wb solve learn-keyboard
```

Moves the project to `projects/personal/solved/2026-01/`.

## Configuration

Config file: `~/.config/workbench/config.yaml`

```yaml
vault_path: /home/crpier/vault
editor: nvim
```

The CLI will create this with defaults on first run if it doesn't exist.

## Next Steps

1. **Start using it today**: Run `wb today` and start logging
2. **Create a test project**: `wb new test-project`
3. **Try compilation**: Tag some entries with `[test-project]` then run `wb compile test-project`
4. **Check status**: Run `wb status` to see your dashboard

## Tips

- **Tag everything**: Use `[project-name]` tags in your daybook entries so they can be compiled later
- **Compile weekly**: Every Sunday, compile your active projects to see the week's progress
- **Don't over-organize**: The system works best when you just write and compile later, not when you perfectly categorize up front

## Development

The CLI is installed in editable mode, so any changes you make to the source code will be immediately available.

Project structure:
```
~/Projects/active-workbench/cli/
├── src/wb/
│   ├── cli.py          # Main entry point
│   ├── config.py       # Configuration handling
│   ├── vault.py        # Vault operations
│   └── commands/       # Individual command modules
└── pyproject.toml      # Package configuration
```

To reinstall after changes:
```bash
cd ~/Projects/active-workbench/cli
uv pip install -e .
```
