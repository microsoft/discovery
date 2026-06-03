"""Submit-related CLI commands: start, batch, vscode, cancel."""

from __future__ import annotations

import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx
import typer
from rich.console import Console
from rich.panel import Panel

from discovery.common.job_history import (
    MODE_BATCH,
    MODE_START,
    MODE_VSCODE,
    JobHistoryEntry,
    load_history,
    parse_since,
    record_submission,
)
from discovery.common.logging import debug, error, info, pretty_debug
from discovery.poll.models.api_version import ApiVersion
from discovery.poll.models.tool_run import (
    DataMount,
    InfraOverrides,
    InfraOverridesFlat,
    ResourceSpec,
    ToolRunRequest,
)

from .cli_helpers import (
    DEFAULT_INTERVAL,
    DEFAULT_TIMEOUT,
    emit_env,
    ensure_datacontainer,
    format_service_error,
    get_azure_username,
    get_config_file_path,
    get_raw_azure_username,
    load_project_config,
    load_tool_config,
    prepare_command,
    render_error_with_details,
)
from .dataplane_api import (
    PollError,
    cancel_operation,
    get_operation_status,
    poll_operation,
    start_tool_run,
)


def _record_job_submission(
    operation_id: str,
    env_cfg,
    *,
    command: str,
    nodepool_id: str,
    mode: str,
) -> None:
    """Append a job-history entry; never raises into the submit flow."""
    try:
        # ``get_raw_azure_username`` may shell out to ``az`` and may
        # raise / time out in degraded environments. Whatever happens,
        # recording is best-effort — we only use the value to scope
        # later bulk operations to "this Azure principal".
        try:
            az_user = get_raw_azure_username() or ""
        except Exception:
            az_user = ""
        record_submission(
            operation_id,
            command=command,
            tool_id=getattr(env_cfg, "tool_id", "") or "",
            nodepool_id=nodepool_id,
            project_name=getattr(env_cfg, "project_name", "") or "",
            workspace_url=getattr(env_cfg, "workspace_url", "") or "",
            mode=mode,
            cli_argv=list(sys.argv),
            azure_username=az_user,
        )
    except Exception as exc:  # pragma: no cover - defensive
        debug(f"job-history: record_submission swallowed {exc}")

# Backward-compatibility re-exports: the canonical source of truth is
# :class:`ApiVersion` in ``discovery.poll.models.api_version``. These sets exist so
# existing callers/tests that import the constants continue to work; new code should
# prefer ``ApiVersion.parse(x).uses_storage_id`` etc.
_LEGACY_API_VERSIONS = frozenset(v.wire_value for v in ApiVersion if v.uses_storage_id)
_NESTED_INFRA_OVERRIDES_API_VERSIONS = frozenset(
    v.wire_value for v in ApiVersion if v.uses_nested_infra_overrides
)


def _resolve_scratch_wrapper_id(np_info, env_cfg, av: ApiVersion) -> str:
    """Resolve the scratch ANF wrapper resource ID for a given nodepool's supercomputer.

    Strict per-SC lookup: returns the wrapper mapped for *this* nodepool's
    supercomputer, or "" otherwise. Never falls back to another SC's wrapper —
    cross-SC mounting would violate the same-region ANF constraint enforced
    at config time.

    Returns the V1 dataContainer ID or V2 storageContainer ID (whichever
    matches the active API version), or "" when no mapping is configured for
    this supercomputer.
    """
    sc_id = getattr(np_info, "supercomputer_id", "") if np_info else ""

    if av.uses_dataassets_uri:
        # V1: prefer the cached per-NP value (mirrored from the dict during
        # list_all_nodepools_with_details). Fall back to the dict only when
        # we can match by supercomputer_id; never to a different SC's entry.
        cached = getattr(np_info, "scratch_dc_id", "") if np_info else ""
        if cached:
            return cached
        if sc_id and env_cfg.supercomputer_scratch_dcs:
            for k, v in env_cfg.supercomputer_scratch_dcs.items():
                if k.lower() == sc_id.lower():
                    return v
        return ""

    # V2: NodepoolInfo doesn't currently cache the V2 mapping; resolve via
    # env_cfg.supercomputer_scratch_scs, also strictly per-SC.
    if sc_id and env_cfg.supercomputer_scratch_scs:
        for k, v in env_cfg.supercomputer_scratch_scs.items():
            if k.lower() == sc_id.lower():
                return v
    return ""


def _build_scratch_mount(np_info, env_cfg, av: ApiVersion) -> "DataMount | None":
    """Construct an explicit /scratch DataMount for the active API version, if possible.

    On V1 builds ``discovery://dataassets{dc_id}/dataassets/scratch/paths/{uuid}``;
    on V2 builds ``discovery://storageassets{sc_id}/storageassets/scratch/paths/{uuid}``.
    The wrapper resource (dataContainer / storageContainer) is the one chosen
    by the user for this nodepool's supercomputer in
    ``discovery configure --scratch-select``. The asset itself (``scratch``)
    is auto-created by ``ensure_scratch_assets`` during configure.

    Returns None when no scratch wrapper is configured for this supercomputer.
    Callers should then either error (if ``--scratch`` was explicitly requested)
    or omit the ``/scratch`` mount silently.
    """
    import uuid

    wrapper_id = _resolve_scratch_wrapper_id(np_info, env_cfg, av)
    if not wrapper_id:
        return None
    sub_id = uuid.uuid4().hex
    if av.uses_dataassets_uri:
        uri = f"discovery://dataassets{wrapper_id}/dataassets/scratch/paths/{sub_id}"
        return DataMount(mountPath="/scratch", uri=uri)
    storage_uri = f"discovery://storageassets{wrapper_id}/storageassets/scratch/paths/{sub_id}"
    return DataMount(mountPath="/scratch", storageUri=storage_uri)


