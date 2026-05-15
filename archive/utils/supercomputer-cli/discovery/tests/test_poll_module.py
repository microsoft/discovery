"""Tests for poll module helpers and control flow."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest

from discovery.poll import dataplane_api
from discovery.poll.models.tool_response import (
    OperationsListResponse,
    ToolExecutionResponse,
    ToolReport,
)
from discovery.poll.models.tool_run import ToolRunRequest


@pytest.fixture(autouse=True)
def _reset_persistent_client():
    """Reset the persistent HTTP client between tests so monkeypatches work."""
    dataplane_api._persistent_client = None
    yield
    dataplane_api._persistent_client = None


@pytest.fixture(autouse=True)
def _reset_token_cache():
    """Clear the token cache between tests."""
    dataplane_api._token_cache.clear()
    yield
    dataplane_api._token_cache.clear()


@pytest.fixture
def sample_response_dict() -> dict[str, Any]:
    path = Path(__file__).resolve().parent / "artifacts" / "response.json"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def sample_toolrun_request() -> ToolRunRequest:
    path = Path(__file__).resolve().parent / "artifacts" / "toolrun.json"
    return ToolRunRequest.model_validate_json(path.read_text(encoding="utf-8"))


def test_log_diff_returns_new_entries() -> None:
    old = ["a", "b"]
    new = ["a", "b", "c", "d"]
    assert dataplane_api._log_diff(old, new) == ["c", "d"]


def test_extract_tool_report_logs_from_dict(sample_response_dict: dict[str, Any]) -> None:
    report_dict = sample_response_dict["result"]["toolReport"]
    logs = dataplane_api._extract_tool_report_logs(report_dict)
    assert "glxgears-viz:" in logs[0]
    assert "bin" in logs[1]


def test_extract_tool_report_logs_from_model(sample_response_dict: dict[str, Any]) -> None:
    report_dict = sample_response_dict["result"]["toolReport"]
    report = ToolReport.model_validate(report_dict)
    logs = dataplane_api._extract_tool_report_logs(report)
    assert logs[0] == "glxgears-viz:"


def test_debug_http_response_handles_response() -> None:
    resp = dataplane_api.httpx.Response(
        200, headers={"content-type": "application/json"}, text="{}"
    )
    dataplane_api._debug_http_response("label", resp)


def test_http_post_success(
    monkeypatch: pytest.MonkeyPatch, sample_response_dict: dict[str, Any]
) -> None:
    called = {}
    response_text = json.dumps(sample_response_dict)

    class StubResponse:
        status_code = 200
        ok = True
        headers = {"content-type": "application/json"}
        text = response_text
        content = response_text.encode("utf-8")

        def raise_for_status(self) -> None:
            """Pretend status is fine."""

        def json(self) -> dict[str, Any]:
            return sample_response_dict

    class StubClient:
        def __enter__(self) -> StubClient:
            return self

        def __exit__(self, exc_type, exc, tb) -> None:  # type: ignore[override]
            return None

        def post(self, url: str, headers: dict[str, str], content: str, params=None):
            """Capture invocation and return stub response."""
            called["url"] = url
            called["headers"] = headers
            called["content"] = content
            return StubResponse()

    monkeypatch.setattr(dataplane_api.httpx, "Client", lambda **kwargs: StubClient())

    headers = dataplane_api.AuthHeaders.model_validate({"Authorization": "Bearer token"})
    body = ToolExecutionResponse.model_validate(sample_response_dict)
    raw = dataplane_api._http_post(url="https://example.com", headers=headers, data=body)
    resp = cast(dict[str, Any], raw)
    assert resp["status"] == "Succeeded"
    assert called["headers"]["Authorization"] == "Bearer token"


def test_http_get_success(
    monkeypatch: pytest.MonkeyPatch, sample_response_dict: dict[str, Any]
) -> None:
    response_text = json.dumps(sample_response_dict)

    class StubResponse:
        status_code = 200
        ok = True
        headers = {"content-type": "application/json"}
        text = response_text
        content = response_text.encode("utf-8")

        def raise_for_status(self) -> None:
            """Pretend status is fine."""

        def json(self) -> dict[str, Any]:
            return sample_response_dict

    class StubClient:
        def __enter__(self) -> StubClient:
            return self

        def __exit__(self, exc_type, exc, tb) -> None:  # type: ignore[override]
            return None

        def get(self, url: str, headers: dict[str, str], params: dict[str, str] | None = None):
            """Return stub response."""
            return StubResponse()

    monkeypatch.setattr(dataplane_api.httpx, "Client", lambda **kwargs: StubClient())

    headers = dataplane_api.AuthHeaders.model_validate({"Authorization": "Bearer token"})
    raw = dataplane_api._http_get(url="https://example.com", headers=headers)
    resp = cast(dict[str, Any], raw)
    assert resp["status"] == "Succeeded"


def test_start_tool_run_uses_access_token(
    monkeypatch: pytest.MonkeyPatch,
    sample_response_dict: dict[str, Any],
    sample_toolrun_request: ToolRunRequest,
) -> None:
    monkeypatch.setattr(
        dataplane_api, "get_access_token", lambda scope=dataplane_api.DEFAULT_SCOPE: "token123"
    )
    captured = {}

    def fake_post(*, url: str, headers: dataplane_api.AuthHeaders, data: Any, params=None) -> dict[str, Any]:
        captured["url"] = url
        captured["auth"] = headers.authorization
        return sample_response_dict

    monkeypatch.setattr(dataplane_api, "_http_post", fake_post)

    resp = dataplane_api.start_tool_run("proj", sample_toolrun_request, "https://workspace", api_version="2025-07-01-preview")
    assert resp.id == sample_response_dict["id"]
    assert captured["url"].endswith("/tools/projects/proj:run")
    assert captured["auth"] == "Bearer token123"


def test_poll_operation_until_success(
    monkeypatch: pytest.MonkeyPatch, sample_response_dict: dict[str, Any]
) -> None:
    monkeypatch.setattr(
        dataplane_api, "get_access_token", lambda scope=dataplane_api.DEFAULT_SCOPE: "token123"
    )
    responses = [
        {**sample_response_dict, "status": "Active"},
        sample_response_dict,
    ]

    def fake_get(*, url: str, headers: dataplane_api.AuthHeaders, params=None) -> dict[str, Any]:
        return responses.pop(0)

    monkeypatch.setattr(dataplane_api, "_http_get", fake_get)
    monkeypatch.setattr(dataplane_api.time, "sleep", lambda _: None)

    final = dataplane_api.poll_operation("proj", "op123", "https://workspace", poll_interval=0, api_version="2025-07-01-preview")
    assert final.status == "Succeeded"


def test_cancel_operation_posts_cancel(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        dataplane_api, "get_access_token", lambda scope=dataplane_api.DEFAULT_SCOPE: "token123"
    )
    captured = {}

    def fake_post(*, url: str, headers: dataplane_api.AuthHeaders, data: Any, params=None) -> dict[str, Any]:
        captured["url"] = url
        captured["token"] = headers.authorization
        return {}

    monkeypatch.setattr(dataplane_api, "_http_post", fake_post)
    dataplane_api.cancel_operation("proj", "op", "https://workspace", api_version="2025-07-01-preview")
    assert captured["url"].endswith("/tools/projects/proj/operations/op:cancel")
    assert captured["token"] == "Bearer token123"


def test_run_and_poll_combines_calls(
    monkeypatch: pytest.MonkeyPatch,
    sample_response_dict: dict[str, Any],
    sample_toolrun_request: ToolRunRequest,
) -> None:
    start_resp = ToolExecutionResponse.model_validate(sample_response_dict)
    monkeypatch.setattr(dataplane_api, "start_tool_run", lambda *args, **kwargs: start_resp)
    monkeypatch.setattr(dataplane_api, "poll_operation", lambda *args, **kwargs: start_resp)

    result = dataplane_api.run_and_poll("proj", sample_toolrun_request, "https://workspace", api_version="2025-07-01-preview")
    assert result.id == start_resp.id


def test_get_access_token_success(monkeypatch: pytest.MonkeyPatch) -> None:
    class StubCompleted:
        def __init__(self) -> None:
            self.returncode = 0
            self.stdout = json.dumps({"accessToken": "abc"})
            self.stderr = ""

    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: StubCompleted())
    assert dataplane_api.get_access_token() == "abc"


def test_get_access_token_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    class StubCompleted:
        def __init__(self) -> None:
            self.returncode = 1
            self.stdout = ""
            self.stderr = "boom"

    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: StubCompleted())
    with pytest.raises(dataplane_api.PollError):
        dataplane_api.get_access_token()


@pytest.fixture
def sample_operations_list_dict() -> dict[str, Any]:
    path = Path(__file__).resolve().parent / "artifacts" / "operations_list.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_list_operations_success(
    monkeypatch: pytest.MonkeyPatch,
    sample_operations_list_dict: dict[str, Any],
) -> None:
    """Test list_operations returns parsed operations list."""
    monkeypatch.setattr(
        dataplane_api, "get_access_token", lambda scope=dataplane_api.DEFAULT_SCOPE: "token123"
    )
    captured = {}

    class StubResponse:
        status_code = 200
        ok = True
        headers = {"content-type": "application/json"}
        text = json.dumps(sample_operations_list_dict)

        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict[str, Any]:
            return sample_operations_list_dict

    class StubClient:
        def __enter__(self) -> StubClient:
            return self

        def __exit__(self, exc_type, exc, tb) -> None:  # type: ignore[override]
            return None

        def get(self, url: str, headers: dict[str, str], params: dict[str, str]) -> StubResponse:
            captured["url"] = url
            captured["headers"] = headers
            captured["params"] = params
            return StubResponse()

    monkeypatch.setattr(dataplane_api.httpx, "Client", lambda **kwargs: StubClient())

    result = dataplane_api.list_operations("proj", "https://workspace", {"status": "Running"}, api_version="2025-07-01-preview")

    assert isinstance(result, OperationsListResponse)
    assert len(result.values) == 2
    assert result.values[0].id == "12345678-1234-1234-1234-123456789abc"
    assert result.values[0].status == "Succeeded"
    assert result.values[1].status == "Running"
    assert result.next_link == "https://example.com/next-page"
    assert captured["url"] == "https://workspace/tools/projects/proj/operations"
    assert captured["params"] == {"status": "Running", "api-version": "2025-07-01-preview", "$top": "128"}
    assert "Bearer token123" in captured["headers"]["Authorization"]


def test_list_operations_empty_query(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test list_operations with no query parameters uses default reverse=true."""
    monkeypatch.setattr(
        dataplane_api, "get_access_token", lambda scope=dataplane_api.DEFAULT_SCOPE: "token123"
    )
    captured = {}

    class StubResponse:
        status_code = 200
        ok = True
        headers = {"content-type": "application/json"}
        text = '{"values": [], "nextLink": null}'

        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict[str, Any]:
            return {"values": [], "nextLink": None}

    class StubClient:
        def __enter__(self) -> StubClient:
            return self

        def __exit__(self, exc_type, exc, tb) -> None:  # type: ignore[override]
            return None

        def get(self, url: str, headers: dict[str, str], params: dict[str, str]) -> StubResponse:
            captured["params"] = params
            return StubResponse()

    monkeypatch.setattr(dataplane_api.httpx, "Client", lambda **kwargs: StubClient())

    result = dataplane_api.list_operations("proj", "https://workspace", api_version="2025-07-01-preview")
    assert isinstance(result, OperationsListResponse)
    assert len(result.values) == 0
    assert result.next_link is None
    assert captured["params"] == {"reverse": "true", "api-version": "2025-07-01-preview", "$top": "128"}


