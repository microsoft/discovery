"""Simple programmatic API for Discovery CLI.

This module provides a clean Python API that mirrors the CLI experience,
abstracting away the complexity of configuration loading and payload building.

Example usage:

    from discovery.poll.api import DiscoveryClient

    # Initialize client (loads config from ~/.discovery-sc-config)
    client = DiscoveryClient()

    # Upload files
    client.upload("./local/file.txt", "user:data/file.txt")
    client.upload("./local/folder", "user:data/", recursive=True)

    # Download files
    client.download("user:data/file.txt", "./local/")
    client.download("user:data/", "./local/data", recursive=True)

    # List files
    files = client.ls("user:data/")

    # Submit a job
    result = client.start("python train.py", gpus=4, memory="64Gi")

    # Submit and don't wait
    operation_id = client.start("python train.py", wait=False)

    # Check status
    status = client.status(operation_id)

    # Cancel a job
    client.cancel(operation_id)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from discovery.poll.cli_helpers import (
    get_azure_username,
    get_config_file_path,
    load_project_config,
)
from discovery.poll.cli_storage import (
    get_storage_account_name,
    list_blobs_az,
    parse_storage_path,
    remove_blobs_az,
    run_azcopy_command,
)
from discovery.poll.dataplane_api import (
    cancel_operation,
    get_operation_status,
    list_operations,
    run_and_poll,
    start_tool_run,
)
from discovery.poll.models.config import EnvConfig
from discovery.poll.models.tool_run import (
    DataMount,
    InfraOverrides,
    ResourceSpec,
    ToolRunRequest,
)


def _normalize_memory(memory: str | None) -> str | None:
    """Normalize memory specification to proper format with 'Gi' suffix."""
    if memory is None:
        return None
    if re.match(r"^\d+$", memory.strip()):
        return f"{memory.strip()}Gi"
    return re.sub(r"gi$", "Gi", memory.strip(), flags=re.IGNORECASE)


@dataclass
class JobResult:
    """Result of a submitted job."""

    operation_id: str
    status: str
    logs: list[str] = field(default_factory=list)
    error: str | None = None
    runtime_details: str | None = None


@dataclass
class BlobInfo:
    """Information about a blob in storage."""

    name: str
    size: int
    last_modified: str


class DiscoveryClient:
    """Simple API client for Discovery operations.

    Loads configuration from ~/.discovery-sc-config on initialization.
    Provides methods that mirror CLI commands with sensible defaults.
    """

    def __init__(self, config_path: Path | None = None) -> None:
        """Initialize the client.

        Args:
            config_path: Optional path to config file. Defaults to ~/.discovery-sc-config
        """
        self._config_path = config_path or get_config_file_path()
        self._env_cfg: EnvConfig | None = None
        self._username: str | None = None

    @property
    def config(self) -> EnvConfig:
        """Lazy-load and cache the environment configuration."""
        if self._env_cfg is None:
            self._env_cfg = load_project_config(self._config_path)
        return self._env_cfg

    @property
    def username(self) -> str:
        """Get the current Azure username."""
        if self._username is None:
            self._username = get_azure_username()
        return self._username

    # -------------------------------------------------------------------------
    # Storage Operations
    # -------------------------------------------------------------------------

    def upload(
        self,
        source: str | Path,
        destination: str,
        recursive: bool = False,
        overwrite: bool = True,
    ) -> bool:
        """Upload a file or directory to storage.

        Args:
            source: Local file or directory path
            destination: Remote path (e.g., "user:data/file.txt" or "shared:models/")
            recursive: Required for directories
            overwrite: Whether to overwrite existing files

        Returns:
            True if upload succeeded

        Examples:
            client.upload("./model.bin", "user:models/model.bin")
            client.upload("./data/", "shared:datasets/", recursive=True)
        """
        source_path = Path(source).resolve()
        if source_path.is_dir() and not recursive:
            raise ValueError(f"'{source}' is a directory. Use recursive=True to upload directories.")

        container, blob_path = parse_storage_path(destination, self.username)
        storage_account = get_storage_account_name(self.config.datacontainer_id)

        if source_path.is_dir():
            if not blob_path.endswith("/"):
                blob_path += "/"
            blob_url = f"https://{storage_account}.blob.core.windows.net/{container}/{blob_path}"
        else:
            blob_url = f"https://{storage_account}.blob.core.windows.net/{container}/{blob_path}"

        args = ["copy", str(source_path), blob_url]
        if recursive:
            args.append("--recursive")
        if overwrite:
            args.extend(["--overwrite", "true"])
        else:
            args.extend(["--overwrite", "false"])

        result = run_azcopy_command(args)
        return result.returncode == 0

    def download(
        self,
        source: str,
        destination: str | Path,
        recursive: bool = False,
        overwrite: bool = True,
    ) -> bool:
        """Download a file or directory from storage.

        Args:
            source: Remote path (e.g., "user:data/file.txt")
            destination: Local destination path
            recursive: Required for directories
            overwrite: Whether to overwrite existing local files

        Returns:
            True if download succeeded

        Examples:
            client.download("user:models/model.bin", "./local/")
            client.download("shared:datasets/", "./data/", recursive=True)
        """
        container, blob_path = parse_storage_path(source, self.username)
        storage_account = get_storage_account_name(self.config.datacontainer_id)

        if not blob_path:
            blob_url = f"https://{storage_account}.blob.core.windows.net/{container}/*"
        else:
            blob_url = f"https://{storage_account}.blob.core.windows.net/{container}/{blob_path}"

        args = ["copy", blob_url, str(destination)]
        if recursive:
            args.append("--recursive")
        if overwrite:
            args.extend(["--overwrite", "true"])
        else:
            args.extend(["--overwrite", "false"])

        result = run_azcopy_command(args)
        return result.returncode == 0

    def ls(self, path: str = "") -> list[BlobInfo]:
        """List contents of storage.

        Args:
            path: Remote path (e.g., "user:data/" or "shared:"). Default: user root

        Returns:
            List of BlobInfo objects

        Examples:
            files = client.ls()  # List user storage root
            files = client.ls("user:data/")
            files = client.ls("shared:models/")
        """
        container, blob_path = parse_storage_path(path, self.username)
        storage_account = get_storage_account_name(self.config.datacontainer_id)

        blobs = list_blobs_az(
            storage_account, container, prefix=blob_path, subscription=self.config.subscription
        )

        return [
            BlobInfo(
                name=blob.get("name", ""),
                size=blob.get("properties", {}).get("contentLength", 0),
                last_modified=blob.get("properties", {}).get("lastModified", ""),
            )
            for blob in blobs
        ]

    def remove(self, path: str, recursive: bool = False) -> bool:
        """Remove files from storage.

        Args:
            path: Remote path to remove
            recursive: Whether to remove directories recursively

        Returns:
            True if removal succeeded

        Examples:
            client.remove("user:data/old_file.txt")
            client.remove("user:data/old_folder/", recursive=True)
        """
        container, blob_path = parse_storage_path(path, self.username)
        storage_account = get_storage_account_name(self.config.datacontainer_id)

        success, _ = remove_blobs_az(
            storage_account,
            container,
            blob_path,
            recursive=recursive,
            subscription=self.config.subscription,
        )
        return success

    # -------------------------------------------------------------------------
    # Job Submission
    # -------------------------------------------------------------------------

    def start(
        self,
        command: str,
        *,
        cpus: int | None = None,
        gpus: int | None = None,
        memory: str | None = None,
        image: str | None = None,
        pool: str | None = None,
        wait: bool = True,
        poll_interval: int = 5,
        timeout: int = 3600,
    ) -> JobResult | str:
        """Start a job on the cluster.

        Args:
            command: Bash command to run
            cpus: Number of CPUs (default: full node from pool config)
            gpus: Number of GPUs (default: full node from pool config)
            memory: Memory to request (e.g., "32Gi")
            image: Custom image URI
            pool: Nodepool name or ID (default: configured default)
            wait: If True, poll until completion. If False, return operation ID immediately.
            poll_interval: Seconds between status polls (when wait=True)
            timeout: Maximum seconds to wait (when wait=True)

        Returns:
            JobResult if wait=True, or operation_id string if wait=False

        Examples:
            # Wait for completion
            result = client.start("python train.py", gpus=4)
            print(result.status)

            # Fire and forget
            op_id = client.start("python train.py", gpus=4, wait=False)
            # ... later ...
            status = client.status(op_id)
        """
        env_cfg = self.config

        # Resolve nodepool
        effective_nodepool_id = env_cfg.nodepool_id
        np_info = None

        if pool:
            try:
                np_info = env_cfg.get_nodepool(pool)
            except ValueError:
                pass
            if np_info:
                effective_nodepool_id = np_info.id
            elif pool.startswith("/"):
                effective_nodepool_id = pool
        else:
            for np in env_cfg.nodepools:
                if np.id == effective_nodepool_id:
                    np_info = np
                    break

        # Apply pool defaults if not specified
        if np_info:
            if cpus is None and np_info.allocatable_cpus:
                try:
                    cpus = int(np_info.allocatable_cpus)
                except ValueError:
                    pass
            if memory is None and np_info.allocatable_memory:
                memory = f"{np_info.allocatable_memory}Gi"
            if gpus is None and np_info.gpus:
                try:
                    gpus = int(np_info.gpus)
                except ValueError:
                    pass

        memory = _normalize_memory(memory)

        # Build infra overrides
        infra_overrides = None
        if any([cpus, gpus, memory, image]):
            resources = None
            if any([cpus, gpus, memory]):
                resources = ResourceSpec(
                    cpu=str(cpus) if cpus is not None else None,
                    gpu=gpus,
                    ram=memory,
                )
            infra_overrides = InfraOverrides(
                resources=resources,
                image_uri=image,
            )

        # Build output URIs
        output_uri = f"discovery://dataassets{env_cfg.datacontainer_id}/dataassets/{self.username}"
        shared_output_uri = f"discovery://dataassets{env_cfg.datacontainer_id}/dataassets/shared"

        payload = ToolRunRequest(
            toolId=env_cfg.tool_id,
            command=command,
            nodePoolIds=[effective_nodepool_id],
            infraOverrides=infra_overrides,
            inputData=[],
            outputData=[
                DataMount(mountPath="/blob_user", uri=output_uri),
                DataMount(mountPath="/blob_shared", uri=shared_output_uri),
            ],
        )

        if not wait:
            response = start_tool_run(env_cfg.project_name, payload, env_cfg.workspace_url, api_version=env_cfg.api_version)
            return response.id

        result = run_and_poll(
            env_cfg.project_name,
            payload,
            env_cfg.workspace_url,
            poll_interval=poll_interval,
            timeout_seconds=timeout,
            api_version=env_cfg.api_version,
        )

        return JobResult(
            operation_id=result.id,
            status=result.status,
            logs=result.result.tool_report.logs if result.result and result.result.tool_report else [],
            error=str(result.error) if result.error else None,
            runtime_details=result.result.runtime_details if result.result else None,
        )

    def status(self, operation_id: str) -> JobResult:
        """Get the status of a job.

        Args:
            operation_id: The operation ID returned from start()

        Returns:
            JobResult with current status
        """
        result = get_operation_status(
            self.config.project_name,
            operation_id,
            self.config.workspace_url,
            api_version=self.config.api_version,
        )

        return JobResult(
            operation_id=result.id,
            status=result.status,
            logs=result.result.tool_report.logs if result.result and result.result.tool_report else [],
            error=str(result.error) if result.error else None,
            runtime_details=result.result.runtime_details if result.result else None,
        )

    def cancel(self, operation_id: str) -> bool:
        """Cancel a running job.

        Args:
            operation_id: The operation ID to cancel

        Returns:
            True if cancellation succeeded
        """
        try:
            cancel_operation(
                self.config.project_name,
                operation_id,
                self.config.workspace_url,
                api_version=self.config.api_version,
            )
            return True
        except Exception:
            return False

    def list_jobs(
        self,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List recent jobs.

        Args:
            status: Filter by status (e.g., "Active", "Succeeded", "Failed")
            limit: Maximum number of jobs to return

        Returns:
            List of job information dictionaries
        """
        response = list_operations(
            self.config.project_name,
            self.config.workspace_url,
            api_version=self.config.api_version,
        )

        jobs = []
        for op in response.values[:limit]:
            if status and op.status != status:
                continue
            jobs.append({
                "id": op.id,
                "status": op.status,
                "created": op.created_at,
            })
        return jobs


__all__ = [
    "BlobInfo",
    "DiscoveryClient",
    "JobResult",
]
