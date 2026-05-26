"""Tests for deploy_storagecontainer module (V2 ANF storageContainer creation)."""

from __future__ import annotations

import pytest

from discovery.poll import deploy_storagecontainer
from discovery.poll.models.dataasset import StorageContainerInputs


def _make_proc(returncode: int = 0, stdout: str = "", stderr: str = ""):
    class Proc:
        def __init__(self) -> None:
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    return Proc()


def _default_inputs() -> StorageContainerInputs:
    return StorageContainerInputs(
        name="scratch-sc-test",
        location="uksouth",
        netapp_volume_id=(
            "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.NetApp/"
            "netAppAccounts/anf1/capacityPools/pool1/volumes/vol1"
        ),
    )


class TestRender:
    def test_render_basic(self) -> None:
        params = deploy_storagecontainer.render_storagecontainer_parameters(_default_inputs())
        assert params["parameters"]["outLocation"]["value"] == "uksouth"
        assert params["parameters"]["outStorageContainerName"]["value"] == "scratch-sc-test"
        assert params["parameters"]["outApiVersion"]["value"] == "2026-02-01-preview"
        assert params["parameters"]["outNetAppVolumeId"]["value"].endswith("/volumes/vol1")


class TestCheckExists:
    def test_returns_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("subprocess.run", lambda *a, **k: _make_proc(0, "{}"))
        assert deploy_storagecontainer.check_storagecontainer_exists("sub", "rg", "name")

    def test_returns_false_on_404(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "subprocess.run",
            lambda *a, **k: _make_proc(3, stderr="ResourceNotFound: nope"),
        )
        assert not deploy_storagecontainer.check_storagecontainer_exists("sub", "rg", "name")


class TestDeploy:
    def test_dry_run_returns_template(self) -> None:
        result = deploy_storagecontainer.deploy_storagecontainer(
            "sub", "rg", _default_inputs(), execute=False,
        )
        assert any(
            r["type"] == "Microsoft.Discovery/storageContainers"
            for r in result["template"]["resources"]
        )
        assert (
            result["parameters"]["parameters"]["outNetAppVolumeId"]["value"].endswith("vol1")
        )

    def test_skips_when_exists(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            deploy_storagecontainer, "check_storagecontainer_exists", lambda *a, **k: True,
        )
        result = deploy_storagecontainer.deploy_storagecontainer(
            "sub", "rg", _default_inputs(), execute=True, skip_if_exists=True,
        )
        assert result == {"success": True, "skipped": True, "reason": "exists"}


# --- Blob (AzureStorageBlob-kind) variant -----------------------------------

from discovery.poll.models.dataasset import BlobStorageContainerInputs


def _default_blob_inputs() -> BlobStorageContainerInputs:
    return BlobStorageContainerInputs(
        name="archive-sc-test",
        location="uksouth",
        storage_account_id="/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Storage/storageAccounts/sa1",
    )


class TestRenderBlobParameters:
    def test_render_basic(self) -> None:
        params = deploy_storagecontainer.render_blob_storagecontainer_parameters(_default_blob_inputs())
        assert params["parameters"]["outStorageContainerName"]["value"] == "archive-sc-test"
        assert params["parameters"]["outStorageAccountId"]["value"].endswith("/sa1")


class TestDeployBlob:
    def test_dry_run_returns_template(self) -> None:
        result = deploy_storagecontainer.deploy_blob_storagecontainer(
            "sub", "rg", _default_blob_inputs(), execute=False,
        )
        assert (
            result["template"]["resources"][0]["properties"]["storageStore"]["kind"]
            == "AzureStorageBlob"
        )
