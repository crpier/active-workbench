"""Configuration management for Workbench."""

from pathlib import Path
from dataclasses import dataclass
import yaml


@dataclass
class Config:
    """Workbench configuration."""

    vault_path: Path
    editor: str = "nvim"

    @classmethod
    def load(cls) -> "Config":
        """Load config from ~/.config/workbench/config.yaml or use defaults."""
        config_path = Path.home() / ".config" / "workbench" / "config.yaml"

        if config_path.exists():
            with open(config_path) as f:
                data = yaml.safe_load(f) or {}
                return cls(
                    vault_path=Path(data.get("vault_path", Path.home() / "vault")),
                    editor=data.get("editor", "nvim")
                )

        # Default config
        return cls(vault_path=Path.home() / "vault")

    def save(self):
        """Save config to file."""
        config_path = Path.home() / ".config" / "workbench" / "config.yaml"
        config_path.parent.mkdir(parents=True, exist_ok=True)

        with open(config_path, "w") as f:
            yaml.dump({
                "vault_path": str(self.vault_path),
                "editor": self.editor
            }, f)