def _scratch_mount_or_exit(np_info, env_cfg, av: ApiVersion, scratch: bool) -> "DataMount | None":
    """Return a /scratch DataMount when ``scratch`` is True, else None.

    Fails fast (typer.Exit code 2) when the user passed ``--scratch`` but no
    per-supercomputer scratch wrapper is configured for the chosen nodepool's
    supercomputer — pointing them at ``discovery configure --scratch-select``.
    """
    if not scratch:
        return None
    mount = _build_scratch_mount(np_info, env_cfg, av)
    if mount is None:
        sc_label = (
            getattr(np_info, "supercomputer_name", "")
            or getattr(np_info, "supercomputer_id", "")
            or "this supercomputer"
        )
        wrapper_label = "dataContainer" if av.uses_dataassets_uri else "storageContainer"
        error(
            f"--scratch was requested but no scratch {wrapper_label} is "
            f"configured for {sc_label}. "
            f"Run 'discovery configure --scratch-select' to map an ANF "
            f"wrapper for each supercomputer."
        )
        raise typer.Exit(code=2)
    return mount


def build_infra_overrides(
    api_version: str | ApiVersion | None,
    cpus: int | None,
    gpus: int | None,
    memory: str | None,
    image: str | None,
) -> InfraOverrides | InfraOverridesFlat | None:
    """Build the correct InfraOverrides variant for the target api-version.

    Returns None if no override parameters were supplied. Otherwise returns the shape
    mandated by the target api-version's server contract (nested for 2025-07-01-preview,
    flat for everything else).
    """
    if not any([cpus, gpus, memory, image]):
        return None

    av = ApiVersion.parse(api_version)
    if av.uses_nested_infra_overrides:
        resources = None
        if any([cpus, gpus, memory]):
            resources = ResourceSpec(
                cpu=str(cpus) if cpus is not None else None,
                gpu=gpus,
                ram=memory,
            )
        return InfraOverrides(resources=resources, pool_size=None, image_uri=image)

    return InfraOverridesFlat(
        cpu=str(cpus) if cpus is not None else None,
        ram=memory,
        gpu=str(gpus) if gpus is not None else None,
        replica_count=None,
        image_uri=image,
    )


def normalize_memory(memory: str | None) -> str | None:
    """Normalize memory specification to proper format with 'Gi' suffix.

    - Fixes case on 'gi'/'GI'/'gI' -> 'Gi'
    - Adds 'Gi' suffix if missing (bare number)

    Examples:
        "32" -> "32Gi"
        "32gi" -> "32Gi"
        "32GI" -> "32Gi"
        "32Gi" -> "32Gi"
        "32Mi" -> "32Mi" (other units preserved)
    """
    if memory is None:
        return None

    # Check if it's just a number (no suffix)
    if re.match(r"^\d+$", memory.strip()):
        return f"{memory.strip()}Gi"

    # Fix case on Gi suffix (gi, GI, gI -> Gi)
    return re.sub(r"gi$", "Gi", memory.strip(), flags=re.IGNORECASE)


# ---------------------------------------------------------------------------
# Device-flow URL polling (named tunnel mode)
# ---------------------------------------------------------------------------

_DEVICE_FLOW_POLL_INTERVAL = 5  # seconds between log checks
_DEVICE_FLOW_POLL_TIMEOUT = 1800  # give up after 30 minutes (jobs can queue for a while)


_VALID_PROVIDERS = ("github", "microsoft")

# Provider-specific device-flow login URL detection. Detected in job logs so
# the CLI can surface the correct link to the user once auth is required.
# Each entry maps provider -> (list of substring fragments to match in a log
# line, canonical URL to show in the UI once detected). We list multiple
# fragments because VS Code's Microsoft provider has used different URL
# hosts across versions (``microsoft.com/devicelogin`` historically,
# ``login.microsoft.com/device`` as of code CLI 1.116.x).
_PROVIDER_DEVICE_FLOW: dict[str, tuple[tuple[str, ...], str]] = {
    "github": (("github.com/login/device",), "https://github.com/login/device"),
    "microsoft": (
        ("login.microsoft.com/device", "microsoft.com/devicelogin"),
        "https://login.microsoft.com/device",
    ),
}


def _provider_label(provider: str) -> str:
    return {"github": "GitHub", "microsoft": "Microsoft"}.get(provider, provider)


