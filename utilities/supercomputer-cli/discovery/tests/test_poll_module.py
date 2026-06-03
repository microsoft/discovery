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
    """2026-02-01-preview and 2026-06-01 (GA) use storageUri on the data mounts, not top-level storageId."""
    from discovery.poll.models.api_version import ApiVersion
    assert not ApiVersion.parse("2026-02-01-preview").uses_storage_id
    assert not ApiVersion.parse("2026-02-01-preview").uses_dataassets_uri
    assert not ApiVersion.parse("2026-06-01").uses_storage_id
    assert not ApiVersion.parse("2026-06-01").uses_dataassets_uri


def test_api_version_enum_nested_infra_overrides():
    """Only 2025-07-01-preview uses the nested infraOverrides shape."""
    from discovery.poll.models.api_version import ApiVersion
    assert ApiVersion.parse("2025-07-01-preview").uses_nested_infra_overrides
    assert not ApiVersion.parse("2025-12-01-preview").uses_nested_infra_overrides
    assert not ApiVersion.parse("2026-02-01-preview").uses_nested_infra_overrides
    assert not ApiVersion.parse("2026-06-01").uses_nested_infra_overrides


def test_api_version_enum_ga_is_latest():
    """The GA version (2026-06-01) is the newest known member and the fallback target."""
    from discovery.poll.models.api_version import ApiVersion
    assert ApiVersion.latest() is ApiVersion.V2026_06_01
    assert ApiVersion.parse("2026-06-01") is ApiVersion.V2026_06_01
    # GA shares the modern (V2) capability flags with 2026-02-01-preview:
    # no storageId, storageassets URIs, flat infraOverrides.
    ga = ApiVersion.V2026_06_01
    assert not ga.uses_storage_id
    assert not ga.uses_dataassets_uri
    assert not ga.uses_nested_infra_overrides


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
    assert "2026-06-01" not in _LEGACY_API_VERSIONS
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
# -------- connect_debug_container contract --------


class _ConnectStubResponse:
    def __init__(
        self,
        status_code: int = 200,
        payload: dict[str, Any] | None = None,
    ) -> None:
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self.headers = {"content-type": "application/json"}
        body = json.dumps(payload or {})
        self.text = body
        self.content = body.encode("utf-8")
        self._payload = payload or {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            msg = "stub http error"
            raise dataplane_api.httpx.HTTPStatusError(
                msg, request=None, response=None  # type: ignore[arg-type]
            )

    def json(self) -> dict[str, Any]:
        return self._payload


def _install_connect_stub(
    monkeypatch: pytest.MonkeyPatch,
    *,
    response_payload: dict[str, Any] | None = None,
    status_code: int = 200,
    captured: dict[str, Any] | None = None,
) -> None:
    monkeypatch.setattr(
        dataplane_api, "get_access_token", lambda scope=dataplane_api.DEFAULT_SCOPE: "tok"
    )

    class StubClient:
        def __enter__(self) -> StubClient:
            return self

        def __exit__(self, exc_type, exc, tb) -> None:  # type: ignore[override]
            return None

        def post(self, url: str, **kwargs: Any) -> _ConnectStubResponse:
            if captured is not None:
                captured["url"] = url
                captured["kwargs"] = kwargs
            return _ConnectStubResponse(status_code=status_code, payload=response_payload)

        def get(self, url: str, **kwargs: Any) -> _ConnectStubResponse:
            if captured is not None:
                captured["url"] = url
                captured["kwargs"] = kwargs
            return _ConnectStubResponse(status_code=status_code, payload=response_payload)

    monkeypatch.setattr(dataplane_api.httpx, "Client", lambda **kwargs: StubClient())


def test_connect_debug_container_default_pod_omits_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    _install_connect_stub(
        monkeypatch,
        response_payload={"tunnelId": "t1", "tunnelName": "name-1"},
        captured=captured,
    )

    result = dataplane_api.connect_debug_container(
        project_name="proj",
        operation_id="op1",
        workspace_url="https://ws",
    )

    assert captured["url"] == "https://ws/tools/projects/proj/operations/op1:connect"
    # No JSON body
    assert "content" not in captured["kwargs"]
    assert "data" not in captured["kwargs"]
    assert "json" not in captured["kwargs"]
    # Bearer header
    assert captured["kwargs"]["headers"]["Authorization"] == "Bearer tok"
    assert result["tunnelName"] == "name-1"


def test_connect_debug_container_nonzero_pod_adds_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    _install_connect_stub(monkeypatch, response_payload={}, captured=captured)

    dataplane_api.connect_debug_container(
        project_name="proj",
        operation_id="op1",
        workspace_url="https://ws/",
        pod_index=3,
    )

    assert captured["url"] == "https://ws/tools/projects/proj/operations/op1:connect?pod=3"


# -------- get_operation_pods contract --------


def test_get_operation_pods_success(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}
    payload = {
        "pods": [
            {"index": 0, "role": "leader", "phase": "Running"},
            {"index": 1, "role": "worker", "phase": "Pending"},
        ]
    }
    _install_connect_stub(monkeypatch, response_payload=payload, captured=captured)

    pods = dataplane_api.get_operation_pods("proj", "op1", "https://ws")

    assert captured["url"] == "https://ws/tools/projects/proj/preview/operations/op1/pods"
    assert captured["kwargs"]["headers"]["Authorization"] == "Bearer tok"
    assert [p.index for p in pods] == [0, 1]
    assert pods[0].role == "leader"
    assert pods[1].phase == "Pending"


def test_get_operation_pods_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_connect_stub(monkeypatch, response_payload={"pods": []})
    assert dataplane_api.get_operation_pods("proj", "op1", "https://ws") == []


def test_get_operation_pods_404_raises_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_connect_stub(monkeypatch, response_payload={}, status_code=404)
    with pytest.raises(dataplane_api.OperationNotFoundError):
        dataplane_api.get_operation_pods("proj", "op1", "https://ws")
