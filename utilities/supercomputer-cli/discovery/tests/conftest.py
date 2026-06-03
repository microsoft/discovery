"""Pytest fixtures for discovery tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from discovery.common import auto_update
from discovery.common import logging as disc_logging


@pytest.fixture(autouse=True)
def reset_logging_console():
    """Reset the Rich console singleton before each test.
    
    This is necessary because the logging module caches a Rich Console 
    instance with a reference to sys.stdout. When using Typer's CliRunner,
    stdout is redirected and then closed after each test. The cached console
    then holds a reference to a closed file, causing "I/O operation on closed file"
    errors in subsequent tests.
    
    This fixture runs automatically before every test to ensure a fresh console.
    """
    disc_logging._STATE.console = None
    disc_logging._STATE.file_logger = None
    yield
    disc_logging._STATE.console = None
    disc_logging._STATE.file_logger = None


@pytest.fixture(autouse=True)
def isolate_job_history(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Redirect ``~/.discovery`` writes to a per-test tmp directory.

    Prevents tests from accidentally polluting the developer's real
    job-history file when they exercise CLI commands that invoke the
    submit / history paths.
    """
    fake_home = tmp_path / "fake-home"
    fake_home.mkdir()
    monkeypatch.setattr(
        "discovery.common.job_history.get_home_dir", lambda: fake_home
    )


@pytest.fixture(autouse=True)
def disable_auto_update_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Disable real network update checks during tests.

    Tests that exercise the auto-update code paths should mock the
    relevant helpers explicitly. This autouse fixture guarantees that
    no test accidentally hits ``api.github.com`` simply because it
    invokes the CLI through Typer's ``CliRunner``.
    """
    monkeypatch.setenv(auto_update.ENV_OPT_OUT, "1")
