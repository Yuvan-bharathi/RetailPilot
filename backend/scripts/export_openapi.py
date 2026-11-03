"""Write the FastAPI OpenAPI spec to a file (input for `npm run gen:api` in the frontend).

Usage (from backend/):  uv run python -m scripts.export_openapi ../frontend/openapi.json
"""

import json
import sys
from pathlib import Path

from app.main import app


def main(argv: list[str]) -> int:
    target = Path(argv[1]) if len(argv) > 1 else Path("../frontend/openapi.json")
    target.write_text(json.dumps(app.openapi(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"OpenAPI spec written to {target.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
