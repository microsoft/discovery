"""Tests for deploy_storageasset module."""

from __future__ import annotations

import pytest

from discovery.poll import deploy_storageasset
from discovery.poll.models.dataasset import StorageAssetInputs


def _make_proc(returncode: int = 0, stdout: str = "", stderr: str = ""):
    class Proc:
        def __init__(self) -> None:
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    return Proc()


def _default_storageasset_inputs() -> StorageAssetInputs:
    return StorageAssetInputs(
        name="test-asset",
        storage_container_name="test-sc",
        location="eastus2",
        description="Test storage asset",
        path="test-asset/",
    )


class TestRenderStorageassetParameters:
    def test_render_basic(self) -> None:
        inputs = _default_storageasset_inputs()
        params = deploy_storageasset.render_storageasset_parameters(inputs)

        assert params["parameters"]["outLocation"]["value"] == "eastus2"
        assert params["parameters"]["outStorageContainerName"]["value"] == "test-sc"
        assert params["parameters"]["outStorageAssetName"]["value"] == "test-asset"
        assert params["parameters"]["outStorageAssetDescription"]["value"] == "Test storage asset"
        assert params["parameters"]["outStorageAssetPath"]["value"] == "test-asset/"
        assert params["parameters"]["outApiVersion"]["value"] == "2026-02-01-preview"

    def test_render_custom_api_version(self) -> None:
        inputs = StorageAssetInputs(
            name="custom",
            storage_container_name="sc",
            location="westus",
            path="custom/",
            api_version="2027-01-01-preview",
        )
        params = deploy_storageasset.render_storageasset_parameters(inputs)
        assert params["parameters"]["outApiVersion"]["value"] == "2027-01-01-preview"


class TestCheckStorageassetExists:
    def test_exists_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "subprocess.run",
            lambda *a, **k: _make_proc(returncode=0, stdout="{}"),
        )
        assert deploy_storageasset.check_storageasset_exists(
            subscription_id="sub",
            storage_container_resource_id=(
                "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Discovery"
                "/storagecontainers/sc"
            ),
            asset_name="asset",
        ) is True

    def test_exists_false_not_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "subprocess.run",
            lambda *a, **k: _make_proc(returncode=1, stderr="Resource not found (404)"),
        )
        assert deploy_storageasset.check_storageasset_exists(
            subscription_id="sub",
            storage_container_resource_id=(
                "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Discovery"
                "/storagecontainers/sc"
            ),
            asset_name="missing",
        ) is False

    def test_exists_false_notfound_lowercase(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "subprocess.run",
            lambda *a, **k: _make_proc(returncode=1, stderr="ResourceNotFound"),
        )
        assert deploy_storageasset.check_storageasset_exists(
            subscription_id="sub",
            storage_container_resource_id=(
                "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Discovery"
                "/storagecontainers/sc"
            ),
            asset_name="missing",
        ) is False

    def test_exists_unexpected_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "subprocess.run",
            lambda *a, **k: _make_proc(returncode=1, stderr="Authentication failed"),
        )
        with pytest.raises(RuntimeError, match="Failed to check storage asset existence"):
            deploy_storageasset.check_storageasset_exists(
                subscription_id="sub",
                storage_container_resource_id=(
                    "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Discovery"
                    "/storagecontainers/sc"
                ),
                asset_name="asset",
            )

    def test_az_not_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def raise_oserror(*a, **k):
            msg = "az not found"
            raise OSError(msg)

        monkeypatch.setattr("subprocess.run", raise_oserror)
        with pytest.raises(RuntimeError, match="Azure CLI 'az' not found"):
            deploy_storageasset.check_storageasset_exists(
                subscription_id="sub",
                storage_container_resource_id=(
                    "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Discovery"
                    "/storagecontainers/sc"
                ),
                asset_name="asset",
            )


class TestDeployStorageasset:
    def test_execute_false_returns_payload(self) -> None:
        inputs = _default_storageasset_inputs()
        result = deploy_storageasset.deploy_storageasset(
            subscription_id="sub",
            resource_group="rg",
            inputs=inputs,
            execute=False,
        )
        assert "template" in result
        assert "parameters" in result
        # Template targets the correct resource type
        assert (
            result["template"]["resources"][0]["type"]
            == "Microsoft.Discovery/storagecontainers/storageassets"
        )
