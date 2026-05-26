"""Tests for Azure resource helper utilities."""

from __future__ import annotations

import json

import pytest

from discovery.poll import resources
from discovery.poll.models.config import EnvConfig


def _make_proc(returncode: int = 0, stdout: str = "[]", stderr: str = ""):
    class Proc:
        def __init__(self) -> None:
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    return Proc()


def test_list_resources_success(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = json.dumps(
        [
            {"id": "/a", "name": "alpha"},
            {"id": "/b", "name": "beta"},
        ]
    )
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: _make_proc(stdout=payload))
    rows = resources.list_resources("Microsoft.Discovery/tools", properties=("name", "id"))
    assert rows == ["alpha\t/a", "beta\t/b"]


def test_list_resources_allow_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: _make_proc(stdout="[]"))
    rows = resources.list_resources("Microsoft.Discovery/tools", assert_present=False)
    assert rows == []


def test_list_resources_raises_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "subprocess.run", lambda *args, **kwargs: _make_proc(returncode=1, stderr="boom")
    )
    with pytest.raises(RuntimeError):
        resources.list_resources("Microsoft.Discovery/tools")


def test_get_workspace_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = json.dumps({"properties": {"supercomputerIds": ["/supers/1"]}})
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: _make_proc(stdout=payload))
    ids = resources.get_workspace_ids("/workspaces/ws", "supercomputerIds")
    assert ids == ["/supers/1"]


def test_derive_workspace_id_and_mutates_env(tmp_path) -> None:
    env = EnvConfig(path=tmp_path / ".env")
    project_id = "/subscriptions/1/resourceGroups/rg/providers/Microsoft.Discovery/workspaces/ws/projects/proj"
    derived = resources.derive_workspace_id_from_project_id(project_id, env)
    assert derived is not None
    assert derived.endswith("/workspaces/ws")
    assert env.workspace_resource_id == derived


def test_fetch_workspace_url_success(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    payload = json.dumps({"properties": {"workspaceApiUri": "https://example/"}})
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: _make_proc(stdout=payload))
    env = EnvConfig(path=tmp_path / ".env")
    url = resources.fetch_workspace_url_from_resource_id("/workspaces/ws", env)
    assert url == "https://example"
    assert env.workspace_url == "https://example"


def test_fetch_workspace_url_missing(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    payload = json.dumps({"properties": {}})
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: _make_proc(stdout=payload))
    env = EnvConfig(path=tmp_path / ".env")
    with pytest.raises(RuntimeError):
        resources.fetch_workspace_url_from_resource_id("/workspaces/ws", env)