def test_list_operations_uses_access_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test list_operations gets and uses access token."""
    token_called = []

    def fake_token(scope: str = dataplane_api.DEFAULT_SCOPE) -> str:
        token_called.append(scope)
        return "test-token-xyz"

    monkeypatch.setattr(dataplane_api, "get_access_token", fake_token)

    class StubResponse:
        status_code = 200
        headers = {"content-type": "application/json"}
        text = '{"values": []}'

        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict[str, Any]:
            return {"values": []}

    class StubClient:
        def __enter__(self) -> StubClient:
            return self

        def __exit__(self, exc_type, exc, tb) -> None:  # type: ignore[override]
            return None

        def get(self, url: str, headers: dict[str, str], params: dict[str, str]) -> StubResponse:
            return StubResponse()

    monkeypatch.setattr(dataplane_api.httpx, "Client", lambda **kwargs: StubClient())

    dataplane_api.list_operations("proj", "https://workspace", api_version="2025-07-01-preview")
    assert len(token_called) == 1
    assert token_called[0] == dataplane_api.DEFAULT_SCOPE


# --- Version branching tests ---

def test_api_version_enum_uses_storage_id():
    """Legacy API versions include storageId in the tool-run payload."""
    from discovery.poll.models.api_version import ApiVersion
    assert ApiVersion.parse("2025-07-01-preview").uses_storage_id
    assert ApiVersion.parse("2025-12-01-preview").uses_storage_id


def test_api_version_enum_modern_omits_storage_id():
    """2026-02-01-preview uses storageUri on the data mounts, not top-level storageId."""
    from discovery.poll.models.api_version import ApiVersion
    assert not ApiVersion.parse("2026-02-01-preview").uses_storage_id
    assert not ApiVersion.parse("2026-02-01-preview").uses_dataassets_uri


def test_api_version_enum_nested_infra_overrides():
    """Only 2025-07-01-preview uses the nested infraOverrides shape."""
    from discovery.poll.models.api_version import ApiVersion
    assert ApiVersion.parse("2025-07-01-preview").uses_nested_infra_overrides
    assert not ApiVersion.parse("2025-12-01-preview").uses_nested_infra_overrides
    assert not ApiVersion.parse("2026-02-01-preview").uses_nested_infra_overrides


def test_api_version_enum_unknown_falls_back_to_latest():
    """Unknown / future versions default to the latest known member (forward-compat)."""
    from discovery.poll.models.api_version import ApiVersion
    assert ApiVersion.parse("2027-01-01-preview") is ApiVersion.latest()
    assert ApiVersion.parse(None) is ApiVersion.latest()
    # latest() should not use the nested (V1) schema
    assert not ApiVersion.latest().uses_nested_infra_overrides


def test_legacy_api_versions_backcompat_shim():
    """Back-compat re-export in cli_submit still reflects the enum capabilities."""
    from discovery.poll.cli_submit import (
        _LEGACY_API_VERSIONS,
        _NESTED_INFRA_OVERRIDES_API_VERSIONS,
    )
    assert "2025-07-01-preview" in _LEGACY_API_VERSIONS
    assert "2025-12-01-preview" in _LEGACY_API_VERSIONS
    assert "2026-02-01-preview" not in _LEGACY_API_VERSIONS
    assert _NESTED_INFRA_OVERRIDES_API_VERSIONS == frozenset({"2025-07-01-preview"})


# ---------------------------------------------------------------------------
# OperationsListResponse dual-key support (values / value)
# ---------------------------------------------------------------------------

_SAMPLE_OP = {
    "nodepoolId": "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Discovery/supercomputers/sc/nodepools/np",
    "id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    "status": "Succeeded",
    "runtimeDetails": "done",
    "createdAt": "2025-01-01T00:00:00Z",
    "completedAt": "2025-01-01T01:00:00Z",
    "createdBy": "user@example.com",
}


class TestOperationsListDualKey:
    """OperationsListResponse must accept both 'values' and 'value' as the list key."""

    def test_parse_with_values_key(self) -> None:
        """The current API format uses 'values' (plural)."""
        payload = {"values": [_SAMPLE_OP], "nextLink": None}
        result = OperationsListResponse.model_validate(payload)
        assert len(result.values) == 1
        assert result.values[0].id == _SAMPLE_OP["id"]

    def test_parse_with_value_key(self) -> None:
        """Future API format will use 'value' (singular)."""
        payload = {"value": [_SAMPLE_OP], "nextLink": None}
        result = OperationsListResponse.model_validate(payload)
        assert len(result.values) == 1
        assert result.values[0].id == _SAMPLE_OP["id"]

    def test_parse_value_key_empty_list(self) -> None:
        """Empty 'value' list parses correctly."""
        payload = {"value": []}
        result = OperationsListResponse.model_validate(payload)
        assert result.values == []

    def test_parse_values_key_multiple_ops(self) -> None:
        """Multiple operations via 'values' key."""
        op2 = {**_SAMPLE_OP, "id": "11111111-2222-3333-4444-555555555555", "status": "Running"}
        payload = {"values": [_SAMPLE_OP, op2]}
        result = OperationsListResponse.model_validate(payload)
        assert len(result.values) == 2
        assert result.values[1].status == "Running"

    def test_serialization_uses_values_key(self) -> None:
        """Serialized JSON should use 'values' (current format)."""
        payload = {"value": [_SAMPLE_OP]}
        result = OperationsListResponse.model_validate(payload)
        dumped = result.model_dump(by_alias=True)
        assert "values" in dumped
        assert "value" not in dumped
