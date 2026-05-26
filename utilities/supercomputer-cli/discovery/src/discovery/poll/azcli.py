"""Safe wrapper around ``az`` invocations.

The Azure CLI prompts on stdin when an extension is missing (e.g. when
``resource-graph`` is not installed for ``az graph query``). With
``capture_output=True`` the prompt is hidden from the user but stdin is
inherited, so the process appears to freeze indefinitely. :func:`run_az`
ensures every ``az`` call in the Discovery CLI is hardened against that
class of hang.
"""

from __future__ import annotations

import os
import subprocess


__all__ = ["run_az"]


def run_az(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    """Invoke an ``az`` command safely, never blocking on stdin prompts.

    This helper:

    * passes ``stdin=subprocess.DEVNULL`` so the child can never block on a
      hidden prompt; and
    * sets ``AZURE_EXTENSION_USE_DYNAMIC_INSTALL=no`` so missing extensions
      surface as a non-zero exit code with a clear stderr message instead of
      triggering an interactive install prompt.

    Callers continue to inspect ``returncode`` / ``stderr`` exactly as they
    would for a regular :func:`subprocess.run` call.
    """
    env = {**os.environ, "AZURE_EXTENSION_USE_DYNAMIC_INSTALL": "no"}
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
        stdin=subprocess.DEVNULL,
        env=env,
    )
