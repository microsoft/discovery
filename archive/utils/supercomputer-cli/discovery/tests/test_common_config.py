"""Tests for discovery.common.config module."""

from __future__ import annotations

import os

import pytest

from discovery.common import config


def test_load_settings_default() -> None:
    """Test load_settings returns default prefix when no env var set."""
    # Clear the cache to ensure fresh state
    config.load_settings.cache_clear()

    # Remove the PREFIX env var if it exists
    env_backup = os.environ.pop("PREFIX", None)
    try:
        settings = config.load_settings()
        assert settings.prefix == "default"
    finally:
        # Restore env var if it existed
        if env_backup is not None:
            os.environ["PREFIX"] = env_backup
        config.load_settings.cache_clear()


def test_load_settings_with_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test load_settings uses PREFIX env var when set."""
    # Clear the cache to ensure fresh state
    config.load_settings.cache_clear()

    monkeypatch.setenv("PREFIX", "custom-prefix")
    try:
        settings = config.load_settings()
        assert settings.prefix == "custom-prefix"
    finally:
        config.load_settings.cache_clear()


def test_settings_dataclass() -> None:
    """Test Settings dataclass can be instantiated directly."""
    settings = config.Settings(prefix="test-prefix")
    assert settings.prefix == "test-prefix"


def test_settings_default_value() -> None:
    """Test Settings dataclass has correct default value."""
    settings = config.Settings()
    assert settings.prefix == "default"


def test_load_settings_caching(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that load_settings caches results."""
    config.load_settings.cache_clear()

    monkeypatch.setenv("PREFIX", "cached-value")
    try:
        # First call
        settings1 = config.load_settings()
        assert settings1.prefix == "cached-value"

        # Change env var - should NOT affect result due to caching
        monkeypatch.setenv("PREFIX", "new-value")
        settings2 = config.load_settings()

        # Should be the same object due to caching
        assert settings1 is settings2
        assert settings2.prefix == "cached-value"
    finally:
        config.load_settings.cache_clear()