def _poll_for_device_flow_url(
    project_name: str,
    operation_id: str,
    workspace_url: str,
    provider: str = "github",
    api_version: str = "2025-07-01-preview",
) -> str | None:
    """Poll operation logs until the device-flow URL appears.

    Returns the URL string (e.g. ``https://github.com/login/device`` or
    ``https://microsoft.com/devicelogin``) or ``None`` if the timeout is
    reached or the operation fails before the URL appears.
    """
    import itertools
    import sys

    fragments, full_url = _PROVIDER_DEVICE_FLOW.get(
        provider, _PROVIDER_DEVICE_FLOW["github"]
    )

    spinner = itertools.cycle(["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"])
    start = time.time()
    seen_lines = 0
    poll_count = 0
    last_status: str | None = None
    last_exc: Exception | None = None

    debug(
        f"_poll_for_device_flow_url: start op={operation_id} provider={provider} "
        f"timeout={_DEVICE_FLOW_POLL_TIMEOUT}s interval={_DEVICE_FLOW_POLL_INTERVAL}s "
        f"project={project_name}"
    )

    while time.time() - start < _DEVICE_FLOW_POLL_TIMEOUT:
        poll_count += 1
        try:
            data = get_operation_status(
                project_name, operation_id, workspace_url, api_version=api_version
            )
        except Exception as exc:
            last_exc = exc
            # Swallow-and-retry is intentional (service may flake), but the
            # failure itself must be visible — otherwise a persistent error
            # looks identical to a normal waiting-for-logs state.
            debug(
                f"_poll_for_device_flow_url: poll {poll_count} failed: "
                f"{type(exc).__name__}: {exc}"
            )
            time.sleep(_DEVICE_FLOW_POLL_INTERVAL)
            continue

        last_status = data.status

        # Extract logs
        logs_raw = ""
        if data.result and data.result.tool_report:
            report = data.result.tool_report
            logs_raw = report.logs if isinstance(report.logs, str) else "\n".join(report.logs)

        lines = logs_raw.splitlines()
        new_lines = lines[seen_lines:]
        if new_lines:
            # Clear spinner and print new log lines
            sys.stdout.write("\r\033[K")
            for line in new_lines:
                info(line)
            seen_lines = len(lines)

            # Check if any line contains a device-flow URL fragment for the
            # selected provider.
            for line in new_lines:
                if any(frag in line for frag in fragments):
                    debug(
                        f"_poll_for_device_flow_url: device-flow URL detected "
                        f"after {poll_count} polls ({int(time.time() - start)}s)"
                    )
                    return full_url
        else:
            sys.stdout.write(f"\r{next(spinner)} Waiting for tunnel to start...")
            sys.stdout.flush()

        # Stop if the operation has already failed/completed
        if data.status not in ("Active", "Pending", "NotStarted", "Running"):
            sys.stdout.write("\r\033[K")
            # Surface *why* we gave up — this is the single most common
            # troubleshooting question for "my tunnel never came up".
            err_msg = ""
            if data.result and getattr(data.result, "error", None):
                err_msg = f" error={data.result.error}"  # type: ignore[attr-defined]
            error(
                f"Operation {operation_id} reached terminal status "
                f"'{data.status}' before device-flow URL appeared."
                f"{err_msg}"
            )
            return None

        time.sleep(_DEVICE_FLOW_POLL_INTERVAL)

    sys.stdout.write("\r\033[K")
    # Timeout path — log enough context to diagnose without a repro.
    last_exc_str = (
        f" last_poll_exc={type(last_exc).__name__}: {last_exc}" if last_exc else ""
    )
    error(
        f"Timed out waiting {_DEVICE_FLOW_POLL_TIMEOUT}s for device-flow URL "
        f"(op={operation_id}, polls={poll_count}, last_status={last_status}, "
        f"log_lines_seen={seen_lines}){last_exc_str}"
    )
    return None


app = typer.Typer()


