"""Tests for the ``discovery.poll.az_extensions`` module."""

from __future__ import annotations

import subprocess as sp

import pytest

from discovery.poll import az_extensions
from discovery.poll.azcli import run_az


def _make_proc(returncode: int = 0, stdout: str = "", stderr: str = ""):
    class Proc:
        def __init__(self) -> None:
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    return Proc()


def _unexpected_command(cmd: list[str]) -> AssertionError:
    """Build an AssertionError for an unexpected subprocess command.

    Extracted to satisfy ruff's EM102 rule (no f-string literals in raise).
    """
    msg = f"unexpected command: {cmd}"
    return AssertionError(msg)


# ---------------------------------------------------------------------------
# is_extension_installed
# ---------------------------------------------------------------------------


def test_is_extension_installed_true(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **kw: _make_proc(returncode=0, stdout='{"name": "resource-graph"}'),
    )
    assert az_extensions.is_extension_installed("resource-graph") is True


def test_is_extension_installed_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **kw: _make_proc(returncode=1, stderr="ERROR: extension 'x' is not installed"),
    )
    assert az_extensions.is_extension_installed("not-real") is False


# ---------------------------------------------------------------------------
# check_extension / check_required_extensions
# ---------------------------------------------------------------------------


def test_check_extension_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("subprocess.run", lambda *a, **kw: _make_proc(returncode=0, stdout="{}"))
    r = az_extensions.check_extension("resource-graph")
    assert r.ok is True
    assert r.action == "already-installed"
    assert r.name == "resource-graph"


def test_check_extension_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **kw: _make_proc(returncode=1, stderr="not installed"),
    )
    r = az_extensions.check_extension("resource-graph")
    assert r.ok is False
    assert r.action == "missing"
    # Detail should suggest a remediation command.
    assert "az extension add --name resource-graph" in r.detail


