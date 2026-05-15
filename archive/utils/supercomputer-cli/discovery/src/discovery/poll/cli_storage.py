"""Storage-related CLI commands: upload (up), download (down), ls.

These commands support `user:` and `shared:` prefixes to specify which storage
container to use. Default is the current user's storage container.

Examples:
    discovery up ./local/file.txt user:data/file.txt       # Upload to user storage
    discovery down shared:models/model.bin ./local/        # Download from shared storage
    discovery ls user:data/                                 # List user storage contents
    discovery ls shared:                                    # List shared storage root
"""

from __future__ import annotations

import subprocess
from enum import Enum
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from discovery.common.logging import debug, error, info
from discovery.poll.cli_helpers import get_azure_username, get_config_file_path, load_project_config, run_configure_if_needed
from discovery.poll.resources import get_blob_uri_from_datacontainer, get_datacontainer_storage_details


app = typer.Typer()


class StorageType(str, Enum):
    """Storage container type."""

    USER = "user"
    SHARED = "shared"


def parse_storage_path(path: str, default_user: str) -> tuple[str, str]:
    """Parse a storage path with optional prefix.

    Supports formats:
        - "user:path/to/file" - explicit user storage
        - "shared:path/to/file" - shared storage
        - "path/to/file" - defaults to user storage
        - "." or "user:." or "shared:." - root of the storage container

    Args:
        path: The path string, optionally prefixed with "user:" or "shared:"
        default_user: The sanitized username for default user storage

    Returns:
        Tuple of (container_name, blob_path)
    """
    # Handle "." as root/current directory
    if path == ".":
        return default_user, ""

    if path.startswith("user:"):
        blob_path = path[5:].lstrip("/")
        # Treat "." as root
        if blob_path == ".":
            blob_path = ""
        return default_user, blob_path
    elif path.startswith("shared:"):
        blob_path = path[7:].lstrip("/")
        # Treat "." as root
        if blob_path == ".":
            blob_path = ""
        return "shared", blob_path
    else:
        # Default to user storage
        return default_user, path.lstrip("/")


def get_storage_account_name(datacontainer_id: str) -> str:
    """Get storage account name from datacontainer ID.

    Args:
        datacontainer_id: The data container resource ID

    Returns:
        Storage account name
    """
    storage_account_id = get_datacontainer_storage_details(datacontainer_id)
    return storage_account_id.split("/")[-1]


def run_azcopy_command(args: list[str], capture_output: bool = False) -> subprocess.CompletedProcess:
    """Run an azcopy command with proper authentication.

    Args:
        args: Arguments to pass to azcopy (after 'azcopy')
        capture_output: Whether to capture stdout/stderr

    Returns:
        CompletedProcess with return code and output

    Raises:
        RuntimeError: If azcopy is not found or authentication fails
    """
    cmd = ["azcopy"] + args
    debug(f"Running azcopy command: {' '.join(cmd)}")

    try:
        # azcopy uses Azure CLI credentials via AZCOPY_AUTO_LOGIN_TYPE
        env_vars = {"AZCOPY_AUTO_LOGIN_TYPE": "AZCLI"}
        result = subprocess.run(
            cmd,
            capture_output=capture_output,
            text=True,
            check=False,
            env={**subprocess.os.environ, **env_vars},  # type: ignore
        )
        return result
    except FileNotFoundError as exc:
        msg = (
            "azcopy not found. Please install it:\n"
            "  - Linux: https://docs.microsoft.com/en-us/azure/storage/common/storage-use-azcopy-v10\n"
            "  - macOS: brew install azcopy\n"
            "  - Windows: winget install Microsoft.AzCopy"
        )
        raise RuntimeError(msg) from exc


def list_blobs_az(
    storage_account: str,
    container: str,
    prefix: str = "",
    subscription: str | None = None,
) -> list[dict]:
    """List blobs using Azure CLI.

    Args:
        storage_account: Storage account name
        container: Container name
        prefix: Optional prefix to filter by
        subscription: Optional subscription ID

    Returns:
        List of blob info dictionaries
    """
    import json

    cmd = [
        "az",
        "storage",
        "blob",
        "list",
        "--account-name",
        storage_account,
        "--container-name",
        container,
        "--auth-mode",
        "login",
        "-o",
        "json",
    ]

    if prefix:
        cmd.extend(["--prefix", prefix])

    if subscription:
        cmd.extend(["--subscription", subscription])

    debug(f"Listing blobs: {' '.join(cmd)}")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            error(f"Failed to list blobs: {result.stderr.strip()}")
            return []

        return json.loads(result.stdout)
    except Exception as ex:
        error(f"Failed to list blobs: {ex}")
        return []


