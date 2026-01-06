"""Service for git auto-commit and push."""

import subprocess
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


class GitSync:
    """Handles automatic git commits and pushes."""

    def __init__(self, vault_path: Path):
        self.vault_path = vault_path

    def commit_and_push(self, file_path: Path):
        """Auto-commit and push new note.

        Args:
            file_path: Path to the file to commit
        """
        try:
            # Get relative path for git
            relative_path = file_path.relative_to(self.vault_path)

            # Stage the file
            subprocess.run(
                ["git", "add", str(relative_path)],
                cwd=self.vault_path,
                check=True,
                capture_output=True
            )

            # Commit
            commit_msg = f"Add voice note: {file_path.name}"
            subprocess.run(
                ["git", "commit", "-m", commit_msg],
                cwd=self.vault_path,
                check=True,
                capture_output=True
            )

            # Push
            subprocess.run(
                ["git", "push"],
                cwd=self.vault_path,
                check=True,
                capture_output=True
            )

            logger.info(f"Successfully synced: {file_path.name}")

        except subprocess.CalledProcessError as e:
            # Log error but don't fail the request
            logger.error(f"Git sync failed: {e}")
            logger.error(f"stdout: {e.stdout.decode() if e.stdout else 'none'}")
            logger.error(f"stderr: {e.stderr.decode() if e.stderr else 'none'}")

    def is_git_repo(self) -> bool:
        """Check if vault is a git repository."""
        try:
            subprocess.run(
                ["git", "rev-parse", "--git-dir"],
                cwd=self.vault_path,
                check=True,
                capture_output=True
            )
            return True
        except subprocess.CalledProcessError:
            return False