@app.command()
def start(
    command: str = typer.Argument(
        ..., help="Bash command to run (templated into payload as 'command')"
    ),
    config_tool: bool = typer.Option(False, "--select-tool", help="Interactively select a tool id"),
    use_entire_node: bool = typer.Option(
        False,
        "--use-entire-node",
        help="Request the entire node's resources",
    ),
    cpus: int = typer.Option(
        None,
        "--cpus",
        help="Number of CPUs to request",
    ),
    gpus: int = typer.Option(
        None,
        "--gpus",
        help="Number of GPUs to request",
    ),
    memory: str = typer.Option(
        None,
        "--memory",
        help="Amount of RAM to request, e.g. '32Gi'",
    ),
    image: str = typer.Option(
        None,
        "--image",
        help="Image URI to use",
    ),
    username: str = typer.Option(
        None,
        "--username",
        help="Username for output archive container (default: current user)",
    ),
    no_wait: bool = typer.Option(
        False,
        "--no-wait",
        help="Submit job and exit without polling for completion",
    ),
    pool: str = typer.Option(
        None,
        "--pool",
        help="Nodepool name or ID to use (default: configured default pool)",
    ),
    tunnel_name: str = typer.Option(
        None,
        "--tunnel-name",
        help="Use named tunnel mode (device-flow auth; GitHub by default)",
    ),
    api_version: str = typer.Option(
        None,
        "--api-version",
        help="Override API version (e.g. 2026-02-01-preview). Defaults to configured version.",
    ),
    scratch: bool = typer.Option(
        False,
        "--scratch",
        help=(
            "Mount per-supercomputer scratch ANF at /scratch. Requires "
            "'discovery configure --scratch-select' to have set a scratch "
            "wrapper for this supercomputer."
        ),
    ),
) -> None:
    """Start a tool run. Polls until terminal status unless --no-wait provided."""
    debug("start(): entering")

    # Get username - use provided value or Azure CLI logged-in user
    effective_username = username or get_azure_username()

    env_cfg = load_project_config(get_config_file_path())
    load_tool_config(config_tool, env_cfg)

    # Resolve nodepool - use provided pool or default from config
    effective_nodepool_id = env_cfg.nodepool_id
    np_info = None
    if pool:
        try:
            np_info = env_cfg.get_nodepool(pool)
        except ValueError as e:
            error(str(e))
            raise typer.Exit(code=1) from e
        if np_info:
            effective_nodepool_id = np_info.id
            info(f"Using nodepool: {np_info.qualified_name}")
        # Check if it's a full ID that wasn't in our cached list
        elif pool.startswith("/"):
            effective_nodepool_id = pool
            info(f"Using nodepool ID: {pool}")
        else:
            available = [np.qualified_name for np in env_cfg.nodepools]
            error(f"Nodepool '{pool}' not found. Available pools: {available}")
            raise typer.Exit(code=1)
    else:
        # Try to get nodepool info for the default pool to use full-node defaults
        for np in env_cfg.nodepools:
            if np.id == effective_nodepool_id:
                np_info = np
                break

    # Apply full-node defaults from nodepool if user didn't specify resources
    # Use allocatable values which account for AKS system overhead
    if use_entire_node and np_info:
        if cpus is None and np_info.allocatable_cpus:
            try:
                cpus = int(np_info.allocatable_cpus)
                debug(f"Using allocatable CPUs from pool (AKS-adjusted): {cpus}")
            except ValueError:
                pass
        if memory is None and np_info.allocatable_memory:
            memory = f"{np_info.allocatable_memory}Gi"
            debug(f"Using allocatable memory from pool (AKS-adjusted): {memory}")
        if gpus is None and np_info.gpus:
            try:
                gpus = int(np_info.gpus)
                debug(f"Using full-node GPUs from pool: {gpus}")
            except ValueError:
                pass

    # Normalize memory specification (fix case, add Gi suffix if missing)
    memory = normalize_memory(memory)

    # Ensure data container is configured for output data
    ensure_datacontainer(env_cfg)


    emit_env(env_cfg)

    # If --tunnel-name is given, enable vscode tunnel mode
    vscode = bool(tunnel_name)

    command_effective = prepare_command(command, env_cfg, vscode, [], tunnel_name=tunnel_name)

    # Resolve effective API version: CLI flag overrides config
    effective_api_version = api_version or env_cfg.api_version or None

    # Build infra_overrides using the schema variant matching the target api-version.
    infra_overrides = build_infra_overrides(effective_api_version, cpus, gpus, memory, image)

    # Build payload — branching on API version capability.
    # Legacy: uri + discovery://dataassets, storageId required.
    # Modern: storageUri + discovery://storageassets, no storageId.
    av = ApiVersion.parse(effective_api_version)
    _scratch_mount = _scratch_mount_or_exit(np_info, env_cfg, av, scratch)
    if av.uses_dataassets_uri:
        output_uri = f"discovery://dataassets{env_cfg.datacontainer_id}/dataassets/{effective_username}"
        shared_output_uri = f"discovery://dataassets{env_cfg.datacontainer_id}/dataassets/shared"
        payload = ToolRunRequest(
            toolId=env_cfg.tool_id,
            command=command_effective,
            nodePoolIds=[effective_nodepool_id],
            infraOverrides=infra_overrides,
            inputData=[],
            outputData=[
                DataMount(mountPath="/blob_user", uri=output_uri),
                DataMount(mountPath="/blob_shared", uri=shared_output_uri),
                *([_scratch_mount] if _scratch_mount else []),
            ],
        )
    else:
        output_mounts = [
            DataMount(mountPath="/blob_user", storageUri=f"discovery://storageassets{env_cfg.storagecontainer_id}/storageassets/{effective_username}"),
            DataMount(mountPath="/blob_shared", storageUri=f"discovery://storageassets{env_cfg.storagecontainer_id}/storageassets/shared"),
            *([_scratch_mount] if _scratch_mount else []),
        ]
        payload = ToolRunRequest(
            toolId=env_cfg.tool_id,
            command=command_effective,
            nodePoolIds=[effective_nodepool_id],
            infraOverrides=infra_overrides,
            inputData=[],
            outputData=output_mounts,
        )
    pretty_debug(payload, label="ToolRunRequest payload")

    try:
        # Submit first, then record locally so the at-exit / list filters
        # see the operation immediately. ``run_and_poll`` is inlined
        # here as ``start_tool_run`` + ``poll_operation`` so we can
        # record between the two calls — that way even Ctrl+C during
        # polling leaves a usable history entry.
        response = start_tool_run(
            env_cfg.project_name,
            payload,
            env_cfg.workspace_url,
            api_version=effective_api_version,
        )
        _record_job_submission(
            response.id,
            env_cfg,
            command=command,
            nodepool_id=effective_nodepool_id,
            mode=MODE_START,
        )
        if no_wait:
            info(f"Job submitted. Operation ID: {response.id}")
            return

        result = poll_operation(
            env_cfg.project_name,
            response.id,
            env_cfg.workspace_url,
            poll_interval=DEFAULT_INTERVAL,
            timeout_seconds=DEFAULT_TIMEOUT,
            api_version=effective_api_version,
        )
        runtime_details = result.result.runtime_details if result.result else "N/A"
        info(f"Result={result.status}, details: {runtime_details}")
        if result.status == "Failed":
            error("Errors occurred: " + render_error_with_details(result.error))
            raise typer.Exit(code=1)
    except httpx.HTTPStatusError as exc:
        error(format_service_error(exc))
        raise typer.Exit(code=1) from exc
    except httpx.TransportError as exc:
        error(f"Network error (retries exhausted): {type(exc).__name__}: {exc}")
        raise typer.Exit(code=1) from exc
    except PollError as exc:
        error(f"Operation failed: {exc}")
        raise typer.Exit(code=1) from exc