def remove_blobs_az(
    storage_account: str,
    container: str,
    blob_path: str,
    recursive: bool = False,
    subscription: str | None = None,
) -> tuple[bool, str]:
    """Remove blob(s) using Azure CLI.

    Args:
        storage_account: Storage account name
        container: Container name
        blob_path: Path to blob or prefix for recursive delete
        recursive: Whether to delete all blobs with this prefix
        subscription: Optional subscription ID

    Returns:
        Tuple of (success, message)
    """
    if recursive:
        # Delete all blobs with the given prefix
        cmd = [
            "az",
            "storage",
            "blob",
            "delete-batch",
            "--account-name",
            storage_account,
            "--source",
            container,
            "--pattern",
            f"{blob_path}*" if blob_path else "*",
            "--auth-mode",
            "login",
        ]
    else:
        # Delete a single blob
        cmd = [
            "az",
            "storage",
            "blob",
            "delete",
            "--account-name",
            storage_account,
            "--container-name",
            container,
            "--name",
            blob_path,
            "--auth-mode",
            "login",
        ]

    if subscription:
        cmd.extend(["--subscription", subscription])

    debug(f"Removing blob(s): {' '.join(cmd)}")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            return False, result.stderr.strip()
        return True, result.stdout.strip()
    except Exception as ex:
        return False, str(ex)


@app.command(name="upload")
def upload(
    source: Path = typer.Argument(
        ...,
        exists=True,
        help="Local file or directory to upload",
    ),
    destination: str = typer.Argument(
        ...,
        help="Remote destination path. Prefix with 'user:' or 'shared:' (default: user:)",
    ),
    recursive: bool = typer.Option(
        False,
        "--recursive",
        "-r",
        help="Recursively upload directory contents (required for directories)",
    ),
    overwrite: bool = typer.Option(
        True,
        "--overwrite/--no-overwrite",
        help="Overwrite existing files",
    ),
) -> None:
    """Upload files to storage.

    Examples:
        discovery blob upload ./file.txt user:data/
        discovery blob upload ./folder shared:datasets/ -r
        discovery blob up ./model.bin data/models/
        discovery blob up ./file.txt .                         # Upload to user storage root
        discovery blob up ./file.txt shared:.                  # Upload to shared storage root
        discovery blob up . user:myproject/ -r                 # Upload current dir contents
    """
    env_cfg = load_project_config(get_config_file_path())

    if not env_cfg.datacontainer_id:
        error("Data container not configured. Run 'discovery configure --datacontainer' first.")
        raise typer.Exit(code=1)

    # Check if source is a directory - require -r flag
    if source.is_dir() and not recursive:
        error(f"'{source}' is a directory. Use -r/--recursive to upload directories.")
        raise typer.Exit(code=1)

    try:
        username = get_azure_username()
        container_name, blob_path = parse_storage_path(destination, username)
        storage_account = get_storage_account_name(env_cfg.datacontainer_id)

        # Resolve source to handle "." properly
        source_resolved = source.resolve()

        if source.is_dir():
            # For directories: upload contents INTO the destination path
            # Don't append folder name - user specifies where contents go
            # Ensure destination ends with / for azcopy to treat as directory
            if blob_path and not blob_path.endswith("/"):
                blob_path = blob_path + "/"
            # Use source/* pattern to upload contents, not the folder itself
            source_path = str(source_resolved) + "/*"
        else:
            # For files: if destination is empty or ends with "/", append filename
            if not blob_path or blob_path.endswith("/"):
                blob_path = blob_path + source_resolved.name
            source_path = str(source_resolved)

        # Build blob URL
        blob_url = f"https://{storage_account}.blob.core.windows.net/{container_name}/{blob_path}"

        info(f"Uploading {source} -> {container_name}:{blob_path}")

        # Build azcopy command
        azcopy_args = ["copy", source_path, blob_url]

        if recursive:
            azcopy_args.append("--recursive")

        if overwrite:
            azcopy_args.extend(["--overwrite", "true"])
        else:
            azcopy_args.extend(["--overwrite", "false"])

        result = run_azcopy_command(azcopy_args)

        if result.returncode == 0:
            typer.secho("✓ Upload completed successfully", fg=typer.colors.GREEN)
        else:
            error("Upload failed")
            raise typer.Exit(code=result.returncode)

    except RuntimeError as ex:
        error(str(ex))
        raise typer.Exit(code=1) from ex


