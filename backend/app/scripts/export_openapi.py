from __future__ import annotations

import json
from pathlib import Path

from backend.app.main import app


def main() -> None:
    openapi_dir = Path("openapi")
    openapi_dir.mkdir(parents=True, exist_ok=True)
    schema_path = openapi_dir / "openapi.json"
    schema_path.write_text(json.dumps(app.openapi(), indent=2), encoding="utf-8")
    print(f"Wrote OpenAPI schema to {schema_path}")


if __name__ == "__main__":
    main()
