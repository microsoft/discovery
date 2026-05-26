"""Authentication / HTTP header models.

Provides a structured model for common headers used in tool requests / responses.
Case-insensitive input with normalized lowercase attribute access.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AuthHeaders(BaseModel):
    """Represents a minimal set of HTTP headers relevant to tool operations.

    Fields use lowercase python identifiers. The wire representation may include
    canonical header casing; use model_dump(by_alias=True) to serialize.
    """

    authorization: str | None = Field(
        None, alias="Authorization", description="Bearer or other authorization header value"
    )
    accept: str | None = Field(
        "application/json", alias="Accept", description="Accept header (expected media types)"
    )
    content_type: str | None = Field(
        "application/json", alias="Content-Type", description="Content-Type header value"
    )
    user_agent: str | None = Field(
        "Microsoft-Discovery-CLI/1.0",
        alias="User-Agent",
        description="User-Agent header for WAF compatibility (rule 920320)",
    )

    model_config = ConfigDict(
        populate_by_name=True,
        str_strip_whitespace=True,
        serialize_by_alias=True,
    )

    @field_validator("authorization", "accept", "content_type", "user_agent")
    def _empty_to_none(cls, v: str | None):  # noqa: N805
        """Normalize blank strings to None for cleaner downstream logic."""
        if v is not None and not v.strip():
            return None
        return v


__all__ = ["AuthHeaders"]
