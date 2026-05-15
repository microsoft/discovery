"""Utilities to layer VS Code CLI and a CMD wrapper onto an existing ACR-built image.

This module centralizes logic previously embedded in build_acr_task:
  * Downloading and unpacking the VS Code CLI binary
  * Parsing a base Dockerfile's CMD instruction (simple heuristic)
  * Generating a wrapper script that launches a VS Code tunnel then the original CMD
  * Preparing a temporary build context that layers the CLI + wrapper onto a base image

Public API:
    prepare_vscode_layer(base_full_image: str, dest_dir: Path, base_context: Path) -> Optional[str]
        Populate dest_dir with Dockerfile, VS Code CLI binary, and optional wrapper script.
        Returns wrapper path in image ("/usr/local/bin/cmd-wrapper") if created.

    extract_base_cmd_text(dockerfile_text: str) -> tuple[str|None, list[str]|None]
        Lightweight parser returning shell-form or exec-form CMD.

    download_vscode_cli(dest_dir: Path) -> Path
        Download & extract CLI binary, returning path to 'code'.

Limitations:
  * CMD parse is heuristic; multi-line JSON arrays not fully supported.
  * No checksum validation (could be added later).
  * Tunnel wrapper is optional; created only if a CMD exists.
"""

from __future__ import annotations

import hashlib
import os
import shlex
import shutil
import tarfile
import urllib.request
from pathlib import Path
from textwrap import dedent

import typer

from discovery.common.logging import debug, info


WRAPPER_TARGET_PATH = "/usr/local/bin/start-vscode-tunnel.sh"

CLI_DOWNLOAD_URL = "https://code.visualstudio.com/sha/download?build=stable&os=cli-alpine-x64"


