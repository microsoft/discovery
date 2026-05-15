"""AI Infrastructure MCP server package.

Contains the MCP server plus its tools and SSH configuration helpers.

We intentionally avoid importing the heavy ``server`` module at package import
time because running ``python -m ai_infrastructure_mcp.server`` (or similar execution via
``runpy``) can trigger a warning like:

	RuntimeWarning: 'ai_infrastructure_mcp.server' found in sys.modules after import of
	package 'ai_infrastructure_mcp', but prior to execution of 'ai_infrastructure_mcp.server'; this may
	result in unpredictable behaviour

That warning appears when ``__init__`` eagerly imports ``server`` while
``runpy`` is preparing to execute it as a script. To avoid the partially
initialized module scenario we provide a lazy attribute proxy for
``build_server``.
"""

from importlib import import_module
from typing import Any

__all__ = ["build_server"]


def __getattr__(name: str) -> Any:  # pragma: no cover - trivial
    if name == "build_server":
        # Lazy import to avoid runpy warning when executing server module
        return import_module("ai_infrastructure_mcp.server").build_server  # type: ignore[attr-defined]
    raise AttributeError(f"module 'ai_infrastructure_mcp' has no attribute {name!r}")