def test_check_blob_container_permissions_with_required_role(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Mock two calls: first for user ID, second for role assignments
    call_count = [0]

    def mock_run(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            # First call: get user ID
            return _make_proc(stdout="user-object-id-123\n")
        # Second call: get role assignments
        payload = json.dumps(["Storage Blob Data Contributor", "Reader"])
        return _make_proc(stdout=payload)

    monkeypatch.setattr("subprocess.run", mock_run)
    result = resources.check_blob_container_permissions("/containers/test")
    assert result["has_required_permission"] is True
    assert "Storage Blob Data Contributor" in result["role_assignments"]


def test_check_blob_container_permissions_without_required_role(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call_count = [0]

    def mock_run(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            return _make_proc(stdout="user-object-id-123\n")
        payload = json.dumps(["Reader", "Contributor"])
        return _make_proc(stdout=payload)

    monkeypatch.setattr("subprocess.run", mock_run)
    result = resources.check_blob_container_permissions("/containers/test")
    assert result["has_required_permission"] is False
    assert len(result["role_assignments"]) == 2


def test_check_blob_container_permissions_owner_role(monkeypatch: pytest.MonkeyPatch) -> None:
    call_count = [0]

    def mock_run(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            return _make_proc(stdout="user-object-id-123\n")
        payload = json.dumps(["Storage Blob Data Owner"])
        return _make_proc(stdout=payload)

    monkeypatch.setattr("subprocess.run", mock_run)
    result = resources.check_blob_container_permissions("/containers/test")
    assert result["has_required_permission"] is True
    assert "Storage Blob Data Owner" in result["role_assignments"]


def test_get_resource_group_and_location_success(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = json.dumps(
        {
            "resourceGroup": "my-resource-group",
            "location": "eastus",
            "id": "/subscriptions/1/resourceGroups/my-resource-group/providers/Microsoft.Discovery/datacontainers/dc1",
        }
    )
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: _make_proc(stdout=payload))
    rg, location = resources.get_resource_group_and_location("/datacontainers/dc1")
    assert rg == "my-resource-group"
    assert location == "eastus"


def test_get_resource_group_and_location_missing_rg(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = json.dumps({"location": "eastus", "id": "/some/resource"})
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: _make_proc(stdout=payload))
    with pytest.raises(RuntimeError, match="resourceGroup field missing"):
        resources.get_resource_group_and_location("/some/resource")


def test_get_resource_group_and_location_missing_location(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = json.dumps({"resourceGroup": "my-rg", "id": "/some/resource"})
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: _make_proc(stdout=payload))
    with pytest.raises(RuntimeError, match="location field missing"):
        resources.get_resource_group_and_location("/some/resource")


def test_get_resource_group_and_location_cli_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "subprocess.run", lambda *args, **kwargs: _make_proc(returncode=1, stderr="not found")
    )
    with pytest.raises(RuntimeError, match="az CLI failed"):
        resources.get_resource_group_and_location("/some/resource")


def test_get_datacontainer_storage_details_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test successful retrieval of storage account ID from data container."""
    payload = json.dumps(
        {
            "properties": {
                "dataStore": {
                    "storageAccountId": "/subscriptions/1/resourceGroups/rg/providers/Microsoft.Storage/storageAccounts/myacct"
                }
            }
        }
    )
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: _make_proc(stdout=payload))
    storage_id = resources.get_datacontainer_storage_details("/datacontainers/dc1")
    assert (
        storage_id
        == "/subscriptions/1/resourceGroups/rg/providers/Microsoft.Storage/storageAccounts/myacct"
    )


def test_get_datacontainer_storage_details_missing_storage_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test when storageAccountId is missing in data container properties."""
    payload = json.dumps({"properties": {"dataStore": {}}})
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: _make_proc(stdout=payload))
    with pytest.raises(RuntimeError, match="storageAccountId missing"):
        resources.get_datacontainer_storage_details("/datacontainers/dc1")


def test_get_datacontainer_storage_details_discovery_storage_kind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DiscoveryStorage-kind data containers don't have storageAccountId."""
    payload = json.dumps(
        {
            "properties": {
                "dataStore": {
                    "kind": "DiscoveryStorage",
                    "discoveryStorageId": "/subscriptions/1/.../discoveryStorage/x",
                }
            }
        }
    )
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: _make_proc(stdout=payload))
    with pytest.raises(RuntimeError, match="DiscoveryStorage"):
        resources.get_datacontainer_storage_details("/datacontainers/dc1")


def test_get_datacontainer_datastore_returns_full_dict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """get_datacontainer_datastore returns the full dataStore dict."""
    payload = json.dumps(
        {
            "properties": {
                "dataStore": {
                    "kind": "DiscoveryStorage",
                    "discoveryStorageId": "/subscriptions/1/.../discoveryStorage/x",
                }
            }
        }
    )
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: _make_proc(stdout=payload))
    ds = resources.get_datacontainer_datastore("/datacontainers/dc1")
    assert ds["kind"] == "DiscoveryStorage"
    assert ds["discoveryStorageId"] == "/subscriptions/1/.../discoveryStorage/x"


def test_get_datacontainer_storage_details_cli_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test when az CLI fails."""
    monkeypatch.setattr(
        "subprocess.run",
        lambda *args, **kwargs: _make_proc(returncode=1, stderr="Resource not found"),
    )
    with pytest.raises(RuntimeError, match="az CLI failed"):
        resources.get_datacontainer_storage_details("/datacontainers/dc1")


def test_get_datacontainer_storage_details_az_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test when az CLI is not installed."""

    def raise_oserror(*args, **kwargs):
        raise OSError("az not found")

    monkeypatch.setattr("subprocess.run", raise_oserror)
    with pytest.raises(RuntimeError, match="Azure CLI 'az' not found"):
        resources.get_datacontainer_storage_details("/datacontainers/dc1")


def test_get_datacontainer_storage_details_invalid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test when az CLI returns invalid JSON."""
    monkeypatch.setattr(
        "subprocess.run", lambda *args, **kwargs: _make_proc(stdout="not valid json")
    )
    with pytest.raises(RuntimeError, match="Failed to parse JSON"):
        resources.get_datacontainer_storage_details("/datacontainers/dc1")


def test_get_blob_uri_from_datacontainer(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test constructing blob URI from data container."""
    payload = json.dumps(
        {
            "properties": {
                "dataStore": {
                    "storageAccountId": "/subscriptions/1/resourceGroups/rg/providers/Microsoft.Storage/storageAccounts/teststorage"
                }
            }
        }
    )
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: _make_proc(stdout=payload))
    uri = resources.get_blob_uri_from_datacontainer("/datacontainers/dc1", "testcontainer")
    assert uri == "https://teststorage.blob.core.windows.net/testcontainer/"


