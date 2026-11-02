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

import pytest

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))


@pytest.fixture
def removal_offline(monkeypatch):
    import report_pr_review
    import urllib.request

    def unexpected_network(*args, **kwargs):
        pytest.fail("Unexpected real GitHub/network request in removal migration tests")

    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setattr(urllib.request, "urlopen", unexpected_network)
    monkeypatch.setattr(report_pr_review.GitHub, "request", unexpected_network)
