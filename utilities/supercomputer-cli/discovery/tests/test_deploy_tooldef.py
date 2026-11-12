"""Tests for deploy_tooldef rendering and command construction."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from discovery.poll import deploy_tooldef
from discovery.poll.models.arm_versions import LEGACY_TOOL_ARM_API_VERSION, ToolArmApiVersion


def _default_inputs(
    *, mpi: bool = False, pool_size: int | None = None
) -> deploy_tooldef.ToolDefinitionInputs:
    return deploy_tooldef.ToolDefinitionInputs(
        name="demo",
        description="desc",
        image="acr.azurecr.io/demo:latest",
        location="eastus",
        version="2.0",
        environment={"VAR": "value"},
        tags={"rg": {"key": "value"}},
        mpi=mpi,
        pool_size=pool_size,
    )


def test_render_tool_definition_replaces_placeholders() -> None:
    inputs = _default_inputs()
    template = deploy_tooldef.render_tool_definition(inputs)
    infra = template["infra"][0]
    assert infra["image"]["acr"] == inputs.image
    assert infra["infra_type"] == "container"
    assert infra["compute"]["pool_size"] == 1
    assert "mpi" not in infra
    assert "internal_ports" not in infra
    assert "infiniband" not in infra["compute"]


@pytest.mark.parametrize(
    ("mpi", "pool_size", "infiniband"),
    [(True, 2, False), (True, 3, False), (True, 2, True), (False, 3, False), (False, 1, True)],
)
def test_deploy_tool_definition_serializes_compute_options(
    mpi: bool, pool_size: int, infiniband: bool
) -> None:
    """Creation options survive rendering and the ARM definitionContent wrapper."""
    inputs = replace(_default_inputs(), mpi=mpi, pool_size=pool_size, infiniband=infiniband)
    result = deploy_tooldef.deploy_tool_definition(
        subscription_id="sub",
        resource_group="rg",
        inputs=inputs,
        execute=False,
    )
    tool_def = json.loads(result["parameters"]["parameters"]["outDefinitionContent"]["value"])
    infra = tool_def["infra"][0]
    assert infra["infra_type"] == "container"
    assert infra["compute"]["pool_size"] == pool_size
    if mpi:
        assert infra["mpi"] == {"follower_command": "/opt/Microsoft.Discovery/mpid"}
        assert infra["internal_ports"] == [{"destination": 22, "protocol": "tcp"}]
    else:
        assert "mpi" not in infra
        assert "internal_ports" not in infra
    if infiniband:
        assert infra["compute"]["infiniband"] is True
    else:
        assert "infiniband" not in infra["compute"]


@pytest.mark.parametrize(("mpi", "expected_size"), [(False, 1), (True, 2)])
def test_tool_definition_uses_valid_mode_default(mpi: bool, expected_size: int) -> None:
    """Omitted size renders two pods for MPI and preserves one for non-MPI."""
    inputs = _default_inputs(mpi=mpi)
    tool_def = deploy_tooldef.render_tool_definition(inputs)
    assert inputs.pool_size == expected_size
    assert tool_def["infra"][0]["compute"]["pool_size"] == expected_size


@pytest.mark.parametrize("pool_size", [0, -1, 1])
def test_tool_definition_rejects_insufficient_mpi_pool_size(pool_size: int) -> None:
    """The creation input model enforces MPI's leader-plus-worker minimum."""
    with pytest.raises(ValueError, match="pool_size must be at least 2 for MPI tools"):
        _default_inputs(mpi=True, pool_size=pool_size)


@pytest.mark.parametrize("pool_size", [0, -1])
def test_tool_definition_rejects_nonpositive_pool_size(pool_size: int) -> None:
    """Invalid replica counts fail before deployment."""
    with pytest.raises(ValueError, match="pool_size must be at least 1"):
        replace(_default_inputs(), pool_size=pool_size)


def test_build_arm_parameters_injects_environment() -> None:
    inputs = _default_inputs()
    tool_def = deploy_tooldef.render_tool_definition(inputs)
    params = deploy_tooldef.build_arm_parameters(inputs, tool_def)
    env_vars = params["parameters"]["OutEnvironmentVariables"]["value"]
    assert json.loads(env_vars)["VAR"] == "value"
    assert params["parameters"]["outToolVersion"]["value"] == "2.0"


@pytest.mark.parametrize("api_version", list(ToolArmApiVersion))
def test_tool_arm_api_routes_same_resource_and_preserves_payload(
    api_version: ToolArmApiVersion,
) -> None:
    """API selection changes routing, not the verified tool properties/content."""
    inputs = replace(_default_inputs(), api_version=api_version.value, mpi=True, pool_size=3)
    result = deploy_tooldef.deploy_tool_definition("sub", "rg", inputs, execute=False)
    template = result["template"]
    resource = template["resources"][0]
    parameters = result["parameters"]["parameters"]

    assert resource["type"] == "Microsoft.Discovery/tools"
    assert resource["apiVersion"] == "[variables('apiVersion')]"
    assert template["variables"]["apiVersion"] == "[parameters('outApiVersion')]"
    assert parameters["outApiVersion"]["value"] == api_version.value
    assert set(resource["properties"]) == {"definitionContent", "version", "environmentVariables"}
    assert json.loads(parameters["OutEnvironmentVariables"]["value"]) == {"VAR": "value"}
    assert parameters["outTagsByResource"]["value"] == {"rg": {"key": "value"}}
    definition = json.loads(parameters["outDefinitionContent"]["value"])
    infra = definition["infra"][0]
    assert infra["mpi"] == {"follower_command": "/opt/Microsoft.Discovery/mpid"}
    assert infra["internal_ports"] == [{"destination": 22, "protocol": "tcp"}]
    assert infra["compute"]["pool_size"] == 3


