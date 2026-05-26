"""Config models using Pydantic for validation and persistence logic."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from discovery.common.logging import info
from discovery.poll.models.compute import NodepoolInfo


# Field names (root-level, by alias) that previous CLI versions persisted but
# the current schema no longer recognises. Listed here so they can be silently
# scrubbed during load without weakening extra='forbid' for genuine typos.
# Append to this list whenever a field is removed; never delete entries.
_REMOVED_ENVCONFIG_FIELDS: frozenset[str] = frozenset({
    "DISCOVERY_SUPERCOMPUTER_ID",  # removed: never read; SC ID derived from nodepool_id / NodepoolInfo
    "DISCOVERY_STORAGE_ID",        # removed when V1 storageId field was dropped from wire
})


class EnvConfig(BaseSettings):
    """Represents values stored in ~/.discovery-sc-config for Discovery Poll CLI.

    Behavior parity with previous dataclass version:
      - Empty strings instead of None for unset fields
      - load() classmethod populates from file, tracking original values
      - persist_* methods write only changed/selected keys
    """

    path: Path
    workspace_url: str = Field(default="", alias="DISCOVERY_WORKSPACE_URL")
    workspace_resource_id: str = Field(default="", alias="DISCOVERY_WORKSPACE_RESOURCE_ID")
    project_id: str = Field(default="", alias="DISCOVERY_PROJECT_ID")
    datacontainer_id: str = Field(default="", alias="DISCOVERY_DATACONTAINER_ID")
    storagecontainer_id: str = Field(default="", alias="DISCOVERY_STORAGECONTAINER_ID")
    api_version: str = Field(default="2025-07-01-preview", alias="DISCOVERY_API_VERSION")
    nodepool_id: str = Field(default="", alias="DISCOVERY_NODEPOOL_ID")
    nodepools: list[NodepoolInfo] = Field(default_factory=list, description="Available nodepools")
    supercomputer_scratch_dcs: dict[str, str] = Field(
        default_factory=dict,
        alias="DISCOVERY_SUPERCOMPUTER_SCRATCH_DCS",
        description=(
            "V1: per-supercomputer scratch dataContainer selection "
            "(supercomputer ID -> Microsoft.Discovery/datacontainers ID of kind=DiscoveryStorage). "
            "Used when the user passes --scratch on a tool-run submission to construct the "
            "explicit /scratch URI."
        ),
    )
    supercomputer_scratch_scs: dict[str, str] = Field(
        default_factory=dict,
        alias="DISCOVERY_SUPERCOMPUTER_SCRATCH_SCS",
        description=(
            "V2: per-supercomputer scratch storageContainer selection "
            "(supercomputer ID -> Microsoft.Discovery/storagecontainers ID of "
            "kind=AzureNetAppFiles). Used when the user passes --scratch on a tool-run "
            "submission on V2+ APIs to construct the explicit /scratch URI."
        ),
    )
    tool_id: str = Field(default="", alias="DISCOVERY_TOOL_ID")
    acr_name: str = Field(default="", alias="ACR_NAME")
    acr_login_server: str = Field(default="", alias="ACR_LOGIN_SERVER")

    model_config = SettingsConfigDict(
        str_strip_whitespace=True, populate_by_name=True, env_prefix="",
        serialize_by_alias=True,
        # Strict: unknown fields surface as ValidationError so typos can't
        # silently slip through. Known historical fields removed by past CLI
        # upgrades are scrubbed pre-validation by the @model_validator below.
        extra="forbid",
    )

    @model_validator(mode="before")
    @classmethod
    def _strip_removed_fields(cls, data: Any) -> Any:
        """Drop fields removed in past CLI upgrades before strict validation.

        Pydantic-native migration shim: known dead fields (``_REMOVED_ENVCONFIG_FIELDS``)
        are silently dropped here so loading a config saved by an older CLI
        keeps working. Fields not in that allowlist still trigger
        ``extra='forbid'`` and surface as ``ValidationError`` — protects
        against typos.

        Logs an info-level message naming each dropped field so the user
        sees the migration happen. The load site re-serializes the model
        and writes it back when the on-disk content differs.
        """
        if not isinstance(data, dict):
            return data
        dropped = sorted(k for k in data if k in _REMOVED_ENVCONFIG_FIELDS)
        if not dropped:
            return data
        info(
            f"Dropping {len(dropped)} field(s) removed by past CLI upgrades: "
            f"{', '.join(dropped)}"
        )
        return {k: v for k, v in data.items() if k not in _REMOVED_ENVCONFIG_FIELDS}

    # ---------------- derived properties -----------------
    @property
    def project_name(self) -> str:
        return self.project_id.split("/")[-1] if self.project_id else ""

    @property
    def subscription(self) -> str:
        return self.workspace_resource_id.split("/")[2] if self.workspace_resource_id else ""

    @property
    def resource_group(self) -> str:
        return self.workspace_resource_id.split("/")[4] if self.workspace_resource_id else ""

    # -------------- completeness checks --------------
    @property
    def project_ready(self) -> bool:
        return all(
            bool(b)
            for b in [
                self.project_id,
                self.workspace_resource_id,
                self.nodepool_id,
            ]
        )

    def acr_ready(self) -> bool:
        return bool(self.acr_name)

    @property
    def acr_url(self) -> str:
        """Return the ACR login server, falling back to ``{acr_name}.azurecr.io``."""
        if self.acr_login_server:
            return self.acr_login_server
        if self.acr_name:
            return f"{self.acr_name}.azurecr.io"
        return ""

    def get_nodepool(self, name_or_id: str) -> NodepoolInfo | None:
        """Get a nodepool by name, qualified name (supercomputer/name), or full ID.

        Args:
            name_or_id: The nodepool identifier - can be:
                - Short name (matches first if unique, errors if ambiguous)
                - Qualified name: "supercomputer/name"
                - Full Azure resource ID

        Returns:
            NodepoolInfo if found, None otherwise

        Raises:
            ValueError: If name matches multiple nodepools (ambiguous)
        """
        # Try exact ID match first
        for np in self.nodepools:
            if np.id == name_or_id:
                return np

        # Try qualified name match (supercomputer/name)
        if "/" in name_or_id and not name_or_id.startswith("/"):
            for np in self.nodepools:
                if np.qualified_name == name_or_id:
                    return np

        # Try short name match
        matches = [np for np in self.nodepools if np.name == name_or_id]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            qualified_names = [np.qualified_name for np in matches]
            msg = f"Ambiguous nodepool name '{name_or_id}'. Use qualified name (supercomputer/pool): {qualified_names}"
            raise ValueError(msg)

        return None

    def get_default_nodepool(self) -> NodepoolInfo | None:
        """Get the default nodepool (matching nodepool_id).

        Returns:
            NodepoolInfo for the default nodepool, or None if not found
        """
        return self.get_nodepool(self.nodepool_id)

    # -------------- public operations --------------
    def save(self) -> None:
        """Persist all current values to the .env file."""
        info(f"Writing all config values to {self.path}")
        self.path.write_text(self.model_dump_json(indent=4))


__all__ = ["EnvConfig"]
