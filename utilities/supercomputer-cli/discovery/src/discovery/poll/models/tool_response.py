"""Models for standardized tool execution response.

These mirror the JSON schema located at tests/artifacts/tool_response.schema.json.
"""

from __future__ import annotations

import re
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

from discovery.poll.models.auth import AuthHeaders


# -------------------- Sub-models --------------------


class AzureCoreOperationState(str, Enum):
    """
    State as per defined in Azure for all long running operations.
    """

    NOT_STARTED = "NotStarted"
    PENDING = "Pending"
    ACCEPTED = "TaskAccepted"
    ACTIVE = "Active"
    RUNNING = "Running"
    SUCCEEDED = "Succeeded"
    FAILED = "Failed"
    CANCELED = "Canceled"


class ToolReport(BaseModel):
    """Progress and logging information from a tool execution."""

    logs: str = Field(..., description="Raw log output or concatenated log text.")
    percentage_complete: float = Field(
        ..., ge=0, le=100, alias="percentageComplete", description="Progress indicator (0-100)."
    )
    status_information: str | dict[str, Any] | None = Field(
        None, alias="statusInformation", description="Optional additional status detail."
    )

    model_config = ConfigDict(
        populate_by_name=True,
        str_strip_whitespace=True,
        serialize_by_alias=True,
    )


class ToolResult(BaseModel):
    """Encapsulates the result details of a tool execution."""

    completed_at: datetime | None = Field(..., alias="completedAt")
    created_at: datetime = Field(..., alias="createdAt")
    debug_info: str = Field("", alias="debugInfo")
    output_data: list[Any] = Field(default_factory=list, alias="outputData")
    runtime_details: str = Field(..., alias="runtimeDetails")
    status: AzureCoreOperationState = Field(
        ..., description="Status of the tool execution at completion."
    )  # noqa: E501
    tool_report: ToolReport = Field(..., alias="toolReport")

    model_config = ConfigDict(
        populate_by_name=True,
        str_strip_whitespace=True,
        serialize_by_alias=True,
    )


class ToolExecutionResponse(BaseModel):
    """Body object for a tool execution response (no transport headers)."""

    error: str | dict | None = Field(
        None, description="Null if no error, otherwise an error object or message."
    )
    id: str = Field(..., description="Correlation or operation identifier (UUID).")
    result: ToolResult | None = Field(..., description="Detailed result information.")
    status: str = Field(..., description="Top-level request lifecycle status.")

    model_config = ConfigDict(
        populate_by_name=True,
        str_strip_whitespace=True,
        serialize_by_alias=True,
    )

    @field_validator("id")
    @classmethod
    def _validate_id(cls, v: str) -> str:
        """Validate ID is plausibly a UUID (accepts hyphenated or 32 hex)."""
        pattern = re.compile(r"^(?:[0-9a-fA-F]{32}|[0-9a-fA-F-]{36})$")
        if not pattern.match(v):
            msg = "id is not a valid UUID-like value"
            raise ValueError(msg)
        return v


class ToolExecutionEnvelope(BaseModel):
    """Envelope containing HTTP headers plus the parsed body.

    headers: Raw HTTP response headers (case-insensitive; normalized to lowercase keys)
    body: Parsed JSON body as ToolExecutionResponse
    """

    headers: AuthHeaders
    body: ToolExecutionResponse

    model_config = ConfigDict(str_strip_whitespace=True, serialize_by_alias=True)


class OperationsResultModel(BaseModel):
    """Model representing a single operation in the operations list."""

    nodepool_id: str = Field(alias="nodepoolId")
    id: str = Field(..., description="Operation identifier (UUID).")
    status: AzureCoreOperationState = Field(..., description="Operation status.")
    runtime_details: str | None = Field(None, alias="runtimeDetails")
    created_at: datetime = Field(..., alias="createdAt")
    completed_at: datetime | None = Field(None, alias="completedAt")
    created_by: str | None = Field(None, alias="createdBy")

    model_config = ConfigDict(
        populate_by_name=True,
        str_strip_whitespace=True,
        serialize_by_alias=True,
    )


class OperationsListResponse(BaseModel):
    """Response model for listing operations."""

    values: list[OperationsResultModel] = Field(
        ...,
        validation_alias=AliasChoices("values", "value"),
        description="List of operations.",
    )
    next_link: str | None = Field(
        None, alias="nextLink", description="Link to next page of results."
    )

    model_config = ConfigDict(
        populate_by_name=True,
        str_strip_whitespace=True,
        serialize_by_alias=True,
    )


__all__ = [
    "OperationsListResponse",
    "OperationsResultModel",
    "ToolExecutionEnvelope",
    "ToolExecutionResponse",
    "ToolReport",
    "ToolResult",
]