def test_tool_arm_default_is_explicit_ga_without_rewriting_legacy_template() -> None:
    """Python selects GA; standalone legacy template use remains available."""
    result = deploy_tooldef.deploy_tool_definition("sub", "rg", _default_inputs(), execute=False)
    assert result["parameters"]["parameters"]["outApiVersion"]["value"] == "2026-06-01"
    assert result["template"]["parameters"]["outApiVersion"]["defaultValue"] == (
        LEGACY_TOOL_ARM_API_VERSION
    )


def test_tool_definition_rejects_unknown_arm_api() -> None:
    """Do not silently substitute a different protocol version."""
    with pytest.raises(ValueError, match="ToolArmApiVersion"):
        replace(_default_inputs(), api_version="unsupported")


def test_deploy_tool_definition_execute_false() -> None:
    inputs = _default_inputs()
    result = deploy_tooldef.deploy_tool_definition(
        subscription_id="sub",
        resource_group="rg",
        inputs=inputs,
        execute=False,
    )
    assert "template" in result
    assert "parameters" in result


def test_deploy_tool_definition_cancelled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that deploy_tool_definition returns cancelled when user says no."""
    inputs = _default_inputs()

    # Mock typer interactions
    monkeypatch.setattr(deploy_tooldef.typer, "echo", lambda *args, **kwargs: None)
    monkeypatch.setattr(deploy_tooldef.typer, "secho", lambda *args, **kwargs: None)
    monkeypatch.setattr(deploy_tooldef.typer, "confirm", lambda *args, **kwargs: False)

    result = deploy_tooldef.deploy_tool_definition(
        subscription_id="sub",
        resource_group="rg",
        inputs=inputs,
        execute=True,
    )

    assert result.get("cancelled") is True


def test_deploy_tool_definition_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test successful tool definition deployment."""
    inputs = _default_inputs()

    # Mock typer interactions
    monkeypatch.setattr(deploy_tooldef.typer, "echo", lambda *args, **kwargs: None)
    monkeypatch.setattr(deploy_tooldef.typer, "secho", lambda *args, **kwargs: None)
    monkeypatch.setattr(deploy_tooldef.typer, "confirm", lambda *args, **kwargs: True)

    # Mock subprocess.run to succeed
    class MockProc:
        returncode = 0

    monkeypatch.setattr(deploy_tooldef.subprocess, "run", lambda *args, **kwargs: MockProc())

    result = deploy_tooldef.deploy_tool_definition(
        subscription_id="sub",
        resource_group="rg",
        inputs=inputs,
        execute=True,
    )

    assert result["success"] is True
    assert result["exitCode"] == 0


def test_deploy_tool_definition_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test tool definition deployment failure."""
    inputs = _default_inputs()

    # Mock typer interactions
    monkeypatch.setattr(deploy_tooldef.typer, "echo", lambda *args, **kwargs: None)
    monkeypatch.setattr(deploy_tooldef.typer, "secho", lambda *args, **kwargs: None)
    monkeypatch.setattr(deploy_tooldef.typer, "confirm", lambda *args, **kwargs: True)

    # Mock subprocess.run to fail
    class MockProc:
        returncode = 1

    monkeypatch.setattr(deploy_tooldef.subprocess, "run", lambda *args, **kwargs: MockProc())

    with pytest.raises(RuntimeError, match="Deployment command exited"):
        deploy_tooldef.deploy_tool_definition(
            subscription_id="sub",
            resource_group="rg",
            inputs=inputs,
            execute=True,
        )


def test_escape_tool_json() -> None:
    """Test _escape_tool_json creates properly escaped JSON string."""
    obj = {"key": "value", "nested": {"a": 1}}
    result = deploy_tooldef._escape_tool_json(obj)
    # Should be a JSON string without spaces
    assert result == '{"key":"value","nested":{"a":1}}'


def test_load_text() -> None:
    """Test _load_text loads template files."""
    # Should be able to load the template
    result = deploy_tooldef._load_text("template.json")
    assert isinstance(result, str)
    assert len(result) > 0


def test_build_arm_parameters_with_tags() -> None:
    """Test build_arm_parameters with tags."""
    inputs = deploy_tooldef.ToolDefinitionInputs(
        name="test",
        description="desc",
        image="img",
        location="eastus",
        tags={"rg": {"env": "test"}},
    )
    tool_def = deploy_tooldef.render_tool_definition(inputs)
    params = deploy_tooldef.build_arm_parameters(inputs, tool_def)

    assert params["parameters"]["outTagsByResource"]["value"] == {"rg": {"env": "test"}}
