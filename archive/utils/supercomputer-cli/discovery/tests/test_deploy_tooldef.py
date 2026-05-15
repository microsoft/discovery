"""Tests for deploy_tooldef rendering and command construction."""

from __future__ import annotations

import json

import pytest

from discovery.poll import deploy_tooldef


def _default_inputs() -> deploy_tooldef.ToolDefinitionInputs:
    return deploy_tooldef.ToolDefinitionInputs(
        name="demo",
        description="desc",
        image="acr.azurecr.io/demo:latest",
        location="eastus",
        version="2.0",
        environment={"VAR": "value"},
        tags={"rg": {"key": "value"}},
    )


def test_render_tool_definition_replaces_placeholders() -> None:
    inputs = _default_inputs()
    template = deploy_tooldef.render_tool_definition(inputs)
    assert template["infra"][0]["image"]["acr"] == inputs.image


def test_build_arm_parameters_injects_environment() -> None:
    inputs = _default_inputs()
    tool_def = deploy_tooldef.render_tool_definition(inputs)
    params = deploy_tooldef.build_arm_parameters(inputs, tool_def)
    env_vars = params["parameters"]["OutEnvironmentVariables"]["value"]
    assert json.loads(env_vars)["VAR"] == "value"
    assert params["parameters"]["outToolVersion"]["value"] == "2.0"


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
