"""Configuration management for backend."""

from pathlib import Path
from pydantic_settings import BaseSettings
import yaml


class Config(BaseSettings):
    """Backend configuration."""

    vault_path: Path = Path.home() / "vault"
    host: str = "0.0.0.0"
    port: int = 8765

    @classmethod
    def from_yaml(cls, path: Path):
        """Load from YAML file."""
        with open(path) as f:
            data = yaml.safe_load(f) or {}
        return cls(**data)


# Global config instance
_config = None


def get_config() -> Config:
    """Get or create config instance."""
    global _config
    if _config is None:
        config_path = Path.home() / ".config" / "workbench" / "config.yaml"
        if config_path.exists():
            _config = Config.from_yaml(config_path)
        else:
            _config = Config()
    return _config
