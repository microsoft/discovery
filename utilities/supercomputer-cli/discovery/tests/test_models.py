"""Tests for discovery_poll models."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from discovery.poll.models.auth import AuthHeaders
from discovery.poll.models.config import EnvConfig
from discovery.poll.models.tool_response import ToolExecutionEnvelope, ToolExecutionResponse
from discovery.poll.models.tool_run import DataMount, ToolRunRequest


def _load_response_dict() -> dict[str, Any]:
    path = Path(__file__).resolve().parent / "artifacts" / "response.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_auth_headers_normalization() -> None:
    headers = AuthHeaders.model_validate(
        {
            "Authorization": "  Bearer token  ",
            "Accept": "",
            "Content-Type": "application/json",
        }
    )
    assert headers.authorization == "Bearer token"
    assert headers.accept is None
    dumped = headers.model_dump(by_alias=True)
    assert dumped["Content-Type"] == "application/json"


def test_env_config_properties_and_save(tmp_path) -> None:
    env_path = tmp_path / ".env"
    env = EnvConfig(path=env_path)
    env.workspace_resource_id = (
        "/subscriptions/1/resourceGroups/rg/providers/Microsoft.Discovery/workspaces/ws"
    )
    env.project_id = env.workspace_resource_id + "/projects/proj"
    env.nodepool_id = "nodepool"
    env.acr_name = "acr"
    env.save()
    persisted = json.loads(env_path.read_text(encoding="utf-8"))
    assert env.project_name == "proj"
    assert env.subscription == "1"
    assert env.resource_group == "rg"
    assert env.project_ready is True
    assert env.acr_ready() is True
    assert env.acr_url == "acr.azurecr.io"
    assert persisted["DISCOVERY_PROJECT_ID"].endswith("proj")


def test_env_config_acr_url_uses_login_server(tmp_path) -> None:
    env = EnvConfig(path=tmp_path / ".env")
    env.acr_name = "myacr"
    env.acr_login_server = "myacr.azurecr.cn"
    assert env.acr_url == "myacr.azurecr.cn"


def test_env_config_acr_url_fallback(tmp_path) -> None:
    env = EnvConfig(path=tmp_path / ".env")
    env.acr_name = "myacr"
    assert env.acr_url == "myacr.azurecr.io"


def test_env_config_acr_url_empty(tmp_path) -> None:
    env = EnvConfig(path=tmp_path / ".env")
    assert env.acr_url == ""


def test_tool_execution_response_validation() -> None:
    data = _load_response_dict()
    model = ToolExecutionResponse.model_validate(data)
    assert model.status == "Succeeded"
    bad = dict(data)
    bad["id"] = "invalid"
    with pytest.raises(ValueError):
        ToolExecutionResponse.model_validate(bad)


def test_tool_execution_envelope_alias_dump() -> None:
    data = _load_response_dict()
    body = ToolExecutionResponse.model_validate(data)
    headers = AuthHeaders.model_validate({"Authorization": "Bearer token"})
    envelope = ToolExecutionEnvelope(headers=headers, body=body)
    dumped = envelope.model_dump(by_alias=True)
    assert dumped["headers"]["Authorization"] == "Bearer token"


def test_tool_run_request_helpers() -> None:
    mount = DataMount.model_validate({"mountPath": "/mnt", "uri": "https://example"})
    req = ToolRunRequest.model_validate(
        {
            "toolId": "tool",
            "storageId": "storage",
            "command": "echo",
            "outputData": [mount.model_dump(by_alias=True)],
            "inlineFiles": [],
            "inputData": [],
            "nodePoolIds": [],
        }
    )
    assert req.has_outputs() is True