def download_vscode_cli(dest_dir: Path) -> Path:
    """Download and extract VS Code CLI into dest_dir returning path to 'code'."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    archive = dest_dir / "code-server-linux-x64.tar.gz"
    # Also echo to the user with rich formatting; `info` ensures it hits the log file.
    typer.secho(f"Downloading VS Code server CLI: {CLI_DOWNLOAD_URL}", fg=typer.colors.BLUE)
    info(f"download_vscode_cli: GET {CLI_DOWNLOAD_URL} -> {archive}")
    urllib.request.urlretrieve(CLI_DOWNLOAD_URL, archive)  # nosec
    try:
        archive_size = archive.stat().st_size
    except OSError:
        archive_size = -1
    debug(f"download_vscode_cli: downloaded {archive_size} bytes to {archive}")
    bin_path: Path | None = None
    with tarfile.open(archive, "r:gz") as tf:
        for member in tf.getmembers():
            base_name = os.path.basename(member.name)
            if base_name in {"code", "code-server"} and member.isfile():
                debug(f"download_vscode_cli: extracting member {member.name}")
                tf.extract(member, dest_dir)
                extracted = dest_dir / member.name
                final_path = dest_dir / "code"
                shutil.move(str(extracted), final_path)
                bin_path = final_path
                break
    if not bin_path or not bin_path.exists():  # pragma: no cover - defensive
        msg = "VS Code CLI binary not found in archive"
        raise RuntimeError(msg)
    bin_path.chmod(0o755)
    info(f"download_vscode_cli: binary ready at {bin_path}")
    return bin_path


def prepare_vscode_layer(base_full_image: str, dest_dir: Path) -> str:
    """Populate dest_dir with Dockerfile, VS Code CLI, and tunnel wrapper script.

    Args:
        base_full_image: Fully qualified base image reference.
        dest_dir: Temporary build context directory to populate.

    Returns:
        Absolute path inside the container image to the wrapper script.
    """
    info(f"prepare_vscode_layer: base={base_full_image} context={dest_dir}")
    bin_dir = dest_dir / "bin"
    download_vscode_cli(bin_dir)

    wrapper = bin_dir / "start-vscode-tunnel.sh"
    wrapper_text = (
        dedent(
            r"""#!/usr/bin/env bash
            set -euo pipefail

            log_file="${VS_CODE_TUNNEL_LOG:-/tmp/vscode-tunnel.log}"
            max_retries="${VS_CODE_TUNNEL_MAX_RETRIES:-0}"  # 0 = unlimited retries
            retry_delay="${VS_CODE_TUNNEL_RETRY_DELAY:-5}"

            # Mirror all script output to the log file while still writing to
            # stdout so the dataplane captures it in tool_report.logs. Without
            # this, the preflight / startup banner lines below were only ever
            # written to the terminal and never made it into the log file, and
            # any early failure looked like "the job produced no output".
            mkdir -p "$(dirname "${log_file}")"
            exec > >(tee -a "${log_file}") 2>&1

            ts() { date -u +"%Y-%m-%dT%H:%M:%SZ"; }
            log() { echo "[$(ts)] [tunnel] $*"; }

            if [[ "${1:-}" != "--name" || -z "${2:-}" ]]; then
                echo "Usage: $0 --name <tunnel-name> [--provider <github|microsoft>]" >&2
                exit 1
            fi

            tunnel_name="$2"
            shift 2

            # Optional --provider <value>. When absent, we omit the flag and
            # fall back to `code tunnel`'s built-in default (preserves the
            # original GitHub-device-flow behavior for existing images).
            provider=""
            if [[ "${1:-}" == "--provider" ]]; then
                if [[ -z "${2:-}" ]]; then
                    echo "Error: --provider requires a value (github|microsoft)" >&2
                    exit 1
                fi
                provider="$2"
                shift 2
            fi

            cli_data_dir="${VS_CODE_CLI_DATA_DIR:-/root/.vscode-cli}"
            code_bin="/usr/local/bin/code"

            log "=== VS Code tunnel launcher starting ==="
            log "tunnel_name=${tunnel_name}"
            log "provider=${provider:-<default:github>}"
            log "cli_data_dir=${cli_data_dir}"
            log "log_file=${log_file}"
            log "auto-restart=enabled max_retries=${max_retries:-unlimited} delay=${retry_delay}s"

            # ---- Preflight diagnostics ----
            # These cover ~80% of remote-execution support tickets: wrong arch,
            # missing binary, read-only FS, unexpected user, etc.
            log "--- preflight ---"
            log "wrapper version=__WRAPPER_VERSION__ (from CLI generator)"
            log "wrapper sha256=$(sha256sum "$0" 2>/dev/null | cut -d' ' -f1 || echo '?')"
            log "host=$(hostname 2>/dev/null || echo '?') uname=$(uname -a 2>/dev/null || echo '?')"
            log "whoami=$(id -un 2>/dev/null || echo '?') uid=$(id -u 2>/dev/null || echo '?') home=${HOME:-?} pwd=$(pwd)"
            log "PATH=${PATH:-}"
            if [[ -x "${code_bin}" ]]; then
                log "code binary: $(ls -la "${code_bin}" 2>&1 || true)"
                if code_version="$("${code_bin}" --version 2>&1)"; then
                    log "code --version: ${code_version//$'\n'/ | }"
                else
                    log "WARNING: '${code_bin} --version' failed: ${code_version}"
                fi
            else
                log "ERROR: VS Code binary not found or not executable at ${code_bin}"
                ls -la /usr/local/bin/ 2>&1 | sed 's/^/[tunnel] /' || true
                exit 127
            fi
            if ! mkdir -p "${cli_data_dir}" 2>/dev/null; then
                log "WARNING: failed to create cli_data_dir ${cli_data_dir}"
            fi
            log "disk: $(df -h "${cli_data_dir}" 2>/dev/null | tail -1 || echo '?')"
            log "--- end preflight ---"

            # Prefer stdbuf so code's own stdout/stderr are line-buffered when
            # piped. Without this, `code tunnel`'s early output (including the
            # device-flow URL) can sit in a 4KB block buffer and never reach
            # the platform log stream until the process exits.
            if command -v stdbuf >/dev/null 2>&1; then
                buf_prefix=(stdbuf -oL -eL)
                log "output buffering: stdbuf -oL -eL"
            else
                buf_prefix=()
                log "output buffering: default (stdbuf not available)"
            fi

            code_cmd=("${buf_prefix[@]}" "${code_bin}" tunnel --name "${tunnel_name}" --accept-server-license-terms --no-sleep --cli-data-dir "${cli_data_dir}")

            # If the caller selected a non-default auth provider (e.g. microsoft),
            # perform an explicit `code tunnel user login --provider <provider>`
            # first so the subsequent `code tunnel` uses the right identity.
            # Without this step `code tunnel --name` only ever does GitHub
            # device-flow (the built-in default). `user login` is idempotent —
            # if the chosen provider is already cached it returns quickly.
            login_cmd=()
            if [[ -n "${provider}" ]]; then
                login_cmd=("${buf_prefix[@]}" "${code_bin}" tunnel --cli-data-dir "${cli_data_dir}" user login --provider "${provider}")
            fi

            # Auto-restart loop — runs in foreground so code tunnel
            # has proper process context for device-flow auth.
            # Uses exponential backoff to avoid tight restart loops on persistent failures.
            attempt=0
            while true; do
                attempt=$((attempt + 1))
                log "Starting VS Code tunnel (attempt ${attempt})..."

                if [[ -d "${cli_data_dir}" ]] && [[ -n "$(ls -A "${cli_data_dir}" 2>/dev/null)" ]]; then
                    log "Cached CLI data found at ${cli_data_dir} — tunnel should reconnect without re-auth."
                else
                    log "No cached CLI data at ${cli_data_dir} — expect device-flow auth prompt."
                fi

                # Run `user login --provider <provider>` first on each attempt
                # when a non-default provider was requested. `code` itself
                # no-ops this when creds are already cached with the right
                # provider, so the cost of running it every loop iteration is
                # negligible and it makes the behavior self-healing across
                # restarts of the tunnel loop.
                if (( ${#login_cmd[@]} > 0 )); then
                    log "Ensuring ${provider} login via: ${login_cmd[*]}"
                    set +e
                    "${login_cmd[@]}"
                    login_exit=$?
                    set -e
                    log "code tunnel user login exited with code ${login_exit}."
                fi

                set +e
                "${code_cmd[@]}"
                exit_code=$?
                set -e

                log "VS Code tunnel exited with code ${exit_code}."

                if [[ ${max_retries} -gt 0 && ${attempt} -ge ${max_retries} ]]; then
                    log "Max retries (${max_retries}) reached. Giving up."
                    break
                fi

                # Exponential backoff: 5s, 10s, 20s, 40s ... capped at 300s (5 min)
                backoff=$(( retry_delay * (2 ** (attempt - 1)) ))
                if [[ ${backoff} -gt 300 ]]; then
                    backoff=300
                fi
                log "Restarting in ${backoff} seconds..."
                sleep "${backoff}"
            done
            """
        ).strip()
        + "\n"
    )
    # Stamp the rendered wrapper with a short hash of its own pre-substitution
    # source so operators can correlate a running image's logs with the CLI
    # version that generated it. Pair with `sha256sum $0` logged at runtime to
    # also detect post-build tampering.
    wrapper_version = hashlib.sha256(wrapper_text.encode("utf-8")).hexdigest()[:12]
    wrapper_text = wrapper_text.replace("__WRAPPER_VERSION__", wrapper_version)
    debug(f"generated start-vscode-tunnel.sh wrapper version={wrapper_version}")
    wrapper.write_text(wrapper_text, encoding="utf-8")
    wrapper.chmod(0o755)

    # Create azure-login script for interactive Azure CLI login and git credential setup
    azure_login = bin_dir / "azure-login"
    azure_login.write_text(
        r"""#!/bin/bash

# Azure Login and Git Credential Setup Script
# This script performs interactive login and configures git for Azure DevOps

echo "=========================================="
echo "Azure CLI Login and Git Configuration"
echo "=========================================="
echo ""

# Check if az cli is installed
if ! command -v az &> /dev/null; then
    echo "Error: Azure CLI is not installed. Please install it first."
    exit 1
fi

# Perform Azure CLI login
echo "Starting Azure CLI login..."
echo ""
echo "Instructions:"
echo "1. az login will show a URL - open it in your browser"
echo "2. Complete the authentication"
echo "3. Your browser will try to redirect to localhost (it may show an error - that's OK)"
echo "4. Copy the FULL URL from your browser's address bar"
echo "5. Paste it here when prompted"
echo ""

# Run az login in background
az login &
AZ_PID=$!

# Give az login time to start and print the URL
sleep 3

echo ""
echo "=========================================="
read -p "Paste the redirect URL from your browser: " REDIRECT_URL
echo "=========================================="
echo ""

# The redirect URL will be something like:
# http://localhost:8400/?code=xxx&state=xxx
# We need to hit that URL on localhost to complete the az login process

if [[ "$REDIRECT_URL" == *"localhost"* ]]; then
    # Make the request to the local az login server to complete authentication
    echo "Completing authentication..."
    curl -s "$REDIRECT_URL" > /dev/null 2>&1 || true
fi

# Wait for az login to complete
wait $AZ_PID 2>/dev/null
AZ_EXIT=$?

# Check if login was successful
if az account show &>/dev/null; then
    echo ""
    echo "✓ Azure login successful!"
    echo ""

    # Show current account info
    echo "Logged in as:"
    az account show --query "{Name:name, User:user.name, Subscription:id}" -o table
    echo ""
else
    echo "✗ Azure login failed!"
    exit 1
fi

# Configure git credential helper for Azure DevOps
echo "=========================================="
echo "Configuring Git for Azure DevOps..."
echo "=========================================="
echo ""

# Create a custom credential helper script for Azure DevOps
cat > ~/.git-credential-azure << 'CREDHELPER'
#!/bin/bash
# Git credential helper for Azure DevOps using Azure CLI tokens

# Read the input from git
declare -A params
while IFS='=' read -r key value; do
    [[ -z "$key" ]] && break
    params[$key]="$value"
done

protocol="${params[protocol]}"
host="${params[host]}"

# Only handle Azure DevOps URLs
if [[ "$host" == *"dev.azure.com"* ]] || [[ "$host" == *"visualstudio.com"* ]]; then
    # Get an access token for Azure DevOps from Azure CLI
    # Azure DevOps resource ID: 499b84ac-1321-427f-aa17-267ca6975798
    TOKEN=$(az account get-access-token --resource 499b84ac-1321-427f-aa17-267ca6975798 --query accessToken -o tsv 2>/dev/null)

    if [[ -n "$TOKEN" ]]; then
        echo "protocol=$protocol"
        echo "host=$host"
        echo "username=oauth"
        echo "password=$TOKEN"
    fi
fi
CREDHELPER
chmod +x ~/.git-credential-azure

# Configure git to use our custom credential helper for Azure DevOps
git config --global credential.https://dev.azure.com.helper "$HOME/.git-credential-azure"
git config --global credential.https://dev.azure.com.useHttpPath true

# Also configure for the legacy visualstudio.com URLs
git config --global credential.https://visualstudio.com.helper "$HOME/.git-credential-azure"
git config --global credential.https://visualstudio.com.useHttpPath true

echo "✓ Git credential helper configured for Azure DevOps"
echo ""

# Install Azure DevOps extension if not present
echo "Checking Azure DevOps CLI extension..."
if ! az extension show --name azure-devops &> /dev/null; then
    echo "Installing Azure DevOps extension..."
    az extension add --name azure-devops
    echo "✓ Azure DevOps extension installed"
else
    echo "✓ Azure DevOps extension already installed"
fi
echo ""

# Configure default organization (optional - user can set this)
echo "=========================================="
echo "Setup Complete!"
echo "=========================================="
echo ""
echo "You can now use git with Azure DevOps repositories."
echo ""
echo "To clone a repo:"
echo "  git clone https://dev.azure.com/{org}/{project}/_git/{repo}"
echo ""
echo "To set a default Azure DevOps organization:"
echo "  az devops configure --defaults organization=https://dev.azure.com/{your-org}"
echo ""
echo "To set a default project:"
echo "  az devops configure --defaults project={your-project}"
echo ""
""",
        encoding="utf-8",
    )
    azure_login.chmod(0o755)

    dockerfile = dest_dir / "Dockerfile"
    lines = [
        "# Auto-generated Dockerfile layering VS Code CLI and optional CMD wrapper",
        f"FROM {base_full_image}",
        "# Add VS Code CLI binary",
        "COPY --chmod=755 bin/code /usr/local/bin/code",
        "# Add VS Code tunnel start helper",
        "COPY --chmod=755 bin/start-vscode-tunnel.sh /usr/local/bin/start-vscode-tunnel.sh",
        "# Add Azure login helper script",
        "COPY --chmod=755 bin/azure-login /usr/local/bin/azure-login",
    ]
    dockerfile.write_text("\n".join(lines) + "\n", encoding="utf-8")
    debug(
        f"prepare_vscode_layer: wrote Dockerfile={dockerfile} wrapper={wrapper} "
        f"azure_login={azure_login}"
    )

    return WRAPPER_TARGET_PATH


def build_named_tunnel_command(
    command: str, tunnel_name: str, provider: str | None = None
) -> str:
    """Return command that runs the user command in the background and the tunnel in foreground.

    Uses ``code tunnel --name`` which authenticates via device-flow and does
    not require a pre-created tunnel or token.  The session persists across
    process restarts.

    The user command (e.g. ``sleep 7d``) is backgrounded so the tunnel
    process runs in the foreground with proper process context for
    device-flow auth.

    Arguments:
        command: Original user command (will be backgrounded).
        tunnel_name: Stable friendly name for the tunnel.
        provider: Optional auth provider for the tunnel (``"github"`` or
            ``"microsoft"``). When ``None`` (the default) no ``--provider``
            flag is forwarded, preserving ``code tunnel``'s built-in default
            (GitHub) and wire-compatibility with images built before this
            option existed.
    """
    wrapper_args = f"--name {shlex.quote(tunnel_name)}"
    if provider:
        wrapper_args += f" --provider {shlex.quote(provider)}"
    # Background the user command; tunnel runs in foreground
    final_command = (
        f"sh -c '{command} & {WRAPPER_TARGET_PATH} {wrapper_args}'"
    )
    debug(f"Named tunnel command: {final_command}")
    return final_command


__all__ = [
    "build_named_tunnel_command",
    "download_vscode_cli",
    "prepare_vscode_layer",
]
