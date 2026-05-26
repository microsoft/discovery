"""Pydantic models for tool run request payload.

Derived from sample at tests/artifacts/toolrun.json and schema toolrun.schema.json.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class InlineFile(BaseModel):
    mount_path: str = Field(..., alias="mountPath", min_length=1)
    encoded_file: str = Field(
        ...,
        alias="encodedFile",
        min_length=1,
        description="Base64 encoded file contents",
    )

    model_config = ConfigDict(
        populate_by_name=True,
        str_strip_whitespace=True,
        serialize_by_alias=True,
    )


class DataMount(BaseModel):
    mount_path: str = Field(..., alias="mountPath", min_length=1)
    uri: str | None = Field(None, description="discovery://dataassets URI (api <= 2025-12-01-preview)")
    storage_uri: str | None = Field(None, alias="storageUri", description="discovery://storageassets URI (api >= 2026-02-01-preview)")

    model_config = ConfigDict(
        populate_by_name=True,
        str_strip_whitespace=True,
        serialize_by_alias=True,
    )


class ResourceSpec(BaseModel):
    """Resource requirements specification."""

    cpu: str | None = None
    ram: str | None = None
    gpu: int | None = None

    model_config = ConfigDict(
        populate_by_name=True,
        str_strip_whitespace=True,
        serialize_by_alias=True,
    )


class InfraOverrides(BaseModel):
    """Infrastructure override configuration (legacy api-version 2025-07-01-preview).

    Uses nested ``resources`` and ``poolSize``. For api-version >= 2025-12-01-preview,
    use :class:`InfraOverridesFlat` instead — the server schema changed to flat fields
    and rejects unknown members (including ``resources``).
    """

    resources: ResourceSpec | None = None
    pool_size: int | None = Field(None, alias="poolSize")
    image_uri: str | None = Field(None, alias="imageUri")

    model_config = ConfigDict(
        populate_by_name=True,
        str_strip_whitespace=True,
        serialize_by_alias=True,
    )


class InfraOverridesFlat(BaseModel):
    """Infrastructure override configuration (api-version >= 2025-12-01-preview).

    Flat schema matching the server-side ``InfraOverrides`` contract in
    Microsoft.AiForScience.Supercomputer.Common.Models.Version20251201Preview and
    Version20260201Preview. The server rejects unknown members, so the legacy nested
    ``resources`` field must not be sent on these api versions.
    """

    cpu: str | None = None
    ram: str | None = None
    gpu: str | None = None
    replica_count: int | None = Field(None, alias="replicaCount")
    image_uri: str | None = Field(None, alias="imageUri")

    model_config = ConfigDict(
        populate_by_name=True,
        str_strip_whitespace=True,
        serialize_by_alias=True,
    )


class ToolRunRequest(BaseModel):
    tool_id: str = Field(..., alias="toolId")
    storage_id: str | None = Field(None, alias="storageId")  # omitted for api >= 2026-02-01-preview
    command: str = Field()
    inline_files: list[InlineFile] = Field(default_factory=list, alias="inlineFiles")
    input_data: list[DataMount] = Field(default_factory=list, alias="inputData")
    output_data: list[DataMount] = Field(default_factory=list, alias="outputData")
    node_pool_ids: list[str] = Field(default_factory=list, alias="nodePoolIds")
    infra_overrides: InfraOverrides | InfraOverridesFlat | None = Field(None, alias="infraOverrides")

    model_config = ConfigDict(
        populate_by_name=True,
        str_strip_whitespace=True,
        serialize_by_alias=True,
    )

    def model_dump_json(self, **kwargs) -> str:
        """Serialize to JSON, excluding None fields so storageId/uri/storageUri are omitted when not set."""
        kwargs.setdefault("exclude_none", True)
        return super().model_dump_json(**kwargs)

    def has_outputs(self) -> bool:
        """Return True if any output mount paths defined."""
        return bool(self.output_data)


__all__ = [
    "DataMount",
    "InfraOverrides",
    "InfraOverridesFlat",
    "InlineFile",
    "ResourceSpec",
    "ToolRunRequest",
]