@app.command(name="download")
def download(
    source: str = typer.Argument(
        ...,
        help="Remote source path. Prefix with 'user:' or 'shared:' (default: user:)",
    ),
    destination: Path = typer.Argument(
        Path("."),
        help="Local destination path",
    ),
    recursive: bool = typer.Option(
        False,
        "--recursive",
        "-r",
        help="Recursively download directory contents",
    ),
    overwrite: bool = typer.Option(
        True,
        "--overwrite/--no-overwrite",
        help="Overwrite existing local files",
    ),
) -> None:
    """Download files from storage.

    Examples:
        discovery blob download user:data/file.txt ./local/
        discovery blob download shared:models/ ./models/ -r
        discovery blob down data/results.json ./
        discovery blob down user:. . -r                        # Download all from user storage root
    """
    env_cfg = load_project_config(get_config_file_path())

    if not env_cfg.datacontainer_id:
        error("Data container not configured. Run 'discovery configure --datacontainer' first.")
        raise typer.Exit(code=1)

    try:
        username = get_azure_username()
        container_name, blob_path = parse_storage_path(source, username)
        storage_account = get_storage_account_name(env_cfg.datacontainer_id)

        # Build blob URL - use wildcard for root to download all contents
        if not blob_path:
            blob_url = f"https://{storage_account}.blob.core.windows.net/{container_name}/*"
        else:
            blob_url = f"https://{storage_account}.blob.core.windows.net/{container_name}/{blob_path}"

        info(f"Downloading {container_name}:{blob_path or '/'} -> {destination}")

        # Build azcopy command
        azcopy_args = ["copy", blob_url, str(destination)]

        if recursive:
            azcopy_args.append("--recursive")

        if overwrite:
            azcopy_args.extend(["--overwrite", "true"])
        else:
            azcopy_args.extend(["--overwrite", "false"])

        result = run_azcopy_command(azcopy_args)

        if result.returncode == 0:
            typer.secho("✓ Download completed successfully", fg=typer.colors.GREEN)
        else:
            error("Download failed")
            raise typer.Exit(code=result.returncode)

    except RuntimeError as ex:
        error(str(ex))
        raise typer.Exit(code=1) from ex