@app.command()
def batch(
    size: int = typer.Argument(
        None, help="Number of independent operations to submit (required if using single command)"
    ),
    command: str = typer.Argument(
        None, help="Bash command to run (templated into payload as 'command')"
    ),
    commands_file: Path = typer.Option(
        None,
        "--commands-file",
        "-f",
        help="File containing commands, one per line (each line becomes a separate job)",
    ),
    commands: str = typer.Option(
        None,
        "--commands",
        "-c",
        help="Semicolon-separated list of commands (each command becomes a separate job)",
    ),
    max_workers: int = typer.Option(
        64,
        "--parallel",
        "-p",
        help="Number of parallel submissions (default: 64)",
    ),
    config_tool: bool = typer.Option(False, "--select-tool", help="Interactively select a tool id"),
    cpus: int = typer.Option(
        None,
        "--cpus",
        help="Number of CPUs to request",
    ),
    gpus: int = typer.Option(
        None,
        "--gpus",
        help="Number of GPUs to request",
    ),
    memory: str = typer.Option(
        None,
        "--memory",
        help="Amount of RAM to request, e.g. '32Gi'",
    ),
    image: str = typer.Option(
        None,
        "--image",
        help="Image URI to use",
    ),
    username: str = typer.Option(
        None,
        "--username",
        help="Username for output archive container (default: current user)",
    ),
    pool: str = typer.Option(
        None,
        "--pool",
        help="Nodepool name or ID to use (default: configured default pool)",
    ),
    api_version: str = typer.Option(
        None,
        "--api-version",
        help="Override API version (e.g. 2026-02-01-preview). Defaults to configured version.",
    ),
    use_entire_node: bool = typer.Option(
        False,
        "--use-entire-node",
        help="Request the entire node's resources (auto-fill CPUs/memory/GPUs from the nodepool)",
    ),
    scratch: bool = typer.Option(
        False,
        "--scratch",
        help=(
            "Mount per-supercomputer scratch ANF at /scratch on every submitted job. "
            "Requires 'discovery configure --scratch-select'."
        ),
    ),
) -> None:
    """Submit multiple independent tool runs. Does not poll for output.

    Commands can be specified in three ways:
    1. Single command with size: `batch 5 "echo hello"` - runs the same command 5 times
    2. Commands file: `batch --commands-file cmds.txt` - one command per line
    3. Semicolon-separated: `batch --commands "echo a;echo b;echo c"` - each becomes a job
    """
    debug("batch(): entering")

    # Build command list from various input methods
    command_list: list[str] = []

    if commands_file:
        # Read commands from file, one per line
        if not commands_file.exists():
            error(f"Commands file not found: {commands_file}")
            raise typer.Exit(code=1)
        with commands_file.open() as f:
            command_list = [line.strip() for line in f if line.strip() and not line.startswith("#")]
        if not command_list:
            error(f"No commands found in file: {commands_file}")
            raise typer.Exit(code=1)
        info(f"Loaded {len(command_list)} commands from {commands_file}")
    elif commands:
        # Parse semicolon-separated commands
        command_list = [cmd.strip() for cmd in commands.split(";") if cmd.strip()]
        if not command_list:
            error("No valid commands found in --commands")
            raise typer.Exit(code=1)
        info(f"Parsed {len(command_list)} commands from --commands")
    elif command and size:
        # Traditional mode: same command repeated `size` times
        if size < 1:
            error("Size must be at least 1")
            raise typer.Exit(code=1)
        command_list = [command] * size
    else:
        error(
            "Must specify either: (1) size and command, (2) --commands-file, or (3) --commands"
        )
        raise typer.Exit(code=1)

    # Get username - use provided value or Azure CLI logged-in user
    effective_username = username or get_azure_username()

    env_cfg = load_project_config(get_config_file_path())
    load_tool_config(config_tool, env_cfg)

    # Resolve nodepool - use provided pool or default from config
    effective_nodepool_id = env_cfg.nodepool_id
    np_info = None
    if pool:
        try:
            np_info = env_cfg.get_nodepool(pool)
        except ValueError as e:
            error(str(e))
            raise typer.Exit(code=1) from e
        if np_info:
            effective_nodepool_id = np_info.id
            info(f"Using nodepool: {np_info.qualified_name}")
        elif pool.startswith("/"):
            effective_nodepool_id = pool
            info(f"Using nodepool ID: {pool}")
        else:
            available = [np.qualified_name for np in env_cfg.nodepools]
            error(f"Nodepool '{pool}' not found. Available pools: {available}")
            raise typer.Exit(code=1)
    else:
        # Try to get nodepool info for the default pool to use full-node defaults
        for np in env_cfg.nodepools:
            if np.id == effective_nodepool_id:
                np_info = np
                break

    # Apply full-node defaults from nodepool if user didn't specify resources
    # Use allocatable values which account for AKS system overhead
    if use_entire_node and np_info:
        if cpus is None and np_info.allocatable_cpus:
            try:
                cpus = int(np_info.allocatable_cpus)
                debug(f"Using allocatable CPUs from pool (AKS-adjusted): {cpus}")
            except ValueError:
                pass
        if memory is None and np_info.allocatable_memory:
            memory = f"{np_info.allocatable_memory}Gi"
            debug(f"Using allocatable memory from pool (AKS-adjusted): {memory}")
        if gpus is None and np_info.gpus:
            try:
                gpus = int(np_info.gpus)
                debug(f"Using full-node GPUs from pool: {gpus}")
            except ValueError:
                pass

    # Normalize memory specification (fix case, add Gi suffix if missing)
    memory = normalize_memory(memory)

    # Ensure data container is configured for output data
    ensure_datacontainer(env_cfg)


    emit_env(env_cfg)

    # Resolve effective API version: CLI flag overrides config
    effective_api_version = api_version or env_cfg.api_version or None
    av = ApiVersion.parse(effective_api_version)
    _scratch_mount = _scratch_mount_or_exit(np_info, env_cfg, av, scratch)

    # Build infra_overrides using the schema variant matching the target api-version.
    infra_overrides = build_infra_overrides(effective_api_version, cpus, gpus, memory, image)

    # Helper function to submit a single job
    def submit_job(idx: int, cmd: str) -> tuple[int, str | None, str | None]:
        """Submit a single job and return (index, operation_id, error_message)."""
        try:
            cmd_effective = prepare_command(cmd, env_cfg, False, [])
            if av.uses_dataassets_uri:
                output_uri = f"discovery://dataassets{env_cfg.datacontainer_id}/dataassets/{effective_username}"
                shared_output_uri = f"discovery://dataassets{env_cfg.datacontainer_id}/dataassets/shared"
                payload = ToolRunRequest(
                    toolId=env_cfg.tool_id,
                    command=cmd_effective,
                    nodePoolIds=[effective_nodepool_id],
                    infraOverrides=infra_overrides,
                    inputData=[],
                    outputData=[
                        DataMount(mountPath="/blob_user", uri=output_uri),
                        DataMount(mountPath="/blob_shared", uri=shared_output_uri),
                        *([_scratch_mount] if _scratch_mount else []),
                    ],
                )
            else:
                output_mounts = [
                    DataMount(mountPath="/blob_user", storageUri=f"discovery://storageassets{env_cfg.storagecontainer_id}/storageassets/{effective_username}"),
                    DataMount(mountPath="/blob_shared", storageUri=f"discovery://storageassets{env_cfg.storagecontainer_id}/storageassets/shared"),
                    *([_scratch_mount] if _scratch_mount else []),
                ]
                payload = ToolRunRequest(
                    toolId=env_cfg.tool_id,
                    command=cmd_effective,
                    nodePoolIds=[effective_nodepool_id],
                    infraOverrides=infra_overrides,
                    inputData=[],
                    outputData=output_mounts,
                )
            response = start_tool_run(env_cfg.project_name, payload, env_cfg.workspace_url, api_version=effective_api_version)
            _record_job_submission(
                response.id,
                env_cfg,
                command=cmd,
                nodepool_id=effective_nodepool_id,
                mode=MODE_BATCH,
            )
            return (idx, response.id, None)
        except Exception as e:
            return (idx, None, str(e))

    # Submit jobs in parallel
    total = len(command_list)
    operation_ids: list[str] = []
    failed_jobs: list[tuple[int, str]] = []

    info(f"Submitting {total} operations using {max_workers} parallel workers...")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all jobs
        futures = {
            executor.submit(submit_job, i, cmd): i for i, cmd in enumerate(command_list)
        }

        # Collect results as they complete
        for future in as_completed(futures):
            idx, op_id, err = future.result()
            if op_id:
                operation_ids.append(op_id)
                info(f"  [{len(operation_ids)}/{total}] Operation ID: {op_id}")
            else:
                failed_jobs.append((idx, err or "Unknown error"))
                error(f"  [FAILED] Job {idx + 1}: {err}")

    info(f"Batch complete. Submitted {len(operation_ids)} operations.")
    if failed_jobs:
        error(f"Failed to submit {len(failed_jobs)} jobs.")


