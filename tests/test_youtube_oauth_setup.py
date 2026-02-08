from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.scripts.youtube_oauth_setup import copy_client_secret_if_needed
from backend.app.services.youtube_service import YouTubeServiceError


def test_copy_client_secret_if_needed(tmp_path: Path) -> None:
    source = tmp_path / "source.json"
    source.write_text('{"installed": {}}', encoding="utf-8")

    destination = tmp_path / "nested" / "dest.json"
    copy_client_secret_if_needed(source, destination)

    assert destination.exists()
    assert destination.read_text(encoding="utf-8") == '{"installed": {}}'


def test_copy_client_secret_missing_file_raises(tmp_path: Path) -> None:
    missing = tmp_path / "missing.json"
    destination = tmp_path / "dest.json"

    with pytest.raises(YouTubeServiceError):
        copy_client_secret_if_needed(missing, destination)
