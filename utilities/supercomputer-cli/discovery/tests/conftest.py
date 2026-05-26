"""Pytest fixtures for discovery tests."""

from __future__ import annotations

import pytest

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
