"""Tests for deploy_dataasset module."""

from __future__ import annotations

import json

import pytest

from discovery.poll import deploy_dataasset
from discovery.poll.models.dataasset import BlobContainerInputs, DataAssetInputs


def _make_proc(returncode: int = 0, stdout: str = "", stderr: str = ""):
    """Create a mock subprocess result."""

    class Proc:
        def __init__(self) -> None:
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    return Proc()


def _default_dataasset_inputs() -> DataAssetInputs:
    return DataAssetInputs(
        name="test-asset",
        data_container_name="test-container",
        location="eastus",
        description="Test data asset",
        path="testuser/",
    )


def _default_blob_container_inputs() -> BlobContainerInputs:
    return BlobContainerInputs(
        storage_account_name="teststorageacct",
        container_name="testcontainer",
        subscription_id="sub-123",
        resource_group="test-rg",
        public_access="off",
    )


class TestRenderDataassetParameters:
    """Tests for render_dataasset_parameters function."""

    def test_render_dataasset_parameters_basic(self) -> None:
        """Test basic parameter rendering."""
        inputs = _default_dataasset_inputs()
        params = deploy_dataasset.render_dataasset_parameters(inputs)

        assert params["parameters"]["outLocation"]["value"] == "eastus"
        assert params["parameters"]["outDataContainerName"]["value"] == "test-container"
        assert params["parameters"]["outDataAssetName"]["value"] == "test-asset"
        assert params["parameters"]["outDataAssetDescription"]["value"] == "Test data asset"
        assert params["parameters"]["outDataAssetPath"]["value"] == "testuser/"

    def test_render_dataasset_parameters_custom_api_version(self) -> None:
        """Test parameter rendering with custom API version."""
        inputs = DataAssetInputs(
            name="custom-asset",
            data_container_name="dc",
            location="westus",
            path="custom/",
            api_version="2024-01-01",
        )
        params = deploy_dataasset.render_dataasset_parameters(inputs)

        assert params["parameters"]["outApiVersion"]["value"] == "2024-01-01"