@app.command(name="ls")
def ls(
    path: str = typer.Argument(
        "",
        help="Remote path to list. Prefix with 'user:' or 'shared:' (default: user:)",
    ),
    reverse: bool = typer.Option(
        False,
        "--reverse",
        "-r",
        help="Reverse sort order (oldest first instead of newest first)",
    ),
    simple: bool = typer.Option(
        False,
        "--simple",
        "-s",
        help="Simple output (names only, no details)",
    ),
) -> None:
    """List contents of storage.

    Shows files sorted by modification time (newest first) with human-readable sizes.

    Examples:
        discovery ls                           # List user storage root
        discovery ls user:data/                # List user:data/ directory
        discovery ls shared:models/            # List shared models
        discovery ls -r                        # Reverse order (oldest first)
        discovery ls -s                        # Simple format (names only)
    """
    env_cfg = load_project_config(get_config_file_path())

    if not env_cfg.datacontainer_id:
        error("Data container not configured. Run 'discovery configure --datacontainer' first.")
        raise typer.Exit(code=1)

    try:
        username = get_azure_username()
        container_name, blob_prefix = parse_storage_path(path, username)
        storage_account = get_storage_account_name(env_cfg.datacontainer_id)

        debug(f"Listing {container_name}:{blob_prefix}")

        blobs = list_blobs_az(
            storage_account,
            container_name,
            blob_prefix,
            env_cfg.subscription,
        )

        if not blobs:
            typer.echo(f"No files found in {container_name}:{blob_prefix or '/'}")
            return

        # Sort by modification time (newest first by default, like ls -t)
        def get_modified_time(blob: dict) -> str:
            return blob.get("properties", {}).get("lastModified", "")

        blobs_sorted = sorted(blobs, key=get_modified_time, reverse=not reverse)

        console = Console()

        if simple:
            # Simple format - just names
            for blob in blobs_sorted:
                name = blob.get("name", "")
                # Remove prefix for cleaner display
                if blob_prefix and name.startswith(blob_prefix):
                    display_name = name[len(blob_prefix):].lstrip("/") or name
                else:
                    display_name = name
                typer.echo(display_name)
        else:
            # Long format with human-readable sizes
            from datetime import datetime

            # Calculate total size
            total_size = sum(blob.get("properties", {}).get("contentLength", 0) for blob in blobs_sorted)

            typer.echo(f"total {_format_size(total_size)}")

            for blob in blobs_sorted:
                name = blob.get("name", "")
                size = blob.get("properties", {}).get("contentLength", 0)
                modified = blob.get("properties", {}).get("lastModified", "")

                size_str = _format_size(size).rjust(10)

                # Format date like ls -l
                if modified:
                    try:
                        dt = datetime.fromisoformat(modified.replace("Z", "+00:00"))
                        # Use different format for recent files vs older files (like ls)
                        now = datetime.now(dt.tzinfo)
                        if (now - dt).days < 180:
                            modified_str = dt.strftime("%b %d %H:%M")
                        else:
                            modified_str = dt.strftime("%b %d  %Y")
                    except Exception:
                        modified_str = modified[:12]
                else:
                    modified_str = ""

                # Remove prefix for cleaner display
                if blob_prefix and name.startswith(blob_prefix):
                    display_name = name[len(blob_prefix):].lstrip("/") or name
                else:
                    display_name = name

                typer.echo(f"{size_str}  {modified_str.ljust(12)}  {display_name}")

        # Show summary
        typer.echo(f"\n{len(blobs)} item(s) in {container_name}:{blob_prefix or '/'}")

    except RuntimeError as ex:
        error(str(ex))
        raise typer.Exit(code=1) from ex


def _format_size(size: int) -> str:
    """Format size in human-readable format.

    Args:
        size: Size in bytes

    Returns:
        Formatted size string (e.g., "1.5 MB")
    """
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024:
            if unit == "B":
                return f"{size} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} PB"


@app.command(name="remove")
def remove(
    path: str = typer.Argument(
        ...,
        help="Remote path to remove. Prefix with 'user:' or 'shared:' (default: user:)",
    ),
    recursive: bool = typer.Option(
        False,
        "--recursive",
        "-r",
        help="Recursively remove directory contents",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Force removal without confirmation",
    ),
) -> None:
    """Remove files from storage.

    By default, prompts for confirmation before deleting.
    Use -f/--force to skip confirmation.
    Use -r/--recursive to delete directories.

    Examples:
        discovery rm user:data/file.txt           # Remove single file (with confirmation)
        discovery rm shared:temp/old.log -f       # Remove without confirmation
        discovery rm data/cache/ -rf              # Remove directory recursively, no confirmation
        discovery remove user:models/old/ -r      # Remove directory (with confirmation)
    """
    env_cfg = load_project_config(get_config_file_path())

    if not env_cfg.datacontainer_id:
        error("Data container not configured. Run 'discovery configure --datacontainer' first.")
        raise typer.Exit(code=1)

    try:
        username = get_azure_username()
        container_name, blob_path = parse_storage_path(path, username)
        storage_account = get_storage_account_name(env_cfg.datacontainer_id)

        if not blob_path:
            error("Cannot remove root directory. Specify a path to remove.")
            raise typer.Exit(code=1)

        # Get list of files to be deleted for confirmation
        blobs = list_blobs_az(
            storage_account,
            container_name,
            blob_path,
            env_cfg.subscription,
        )

        if not blobs:
            error(f"No files found matching {container_name}:{blob_path}")
            raise typer.Exit(code=1)

        # Check if path matches multiple files and -r is not specified
        if len(blobs) > 1 and not recursive:
            # Check if it's a directory (multiple files with same prefix)
            error(
                f"'{container_name}:{blob_path}' matches {len(blobs)} files. "
                "Use -r/--recursive to remove directories."
            )
            raise typer.Exit(code=1)

        # Show what will be deleted
        if recursive:
            info(f"Will remove {len(blobs)} file(s) from {container_name}:{blob_path}")
        else:
            info(f"Will remove: {container_name}:{blob_path}")

        # Confirm deletion unless --force
        if not force:
            if len(blobs) > 5:
                # Show first 5 files for large deletions
                for blob in blobs[:5]:
                    typer.echo(f"  {blob.get('name', '')}")
                typer.echo(f"  ... and {len(blobs) - 5} more file(s)")
            else:
                for blob in blobs:
                    typer.echo(f"  {blob.get('name', '')}")

            confirm = typer.confirm("Are you sure you want to delete these file(s)?")
            if not confirm:
                typer.echo("Aborted.")
                raise typer.Exit(code=0)

        # Perform deletion
        success, message = remove_blobs_az(
            storage_account,
            container_name,
            blob_path,
            recursive=recursive or len(blobs) > 1,
            subscription=env_cfg.subscription,
        )

        if success:
            typer.secho(
                f"✓ Removed {len(blobs)} file(s) from {container_name}:{blob_path}",
                fg=typer.colors.GREEN,
            )
        else:
            error(f"Failed to remove: {message}")
            raise typer.Exit(code=1)

    except typer.Exit:
        # Re-raise typer.Exit as-is (don't convert to error)
        raise
    except RuntimeError as ex:
        error(str(ex))
        raise typer.Exit(code=1) from ex


