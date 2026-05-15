"""Tests for deploy_datacontainer module."""

from __future__ import annotations

import json

import pytest

from discovery.poll import deploy_datacontainer
from discovery.poll.models.dataasset import DataContainerInputs


def _make_proc(returncode: int = 0, stdout: str = "", stderr: str = ""):
    class Proc:
        def __init__(self) -> None:
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    return Proc()


def _default_inputs() -> DataContainerInputs:
    return DataContainerInputs(
        name="scratch-dc-test",
        location="uksouth",
        discovery_storage_id=(
            "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Discovery/storages/anf1"
        ),
        credential_identity_id=(
            "/subscriptions/sub/resourceGroups/rg/providers/"
            "Microsoft.ManagedIdentity/userAssignedIdentities/uami"
        ),
    )


class TestRenderParameters:
    def test_render_basic(self) -> None:
        params = deploy_datacontainer.render_datacontainer_parameters(_default_inputs())
        assert params["parameters"]["outLocation"]["value"] == "uksouth"
        assert params["parameters"]["outDataContainerName"]["value"] == "scratch-dc-test"
        assert params["parameters"]["outApiVersion"]["value"] == "2025-07-01-preview"
        assert params["parameters"]["outDiscoveryStorageId"]["value"].endswith("/storages/anf1")


class TestCheckDatacontainerExists:
    def test_returns_true_on_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "subprocess.run", lambda *a, **k: _make_proc(returncode=0, stdout="{}"),
        )
        assert deploy_datacontainer.check_datacontainer_exists("sub", "rg", "name")

    def test_returns_false_on_notfound(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "subprocess.run",
            lambda *a, **k: _make_proc(returncode=3, stderr="ResourceNotFound: not found"),
        )
        assert not deploy_datacontainer.check_datacontainer_exists("sub", "rg", "name")

    def test_raises_on_unexpected_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "subprocess.run",
            lambda *a, **k: _make_proc(returncode=1, stderr="weird auth failure"),
        )
        with pytest.raises(RuntimeError, match="Failed to check"):
            deploy_datacontainer.check_datacontainer_exists("sub", "rg", "name")


class TestDeploy:
    def test_dry_run_returns_template_and_parameters(self) -> None:
        result = deploy_datacontainer.deploy_datacontainer(
            subscription_id="sub", resource_group="rg",
            inputs=_default_inputs(), execute=False,
        )
        assert "template" in result and "parameters" in result
        # Verify the template has the right resource type
        assert any(
            r["type"] == "Microsoft.Discovery/dataContainers"
            for r in result["template"]["resources"]
        )
        # Verify the params carry our values
        assert (
            result["parameters"]["parameters"]["outDataContainerName"]["value"] == "scratch-dc-test"
        )
        assert (
            result["parameters"]["parameters"]["outDiscoveryStorageId"]["value"].endswith("anf1")
        )

    def test_skips_when_exists(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            deploy_datacontainer, "check_datacontainer_exists", lambda *a, **k: True,
        )
        result = deploy_datacontainer.deploy_datacontainer(
            subscription_id="sub", resource_group="rg",
            inputs=_default_inputs(), execute=True, skip_if_exists=True,
        )
        assert result == {"success": True, "skipped": True, "reason": "exists"}


# --- Blob (AzureStorageBlob-kind) variant -----------------------------------

from discovery.poll.models.dataasset import BlobDataContainerInputs


def _default_blob_inputs() -> BlobDataContainerInputs:
    return BlobDataContainerInputs(
        name="archive-dc-test",
        location="uksouth",
        storage_account_id="/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Storage/storageAccounts/sa1",
        credential_identity_id="/subscriptions/sub/resourceGroups/rg/providers/Microsoft.ManagedIdentity/userAssignedIdentities/uami1",
    )


class TestRenderBlobParameters:
    def test_render_basic(self) -> None:
        params = deploy_datacontainer.render_blob_datacontainer_parameters(_default_blob_inputs())
        assert params["parameters"]["outDataContainerName"]["value"] == "archive-dc-test"
        assert params["parameters"]["outStorageAccountId"]["value"].endswith("/sa1")
        assert params["parameters"]["outCredentialIdentityId"]["value"].endswith("/uami1")


class TestDeployBlob:
    def test_dry_run_returns_template(self) -> None:
        result = deploy_datacontainer.deploy_blob_datacontainer(
            "sub", "rg", _default_blob_inputs(), execute=False,
        )
        assert any(
            r["type"] == "Microsoft.Discovery/dataContainers"
            for r in result["template"]["resources"]
        )
        # Template uses the blob-kind dataStore
        assert (
            result["template"]["resources"][0]["properties"]["dataStore"]["kind"]
            == "AzureStorageBlob"
        )