def test_check_required_extensions_uses_default_list(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("subprocess.run", lambda *a, **kw: _make_proc(returncode=0, stdout="{}"))
    results = az_extensions.check_required_extensions()
    assert [r.name for r in results] == list(az_extensions.REQUIRED_EXTENSIONS)
    assert all(r.ok for r in results)


def test_check_required_extensions_explicit_names(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "subprocess.run", lambda *a, **kw: _make_proc(returncode=1, stderr="missing")
    )
    results = az_extensions.check_required_extensions(["foo", "bar"])
    assert [r.name for r in results] == ["foo", "bar"]
    assert not any(r.ok for r in results)


# ---------------------------------------------------------------------------
# ensure_extension
# ---------------------------------------------------------------------------


def test_ensure_extension_already_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    """When the extension is present, no install command is issued."""
    calls: list[list[str]] = []

    def fake_run(cmd, *a, **kw):
        calls.append(list(cmd))
        # First call (`az extension show`) succeeds → already installed.
        return _make_proc(returncode=0, stdout="{}")

    monkeypatch.setattr("subprocess.run", fake_run)
    r = az_extensions.ensure_extension("resource-graph")
    assert r.ok is True
    assert r.action == "already-installed"
    # Only the show probe should have been invoked, never `extension add`.
    assert len(calls) == 1
    assert calls[0][:3] == ["az", "extension", "show"]


def test_ensure_extension_installs_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing extension triggers `az extension add` and a re-check."""
    calls: list[list[str]] = []
    # Two probes (show: missing, add: ok, show: ok).
    show_states = iter([1, 0])

    def fake_run(cmd, *a, **kw):
        calls.append(list(cmd))
        if cmd[:3] == ["az", "extension", "show"]:
            rc = next(show_states)
            return _make_proc(returncode=rc, stdout="{}" if rc == 0 else "")
        if cmd[:3] == ["az", "extension", "add"]:
            return _make_proc(returncode=0, stdout="installed")
        raise _unexpected_command(cmd)

    monkeypatch.setattr("subprocess.run", fake_run)
    r = az_extensions.ensure_extension("resource-graph")
    assert r.ok is True
    assert r.action == "installed"
    # Sequence: show (miss) → add → show (hit).
    cmds = [c[:3] for c in calls]
    assert cmds == [
        ["az", "extension", "show"],
        ["az", "extension", "add"],
        ["az", "extension", "show"],
    ]
    # `--name <name>` should appear in the add command.
    add_call = calls[1]
    assert "--name" in add_call
    assert "resource-graph" in add_call


def test_ensure_extension_install_failure_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    """A failed install yields a structured ExtensionResult, not a raise."""

    def fake_run(cmd, *a, **kw):
        if cmd[:3] == ["az", "extension", "show"]:
            return _make_proc(returncode=1)
        if cmd[:3] == ["az", "extension", "add"]:
            return _make_proc(returncode=2, stderr="HTTP 503 from extension index")
        raise _unexpected_command(cmd)

    monkeypatch.setattr("subprocess.run", fake_run)
    r = az_extensions.ensure_extension("resource-graph")
    assert r.ok is False
    assert r.action == "install-failed"
    assert "HTTP 503" in r.detail


def test_ensure_extension_install_succeeds_but_show_still_misses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If install reports success but the extension is still not visible,
    treat it as a failure so the caller doesn't proceed under a false
    sense of safety, and surface a concrete actionable detail (not
    "exited with code 0")."""
    # Both show probes return missing; add returns success.

    def fake_run(cmd, *a, **kw):
        if cmd[:3] == ["az", "extension", "show"]:
            return _make_proc(returncode=1)
        if cmd[:3] == ["az", "extension", "add"]:
            return _make_proc(returncode=0)
        raise _unexpected_command(cmd)

    monkeypatch.setattr("subprocess.run", fake_run)
    r = az_extensions.ensure_extension("resource-graph")
    assert r.ok is False
    assert r.action == "install-failed"
    # Detail must NOT claim "exited with code 0" (the legacy bug).
    assert "code 0" not in r.detail
    # And must include the actionable hint.
    assert "still not registered" in r.detail


def test_ensure_extension_failure_detail_keeps_stderr_tail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When stderr is long, the *tail* (where helpful info usually lives —
    HTTP status, URL, error code) must be preserved, not truncated away."""
    long_prefix = "x" * 1000
    helpful_tail = "ERROR: HTTP 503 from https://aka.ms/AzExtensions"
    stderr = long_prefix + helpful_tail

    def fake_run(cmd, *a, **kw):
        if cmd[:3] == ["az", "extension", "show"]:
            return _make_proc(returncode=1)
        if cmd[:3] == ["az", "extension", "add"]:
            return _make_proc(returncode=2, stderr=stderr)
        raise _unexpected_command(cmd)

    monkeypatch.setattr("subprocess.run", fake_run)
    r = az_extensions.ensure_extension("resource-graph")
    assert r.action == "install-failed"
    assert "HTTP 503" in r.detail
    assert "aka.ms/AzExtensions" in r.detail


def test_is_extension_installed_handles_missing_az_binary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If ``az`` itself is not installed, :func:`is_extension_installed`
    must return ``False`` cleanly so callers (notably ``discovery doctor``)
    render a useful diagnostic instead of crashing with a traceback."""

    def boom(*a, **kw):
        msg = "az: not found"
        raise FileNotFoundError(msg)

    monkeypatch.setattr("subprocess.run", boom)
    assert az_extensions.is_extension_installed("resource-graph") is False


# ---------------------------------------------------------------------------
# ensure_required_extensions
# ---------------------------------------------------------------------------


def test_ensure_required_extensions_all_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("subprocess.run", lambda *a, **kw: _make_proc(returncode=0, stdout="{}"))
    results = az_extensions.ensure_required_extensions()
    assert results
    assert all(r.ok for r in results)
    assert all(r.action == "already-installed" for r in results)


def test_ensure_required_extensions_aggregates_per_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each name produces its own ExtensionResult, in iteration order."""
    # First name is already installed; second one fails to install.
    state = {"i": 0}

    def fake_run(cmd, *a, **kw):
        # We don't track per-name state across calls — instead let the
        # first show succeed and the second show fail and add fail.
        if cmd[:3] == ["az", "extension", "show"]:
            state["i"] += 1
            if state["i"] == 1:
                return _make_proc(returncode=0)  # "foo": installed
            return _make_proc(returncode=1)  # "bar": missing, then re-check missing
        if cmd[:3] == ["az", "extension", "add"]:
            return _make_proc(returncode=2, stderr="boom")
        raise _unexpected_command(cmd)

    monkeypatch.setattr("subprocess.run", fake_run)
    results = az_extensions.ensure_required_extensions(["foo", "bar"])
    assert [r.name for r in results] == ["foo", "bar"]
    assert results[0].ok is True
    assert results[1].ok is False
    assert results[1].action == "install-failed"


# ---------------------------------------------------------------------------
# Module invariants
# ---------------------------------------------------------------------------


def test_required_extensions_includes_resource_graph() -> None:
    """`resource-graph` is the extension behind ``az graph query``;
    the Discovery CLI relies on it in :mod:`discovery.poll.resources`."""
    assert "resource-graph" in az_extensions.REQUIRED_EXTENSIONS


def test_run_az_passes_devnull_stdin_and_disables_dynamic_install(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """:func:`discovery.poll.azcli.run_az` must pin stdin and the
    ``AZURE_EXTENSION_USE_DYNAMIC_INSTALL`` env var so missing-extension
    prompts can never freeze the CLI. This is the safety contract every
    other ``az`` invocation in the package depends on."""
    captured: dict = {}

    def fake_run(cmd, *args, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return _make_proc(returncode=0, stdout="{}")

    # Set a sentinel env var on the parent process so we can verify
    # ``run_az`` forwards the existing environment instead of replacing it
    # with a single-key dict (which would strip PATH, HOME, AZURE_CONFIG_DIR
    # etc. and silently break every az call).
    monkeypatch.setenv("DISCOVERY_AZCLI_TEST_SENTINEL", "preserved")
    monkeypatch.setattr("subprocess.run", fake_run)
    run_az(["az", "graph", "query", "-q", "..."])
    assert captured["kwargs"].get("stdin") is sp.DEVNULL
    env = captured["kwargs"].get("env") or {}
    assert env.get("AZURE_EXTENSION_USE_DYNAMIC_INSTALL") == "no"
    # The parent environment must be passed through, not replaced.
    assert env.get("DISCOVERY_AZCLI_TEST_SENTINEL") == "preserved"
    # PATH is required for ``az`` itself to be locatable in the child.
    assert "PATH" in env
    assert captured["kwargs"].get("capture_output") is True
    assert captured["kwargs"].get("text") is True
    assert captured["kwargs"].get("check") is False
