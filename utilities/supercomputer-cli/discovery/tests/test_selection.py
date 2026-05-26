"""Tests for interactive selection helpers (mocked prompts)."""

from __future__ import annotations

import pytest

from discovery.poll import selection
from discovery.poll.models.config import EnvConfig


def test_interactive_choice_single_option() -> None:
    result = selection._interactive_choice("Title", ["only"])
    assert result == "only"


def test_interactive_choice_no_options(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(selection.typer, "echo", lambda *args, **kwargs: None)
    with pytest.raises(selection.typer.Exit):
        selection._interactive_choice("Title", [])


def test_interactive_choice_prompts(monkeypatch) -> None:
    monkeypatch.setattr(selection.typer, "prompt", lambda *args, **kwargs: 2)
    monkeypatch.setattr(selection.typer, "echo", lambda *args, **kwargs: None)
    result = selection._interactive_choice("Pick", ["a", "b", "c"])
    assert result == "b"


def test_parse_name_id_variants() -> None:
    assert selection._parse_name_id("name\tid") == ("name", "id")
    assert selection._parse_name_id("alpha beta") == ("alpha", "beta")
    with pytest.raises(ValueError):
        selection._parse_name_id("invalid")


def test_select_tool_sets_env(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    env = EnvConfig(path=tmp_path / ".env")
    monkeypatch.setattr(selection, "list_resources", lambda *args, **kwargs: ["tool\ttool-id"])
    selection.select_tool(env)
    assert env.tool_id == "tool-id"


def test_select_related_resources(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    env = EnvConfig(path=tmp_path / ".env")
    env.workspace_resource_id = "/workspace"

    # Import NodepoolInfo for creating mock data
    from discovery.poll.models.compute import NodepoolInfo

    def fake_list_all_nodepools_with_details(workspace_id: str) -> list[NodepoolInfo]:
        return [
            NodepoolInfo(
                id="/supercomputers/super-1/nodepools/nodepool-1",
                name="nodepool-1",
                supercomputer_name="super-1",
                scratch_dc_id="/dc/dc1",
                cpus="4",
                memory="16",
                gpus="0",
            )
        ]

    monkeypatch.setattr(selection, "list_all_nodepools_with_details", fake_list_all_nodepools_with_details)
    monkeypatch.setattr(selection, "info", lambda *args, **kwargs: None)
    monkeypatch.setattr(selection.typer, "prompt", lambda *args, **kwargs: 1)
    monkeypatch.setattr(selection.typer, "echo", lambda *args, **kwargs: None)
    selection.select_related_resources(env)
    assert env.nodepool_id == "/supercomputers/super-1/nodepools/nodepool-1"


def test_resolve_project_strips_workspace(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(selection.typer, "prompt", lambda *args, **kwargs: 1)
    monkeypatch.setattr(selection.typer, "echo", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        selection, "list_resources", lambda *args, **kwargs: ["ws/project\t/project-id"]
    )
    pid = selection.resolve_project()
    assert pid == "/project-id"


def test_select_project_and_related(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    env = EnvConfig(path=tmp_path / ".env")

    # Import NodepoolInfo for creating mock data
    from discovery.poll.models.compute import NodepoolInfo

    monkeypatch.setattr(
        selection, "resolve_project", lambda: "/subscriptions/x/workspaces/ws/projects/proj"
    )
    monkeypatch.setattr(
        selection,
        "derive_workspace_id_from_project_id",
        lambda pid, env_cfg: "/subscriptions/x/workspaces/ws",
    )

    def fake_fetch_workspace_url(rid: str, env_cfg: EnvConfig) -> str:
        env_cfg.workspace_url = "https://ws"
        return env_cfg.workspace_url

    def fake_list_all_nodepools_with_details(workspace_id: str) -> list[NodepoolInfo]:
        return [
            NodepoolInfo(
                id="/supercomputers/super-1/nodepools/nodepool-1",
                name="nodepool-1",
                supercomputer_name="super-1",
                scratch_dc_id="/dc/dc1",
                cpus="4",
                memory="16",
                gpus="0",
            )
        ]

    monkeypatch.setattr(selection, "get_workspace_ids", lambda *args, **kwargs: [])
    monkeypatch.setattr(selection, "fetch_workspace_url_from_resource_id", fake_fetch_workspace_url)
    monkeypatch.setattr(selection, "list_all_nodepools_with_details", fake_list_all_nodepools_with_details)
    monkeypatch.setattr(selection, "info", lambda *args, **kwargs: None)
    monkeypatch.setattr(selection.typer, "prompt", lambda *args, **kwargs: 1)
    monkeypatch.setattr(selection.typer, "echo", lambda *args, **kwargs: None)

    selection.select_project_and_related(env)
    assert env.project_id.endswith("proj")
    assert env.workspace_url == "https://ws"
    assert env.nodepool_id == "/supercomputers/super-1/nodepools/nodepool-1"


def test_select_acr_registry(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Test ACR registry selection resolves login server."""
    env = EnvConfig(path=tmp_path / ".env")

    # Mock list_acr_names to return options
    monkeypatch.setattr(selection, "list_acr_names", lambda: ["acr1", "acr2"])
    # Mock _interactive_choice to return first option
    monkeypatch.setattr(selection, "_interactive_choice", lambda title, opts: opts[0])
    # Mock get_acr_login_server
    monkeypatch.setattr(selection, "get_acr_login_server", lambda name: f"{name}.azurecr.cn")

    selection.select_acr_registry(env)
    assert env.acr_name == "acr1"
    assert env.acr_login_server == "acr1.azurecr.cn"


def test_select_datacontainer_filters_to_blob(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """V1 Archive picker should hide non-blob datacontainers; create option always offered."""
    env = EnvConfig(path=tmp_path / ".env")

    monkeypatch.setattr(selection, "info", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        selection,
        "list_datacontainers",
        lambda **kw: [
            {"name": "dc1", "id": "/datacontainers/dc1", "kind": "AzureStorageBlob"},
            {"name": "dc2-anf", "id": "/datacontainers/dc2", "kind": "DiscoveryStorage"},
        ],
    )
    captured: dict = {}

    def _capture(title: str, opts: list[str]) -> str:
        captured["opts"] = opts
        # Pick the existing blob container (option 1 — option 0 is create-new).
        return opts[1]

    monkeypatch.setattr(selection, "_interactive_choice", _capture)

    selection.select_datacontainer(env)
    assert env.datacontainer_id == "/datacontainers/dc1"
    # 1 create option + 1 blob entry; ANF dc filtered out.
    assert len(captured["opts"]) == 2
    assert "__CREATE_NEW__" in captured["opts"][0]
    assert "dc1" in captured["opts"][1]
    assert all("dc2-anf" not in opt for opt in captured["opts"])


def test_select_datacontainer_no_blob_offers_create(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """When no blob dcs exist, the picker still offers the create option."""
    env = EnvConfig(path=tmp_path / ".env")

    monkeypatch.setattr(selection, "info", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        selection,
        "list_datacontainers",
        lambda **kw: [{"name": "dc-anf", "id": "/dc/dc-anf", "kind": "DiscoveryStorage"}],
    )
    captured: dict = {}

    def _capture(title: str, opts: list[str]) -> str:
        captured["opts"] = opts
        # Simulate the user cancelling out of the create flow by returning the
        # create marker; we'll mock _create_archive_dc_interactive to return "".
        return opts[0]

    monkeypatch.setattr(selection, "_interactive_choice", _capture)
    monkeypatch.setattr(selection, "_create_archive_dc_interactive", lambda env_cfg: "")

    with pytest.raises(RuntimeError, match="creation was cancelled"):
        selection.select_datacontainer(env)
    # The picker should have shown only the create option (no existing blob entries).
    assert captured["opts"] == ["+ Create new blob data container...\t__CREATE_NEW__"]


def test_select_datacontainer_create_new_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Picking + Create new... routes to the create helper and persists the new ID."""
    env = EnvConfig(path=tmp_path / ".env")

    monkeypatch.setattr(selection, "info", lambda *args, **kwargs: None)
    monkeypatch.setattr(selection, "list_datacontainers", lambda **kw: [])
    monkeypatch.setattr(
        selection, "_interactive_choice",
        lambda title, opts: opts[0],  # always the create option
    )
    new_id = "/subscriptions/x/resourceGroups/rg/providers/Microsoft.Discovery/dataContainers/freshly-made"
    monkeypatch.setattr(selection, "_create_archive_dc_interactive", lambda env_cfg: new_id)

    selection.select_datacontainer(env)
    assert env.datacontainer_id == new_id


def test_select_storagecontainer_filters_to_blob(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """V2 Archive picker should hide ANF storagecontainers; create option offered."""
    env = EnvConfig(path=tmp_path / ".env")

    monkeypatch.setattr(selection, "info", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        selection,
        "list_storagecontainers",
        lambda **kw: [
            {"name": "anfsc", "id": "/storagecontainers/anfsc", "kind": "AzureNetAppFiles"},
            {"name": "blobsc", "id": "/storagecontainers/blobsc", "kind": "AzureStorageBlob"},
        ],
    )
    captured: dict = {}

    def _capture(title: str, opts: list[str]) -> str:
        captured["opts"] = opts
        return opts[1]  # the existing blob entry

    monkeypatch.setattr(selection, "_interactive_choice", _capture)

    selection.select_storagecontainer(env)
    assert env.storagecontainer_id == "/storagecontainers/blobsc"
    assert len(captured["opts"]) == 2
    assert "__CREATE_NEW__" in captured["opts"][0]
    assert all("anfsc" not in opt for opt in captured["opts"])


def test_select_storagecontainer_create_new_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """V2 + Create new... routes to the create helper."""
    env = EnvConfig(path=tmp_path / ".env")
    monkeypatch.setattr(selection, "info", lambda *args, **kwargs: None)
    monkeypatch.setattr(selection, "list_storagecontainers", lambda **kw: [])
    monkeypatch.setattr(
        selection, "_interactive_choice",
        lambda title, opts: opts[0],
    )
    new_id = "/subscriptions/x/resourceGroups/rg/providers/Microsoft.Discovery/storageContainers/freshly-made"
    monkeypatch.setattr(selection, "_create_archive_sc_interactive", lambda env_cfg: new_id)

    selection.select_storagecontainer(env)
    assert env.storagecontainer_id == new_id


def test_select_nodepool(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Test nodepool selection."""
    env = EnvConfig(path=tmp_path / ".env")
    env.workspace_resource_id = "/workspace"

    # Import NodepoolInfo for creating mock data
    from discovery.poll.models.compute import NodepoolInfo

    def fake_list_all_nodepools_with_details(workspace_id: str) -> list[NodepoolInfo]:
        return [
            NodepoolInfo(
                id="/supercomputers/sc1/nodepools/np1",
                name="np1",
                supercomputer_name="sc1",
                scratch_dc_id="/dc/dc1",
                cpus="4",
                memory="16",
                gpus="0",
            ),
            NodepoolInfo(
                id="/supercomputers/sc1/nodepools/np2",
                name="np2",
                supercomputer_name="sc1",
                scratch_dc_id="/dc/dc2",
                cpus="8",
                memory="32",
                gpus="1",
            ),
        ]

    # Mock info function
    monkeypatch.setattr(selection, "info", lambda *args, **kwargs: None)
    # Mock list_all_nodepools_with_details
    monkeypatch.setattr(
        selection,
        "list_all_nodepools_with_details",
        fake_list_all_nodepools_with_details,
    )
    # Mock _interactive_choice to select first option
    monkeypatch.setattr(
        selection,
        "_interactive_choice",
        lambda title, opts: opts[0],
    )

    selection.select_nodepool(env)
    assert env.nodepool_id == "/supercomputers/sc1/nodepools/np1"


def test_select_nodepool_no_supercomputer(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Test nodepool selection when workspace not configured."""
    env = EnvConfig(path=tmp_path / ".env")
    env.workspace_resource_id = ""

    # Mock typer.echo
    output = []
    monkeypatch.setattr(selection.typer, "echo", lambda msg, **kwargs: output.append(msg))

    selection.select_nodepool(env)
    assert any("not configured" in str(msg) for msg in output)


def test_select_nodepool_no_pools_found(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Test nodepool selection when no pools found."""
    env = EnvConfig(path=tmp_path / ".env")
    env.workspace_resource_id = "/workspace"

    # Mock info function
    monkeypatch.setattr(selection, "info", lambda *args, **kwargs: None)
    # Mock list_all_nodepools_with_details to return empty list
    monkeypatch.setattr(
        selection,
        "list_all_nodepools_with_details",
        lambda *args, **kwargs: [],
    )

    # Mock typer.echo
    output = []
    monkeypatch.setattr(selection.typer, "echo", lambda msg, **kwargs: output.append(msg))

    selection.select_nodepool(env)
    assert any("No nodepools found" in str(msg) for msg in output)


def test_select_nodepool_error_handling(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Test nodepool selection error handling."""
    env = EnvConfig(path=tmp_path / ".env")
    env.workspace_resource_id = "/workspace"

    # Mock info function
    monkeypatch.setattr(selection, "info", lambda *args, **kwargs: None)

    # Mock list_all_nodepools_with_details to raise error
    def raise_error(*args, **kwargs):
        raise RuntimeError("Mock error")

    monkeypatch.setattr(selection, "list_all_nodepools_with_details", raise_error)

    # Mock typer.echo
    output = []
    monkeypatch.setattr(selection.typer, "echo", lambda msg, **kwargs: output.append(msg))

    selection.select_nodepool(env)
    assert any("failed" in str(msg).lower() for msg in output)


def test_select_tool_parse_failure(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Test tool selection when parsing fails."""
    env = EnvConfig(path=tmp_path / ".env")
    env.tool_id = "original"

    # Mock list_resources
    monkeypatch.setattr(selection, "list_resources", lambda *args, **kwargs: ["tool1"])
    # Mock _interactive_choice to return invalid format
    monkeypatch.setattr(selection, "_interactive_choice", lambda title, opts: "invalid-format")

    selection.select_tool(env)
    # tool_id should remain unchanged
    assert env.tool_id == "original"


def test_interactive_choice_with_tabs_multiple_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test interactive selection with tab-delimited options containing multiple fields."""
    # Mock typer.prompt to return 1
    monkeypatch.setattr(selection.typer, "prompt", lambda *args, **kwargs: 1)

    result = selection._interactive_choice(
        "Select item:",
        ["name1\tid1\tlocation1\textra1", "name2\tid2\tlocation2\textra2"],
    )
    assert result == "name1\tid1\tlocation1\textra1"


def test_interactive_choice_invalid_selection_then_valid(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test interactive selection with invalid then valid input."""
    call_count = [0]

    def mock_prompt(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            return 99  # Invalid selection
        return 2  # Valid selection

    monkeypatch.setattr(selection.typer, "prompt", mock_prompt)
    monkeypatch.setattr(selection.typer, "echo", lambda *args, **kwargs: None)

    result = selection._interactive_choice("Select:", ["a", "b", "c"])
    assert result == "b"
    assert call_count[0] == 2  # Prompted twice


def test_resolve_project_no_workspace_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test project resolution when project name has no workspace prefix."""
    monkeypatch.setattr(selection.typer, "prompt", lambda *args, **kwargs: 1)
    monkeypatch.setattr(selection.typer, "echo", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        selection, "list_resources", lambda *args, **kwargs: ["simple-project\t/project-id"]
    )
    pid = selection.resolve_project()
    assert pid == "/project-id"


def test_pick_scratch_resource_skip_returns_empty(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    """Picking the Skip option returns '' without invoking create_callback."""
    create_called = []

    def _capture(title: str, opts: list[str]) -> str:
        return next(o for o in opts if "__SKIP__" in o)

    monkeypatch.setattr(selection, "_interactive_choice", _capture)

    result = selection._pick_scratch_resource(
        sc_name="sc1",
        sc_vnet_id="/subscriptions/s/resourceGroups/rg/providers/Microsoft.Network/virtualNetworks/v1",
        sc_region="uksouth",
        candidates=[],
        label="dataContainer",
        create_callback=lambda: create_called.append(True) or "should-not-see",
    )
    assert result == ""
    assert not create_called


def test_pick_scratch_resource_offers_skip_and_create(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both Skip and Create options are always offered, regardless of candidates."""
    captured: dict = {}

    def _capture(title: str, opts: list[str]) -> str:
        captured["title"] = title
        captured["opts"] = opts
        return opts[0]

    create_called = []
    monkeypatch.setattr(selection, "_interactive_choice", _capture)
    selection._pick_scratch_resource(
        sc_name="sc1",
        sc_vnet_id="/subscriptions/s/resourceGroups/rg/providers/Microsoft.Network/virtualNetworks/v1",
        sc_region="uksouth",
        candidates=[],
        label="dataContainer",
        create_callback=lambda: create_called.append(True) or "new-id",
    )
    assert "Searching for Scratch dataContainers" in captured["title"]
    assert "VNet v1" in captured["title"]
    assert any("__CREATE_NEW__" in o for o in captured["opts"])
    assert any("__SKIP__" in o for o in captured["opts"])
    assert create_called


def test_pick_scratch_resource_filters_by_vnet(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    """Candidates whose ANF lives on a different VNet are not surfaced."""
    sc_vnet = "/subscriptions/s/resourceGroups/rg/providers/Microsoft.Network/virtualNetworks/v1"
    other_vnet = "/subscriptions/s/resourceGroups/rg/providers/Microsoft.Network/virtualNetworks/v2"

    captured: dict = {}

    def _capture(title: str, opts: list[str]) -> str:
        captured["opts"] = opts
        return opts[0]  # Create

    monkeypatch.setattr(selection, "_interactive_choice", _capture)
    selection._pick_scratch_resource(
        sc_name="sc1",
        sc_vnet_id=sc_vnet,
        sc_region="uksouth",
        candidates=[
            {"name": "dc-same", "id": "/dc/same", "vnet": sc_vnet, "region": "uksouth"},
            {"name": "dc-diff", "id": "/dc/diff", "vnet": other_vnet, "region": "uksouth"},
        ],
        label="dataContainer",
        create_callback=lambda: "new-id",
    )
    # Only the same-VNet candidate is shown (alongside Create + Skip)
    assert any("dc-same" in o for o in captured["opts"])
    assert all("dc-diff" not in o for o in captured["opts"])
