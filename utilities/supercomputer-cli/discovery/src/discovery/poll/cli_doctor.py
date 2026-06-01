"""``discovery doctor`` — installation health check.

Audits the Discovery CLI installation:
- Version and build info
- Python version and platform
- All expected Python modules are importable
- All template JSON/YAML files exist and are valid
- External tools (az CLI, azcopy) are available
- Azure CLI authentication status
"""

from __future__ import annotations

import importlib
import json
import platform
import shutil
import subprocess
import sys
from importlib.resources import files

import typer
from rich.console import Console
from rich.table import Table

from discovery._version import get_build_commit, get_version_string
from discovery.common.auto_update import (
    CHECK_INTERVAL_HOURS,
    cache_is_stale,
    is_opted_out,
    load_cache,
)
from discovery.common.paths import get_config_file_path
from discovery.poll.az_extensions import check_required_extensions


app = typer.Typer(help="Installation health checks")

console = Console()

# All modules that should be importable in a correct installation
_EXPECTED_MODULES = [
    "discovery",
    "discovery.common",
    "discovery.common.auto_update",
    "discovery.common.config",
    "discovery.common.logging",
    "discovery.poll",
    "discovery.poll.api",
    "discovery.poll.az_extensions",
    "discovery.poll.azcli",
    "discovery.poll.build_acr_task",
    "discovery.poll.cli",
    "discovery.poll.cli_build",
    "discovery.poll.cli_cleanup",
    "discovery.poll.cli_configure",
    "discovery.poll.cli_doctor",
    "discovery.poll.cli_helpers",
    "discovery.poll.cli_smoke",
    "discovery.poll.cli_status",
    "discovery.poll.cli_storage",
    "discovery.poll.cli_submit",
    "discovery.poll.cli_update",
    "discovery.poll.dataplane_api",
    "discovery.poll.deploy_dataasset",
    "discovery.poll.deploy_tooldef",
    "discovery.poll.models",
    "discovery.poll.models.auth",
    "discovery.poll.models.compute",
    "discovery.poll.models.config",
    "discovery.poll.models.dataasset",
    "discovery.poll.models.tool_response",
    "discovery.poll.models.tool_run",
    "discovery.poll.resources",
    "discovery.poll.selection",
    "discovery.poll.vscode_layer",
    "discovery._version",
]

# Template files expected to exist (relative to discovery.poll.templates package)
_EXPECTED_TEMPLATES = [
    "tool-run.json",
    "tool-run-gpu.json",
    "dataasset/template.json",
    "dataasset/parameters.json",
    "tooldef/arm_template.json",
    "tooldef/template.json",
    "tooldef/parameters.json",
    "tooldef/test/parameters.json",
]


def _check_modules() -> list[tuple[str, bool, str]]:
    """Check all expected modules are importable.

    Returns list of (module_name, ok, detail).
    """
    results: list[tuple[str, bool, str]] = []
    for mod_name in _EXPECTED_MODULES:
        try:
            importlib.import_module(mod_name)
            results.append((mod_name, True, "ok"))
        except Exception as exc:
            results.append((mod_name, False, str(exc)))
    return results


def _check_templates() -> list[tuple[str, bool, str]]:
    """Check all expected template files exist and are valid JSON.

    Returns list of (template_path, ok, detail).
    """
    results: list[tuple[str, bool, str]] = []
    templates_root = files("discovery.poll").joinpath("templates")

    for tmpl_path in _EXPECTED_TEMPLATES:
        try:
            resource = templates_root.joinpath(tmpl_path)
            content = resource.read_text(encoding="utf-8")
            if tmpl_path.endswith(".json"):
                json.loads(content)
                results.append((tmpl_path, True, "valid JSON"))
            else:
                results.append((tmpl_path, True, "exists"))
        except FileNotFoundError:
            results.append((tmpl_path, False, "file not found"))
        except json.JSONDecodeError as exc:
            results.append((tmpl_path, False, f"invalid JSON: {exc}"))
        except Exception as exc:
            results.append((tmpl_path, False, str(exc)))
    return results


def _check_external_tools() -> list[tuple[str, bool, str]]:
    """Check external tools are available on PATH.

    Returns list of (tool_name, ok, detail).
    """
    results: list[tuple[str, bool, str]] = []

    # az CLI
    az_path = shutil.which("az")
    if az_path:
        results.append(("az", True, az_path))
    else:
        results.append(("az", False, "not found on PATH"))

    # azcopy
    azcopy_path = shutil.which("azcopy")
    if azcopy_path:
        results.append(("azcopy", True, azcopy_path))
    else:
        results.append(("azcopy", False, "not found on PATH"))

    return results


