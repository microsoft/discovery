"""Tests for the ARM api-version constants module.

These constants are the single source of truth for every ``az resource …``
call the CLI makes against the Discovery RP, plus the ``outApiVersion``
defaults baked into the ARM templates. The tests below pin the expected
values (cross-reference the docstrings in ``models/arm_versions.py``) and
assert that the templates + Pydantic ``*Inputs`` models actually consume
the constants.
"""

from __future__ import annotations

import json
from importlib.resources import files

from discovery.poll.models import arm_versions
from discovery.poll.models.dataasset import (
    BlobDataContainerInputs,
    BlobStorageContainerInputs,
    DataAssetInputs,
    DataContainerInputs,
    StorageAssetInputs,
    StorageContainerInputs,
)


# ---------------------------------------------------------------------------
# Pinned values — bump these tests in lockstep with arm_versions.py.
# ---------------------------------------------------------------------------

# V2 storage: GA. Bumped from 2026-02-01-preview after the controlplane RP
# exposed 2026-06-01 with the same resource graph (verified against
# science-controlplane swagger + integration test pipeline).
def test_storagecontainer_arm_api_version_is_ga():
    assert arm_versions.STORAGECONTAINER_ARM_API_VERSION == "2026-06-01"


def test_storageasset_arm_api_version_is_ga():
    assert arm_versions.STORAGEASSET_ARM_API_VERSION == "2026-06-01"


# Nodepool ARM reads — supercomputer + nodepool resources are in the GA graph.
def test_nodepool_arm_api_version_is_ga():
    assert arm_versions.NODEPOOL_ARM_API_VERSION == "2026-06-01"


# V1 datacontainer/dataasset are NOT exposed at 2026-06-01 (dropped from the
# RP schema starting at 2026-02-01-preview). Pinning here documents the
# constraint and guards against accidental future bumps that would break the
# legacy-cleanup path.
def test_datacontainer_arm_api_version_pinned_to_v1():
    assert arm_versions.DATACONTAINER_ARM_API_VERSION == "2025-07-01-preview"


def test_dataasset_arm_api_version_pinned_to_v1():
    assert arm_versions.DATAASSET_ARM_API_VERSION == "2025-07-01-preview"


# ---------------------------------------------------------------------------
# Inputs models default to the right constant per resource family.
# ---------------------------------------------------------------------------


def test_storagecontainer_inputs_defaults_to_ga():
    inp = StorageContainerInputs(
        name="sc", location="eastus", netapp_volume_id="/x/y/anf/vol",
    )
    assert inp.api_version == arm_versions.STORAGECONTAINER_ARM_API_VERSION


def test_blob_storagecontainer_inputs_defaults_to_ga():
    inp = BlobStorageContainerInputs(
        name="sc", location="eastus", storage_account_id="/x/y/storage",
    )
    assert inp.api_version == arm_versions.STORAGECONTAINER_ARM_API_VERSION


def test_storageasset_inputs_defaults_to_ga():
    inp = StorageAssetInputs(
        name="asset", storage_container_name="sc", location="eastus", path="p/",
    )
    assert inp.api_version == arm_versions.STORAGEASSET_ARM_API_VERSION


def test_datacontainer_inputs_defaults_to_v1():
    inp = DataContainerInputs(
        name="dc",
        location="eastus",
        discovery_storage_id="/x/y/storages/anf",
        credential_identity_id="/x/y/uami",
    )
    assert inp.api_version == arm_versions.DATACONTAINER_ARM_API_VERSION


def test_blob_datacontainer_inputs_defaults_to_v1():
    inp = BlobDataContainerInputs(
        name="dc",
        location="eastus",
        storage_account_id="/x/y/storage",
        credential_identity_id="/x/y/uami",
    )
    assert inp.api_version == arm_versions.DATACONTAINER_ARM_API_VERSION


def test_dataasset_inputs_defaults_to_v1():
    inp = DataAssetInputs(
        name="da", data_container_name="dc", location="eastus", path="p/",
    )
    assert inp.api_version == arm_versions.DATAASSET_ARM_API_VERSION


# ---------------------------------------------------------------------------
# ARM template JSON files — outApiVersion defaultValue must match the constant.
# These guard against drift between Python and template payloads.
# ---------------------------------------------------------------------------


def _read_template(rel: str) -> dict:
    return json.loads(files("discovery.poll").joinpath(f"templates/{rel}").read_text())


def _read_parameters(rel: str) -> dict:
    return json.loads(files("discovery.poll").joinpath(f"templates/{rel}").read_text())


def test_storagecontainer_template_pinned_to_ga():
    tmpl = _read_template("storagecontainer/template.json")
    assert tmpl["parameters"]["outApiVersion"]["defaultValue"] == (
        arm_versions.STORAGECONTAINER_ARM_API_VERSION
    )


def test_storagecontainer_blob_template_pinned_to_ga():
    tmpl = _read_template("storagecontainer/template_blob.json")
    assert tmpl["parameters"]["outApiVersion"]["defaultValue"] == (
        arm_versions.STORAGECONTAINER_ARM_API_VERSION
    )


def test_storagecontainer_parameters_pinned_to_ga():
    params = _read_parameters("storagecontainer/parameters.json")
    assert params["parameters"]["outApiVersion"]["value"] == (
        arm_versions.STORAGECONTAINER_ARM_API_VERSION
    )


def test_storagecontainer_parameters_blob_pinned_to_ga():
    params = _read_parameters("storagecontainer/parameters_blob.json")
    assert params["parameters"]["outApiVersion"]["value"] == (
        arm_versions.STORAGECONTAINER_ARM_API_VERSION
    )


def test_storageasset_template_pinned_to_ga():
    tmpl = _read_template("storageasset/template.json")
    assert tmpl["parameters"]["outApiVersion"]["defaultValue"] == (
        arm_versions.STORAGEASSET_ARM_API_VERSION
    )


def test_storageasset_parameters_pinned_to_ga():
    params = _read_parameters("storageasset/parameters.json")
    assert params["parameters"]["outApiVersion"]["value"] == (
        arm_versions.STORAGEASSET_ARM_API_VERSION
    )


# ---------------------------------------------------------------------------
# V1 templates: keep pinned to V1 — bumping to GA would break (resource type
# not in the GA RP schema). These tests guard against accidental bumps.
# ---------------------------------------------------------------------------


def test_datacontainer_template_pinned_to_v1():
    tmpl = _read_template("datacontainer/template.json")
    assert tmpl["parameters"]["outApiVersion"]["defaultValue"] == (
        arm_versions.DATACONTAINER_ARM_API_VERSION
    )


def test_dataasset_template_pinned_to_v1():
    tmpl = _read_template("dataasset/template.json")
    assert tmpl["parameters"]["outApiVersion"]["defaultValue"] == (
        arm_versions.DATAASSET_ARM_API_VERSION
    )
