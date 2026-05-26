"""Azure CLI extension management for the Discovery CLI.

The Discovery CLI relies on a small number of ``az`` extensions for the
queries it issues. Today this is only ``resource-graph`` (used by
:func:`discovery.poll.resources.list_containers_with_kind` for
``az graph query``), but the design accepts a list so additional
extensions can be added without ripple-changes.

Two consumption modes:

* :func:`ensure_required_extensions` — used by ``discovery configure`` and
  any other command that *needs* the extensions present. It auto-installs
  missing extensions using ``az extension add`` and returns a structured
  result so callers can render a friendly message and abort cleanly on
  failure.
* :func:`check_required_extensions` — used by ``discovery doctor`` for a
  read-only diagnostic. It never mutates state; missing extensions are
  reported alongside an actionable hint.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from discovery.common.logging import debug, info

from .azcli import run_az


__all__ = [
    "REQUIRED_EXTENSIONS",
    "ExtensionResult",
    "check_extension",
    "check_required_extensions",
    "ensure_extension",
    "ensure_required_extensions",
    "is_extension_installed",
]


REQUIRED_EXTENSIONS: tuple[str, ...] = ("resource-graph",)
"""Extensions the Discovery CLI requires for its ``az`` queries.

``resource-graph`` provides ``az graph query``, used to enrich Discovery
container resources with their ``kind`` discriminator in a single call.
Without it the CLI would hang on a hidden install prompt under the default
Azure CLI configuration; see :func:`discovery.poll.azcli.run_az`.
"""


@dataclass(frozen=True)
class ExtensionResult:
    """Outcome of checking or ensuring a single extension.

    Attributes:
        name: Extension name (e.g. ``"resource-graph"``).
        ok: ``True`` if the extension is installed at the end of the
            operation.
        action: One of ``"already-installed"``, ``"installed"``,
            ``"missing"`` (read-only check), or ``"install-failed"``.
        detail: Free-form human-readable detail (e.g. version string or
            stderr from a failed install).
    """

    name: str
    ok: bool
    action: str
    detail: str


def is_extension_installed(name: str) -> bool:
    """Return ``True`` when ``az extension show --name <name>`` succeeds.

    Uses :func:`discovery.poll.azcli.run_az` to avoid the same hidden-prompt
    hang class the rest of the CLI guards against. If ``az`` itself is not
    installed (``FileNotFoundError`` / ``OSError`` from the underlying
    :func:`subprocess.run`) we treat that as "not installed" so callers like
    :func:`check_required_extensions` can render a clean diagnostic instead
    of crashing with a traceback.
    """
    try:
        res = run_az(["az", "extension", "show", "--name", name, "-o", "json"])
    except (FileNotFoundError, OSError):
        return False
    return res.returncode == 0


def check_extension(name: str) -> ExtensionResult:
    """Read-only check: report whether ``name`` is installed."""
    if is_extension_installed(name):
        return ExtensionResult(name=name, ok=True, action="already-installed", detail="")
    return ExtensionResult(
        name=name,
        ok=False,
        action="missing",
        detail=f"run `az extension add --name {name}` (or `discovery configure`)",
    )


def ensure_extension(name: str) -> ExtensionResult:
    """Install ``name`` if missing, returning a structured result.

    Never raises — failures are reported in the result and surfaced to the
    caller so they can decide whether to abort or continue.
    """
    if is_extension_installed(name):
        debug(f"ensure_extension(): {name} already installed")
        return ExtensionResult(name=name, ok=True, action="already-installed", detail="")

    info(f"Installing az extension '{name}' (this may take a moment)...")
    res = run_az(["az", "extension", "add", "--name", name, "--yes"])
    if res.returncode == 0 and is_extension_installed(name):
        return ExtensionResult(name=name, ok=True, action="installed", detail="")

    stderr = (res.stderr or "").strip()
    if res.returncode == 0:
        # `az extension add` reported success but `extension show` still
        # cannot find it — surface a concrete, actionable detail instead of
        # the contradictory "exited with code 0".
        detail = (
            "install reported success but extension is still not registered; "
            "try restarting your shell or run `az extension list` to verify"
        )
    else:
        detail = stderr[-300:] or f"az extension add exited with code {res.returncode}"
    return ExtensionResult(name=name, ok=False, action="install-failed", detail=detail)


def check_required_extensions(
    names: Iterable[str] = REQUIRED_EXTENSIONS,
) -> list[ExtensionResult]:
    """Read-only check for every name in ``names``."""
    return [check_extension(n) for n in names]


def ensure_required_extensions(
    names: Iterable[str] = REQUIRED_EXTENSIONS,
) -> list[ExtensionResult]:
    """Install every missing extension in ``names``.

    Returns one :class:`ExtensionResult` per name, in iteration order. Use
    ``all(r.ok for r in results)`` to determine overall success.
    """
    return [ensure_extension(n) for n in names]
