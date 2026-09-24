"""Tests for the POL-009 helper functions inside validate_pr.py.

These complement test_model_weights_sniffer.py: that suite covers the
header-validation layer; this suite covers the picklescan integration
and the fail-closed behaviour added in response to security review.
"""

from __future__ import annotations

import io
import pickle
import zipfile
from pathlib import Path

import pytest

from validate_pr import _is_lfs_tracked_strict, _picklescan_unsafe_imports


def _make_torch_zip(path: Path, archive_name: str = "archive",
                    pickle_obj: object | None = None) -> None:
    """Minimal mimic of torch.save(obj, path) zip layout (mirrors sniffer tests)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
        payload = pickle.dumps(pickle_obj if pickle_obj is not None else {"state": 1})
        z.writestr(f"{archive_name}/data.pkl", payload)
        z.writestr(f"{archive_name}/version", "3\n")
    path.write_bytes(buf.getvalue())


def _picklescan_installed() -> bool:
    try:
        import picklescan  # noqa: F401
        return True
    except ImportError:
        return False


@pytest.mark.skipif(not _picklescan_installed(),
                    reason="real picklescan path requires the picklescan package")
def test_picklescan_clean_torch_zip(tmp_path: Path) -> None:
    """A torch ZIP whose pickle is a plain dict has no GLOBAL imports."""
    p = tmp_path / "model.pt"
    _make_torch_zip(p, pickle_obj={"layer.weight": [1.0, 2.0, 3.0]})
    bad = _picklescan_unsafe_imports(p)
    assert bad == [], f"expected clean, got {bad}"


def test_picklescan_fails_closed_when_missing(tmp_path: Path, monkeypatch) -> None:
    """If picklescan is unavailable, return a sentinel so the caller fails POL-009.

    Soft-passing on missing dependencies in a security gate silently
    weakens enforcement (POL-009 reviewer feedback). This test simulates
    the no-picklescan environment by hiding the import.
    """
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "picklescan" or name.startswith("picklescan."):
            raise ImportError("simulated: picklescan not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    p = tmp_path / "model.pt"
    _make_torch_zip(p)
    bad = _picklescan_unsafe_imports(p)
    assert bad, "expected a hard failure sentinel when picklescan is missing"
    assert any("picklescan" in entry.lower() and "not installed" in entry.lower()
               for entry in bad)


# ── LFS tracking: CI must fail closed, local mode is best-effort ────────────

def test_lfs_check_fails_closed_in_ci_when_indeterminate(
    tmp_path: Path, monkeypatch
) -> None:
    """When git can't determine LFS status AND we're running in CI, return False.

    Reviewer #3: an environmental glitch must not silently bypass POL-009 in CI.
    """
    import validate_pr
    monkeypatch.setattr(validate_pr, "_is_lfs_tracked", lambda repo, p: None)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.delenv("CI", raising=False)
    assert _is_lfs_tracked_strict(tmp_path, "weights.pt", ".pt") is False


def test_lfs_check_best_effort_locally_when_indeterminate(
    tmp_path: Path, monkeypatch
) -> None:
    """Outside CI, an indeterminate git result returns True (best-effort).

    Local dev experience: a missing git or a worktree quirk shouldn't block
    iteration. Acceptance is granted only because we are NOT in CI.
    """
    import validate_pr
    monkeypatch.setattr(validate_pr, "_is_lfs_tracked", lambda repo, p: None)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("CI", raising=False)
    assert _is_lfs_tracked_strict(tmp_path, "weights.pt", ".pt") is True


def test_lfs_check_definitive_result_passes_through(
    tmp_path: Path, monkeypatch
) -> None:
    """A definitive True/False from git is honoured regardless of CI mode."""
    import validate_pr
    monkeypatch.setattr(validate_pr, "_is_lfs_tracked", lambda repo, p: True)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    assert _is_lfs_tracked_strict(tmp_path, "x.pt", ".pt") is True

    monkeypatch.setattr(validate_pr, "_is_lfs_tracked", lambda repo, p: False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("CI", raising=False)
    assert _is_lfs_tracked_strict(tmp_path, "x.pt", ".pt") is False


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
