"""Typed Discovery data-plane API versions and schema-capability metadata.

Replaces free-form string matching (e.g. ``api_version in {"2025-07-01-preview", ...}``)
with a single enum whose members expose the capability flags the CLI needs to dispatch
against (URI scheme, presence of ``storageId``, nested vs. flat ``infraOverrides``).

The boundaries encoded here mirror the server contracts in the upstream service
(``Microsoft.AiForScience.Supercomputer.Common.Models.Version*``):

    =====================  =========================  ===========  =====================
    API version            Data mount URI field       storageId    infraOverrides shape
    =====================  =========================  ===========  =====================
    2025-07-01-preview     ``uri`` → dataassets       required     nested (resources/poolSize/imageUri)
    2025-12-01-preview     ``uri`` → dataassets       required     flat (cpu/ram/gpu/replicaCount/imageUri)
    2026-02-01-preview     ``storageUri`` → storageassets  omitted      flat (+ maxCpu/maxRam/maxGpu)
    2026-06-01 (GA)        ``storageUri`` → storageassets  omitted      flat (same as 2026-02-01-preview)
    =====================  =========================  ===========  =====================

The 2026-06-01 GA contract is a strict superset of 2026-02-01-preview: the only wire
delta is an optional ``mountProtocol`` enum field on ``InputDataMount`` / ``OutputDataMount``
(values: ``NFS`` | ``BlobfuseCaching``). The CLI does not surface ``mountProtocol``
as a user-facing argument today; both versions therefore share the same capability flags.

Unknown / future versions fall through to the latest known member so that new
api versions do not immediately break the CLI between releases.
"""

from __future__ import annotations

from enum import Enum
from typing import Iterator


class ApiVersion(str, Enum):
    """Known Discovery data-plane API versions (previews and GA)."""

    V2025_07_01_PREVIEW = "2025-07-01-preview"
    V2025_12_01_PREVIEW = "2025-12-01-preview"
    V2026_02_01_PREVIEW = "2026-02-01-preview"
    V2026_06_01 = "2026-06-01"

    # ---- parsing / defaults -------------------------------------------------

    @classmethod
    def latest(cls) -> "ApiVersion":
        """Return the newest known API version (forward-compat fallback).

        Returning the GA version (rather than a later preview) is safe as a
        fallback target because GA accepts every payload the prior preview
        (2026-02-01-preview) accepted — the only wire delta is an optional
        ``mountProtocol`` field on data mounts, which the CLI does not send.
        """
        return cls.V2026_06_01

    @classmethod
    def parse(cls, value: str | "ApiVersion" | None) -> "ApiVersion":
        """Coerce a string (or None) to an :class:`ApiVersion`.

        Unknown values fall back to :meth:`latest` so the CLI keeps working against
        newer preview versions between releases. Callers that need strict validation
        should use the plain constructor ``ApiVersion(value)`` which raises ``ValueError``.
        """
        if isinstance(value, cls):
            return value
        if value is None or value == "":
            return cls.latest()
        for member in cls:
            if member.value == value:
                return member
        return cls.latest()

    @classmethod
    def known_values(cls) -> Iterator[str]:
        """Yield the wire string of each known member."""
        for member in cls:
            yield member.value

    # ---- schema-capability flags --------------------------------------------

    @property
    def wire_value(self) -> str:
        """The string sent as the ``api-version`` query parameter."""
        return self.value

    @property
    def uses_storage_id(self) -> bool:
        """True when the tool-run payload includes the top-level ``storageId`` field.

        Omitted from 2026-02-01-preview onward in favour of ``storageUri`` on the
        data mounts themselves.
        """
        return self in (ApiVersion.V2025_07_01_PREVIEW, ApiVersion.V2025_12_01_PREVIEW)

    @property
    def uses_dataassets_uri(self) -> bool:
        """True when data mounts use ``uri`` + ``discovery://dataassets/…``.

        Newer versions use ``storageUri`` + ``discovery://storageassets/…`` and also
        consume storage-containers instead of data-containers.
        """
        return self in (ApiVersion.V2025_07_01_PREVIEW, ApiVersion.V2025_12_01_PREVIEW)

    @property
    def uses_nested_infra_overrides(self) -> bool:
        """True when ``infraOverrides`` nests resources: ``{"resources": {...}, "poolSize", "imageUri"}``.

        Only the first preview (2025-07-01) uses the nested shape; every later version
        uses the flat shape (``{"cpu", "ram", "gpu", "replicaCount", "imageUri", …}``).
        Because the server uses ``[JsonUnmappedMemberHandling(Disallow)]``, sending the
        wrong shape causes the request to be rejected (surfaced as HTTP 401 by the
        Discovery data-plane front door).
        """
        return self is ApiVersion.V2025_07_01_PREVIEW


__all__ = ["ApiVersion"]
