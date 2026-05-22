"""Pytest bootstrap for .github/tests/.

These tests exercise modules in .github/scripts/ via bare imports
(`from model_weights_sniffer import …`, `from validate_pr import …`).
Adding the scripts directory to sys.path here lets pytest pick the
suites up without requiring callers to set PYTHONPATH.

Run from the repo root with:
    python -m pytest .github/tests/
"""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))
