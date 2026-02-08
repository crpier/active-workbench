from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.dependencies import reset_cached_dependencies
from backend.app.main import create_app


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("ACTIVE_WORKBENCH_DATA_DIR", str(tmp_path / "runtime-data"))
    reset_cached_dependencies()

    app = create_app()
    with TestClient(app) as test_client:
        yield test_client

    reset_cached_dependencies()