def _check_az_auth() -> tuple[bool, str]:
    """Check if Azure CLI is authenticated."""
    try:
        result = subprocess.run(
            ["az", "account", "show", "--query", "user.name", "-o", "tsv"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            return True, result.stdout.strip()
        return False, result.stderr.strip() or "not logged in"
    except FileNotFoundError:
        return False, "az CLI not installed"
    except subprocess.TimeoutExpired:
        return False, "timed out"
    except Exception as exc:
        return False, str(exc)


def _check_az_extensions() -> list[tuple[str, bool, str]]:
    """Check that all required ``az`` extensions are installed.

    Returns rows compatible with :func:`_render_check_table`. Missing
    extensions report the install command in the detail column so users
    have an actionable next step without scrolling back through logs.
    """
    rows: list[tuple[str, bool, str]] = []
    for r in check_required_extensions():
        if r.ok:
            rows.append((r.name, True, "installed"))
        else:
            rows.append((r.name, False, r.detail))
    return rows


def _render_check_table(title: str, rows: list[tuple[str, bool, str]]) -> None:
    """Render a check results table."""
    table = Table(title=title, show_header=True, header_style="bold cyan", expand=False)
    table.add_column("Item", style="white", no_wrap=True)
    table.add_column("Status", width=6, justify="center")
    table.add_column("Detail", style="dim")

    for name, ok, detail in rows:
        status = "[green]✓[/green]" if ok else "[red]✗[/red]"
        table.add_row(name, status, detail)

    console.print(table)
    console.print()


def _render_az_extensions_section() -> bool:
    """Render the az-extensions diagnostic section.

    Returns ``True`` when every required extension is installed, ``False``
    otherwise. Extracted from :func:`doctor_command` to keep that function
    under the per-function statement limit and to make the section easy to
    test in isolation.
    """
    ext_results = _check_az_extensions()
    failed_exts = [(n, ok, d) for n, ok, d in ext_results if not ok]
    if failed_exts:
        _render_check_table("Azure CLI Extensions", ext_results)
        return False
    console.print(
        f"  [green]✓[/green] All {len(ext_results)} required az extensions installed"
    )
    return True


def _render_update_check_section() -> None:
    """Render the auto-update checker status.

    Informational only — never fails the doctor exit code. Surfaces
    whether checks are enabled, when the cache was last refreshed, and
    whether a newer release is currently pending.
    """
    state = load_cache()
    if is_opted_out(state):
        console.print(
            "  [yellow]![/yellow] Update checks: [yellow]disabled[/yellow] "
            "(use `discovery update --enable`)"
        )
        return

    last = state.last_checked or "never"
    if state.last_checked and cache_is_stale(state):
        last = f"{last} [yellow](stale; >{CHECK_INTERVAL_HOURS}h ago)[/yellow]"
    console.print(f"  Update checks last refreshed: {last}")

    current = get_build_commit()
    if state.latest_commit and state.latest_commit != current:
        console.print(
            f"  [yellow]![/yellow] Update available: "
            f"[green]{state.latest_commit}[/green] "
            f"(run `discovery update` to install)"
        )
    elif state.latest_commit:
        console.print(
            f"  [green]✓[/green] CLI is up to date ({current})"
        )


@app.command(name="doctor")
def doctor_command() -> None:
    """Check installation health and report diagnostics."""
    console.print()
    console.print("[bold]Discovery CLI — Doctor[/bold]")
    console.print()

    # Version and environment info
    console.print(f"  Version:  {get_version_string()}")
    console.print(f"  Commit:   {get_build_commit()}")
    console.print(f"  Python:   {sys.version.split()[0]}")
    console.print(f"  Platform: {platform.system()} {platform.machine()}")
    console.print(f"  Prefix:   {sys.prefix}")

    # Show resolved config path for troubleshooting WSL / multi-env issues
    cfg_path = get_config_file_path()
    cfg_exists = cfg_path.exists()
    cfg_status = "[green]exists[/green]" if cfg_exists else "[yellow]not found[/yellow]"
    console.print(f"  Config:   {cfg_path} ({cfg_status})")

    console.print()

    all_ok = True

    # Module checks
    mod_results = _check_modules()
    failed_mods = [(n, ok, d) for n, ok, d in mod_results if not ok]
    if failed_mods:
        all_ok = False
        _render_check_table("Module Checks", mod_results)
    else:
        console.print(f"  [green]✓[/green] All {len(mod_results)} modules importable")

    # Template checks
    tmpl_results = _check_templates()
    failed_tmpls = [(n, ok, d) for n, ok, d in tmpl_results if not ok]
    if failed_tmpls:
        all_ok = False
        _render_check_table("Template Checks", tmpl_results)
    else:
        console.print(f"  [green]✓[/green] All {len(tmpl_results)} templates valid")

    # External tools
    tool_results = _check_external_tools()
    _render_check_table("External Tools", tool_results)
    if any(not ok for _, ok, _ in tool_results):
        all_ok = False

    # Azure auth
    auth_ok, auth_detail = _check_az_auth()
    if auth_ok:
        console.print(f"  [green]✓[/green] Azure CLI authenticated as: {auth_detail}")
    else:
        console.print(f"  [red]✗[/red] Azure CLI auth: {auth_detail}")
        all_ok = False

    # Azure CLI extensions required by the Discovery CLI's queries
    # (e.g. ``resource-graph`` for ``az graph query``). When missing the
    # CLI would otherwise hang on a hidden install prompt; this check
    # surfaces the situation early with an actionable hint.
    if not _render_az_extensions_section():
        all_ok = False

    # Update-checker status: surface the cached state so users can see
    # whether automatic update notifications will fire and when the
    # cache was last refreshed.
    _render_update_check_section()

    console.print()
    if all_ok:
        console.print("[bold green]All checks passed.[/bold green]")
    else:
        console.print("[bold yellow]Some checks failed. See details above.[/bold yellow]")

    raise typer.Exit(code=0 if all_ok else 1)


__all__ = ["app"]
