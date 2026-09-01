"""Pinned ARM (control-plane) api-versions for ``Microsoft.Discovery`` resources.

The control-plane (ARM RP) api-version is **independent** of the data-plane
api-version selected via ``discovery configure --api-version`` (see
:mod:`models.api_version`). Both can be bumped on their own cadences — for
example, the data plane reached GA at ``2026-06-01`` while V1 ARM resources
were dropped from the RP schema starting at ``2026-02-01-preview``.

These constants are the single source of truth for every ``az resource …``
call the CLI makes against the Discovery RP, plus the ``outApiVersion``
defaults baked into the ARM templates under ``poll/templates/``. Pinning
explicitly (rather than letting the Azure CLI auto-resolve) avoids:

* an extra ARM round-trip per command (``GET /providers/Microsoft.Discovery``
  to discover supported versions),
* silent drift when the RP registers a new api-version that subtly changes
  response shape or accepted-properties enforcement, and
* spurious 404s on child resource types whose auto-resolution sometimes
  picks the parent's latest, not the child's.

When the RP exposes a newer api-version, bump the relevant constant *and*
the matching ``outApiVersion`` ``defaultValue`` in the ARM template JSON,
then update the corresponding unit tests.
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# V2 storage family — Microsoft.Discovery/storageContainers (+ /storageAssets)
# ---------------------------------------------------------------------------
# Introduced at 2026-02-01-preview, GA at 2026-06-01. The GA api-version
# adds the optional ``properties.storageStore.mountProtocol`` field but is
# otherwise a strict superset of the preview shape, so existing templates
# stay valid against GA without changes.

STORAGECONTAINER_ARM_API_VERSION = "2026-06-01"
STORAGEASSET_ARM_API_VERSION = "2026-06-01"


# ---------------------------------------------------------------------------
# Nodepool reads — Microsoft.Discovery/supercomputers/{name}/nodePools/{name}
# ---------------------------------------------------------------------------
# In the GA resource graph per the controlplane fan-out pipeline.

NODEPOOL_ARM_API_VERSION = "2026-06-01"


# ---------------------------------------------------------------------------
# V1 datacontainer family — Microsoft.Discovery/dataContainers (+ /dataAssets)
# ---------------------------------------------------------------------------
# NOT exposed at 2026-06-01: the V1 resources were dropped from the RP
# schema starting with 2026-02-01-preview, superseded by the V2 storage*
# family. The CLI still supports a V1 cleanup path for users with legacy
# resources; that path pins to the last api-version that exposes V1 types.
#
# DO NOT bump these without first verifying the resource type is registered
# in the newer api-version (``az provider show -n Microsoft.Discovery``).

DATACONTAINER_ARM_API_VERSION = "2025-07-01-preview"
DATAASSET_ARM_API_VERSION = "2025-07-01-preview"


__all__ = [
    "DATAASSET_ARM_API_VERSION",
    "DATACONTAINER_ARM_API_VERSION",
    "NODEPOOL_ARM_API_VERSION",
    "STORAGEASSET_ARM_API_VERSION",
    "STORAGECONTAINER_ARM_API_VERSION",
]
