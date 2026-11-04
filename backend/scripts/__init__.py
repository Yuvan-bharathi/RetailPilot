"""Developer scripts (not part of the app package).

The repo root is put on sys.path so scripts run from backend/ (`uv run python -m scripts.<name>`) can import the
synthetic data package `data` that lives at the repo root (pytest does the same via `pythonpath`).
"""

import sys
from pathlib import Path

_REPO_ROOT = str(Path(__file__).resolve().parents[2])
if _REPO_ROOT not in sys.path:
    sys.path.append(_REPO_ROOT)
