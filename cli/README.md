# Workbench CLI (`wb`)

Knowledge management CLI tool for the Active Workbench system.

## Installation

```bash
cd ~/Projects/active-workbench/cli
uv pip install -e .
```

## Usage

```bash
wb today              # Open today's daybook
wb new <project>      # Create new project
wb list               # Show active projects
wb compile <project>  # Compile project log from daybook
wb solve [project]    # Mark project as solved
wb block [project]    # Move project to hiatus
```

## Configuration

Config file: `~/.config/workbench/config.yaml`

```yaml
vault_path: /home/crpier/vault
editor: nvim
```