class TestCheckDataassetExists:
    """Tests for check_dataasset_exists function."""

    def test_check_dataasset_exists_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test when data asset exists."""
        monkeypatch.setattr(
            "subprocess.run",
            lambda *args, **kwargs: _make_proc(returncode=0, stdout="{}"),
        )

        result = deploy_dataasset.check_dataasset_exists(
            subscription_id="sub-123",
            data_container_resource_id="/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Discovery/dataContainers/dc",
            asset_name="test-asset",
        )

        assert result is True

    def test_check_dataasset_exists_false_not_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test when data asset does not exist (not found error)."""
        monkeypatch.setattr(
            "subprocess.run",
            lambda *args, **kwargs: _make_proc(returncode=1, stderr="Resource not found (404)"),
        )

        result = deploy_dataasset.check_dataasset_exists(
            subscription_id="sub-123",
            data_container_resource_id="/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Discovery/dataContainers/dc",
            asset_name="missing-asset",
        )

        assert result is False

    def test_check_dataasset_exists_false_notfound_lowercase(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test when data asset does not exist (notfound lowercase)."""
        monkeypatch.setattr(
            "subprocess.run",
            lambda *args, **kwargs: _make_proc(returncode=1, stderr="ResourceNotFound"),
        )

        result = deploy_dataasset.check_dataasset_exists(
            subscription_id="sub-123",
            data_container_resource_id="/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Discovery/dataContainers/dc",
            asset_name="missing-asset",
        )

        assert result is False

    def test_check_dataasset_exists_unexpected_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test when az CLI fails with unexpected error."""
        monkeypatch.setattr(
            "subprocess.run",
            lambda *args, **kwargs: _make_proc(returncode=1, stderr="Authentication failed"),
        )

        with pytest.raises(RuntimeError, match="Failed to check data asset existence"):
            deploy_dataasset.check_dataasset_exists(
                subscription_id="sub-123",
                data_container_resource_id="/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Discovery/dataContainers/dc",
                asset_name="test-asset",
            )

    def test_check_dataasset_exists_az_not_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test when az CLI is not installed."""

        def raise_oserror(*args, **kwargs):
            raise OSError("az not found")

        monkeypatch.setattr("subprocess.run", raise_oserror)

        with pytest.raises(RuntimeError, match="Azure CLI 'az' not found"):
            deploy_dataasset.check_dataasset_exists(
                subscription_id="sub-123",
                data_container_resource_id="/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Discovery/dataContainers/dc",
                asset_name="test-asset",
            )


class TestDeployDataasset:
    """Tests for deploy_dataasset function."""

    def test_deploy_dataasset_execute_false(self) -> None:
        """Test deploy_dataasset with execute=False returns template and params."""
        inputs = _default_dataasset_inputs()

        result = deploy_dataasset.deploy_dataasset(
            subscription_id="sub-123",
            resource_group="test-rg",
            inputs=inputs,
            execute=False,
        )

        assert "template" in result
        assert "parameters" in result
        assert isinstance(result["template"], dict)
        assert isinstance(result["parameters"], dict)

    def test_deploy_dataasset_skip_if_exists(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test deploy_dataasset skips when asset already exists."""
        inputs = _default_dataasset_inputs()

        # Mock check_dataasset_exists to return True
        monkeypatch.setattr(
            deploy_dataasset,
            "check_dataasset_exists",
            lambda *args, **kwargs: True,
        )

        result = deploy_dataasset.deploy_dataasset(
            subscription_id="sub-123",
            resource_group="test-rg",
            inputs=inputs,
            execute=True,
            skip_if_exists=True,
        )

        assert result["success"] is True
        assert result["skipped"] is True
        assert "already exists" in result["reason"]


class TestCheckBlobContainerExists:
    """Tests for check_blob_container_exists function."""

    def test_check_blob_container_exists_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test when blob container exists."""
        monkeypatch.setattr(
            "subprocess.run",
            lambda *args, **kwargs: _make_proc(returncode=0, stdout=json.dumps({"exists": True})),
        )

        result = deploy_dataasset.check_blob_container_exists(
            storage_account_name="teststorage",
            container_name="testcontainer",
            subscription_id="sub-123",
        )

        assert result is True

    def test_check_blob_container_exists_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test when blob container does not exist."""
        monkeypatch.setattr(
            "subprocess.run",
            lambda *args, **kwargs: _make_proc(returncode=0, stdout=json.dumps({"exists": False})),
        )

        result = deploy_dataasset.check_blob_container_exists(
            storage_account_name="teststorage",
            container_name="testcontainer",
            subscription_id="sub-123",
        )

        assert result is False

    def test_check_blob_container_exists_cli_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test when az CLI fails."""
        monkeypatch.setattr(
            "subprocess.run",
            lambda *args, **kwargs: _make_proc(returncode=1, stderr="CLI error"),
        )

        with pytest.raises(RuntimeError, match="az CLI failed"):
            deploy_dataasset.check_blob_container_exists(
                storage_account_name="teststorage",
                container_name="testcontainer",
                subscription_id="sub-123",
            )

    def test_check_blob_container_exists_az_not_found(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test when az CLI is not installed."""

        def raise_oserror(*args, **kwargs):
            raise OSError("az not found")

        monkeypatch.setattr("subprocess.run", raise_oserror)

        with pytest.raises(RuntimeError, match="Azure CLI 'az' not found"):
            deploy_dataasset.check_blob_container_exists(
                storage_account_name="teststorage",
                container_name="testcontainer",
                subscription_id="sub-123",
            )

    def test_check_blob_container_exists_invalid_json(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test when az CLI returns invalid JSON."""
        monkeypatch.setattr(
            "subprocess.run",
            lambda *args, **kwargs: _make_proc(returncode=0, stdout="not json"),
        )

        with pytest.raises(RuntimeError, match="Failed to parse JSON"):
            deploy_dataasset.check_blob_container_exists(
                storage_account_name="teststorage",
                container_name="testcontainer",
                subscription_id="sub-123",
            )


class TestDeployBlobContainer:
    """Tests for deploy_blob_container function."""

    def test_deploy_blob_container_execute_false(self) -> None:
        """Test deploy_blob_container with execute=False returns command."""
        inputs = _default_blob_container_inputs()

        result = deploy_dataasset.deploy_blob_container(
            inputs=inputs,
            execute=False,
        )

        assert "command" in result
        assert isinstance(result["command"], list)
        assert "az" in result["command"]
        assert "storage" in result["command"]
        assert "container" in result["command"]
        assert "create" in result["command"]

    def test_deploy_blob_container_skip_if_exists(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test deploy_blob_container skips when container already exists."""
        inputs = _default_blob_container_inputs()

        # Mock check_blob_container_exists to return True
        monkeypatch.setattr(
            deploy_dataasset,
            "check_blob_container_exists",
            lambda *args, **kwargs: True,
        )

        result = deploy_dataasset.deploy_blob_container(
            inputs=inputs,
            execute=True,
            skip_if_exists=True,
        )

        assert result["success"] is True
        assert result["skipped"] is True
        assert "already exists" in result["reason"]

    def test_deploy_blob_container_az_not_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test deploy_blob_container when az CLI is not installed."""
        inputs = _default_blob_container_inputs()

        # Mock check_blob_container_exists to return False
        monkeypatch.setattr(
            deploy_dataasset,
            "check_blob_container_exists",
            lambda *args, **kwargs: False,
        )

        # Mock typer.confirm to return True
        monkeypatch.setattr(deploy_dataasset.typer, "confirm", lambda *args, **kwargs: True)
        monkeypatch.setattr(deploy_dataasset.typer, "echo", lambda *args, **kwargs: None)
        monkeypatch.setattr(deploy_dataasset.typer, "secho", lambda *args, **kwargs: None)

        def raise_oserror(*args, **kwargs):
            raise OSError("az not found")

        monkeypatch.setattr("subprocess.run", raise_oserror)

        with pytest.raises(RuntimeError, match="Azure CLI 'az' not found"):
            deploy_dataasset.deploy_blob_container(
                inputs=inputs,
                execute=True,
                skip_if_exists=False,
            )

    def test_deploy_blob_container_cli_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test deploy_blob_container when az CLI fails."""
        inputs = _default_blob_container_inputs()

        # Mock check_blob_container_exists to return False
        monkeypatch.setattr(
            deploy_dataasset,
            "check_blob_container_exists",
            lambda *args, **kwargs: False,
        )

        # Mock typer interactions
        monkeypatch.setattr(deploy_dataasset.typer, "confirm", lambda *args, **kwargs: True)
        monkeypatch.setattr(deploy_dataasset.typer, "echo", lambda *args, **kwargs: None)
        monkeypatch.setattr(deploy_dataasset.typer, "secho", lambda *args, **kwargs: None)

        monkeypatch.setattr(
            "subprocess.run",
            lambda *args, **kwargs: _make_proc(returncode=1, stderr="Permission denied"),
        )

        with pytest.raises(RuntimeError, match="az CLI failed"):
            deploy_dataasset.deploy_blob_container(
                inputs=inputs,
                execute=True,
                skip_if_exists=False,
            )

    def test_deploy_blob_container_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test successful blob container creation."""
        inputs = _default_blob_container_inputs()

        # Mock check_blob_container_exists to return False
        monkeypatch.setattr(
            deploy_dataasset,
            "check_blob_container_exists",
            lambda *args, **kwargs: False,
        )

        # Mock typer interactions
        monkeypatch.setattr(deploy_dataasset.typer, "confirm", lambda *args, **kwargs: True)
        monkeypatch.setattr(deploy_dataasset.typer, "echo", lambda *args, **kwargs: None)
        monkeypatch.setattr(deploy_dataasset.typer, "secho", lambda *args, **kwargs: None)

        monkeypatch.setattr(
            "subprocess.run",
            lambda *args, **kwargs: _make_proc(returncode=0, stdout=json.dumps({"created": True})),
        )

        result = deploy_dataasset.deploy_blob_container(
            inputs=inputs,
            execute=True,
            skip_if_exists=False,
        )

        assert result["success"] is True
        assert result["created"] is True

    def test_deploy_blob_container_cancelled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test blob container creation when user cancels."""
        inputs = _default_blob_container_inputs()

        # Mock check_blob_container_exists to return False
        monkeypatch.setattr(
            deploy_dataasset,
            "check_blob_container_exists",
            lambda *args, **kwargs: False,
        )

        # Mock typer.confirm to return False (user cancels)
        monkeypatch.setattr(deploy_dataasset.typer, "confirm", lambda *args, **kwargs: False)
        monkeypatch.setattr(deploy_dataasset.typer, "echo", lambda *args, **kwargs: None)
        monkeypatch.setattr(deploy_dataasset.typer, "secho", lambda *args, **kwargs: None)

        result = deploy_dataasset.deploy_blob_container(
            inputs=inputs,
            execute=True,
            skip_if_exists=False,
        )

        assert result["cancelled"] is True

    def test_deploy_blob_container_invalid_json_response(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test blob container creation when az CLI returns invalid JSON."""
        inputs = _default_blob_container_inputs()

        # Mock check_blob_container_exists to return False
        monkeypatch.setattr(
            deploy_dataasset,
            "check_blob_container_exists",
            lambda *args, **kwargs: False,
        )

        # Mock typer interactions
        monkeypatch.setattr(deploy_dataasset.typer, "confirm", lambda *args, **kwargs: True)
        monkeypatch.setattr(deploy_dataasset.typer, "echo", lambda *args, **kwargs: None)
        monkeypatch.setattr(deploy_dataasset.typer, "secho", lambda *args, **kwargs: None)

        monkeypatch.setattr(
            "subprocess.run",
            lambda *args, **kwargs: _make_proc(returncode=0, stdout="not json"),
        )

        with pytest.raises(RuntimeError, match="Failed to parse JSON"):
            deploy_dataasset.deploy_blob_container(
                inputs=inputs,
                execute=True,
                skip_if_exists=False,
            )