@app.command("vscode")
def vscode_cmd(
    config_tool: bool = typer.Option(False, "--select-tool", help="Interactively select a tool id"),
    cpus: int = typer.Option(
        None,
        "--cpus",
        help="Number of CPUs to request (default: full node)",
    ),
    gpus: int = typer.Option(
        None,
        "--gpus",
        help="Number of GPUs to request (default: full node)",
    ),
    memory: str = typer.Option(
        None,
        "--memory",
        help="Amount of RAM to request, e.g. '32Gi' (default: full node)",
    ),
    image: str = typer.Option(
        None,
        "--image",
        help="Image URI to use",
    ),
    username: str = typer.Option(
        None,
        "--username",
        help="Username for output archive container (default: current user)",
    ),
    pool: str = typer.Option(
        None,
        "--pool",
        help="Nodepool name or ID to use (default: configured default pool)",
    ),
    tunnel_name: str = typer.Option(
        None,
        "--tunnel-name",
        help="Stable name for the VS Code tunnel (default: discovery-<username>)",
    ),
    provider: str = typer.Option(
        "github",
        "--provider",
        help=(
            "Auth provider for the VS Code tunnel device-flow login. "
            "One of: github, microsoft. Default: github."
        ),
    ),
    api_version: str = typer.Option(
        None,
        "--api-version",
        help="Override API version (e.g. 2026-02-01-preview). Defaults to configured version.",
    ),
    scratch: bool = typer.Option(
        False,
        "--scratch",
        help=(
            "Mount per-supercomputer scratch ANF at /scratch in the tunnel session. "
            "Requires 'discovery configure --scratch-select'."
        ),
    ),
) -> None:
    """Start a VS Code tunnel session. Submits job and polls for device-flow URL."""
    debug("vscode(): entering")

    provider = provider.lower()
    if provider not in _VALID_PROVIDERS:
        msg = (
            f"--provider must be one of {', '.join(_VALID_PROVIDERS)}; got {provider!r}"
        )
        raise typer.BadParameter(msg)

    # Get username - use provided value or Azure CLI logged-in user
    effective_username = username or get_azure_username()

    # Derive a stable default tunnel name from the username when not specified
    if not tunnel_name:
        tunnel_name = f"discovery-{effective_username}"
        debug(f"Using default tunnel name: {tunnel_name}")

    env_cfg = load_project_config(get_config_file_path())
    load_tool_config(config_tool, env_cfg)

    # Resolve nodepool - use provided pool or default from config
    effective_nodepool_id = env_cfg.nodepool_id
    np_info = None
    if pool:
        try:
            np_info = env_cfg.get_nodepool(pool)
        except ValueError as e:
            error(str(e))
            raise typer.Exit(code=1) from e
        if np_info:
            effective_nodepool_id = np_info.id
            info(f"Using nodepool: {np_info.qualified_name}")
    else:
        # Try to get nodepool info for the default pool to use full-node defaults
        for np in env_cfg.nodepools:
            if np.id == effective_nodepool_id:
                np_info = np
                break

    # Apply full-node defaults from nodepool if user didn't specify resources
    # Use allocatable values which account for AKS system overhead
    if np_info:
        if cpus is None and np_info.allocatable_cpus:
            try:
                cpus = int(np_info.allocatable_cpus)
                debug(f"Using allocatable CPUs from pool (AKS-adjusted): {cpus}")
            except ValueError:
                pass
        if memory is None and np_info.allocatable_memory:
            memory = f"{np_info.allocatable_memory}Gi"
            debug(f"Using allocatable memory from pool (AKS-adjusted): {memory}")
        if gpus is None and np_info.gpus:
            try:
                gpus = int(np_info.gpus)
                debug(f"Using full-node GPUs from pool: {gpus}")
            except ValueError:
                pass

    # Normalize memory specification (fix case, add Gi suffix if missing)
    memory = normalize_memory(memory)

    # Ensure data container is configured for output data
    ensure_datacontainer(env_cfg)


    emit_env(env_cfg)

    sleep_command = "sleep 7d"

    # Prepare command with vscode tunnel prefix
    command_effective = prepare_command(
        sleep_command,
        env_cfg,
        vscode=True,
        additional_ports=[],
        tunnel_name=tunnel_name,
        provider=provider,
    )

    # Resolve effective API version: CLI flag overrides config
    effective_api_version = api_version or env_cfg.api_version or None

    # Build infra_overrides with full-node resources using the schema variant matching
    # the target api-version.
    infra_overrides = build_infra_overrides(effective_api_version, cpus, gpus, memory, image)

    # Build payload — branching on API version capability.
    av = ApiVersion.parse(effective_api_version)
    _scratch_mount = _scratch_mount_or_exit(np_info, env_cfg, av, scratch)
    if av.uses_dataassets_uri:
        output_uri = f"discovery://dataassets{env_cfg.datacontainer_id}/dataassets/{effective_username}"
        shared_output_uri = f"discovery://dataassets{env_cfg.datacontainer_id}/dataassets/shared"
        payload = ToolRunRequest(
            toolId=env_cfg.tool_id,
            command=command_effective,
            nodePoolIds=[effective_nodepool_id],
            infraOverrides=infra_overrides,
            inputData=[],
            outputData=[
                DataMount(mountPath="/blob_user", uri=output_uri),
                DataMount(mountPath="/blob_shared", uri=shared_output_uri),
                *([_scratch_mount] if _scratch_mount else []),
            ],
        )
    else:
        output_mounts = [
            DataMount(mountPath="/blob_user", storageUri=f"discovery://storageassets{env_cfg.storagecontainer_id}/storageassets/{effective_username}"),
            DataMount(mountPath="/blob_shared", storageUri=f"discovery://storageassets{env_cfg.storagecontainer_id}/storageassets/shared"),
            *([_scratch_mount] if _scratch_mount else []),
        ]
        payload = ToolRunRequest(
            toolId=env_cfg.tool_id,
            command=command_effective,
            nodePoolIds=[effective_nodepool_id],
            infraOverrides=infra_overrides,
            inputData=[],
            outputData=output_mounts,
        )
    pretty_debug(payload, label="ToolRunRequest payload")

    info(
        f"Submitting VS Code tunnel job: project={env_cfg.project_name} "
        f"tunnel={tunnel_name} provider={provider} nodepool={effective_nodepool_id}"
    )

    # Submit job without polling
    try:
        response = start_tool_run(env_cfg.project_name, payload, env_cfg.workspace_url, api_version=effective_api_version)
        _record_job_submission(
            response.id,
            env_cfg,
            command=f"<vscode tunnel: {tunnel_name}>",
            nodepool_id=effective_nodepool_id,
            mode=MODE_VSCODE,
        )
    except httpx.HTTPStatusError as exc:
        error(format_service_error(exc))
        raise typer.Exit(code=1) from exc
    except httpx.TransportError as exc:
        error(f"Network error (retries exhausted): {type(exc).__name__}: {exc}")
        raise typer.Exit(code=1) from exc
    except PollError as exc:
        error(f"Operation failed: {exc}")
        raise typer.Exit(code=1) from exc

    console = Console()
    console.print()
    info(f"Operation ID: {response.id}")

    provider_label = _provider_label(provider)

    # Poll the operation logs until we see the device-flow URL
    console.print(
        Panel(
            f"Waiting for the container to start and print the {provider_label} login link...\n"
            f"To cancel: [cyan]discovery job cancel {response.id}[/cyan]",
            title=f"[bold]VS Code Session — tunnel: {tunnel_name} (auth: {provider_label})[/bold]",
            border_style="green",
        )
    )
    device_url = _poll_for_device_flow_url(
        env_cfg.project_name,
        response.id,
        env_cfg.workspace_url,
        provider=provider,
        api_version=effective_api_version or env_cfg.api_version,
    )
    if device_url:
        console.print()
        console.print(
            Panel(
                f"[bold green]{provider_label} device-flow login required![/bold green]\n\n"
                f"  1. Open:  [link={device_url}]{device_url}[/link]\n"
                f"  2. Enter the code shown in the logs above\n"
                f"  3. The tunnel will appear in VS Code → Remote Explorer → Tunnels\n\n"
                f"[bold yellow]Remember to cancel when finished:[/bold yellow]\n"
                f"  [cyan]discovery job cancel {response.id}[/cyan]",
                title="[bold]Action Required[/bold]",
                border_style="yellow",
            )
        )
    else:
        console.print(
            "[yellow]Could not detect device-flow URL in logs within timeout.[/yellow]\n"
            f"Check logs manually: [cyan]discovery job status {response.id}[/cyan]\n"
            "The tunnel log inside the container: /tmp/vscode-tunnel.log"
        )