def test_get_acr_location_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test successful ACR location retrieval."""
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: _make_proc(stdout="eastus\n"))
    location = resources.get_acr_location("myacr")
    assert location == "eastus"


def test_get_acr_location_cli_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test when az CLI fails to get ACR location."""
    monkeypatch.setattr(
        "subprocess.run",
        lambda *args, **kwargs: _make_proc(returncode=1, stderr="ACR not found"),
    )
    with pytest.raises(RuntimeError, match="az CLI failed"):
        resources.get_acr_location("nonexistent-acr")


def test_get_acr_location_empty_result(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test when ACR location query returns empty result."""
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: _make_proc(stdout=""))
    with pytest.raises(RuntimeError, match="No location found"):
        resources.get_acr_location("myacr")


def test_list_datacontainers(monkeypatch: pytest.MonkeyPatch) -> None:
    """list_datacontainers returns enriched dicts via az graph query."""
    graph_payload = json.dumps({
        "data": [
            {
                "name": "dc1",
                "id": "/subscriptions/1/resourceGroups/rg/providers/Microsoft.Discovery/datacontainers/dc1",
                "location": "eastus",
                "resourceGroup": "rg",
                "kind_": "AzureStorageBlob",
            },
            {
                "name": "dc2",
                "id": "/subscriptions/1/resourceGroups/rg/providers/Microsoft.Discovery/datacontainers/dc2",
                "location": "eastus",
                "resourceGroup": "rg",
                "kind_": "DiscoveryStorage",
            },
        ],
    })
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: _make_proc(stdout=graph_payload))
    containers = resources.list_datacontainers()
    assert len(containers) == 2
    assert containers[0]["name"] == "dc1"
    assert containers[0]["kind"] == "AzureStorageBlob"
    assert containers[1]["kind"] == "DiscoveryStorage"


def test_list_containers_with_kind_falls_back_to_per_resource(monkeypatch: pytest.MonkeyPatch) -> None:
    """When `az graph query` fails, fall back to per-resource enrichment."""
    base_listing = json.dumps([
        {
            "name": "dc1",
            "id": "/subscriptions/1/resourceGroups/rg/providers/Microsoft.Discovery/datacontainers/dc1",
            "location": "eastus",
            "resourceGroup": "rg",
        },
    ])
    show_payload = json.dumps({
        "properties": {"dataStore": {"kind": "AzureStorageBlob", "storageAccountId": "/sa/x"}},
    })
    calls = {"i": 0}

    def fake_run(cmd, *args, **kwargs):
        calls["i"] += 1
        # 1st call: az graph query → fail
        if calls["i"] == 1:
            assert cmd[1] == "graph"
            return _make_proc(returncode=1, stderr="ARG unavailable")
        # 2nd call: az resource list → succeed
        if calls["i"] == 2:
            assert cmd[1] == "resource" and cmd[2] == "list"
            return _make_proc(stdout=base_listing)
        # 3rd call: az resource show (per-resource enrichment) → succeed
        assert cmd[1] == "resource" and cmd[2] == "show"
        return _make_proc(stdout=show_payload)

    monkeypatch.setattr("subprocess.run", fake_run)
    containers = resources.list_containers_with_kind(
        "Microsoft.Discovery/datacontainers", "properties.dataStore.kind",
    )
    assert containers == [
        {
            "name": "dc1",
            "id": "/subscriptions/1/resourceGroups/rg/providers/Microsoft.Discovery/datacontainers/dc1",
            "location": "eastus",
            "resourceGroup": "rg",
            "kind": "AzureStorageBlob",
        },
    ]


def test_derive_workspace_id_no_workspace_marker(tmp_path) -> None:
    """Test derive_workspace_id when project ID doesn't contain workspace marker."""
    env = EnvConfig(path=tmp_path / ".env")
    project_id = "/subscriptions/1/resourceGroups/rg/providers/OtherProvider/projects/proj"
    result = resources.derive_workspace_id_from_project_id(project_id, env)
    assert result is None


def test_derive_workspace_id_no_project_marker(tmp_path) -> None:
    """Test derive_workspace_id when project ID doesn't contain /projects/ marker."""
    env = EnvConfig(path=tmp_path / ".env")
    project_id = "/subscriptions/1/resourceGroups/rg/providers/Microsoft.Discovery/workspaces/ws"
    result = resources.derive_workspace_id_from_project_id(project_id, env)
    assert result is None


def test_check_blob_container_permissions_user_id_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test when getting user ID fails."""
    monkeypatch.setattr(
        "subprocess.run",
        lambda *args, **kwargs: _make_proc(returncode=1, stderr="Not logged in"),
    )
    with pytest.raises(RuntimeError, match="az CLI failed"):
        resources.check_blob_container_permissions("/containers/test")


def test_check_blob_container_permissions_empty_user_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test when user ID is empty."""
    monkeypatch.setattr(
        "subprocess.run",
        lambda *args, **kwargs: _make_proc(stdout=""),
    )
    with pytest.raises(RuntimeError, match="Could not determine current user"):
        resources.check_blob_container_permissions("/containers/test")


def test_check_blob_container_permissions_az_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test when az CLI is not installed."""

    def raise_oserror(*args, **kwargs):
        raise OSError("az not found")

    monkeypatch.setattr("subprocess.run", raise_oserror)
    with pytest.raises(RuntimeError, match="Azure CLI 'az' not found"):
        resources.check_blob_container_permissions("/containers/test")


def test_check_blob_container_permissions_role_check_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test when role assignment check fails."""
    call_count = [0]

    def mock_run(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            return _make_proc(stdout="user-object-id-123\n")
        return _make_proc(returncode=1, stderr="Permission denied")

    monkeypatch.setattr("subprocess.run", mock_run)
    with pytest.raises(RuntimeError, match="az CLI failed"):
        resources.check_blob_container_permissions("/containers/test")


def test_check_blob_container_permissions_invalid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test when role assignment returns invalid JSON."""
    call_count = [0]

    def mock_run(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            return _make_proc(stdout="user-object-id-123\n")
        return _make_proc(stdout="not json")

    monkeypatch.setattr("subprocess.run", mock_run)
    with pytest.raises(RuntimeError, match="Failed to parse JSON"):
        resources.check_blob_container_permissions("/containers/test")


def test_get_resource_group_and_location_az_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test when az CLI is not installed."""

    def raise_oserror(*args, **kwargs):
        raise OSError("az not found")

    monkeypatch.setattr("subprocess.run", raise_oserror)
    with pytest.raises(RuntimeError, match="Azure CLI 'az' not found"):
        resources.get_resource_group_and_location("/some/resource")


def test_get_resource_group_and_location_invalid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test when az CLI returns invalid JSON."""
    monkeypatch.setattr(
        "subprocess.run", lambda *args, **kwargs: _make_proc(stdout="not valid json")
    )
    with pytest.raises(RuntimeError, match="Failed to parse JSON"):
        resources.get_resource_group_and_location("/some/resource")


def test_get_workspace_ids_cli_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test when az CLI fails to get workspace IDs."""
    monkeypatch.setattr(
        "subprocess.run",
        lambda *args, **kwargs: _make_proc(returncode=1, stderr="Resource not found"),
    )
    with pytest.raises(RuntimeError, match="az CLI failed"):
        resources.get_workspace_ids("/workspaces/ws", "supercomputerIds")


def test_fetch_workspace_url_cli_failure(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Test when az CLI fails to fetch workspace URL."""
    monkeypatch.setattr(
        "subprocess.run",
        lambda *args, **kwargs: _make_proc(returncode=1, stderr="Workspace not found"),
    )
    env = EnvConfig(path=tmp_path / ".env")
    with pytest.raises(RuntimeError, match="az CLI failed"):
        resources.fetch_workspace_url_from_resource_id("/workspaces/ws", env)


def test_list_resources_no_resources_found(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test when no resources are found and assert_present=True."""
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: _make_proc(stdout="[]"))
    with pytest.raises(RuntimeError, match="No resources found"):
        resources.list_resources("Microsoft.Discovery/tools", assert_present=True)
