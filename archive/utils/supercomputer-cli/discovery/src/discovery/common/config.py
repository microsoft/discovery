"""Minimal settings loader used in tests.

Reconstructed after module creation for logging refactor.
Provides load_settings() with environment override behavior expected by tests.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass
class Settings:
    prefix: str = "default"


@lru_cache(maxsize=1)
def load_settings() -> Settings:
    return Settings(prefix=os.getenv("PREFIX", "default"))
