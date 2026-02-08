from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import pytest

from backend.app.models.tool_contracts import ToolResponse
from backend.app.scripts.export_openapi import main as export_openapi


def test_tool_response_default_fields() -> None:
    response = ToolResponse(ok=True, request_id=uuid4())
    assert response.result == {}
    assert response.provenance == []


def test_export_openapi_writes_schema(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    export_openapi()

    output = tmp_path / "openapi" / "openapi.json"
    assert output.exists()

    schema = cast(dict[str, Any], json.loads(output.read_text(encoding="utf-8")))
    assert schema["info"]["title"] == "Active Workbench API"
    assert "/tools" in schema["paths"]