@app.command()
def storage_url() -> None:
    """Print the Azure portal URL for the storage account of the configured data container."""
    env_cfg = run_configure_if_needed(get_config_file_path())

    if not env_cfg.datacontainer_id:
        error("Data container not configured. Run 'configure --datacontainer' first.")
        raise typer.Exit(code=1)

    try:
        storage_account_id = get_datacontainer_storage_details(env_cfg.datacontainer_id)
        storage_account_name = storage_account_id.split("/")[-1]
        debug(f"Storage account: {storage_account_name}")

        parts = storage_account_id.split("/")
        min_parts = 9
        if len(parts) < min_parts or parts[1] != "subscriptions":
            error(f"Invalid storage account resource ID format: {storage_account_id}")
            raise typer.Exit(code=1)

        tenant_cmd = ["az", "account", "show", "--query", "tenantId", "-o", "tsv"]
        debug(f"Getting tenant ID: {' '.join(tenant_cmd)}")

        try:
            tenant_res = subprocess.run(tenant_cmd, capture_output=True, text=True, check=False)
            if tenant_res.returncode != 0:
                error("Failed to get tenant ID from az account")
                raise typer.Exit(code=1)
            tenant_id = tenant_res.stdout.strip()
        except OSError as exc:
            error(f"Azure CLI 'az' not found: {exc}")
            raise typer.Exit(code=1) from exc

        storage_resource_path = storage_account_id.lstrip("/")
        portal_url = f"https://portal.azure.com/#@{tenant_id}/resource/{storage_resource_path}/containersList"

        console = Console()
        console.print(f"\n[cyan]Storage Account:[/cyan] {storage_account_name}")
        console.print(f"\n[green]Azure Portal URL:[/green]\n{portal_url}\n")
        console.print(
            "[dim]Note: Blob containers (like your username and 'shared') are created separately.[/dim]\n"
        )

    except RuntimeError as ex:
        error(f"Failed to get storage URL: {ex}")
        raise typer.Exit(code=1) from ex


@app.command()
def create_user_storage(
    username: str = typer.Argument(
        ..., help="Username to create data asset and blob container for"
    ),
) -> None:
    """Create a data asset and blob container for a specific username.

    This is useful for provisioning storage for team members or service accounts.
    The username should be alphanumeric (hyphens allowed).
    """
    # Import here to avoid circular dependency
    from discovery.poll.cli_build import ensure_data_assets_and_containers

    debug(f"create_user_storage(): entering for username={username}")
    env_cfg = load_project_config(get_config_file_path())

    if not env_cfg.datacontainer_id:
        error("Data container not configured. Run 'discovery configure --datacontainer' first.")
        raise typer.Exit(code=1)

    ensure_data_assets_and_containers(env_cfg, usernames=[username])


__all__ = [
    "app",
    "create_user_storage",
    "download",
    "ls",
    "parse_storage_path",
    "remove",
    "storage_url",
    "upload",
]