@app.command()
def cancel(
    operation_id: str = typer.Argument(
        None,
        help=(
            "Existing operation id to cancel. Omit when using --since to "
            "bulk-cancel from local history."
        ),
    ),
    since: str = typer.Option(
        "",
        "--since",
        help=(
            "Bulk-cancel every job submitted from this machine within the "
            "given window. Accepts shorthand like '10m', '1h', '24h', '7d' "
            "or an absolute YYYY-MM-DD date. Scoped to the current "
            "workspace_url so a typo doesn't reach into a different "
            "Discovery environment."
        ),
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Skip the interactive confirmation prompt.",
    ),
    parallelism: int = typer.Option(
        16,
        "--parallel",
        "-p",
        help="Parallel cancel workers when --since is set (default: 16).",
    ),
) -> None:
    """Cancel a running operation, or bulk-cancel recent local submissions.

    Two modes:

    * ``discovery job cancel <operation-id>`` — cancel a single specific op.
    * ``discovery job cancel --since 10m`` — cancel every locally-recorded
      job submitted in the last 10 minutes (current workspace only).
    """
    debug("cancel(): entering")

    if not operation_id and not since:
        error(
            "Provide either an operation id or --since DURATION "
            "(e.g. `discovery job cancel --since 10m`)."
        )
        raise typer.Exit(code=2)
    if operation_id and since:
        error("--since is mutually exclusive with a positional operation id.")
        raise typer.Exit(code=2)

    env_cfg = load_project_config(get_config_file_path())
    emit_env(env_cfg)

    if since:
        _cancel_recent(env_cfg, since_value=since, yes=yes, parallelism=parallelism)
        return

    info(f"Cancel requested for operation id={operation_id}")
    try:
        cancel_operation(env_cfg.project_name, operation_id, env_cfg.workspace_url, api_version=env_cfg.api_version)
    except httpx.HTTPStatusError as exc:
        error(format_service_error(exc))
        raise typer.Exit(code=1) from exc
    except httpx.TransportError as exc:
        error(f"Network error (retries exhausted): {type(exc).__name__}: {exc}")
        raise typer.Exit(code=1) from exc
    except PollError as exc:
        error(f"Operation failed: {exc}")
        raise typer.Exit(code=1) from exc


