"""Models for compute usage and status responses."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


# NodepoolInfo field names removed in past CLI upgrades. Silently scrubbed
# pre-validation so old cached nodepool entries keep loading. Append-only.
_REMOVED_NODEPOOLINFO_FIELDS: frozenset[str] = frozenset({
    "scratch_dc_region",  # removed when picker switched from region- to vnet-match
    "storage_id",         # legacy V1 field, replaced by scratch_dc_id
    "storage_region",     # legacy V1 field
})


class NodepoolUsage(BaseModel):
    """Usage information for a node pool."""

    model_config = ConfigDict(populate_by_name=True)

    reserved_cpus: str = Field(alias="reservedCPUs")
    allocatable_cpus: str = Field(alias="allocatableCPUs")
    reserved_memory: str = Field(alias="reservedMemory")
    allocatable_memory: str = Field(alias="allocatableMemory")
    reserved_gpus: str = Field(alias="reservedGPUs")
    allocatable_gpus: str = Field(alias="allocatableGPUs")


def calculate_aks_allocatable_cpu(total_cpus: int) -> int:
    """Calculate allocatable CPUs after AKS and system reservation.

    AKS reserves CPU based on the number of cores:
    - 1 core: 60m
    - 2 cores: 100m
    - 4 cores: 140m
    - 8 cores: 180m
    - 16 cores: 260m
    - 32 cores: 420m
    - 64+ cores: 740m

    Additionally, there's overhead from:
    - OS kernel and system services
    - Daemonsets (monitoring, networking, CSI drivers)
    - AKS system pods

    We reserve 2 CPUs for small nodes, 4 CPUs for large nodes (64+ cores).
    """
    if total_cpus <= 0:
        return 0
    if total_cpus >= 64:
        # Large nodes: reserve 4 CPUs for system overhead
        return total_cpus - 4
    elif total_cpus >= 16:
        # Medium nodes: reserve 3 CPUs
        return total_cpus - 3
    else:
        # Small nodes: reserve 2 CPUs
        return max(1, total_cpus - 2)


def calculate_aks_allocatable_memory(total_memory_gb: int, max_pods: int = 110) -> int:
    """Calculate allocatable memory in GB after AKS and system reservation.

    AKS 1.29+ reserves memory using:
    - 100Mi eviction threshold
    - 20MB * max_pods + 50MB for kube-reserved (or 25% of total, whichever is less)

    Additionally, there's overhead from:
    - OS kernel and buffers
    - Daemonsets (monitoring agents, CSI drivers, etc.)
    - AKS system pods

    We add an extra 5% buffer on top of AKS calculations to ensure schedulability.
    """
    if total_memory_gb <= 0:
        return 0

    # Calculate kube-reserved: 20MB * max_pods + 50MB, capped at 25% of total
    kube_reserved_mb = min(20 * max_pods + 50, int(total_memory_gb * 1024 * 0.25))
    eviction_threshold_mb = 100  # 100Mi eviction threshold

    # Add extra buffer for daemonsets and system pods (~5% of total or minimum 4GB)
    system_overhead_mb = max(4 * 1024, int(total_memory_gb * 1024 * 0.05))

    total_reserved_mb = kube_reserved_mb + eviction_threshold_mb + system_overhead_mb
    total_reserved_gb = total_reserved_mb / 1024

    # Round down and ensure at least 1GB allocatable
    allocatable = int(total_memory_gb - total_reserved_gb)
    return max(1, allocatable)


class NodepoolInfo(BaseModel):
    """Static information about a nodepool for configuration."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def _strip_removed_fields(cls, data: Any) -> Any:
        """Drop NodepoolInfo fields removed in past CLI upgrades.

        Same pattern as ``EnvConfig._strip_removed_fields`` — keeps
        ``extra='forbid'`` strict for typos while letting old cached
        ``nodepools[]`` entries continue to load.
        """
        if not isinstance(data, dict):
            return data
        if any(k in _REMOVED_NODEPOOLINFO_FIELDS for k in data):
            return {k: v for k, v in data.items() if k not in _REMOVED_NODEPOOLINFO_FIELDS}
        return data

    id: str = Field(description="Full Azure resource ID of the nodepool")
    name: str = Field(description="Short name of the nodepool")
    supercomputer_id: str = Field(default="", description="Full Azure resource ID of the parent supercomputer")
    supercomputer_name: str = Field(default="", description="Name of the supercomputer containing this nodepool")
    resource_group: str = Field(default="", description="Resource group containing the nodepool")
    scratch_dc_id: str = Field(
        default="",
        description="Full Azure resource ID of the per-supercomputer Scratch ANF wrapper "
                    "(V1: DiscoveryStorage-kind dataContainer; V2: AzureNetAppFiles-kind "
                    "storageContainer) providing /scratch when 'discovery start --scratch' "
                    "is set. Empty when no Scratch wrapper is configured for this SC.",
    )
    sku: str = Field(default="", description="VM SKU/size name (e.g., Standard_ND96amsr_A100_v4)")
    cpus: str = Field(default="", description="vCPUs per node (total)")
    memory: str = Field(default="", description="Memory per node in GB (total)")
    gpus: str = Field(default="", description="GPUs per node")
    max_nodes: int = Field(default=0, description="Maximum number of nodes in the pool")

    @property
    def allocatable_cpus(self) -> str:
        """Return allocatable CPUs after AKS system reservation."""
        if self.cpus:
            try:
                total = int(self.cpus)
                return str(calculate_aks_allocatable_cpu(total))
            except ValueError:
                pass
        return ""

    @property
    def allocatable_memory(self) -> str:
        """Return allocatable memory in GB after AKS system reservation."""
        if self.memory:
            try:
                total = int(self.memory)
                return str(calculate_aks_allocatable_memory(total))
            except ValueError:
                pass
        return ""

    @property
    def qualified_name(self) -> str:
        """Return supercomputer/name for unique identification."""
        if self.supercomputer_name:
            return f"{self.supercomputer_name}/{self.name}"
        return self.name

    @property
    def max_cpus(self) -> str:
        """Return maximum CPUs available in the pool (cpus * max_nodes)."""
        if self.cpus and self.max_nodes:
            try:
                return str(int(self.cpus) * self.max_nodes)
            except ValueError:
                pass
        return ""

    @property
    def max_gpus(self) -> str:
        """Return maximum GPUs available in the pool (gpus * max_nodes)."""
        if self.gpus and self.max_nodes:
            try:
                return str(int(self.gpus) * self.max_nodes)
            except ValueError:
                pass
        return ""


class SupercomputerUsage(BaseModel):
    """Usage information for a supercomputer."""

    model_config = ConfigDict(populate_by_name=True)

    active_jobs: int = Field(alias="activeJobs")
    pending_jobs: int = Field(alias="pendingJobs")
    nodepools: dict[str, NodepoolUsage]


class ComputeUsageModel(BaseModel):
    """Model representing compute usage across supercomputers."""

    model_config = ConfigDict(populate_by_name=True)

    supercomputers: dict[str, SupercomputerUsage]
