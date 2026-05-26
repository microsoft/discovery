"""Pydantic models for data asset management."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class DataAssetInputs(BaseModel):
    """Input parameters for creating or deploying a data asset.

    Maps to the parameters in templates/dataasset/template.json.
    """

    name: str = Field(description="Name of the data asset")
    data_container_name: str = Field(description="Name of the parent data container")
    location: str = Field(description="Azure region for the data asset")
    description: str = Field(default="", description="Description of the data asset")
    path: str = Field(description="Blob storage path for the data asset")
    api_version: str = Field(
        default="2025-07-01-preview",
        description="API version for Microsoft.Discovery/dataContainers/dataAssets",
    )

    model_config = ConfigDict(
        str_strip_whitespace=True,
        populate_by_name=True,
    )


class StorageAssetInputs(BaseModel):
    """Input parameters for creating or deploying a storage asset.

    Storage assets are the v2 equivalent of data assets, introduced in the
    ``2026-02-01-preview`` API version. They live under
    ``Microsoft.Discovery/storagecontainers/{name}/storageAssets/{asset}``
    and carry the same ``description``/``path`` properties as data assets.

    Maps to the parameters in templates/storageasset/template.json.
    """

    name: str = Field(description="Name of the storage asset")
    storage_container_name: str = Field(description="Name of the parent storage container")
    location: str = Field(description="Azure region for the storage asset")
    description: str = Field(default="", description="Description of the storage asset")
    path: str = Field(
        description=(
            "Path within the backing storage. For AzureStorageBlob the first path "
            "segment is the blob container name; any remaining segments are an "
            "in-container subpath."
        )
    )
    api_version: str = Field(
        default="2026-02-01-preview",
        description="API version for Microsoft.Discovery/storagecontainers/storageAssets",
    )

    model_config = ConfigDict(
        str_strip_whitespace=True,
        populate_by_name=True,
    )


class BlobContainerInputs(BaseModel):
    """Input parameters for creating or checking a blob container."""

    storage_account_name: str = Field(description="Name of the storage account")
    container_name: str = Field(description="Name of the blob container")
    subscription_id: str = Field(description="Azure subscription ID")
    resource_group: str = Field(description="Resource group containing the storage account")
    public_access: Literal["off", "blob", "container"] = Field(
        default="off",
        description="Public access level (off, blob, container)",
    )

    model_config = ConfigDict(
        str_strip_whitespace=True,
        populate_by_name=True,
    )


class DataContainerInputs(BaseModel):
    """Input parameters for creating or deploying a DiscoveryStorage-kind data container.

    Maps to the parameters in templates/datacontainer/template.json. Only the
    DiscoveryStorage variant is supported here — the CLI's other flows
    consume blob-kind dataContainers that are typically pre-created (workspace
    setup) and the V1 ANF wrapping pattern is the only kind we need to author
    on demand.
    """

    name: str = Field(description="Name of the data container")
    location: str = Field(description="Azure region for the data container")
    discovery_storage_id: str = Field(
        description=(
            "Full ARM resource ID of the Microsoft.Discovery/storages (ANF) "
            "resource this dataContainer wraps."
        ),
    )
    credential_identity_id: str = Field(
        description=(
            "Full ARM resource ID of a user-assigned managed identity Discovery "
            "should use to access the wrapped storage. V1 dataContainers require "
            "a credentials block on the wire regardless of dataStore.kind; "
            "typically the workspace's workspaceIdentity.id."
        ),
    )
    api_version: str = Field(
        default="2025-07-01-preview",
        description="API version for Microsoft.Discovery/dataContainers",
    )

    model_config = ConfigDict(
        str_strip_whitespace=True,
        populate_by_name=True,
    )


class BlobDataContainerInputs(BaseModel):
    """Input parameters for creating an ``AzureStorageBlob``-kind V1 dataContainer.

    Wraps a ``Microsoft.Storage/storageAccounts`` resource. Requires a UAMI
    that has the necessary RBAC over the wrapped account
    (Storage Blob Data Contributor or similar) — typically the workspace's
    own ``workspaceIdentity``.
    """

    name: str = Field(description="Name of the data container")
    location: str = Field(description="Azure region for the data container")
    storage_account_id: str = Field(
        description="Full ARM resource ID of a Microsoft.Storage/storageAccounts to wrap.",
    )
    credential_identity_id: str = Field(
        description=(
            "Full ARM resource ID of a user-assigned managed identity with RBAC "
            "to access the storage account. Typically the workspace's "
            "workspaceIdentity.id."
        ),
    )
    api_version: str = Field(
        default="2025-07-01-preview",
        description="API version for Microsoft.Discovery/dataContainers",
    )

    model_config = ConfigDict(
        str_strip_whitespace=True,
        populate_by_name=True,
    )


class StorageContainerInputs(BaseModel):
    """Input parameters for creating an AzureNetAppFiles-kind storage container.

    V2 (``2026-02-01-preview``) equivalent of ``DataContainerInputs``: wraps a
    ``Microsoft.NetApp/netAppAccounts/capacityPools/volumes`` resource.
    """

    name: str = Field(description="Name of the storage container")
    location: str = Field(description="Azure region for the storage container")
    netapp_volume_id: str = Field(
        description=(
            "Full ARM resource ID of the "
            "Microsoft.NetApp/netAppAccounts/capacityPools/volumes resource this "
            "storageContainer wraps."
        ),
    )
    api_version: str = Field(
        default="2026-02-01-preview",
        description="API version for Microsoft.Discovery/storageContainers",
    )

    model_config = ConfigDict(
        str_strip_whitespace=True,
        populate_by_name=True,
    )


class BlobStorageContainerInputs(BaseModel):
    """Input parameters for creating an ``AzureStorageBlob``-kind V2 storageContainer.

    Wraps a ``Microsoft.Storage/storageAccounts`` resource. V2 storageContainers
    don't carry a credentials block (RBAC is inferred via the workspace's
    workload identity binding), so this only needs name + location + account ID.
    """

    name: str = Field(description="Name of the storage container")
    location: str = Field(description="Azure region for the storage container")
    storage_account_id: str = Field(
        description="Full ARM resource ID of a Microsoft.Storage/storageAccounts to wrap.",
    )
    api_version: str = Field(
        default="2026-02-01-preview",
        description="API version for Microsoft.Discovery/storageContainers",
    )

    model_config = ConfigDict(
        str_strip_whitespace=True,
        populate_by_name=True,
    )


__all__ = [
    "BlobContainerInputs",
    "BlobDataContainerInputs",
    "BlobStorageContainerInputs",
    "DataAssetInputs",
    "DataContainerInputs",
    "StorageAssetInputs",
    "StorageContainerInputs",
]