def _cancel_recent(env_cfg, *, since_value: str, yes: bool, parallelism: int) -> None:
    """Implement ``discovery job cancel --since DURATION``."""
    try:
        cutoff = parse_since(since_value)
    except ValueError as exc:
        error(str(exc))
        raise typer.Exit(code=2) from exc

    entries = load_history(
        workspace_url=env_cfg.workspace_url,
        since=cutoff,
    )
    if not entries:
        info(
            f"No locally-recorded jobs submitted since {cutoff.isoformat()} "
            f"in workspace {env_cfg.workspace_url}. Nothing to cancel."
        )
        return

    # Scope to the *current* Azure principal. Local history can contain
    # entries from other users when ``$HOME`` is shared (shared
    # workstations, build agents that reauth between users, etc.). We
    # never want one user's bulk-cancel to reach another's jobs.
    #
    # ``get_raw_azure_username`` shells out to ``az`` and may fail in
    # degraded environments — in that case we degrade to "no filter",
    # which preserves the previous behavior, but emit a warning so the
    # user knows what's happening.
    try:
        current_az_user = get_raw_azure_username() or ""
    except Exception as exc:
        debug(f"cancel --since: az lookup failed: {exc}")
        current_az_user = ""

    skipped_other_user: list[JobHistoryEntry] = []
    if current_az_user:
        kept: list[JobHistoryEntry] = []
        for entry in entries:
            recorded = entry.azure_username or ""
            # Older entries (recorded before the azure_username field
            # existed) have an empty recorded user. Treat them as
            # "matches anyone" so backwards compatibility holds — we
            # have no way to verify them, but they were written by
            # whoever owned this HOME at the time.
            if recorded and recorded != current_az_user:
                skipped_other_user.append(entry)
                continue
            kept.append(entry)
        entries = kept
        if skipped_other_user:
            info(
                f"Skipping {len(skipped_other_user)} entr"
                f"{'y' if len(skipped_other_user) == 1 else 'ies'} from a "
                f"different Azure login (current: {current_az_user})."
            )

    if not entries:
        info(
            "No locally-recorded jobs for the current Azure login "
            f"({current_az_user}) since {cutoff.isoformat()}."
        )
        return

    # Sort newest-first for the confirmation preview.
    entries_sorted = sorted(
        entries, key=lambda e: e.submitted_at, reverse=True
    )

    console = Console()
    console.print()
    console.print(
        f"[bold]Will cancel {len(entries_sorted)} job"
        f"{'s' if len(entries_sorted) != 1 else ''}[/bold] submitted since "
        f"[cyan]{cutoff.isoformat()}[/cyan]:"
    )
    preview_n = min(10, len(entries_sorted))
    for entry in entries_sorted[:preview_n]:
        cmd_preview = entry.command or "<no command recorded>"
        if len(cmd_preview) > 72:
            cmd_preview = cmd_preview[:71] + "…"
        console.print(
            f"  [cyan]{entry.operation_id}[/cyan]  "
            f"[dim]{entry.submitted_at}[/dim]  {cmd_preview}"
        )
    if len(entries_sorted) > preview_n:
        console.print(
            f"  [dim]… and {len(entries_sorted) - preview_n} more[/dim]"
        )
    console.print()

    if not yes and not typer.confirm("Proceed with cancellation?", default=False):
        info("Cancellation aborted.")
        raise typer.Exit(code=0)

    _run_parallel_cancel(env_cfg, entries_sorted, parallelism=parallelism)


def _cancel_one_op(env_cfg, op_id: str) -> tuple[str, str | None]:
    """Cancel a single op; return ``(op_id, error_message_or_None)``.

    404/409 responses are treated as success — the op is already in a
    terminal state, so the user's goal ("make it stop") is already true.
    """
    try:
        cancel_operation(
            env_cfg.project_name,
            op_id,
            env_cfg.workspace_url,
            api_version=env_cfg.api_version,
        )
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status in (404, 409):
            return op_id, None
        return op_id, f"HTTP {status}: {exc.response.text[:120]}"
    except (httpx.TransportError, PollError) as exc:
        return op_id, f"{type(exc).__name__}: {exc}"
    return op_id, None


def _run_parallel_cancel(
    env_cfg,
    entries: list[JobHistoryEntry],
    *,
    parallelism: int,
) -> None:
    """Fan out cancel calls across a thread pool; exit 1 on any failure."""
    succeeded: list[str] = []
    failed: list[tuple[str, str]] = []
    total = len(entries)
    workers = max(1, min(parallelism, total))
    info(f"Cancelling {total} job(s) with {workers} parallel worker(s)…")
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_cancel_one_op, env_cfg, entry.operation_id):
                entry.operation_id
            for entry in entries
        }
        for fut in as_completed(futures):
            op_id, err_msg = fut.result()
            if err_msg is None:
                succeeded.append(op_id)
                info(f"  [{len(succeeded) + len(failed)}/{total}] ✓ {op_id}")
            else:
                failed.append((op_id, err_msg))
                error(
                    f"  [{len(succeeded) + len(failed)}/{total}] ✗ "
                    f"{op_id}: {err_msg}"
                )
    info(
        f"Done. Cancelled {len(succeeded)} of {total} job(s)"
        f"{'; ' + str(len(failed)) + ' failed' if failed else ''}."
    )
    if failed:
        raise typer.Exit(code=1)


__all__ = ["app", "batch", "cancel", "start", "vscode_cmd"]
