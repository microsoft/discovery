"""Tests for the 2026-06-01 GA-specific surfaces.

Covers:
* ``StorageMountProtocol`` enum + ``DataMount.mount_protocol`` wire serialization.
* ``ApiVersion.supports_mount_protocol`` capability flag.
* ``_parse_mount_protocol_or_exit`` flag-parse helper (validation + fast-fail).
* ``cancel_operation(wait=True/False)`` semantics, including:
    - polls until the operation reaches a positive terminal state.
    - treats a 404 during the wait phase as terminal success.
    - raises :class:`CancelWaitTimeoutError` (subclass of ``PollError``) on timeout.
    - default ``wait=False`` is preserved so ``JobClient.cancel`` keeps its
      fire-and-forget contract.
"""

from __future__ import annotations

import json

import httpx
import pytest
import typer

from discovery.poll import cli_submit, dataplane_api
from discovery.poll.dataplane_api import (
    _TERMINAL_OPERATION_STATES,
    CancelWaitTimeoutError,
    PollError,
    cancel_operation,
)
from discovery.poll.models.api_version import ApiVersion
from discovery.poll.models.tool_run import DataMount, StorageMountProtocol


# ---------------------------------------------------------------------------
# StorageMountProtocol enum
# ---------------------------------------------------------------------------


def test_storage_mount_protocol_wire_values():
    """Enum values must match the GA swagger exactly (server uses Disallow on unknowns)."""
    assert StorageMountProtocol.NFS.value == "NFS"
    assert StorageMountProtocol.BLOBFUSE_CACHING.value == "BlobfuseCaching"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("NFS", StorageMountProtocol.NFS),
        ("nfs", StorageMountProtocol.NFS),
        ("Nfs", StorageMountProtocol.NFS),
        ("BlobfuseCaching", StorageMountProtocol.BLOBFUSE_CACHING),
        ("blobfusecaching", StorageMountProtocol.BLOBFUSE_CACHING),
        ("BLOBFUSECACHING", StorageMountProtocol.BLOBFUSE_CACHING),
    ],
)
def test_storage_mount_protocol_parse_case_insensitive(raw, expected):
    """User-supplied CLI values are normalized to the wire casing."""
    assert StorageMountProtocol.parse(raw) is expected


def test_storage_mount_protocol_parse_rejects_unknown():
    """Unknown values raise ``ValueError`` with the valid value list in the message."""
    with pytest.raises(ValueError, match="Valid values: NFS, BlobfuseCaching"):
        StorageMountProtocol.parse("SMB")


# ---------------------------------------------------------------------------
# DataMount.mount_protocol wire serialization
# ---------------------------------------------------------------------------


def test_datamount_omits_mountprotocol_when_none():
    """Default ``None`` must be omitted from the wire (server rejects unknown fields)."""
    mount = DataMount(mountPath="/x", storageUri="discovery://storageassets/foo")
    payload = json.loads(mount.model_dump_json(by_alias=True, exclude_none=True))
    assert "mountProtocol" not in payload
    assert payload == {"mountPath": "/x", "storageUri": "discovery://storageassets/foo"}


@pytest.mark.parametrize(
    ("protocol", "wire"),
    [
        (StorageMountProtocol.NFS, "NFS"),
        (StorageMountProtocol.BLOBFUSE_CACHING, "BlobfuseCaching"),
    ],
)
def test_datamount_serializes_mountprotocol_with_wire_casing(protocol, wire):
    """Wire payload must use the canonical casing the server enum expects."""
    mount = DataMount(
        mountPath="/x",
        storageUri="discovery://storageassets/foo",
        mountProtocol=protocol,
    )
    payload = json.loads(mount.model_dump_json(by_alias=True, exclude_none=True))
    assert payload["mountProtocol"] == wire


# ---------------------------------------------------------------------------
# ApiVersion.supports_mount_protocol capability flag
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("version", "expected"),
    [
        ("2025-07-01-preview", False),
        ("2025-12-01-preview", False),
        ("2026-02-01-preview", False),
        ("2026-06-01", True),
    ],
)
def test_supports_mount_protocol(version, expected):
    """Only GA (and any forward-compat versions) accept mountProtocol on the wire."""
    assert ApiVersion.parse(version).supports_mount_protocol is expected


def test_supports_mount_protocol_unknown_falls_back_to_latest():
    """Unknown / future versions inherit support via the deny-list pattern."""
    assert ApiVersion.parse("2099-01-01").supports_mount_protocol is True


# ---------------------------------------------------------------------------
# _parse_mount_protocol_or_exit CLI helper
# ---------------------------------------------------------------------------


def test_parse_mount_protocol_none_returns_none():
    """No flag → no override (use storage container's default protocol)."""
    av = ApiVersion.V2026_06_01
    assert cli_submit._parse_mount_protocol_or_exit(None, av) is None
    assert cli_submit._parse_mount_protocol_or_exit("", av) is None


def test_parse_mount_protocol_returns_enum_member():
    """Recognised values produce the matching :class:`StorageMountProtocol`."""
    av = ApiVersion.V2026_06_01
    assert cli_submit._parse_mount_protocol_or_exit("NFS", av) is StorageMountProtocol.NFS
    assert (
        cli_submit._parse_mount_protocol_or_exit("blobfusecaching", av)
        is StorageMountProtocol.BLOBFUSE_CACHING
    )


@pytest.mark.parametrize(
    "av",
    [
        ApiVersion.V2025_07_01_PREVIEW,
        ApiVersion.V2025_12_01_PREVIEW,
        ApiVersion.V2026_02_01_PREVIEW,
    ],
)
def test_parse_mount_protocol_rejects_on_pre_ga(av):
    """Passing the flag on a pre-GA api-version exits 2 with a clear message."""
    with pytest.raises(typer.Exit) as exc_info:
        cli_submit._parse_mount_protocol_or_exit("NFS", av)
    assert exc_info.value.exit_code == 2


def test_parse_mount_protocol_rejects_unknown_value():
    """Unknown protocol on a supported api-version still exits 2 (bad value)."""
    with pytest.raises(typer.Exit) as exc_info:
        cli_submit._parse_mount_protocol_or_exit("SMB", ApiVersion.V2026_06_01)
    assert exc_info.value.exit_code == 2


# ---------------------------------------------------------------------------
# CancelWaitTimeoutError exception
# ---------------------------------------------------------------------------


def test_cancel_wait_timeout_is_pollerror_subclass():
    """Back-compat: existing ``except PollError`` blocks still catch the new exception."""
    assert issubclass(CancelWaitTimeoutError, PollError)


def test_terminal_states_match_swagger():
    """Allow-list mirrors the Azure.Core.Foundations.OperationState terminal members."""
    assert frozenset({"Succeeded", "Failed", "Canceled"}) == _TERMINAL_OPERATION_STATES


# ---------------------------------------------------------------------------
# cancel_operation(wait=...) behavior
# ---------------------------------------------------------------------------


def _stub_response(status: str, op_id: str = "op-xyz"):
    """Build a ToolExecutionResponse-shaped object whose only attribute we use is `.status`."""

    class _Stub:
        pass

    s = _Stub()
    s.id = op_id
    s.status = status
    s.result = None
    s.error = None
    return s


def test_cancel_operation_default_is_fire_and_forget(monkeypatch):
    """Library default must remain ``wait=False`` so JobClient.cancel doesn't silently block.

    Regression guard for the rubber-duck B1 finding: flipping the default would
    break every programmatic SDK caller in ``api.py``.
    """
    post_calls: list[dict] = []
    poll_calls: list[tuple] = []

    def fake_post(**kwargs):
        post_calls.append(kwargs)
        return {}

    def fake_status(*args, **kwargs):
        poll_calls.append((args, kwargs))
        return _stub_response("Running")

    monkeypatch.setattr(dataplane_api, "_http_post", fake_post)
    monkeypatch.setattr(dataplane_api, "get_operation_status", fake_status)
    monkeypatch.setattr(dataplane_api, "get_access_token", lambda *a, **kw: "tok")

    result = cancel_operation(
        "proj", "op-xyz", "https://workspace", api_version="2026-06-01",
    )

    assert result is None
    assert len(post_calls) == 1
    # Crucially: no status polling without wait=True.
    assert poll_calls == []


def test_cancel_operation_wait_polls_until_terminal(monkeypatch):
    """``wait=True`` calls get_operation_status until status is in the terminal allow-list."""
    statuses = iter(["Running", "Running", "Canceled"])
    poll_calls: list[tuple] = []

    monkeypatch.setattr(dataplane_api, "_http_post", lambda **kw: {})
    monkeypatch.setattr(dataplane_api, "get_access_token", lambda *a, **kw: "tok")
    monkeypatch.setattr(dataplane_api, "time", _FakeTime())

    def fake_status(*args, **kwargs):
        poll_calls.append((args, kwargs))
        return _stub_response(next(statuses))

    monkeypatch.setattr(dataplane_api, "get_operation_status", fake_status)

    result = cancel_operation(
        "proj", "op-xyz", "https://workspace",
        api_version="2026-06-01", wait=True,
    )

    assert result == "Canceled"
    # Three polls: Running, Running, Canceled.
    assert len(poll_calls) == 3


def test_cancel_operation_wait_treats_404_as_terminal(monkeypatch):
    """A 404 during the wait phase means the op was reaped — cancel goal achieved."""
    monkeypatch.setattr(dataplane_api, "_http_post", lambda **kw: {})
    monkeypatch.setattr(dataplane_api, "get_access_token", lambda *a, **kw: "tok")
    monkeypatch.setattr(dataplane_api, "time", _FakeTime())

    fake_response = httpx.Response(
        status_code=404,
        request=httpx.Request("GET", "https://example/status"),
        content=b"{}",
    )
    err = httpx.HTTPStatusError(
        message="not found", request=fake_response.request, response=fake_response,
    )

    def fake_status(*args, **kwargs):
        raise err

    monkeypatch.setattr(dataplane_api, "get_operation_status", fake_status)

    result = cancel_operation(
        "proj", "op-xyz", "https://workspace",
        api_version="2026-06-01", wait=True,
    )
    # Synthetic terminal status: cancel goal satisfied.
    assert result == "Canceled"


def test_cancel_operation_wait_reraises_non_404_http_errors(monkeypatch):
    """500 during the wait phase is a real failure, not a synthetic-terminal case."""
    monkeypatch.setattr(dataplane_api, "_http_post", lambda **kw: {})
    monkeypatch.setattr(dataplane_api, "get_access_token", lambda *a, **kw: "tok")
    monkeypatch.setattr(dataplane_api, "time", _FakeTime())

    fake_response = httpx.Response(
        status_code=500,
        request=httpx.Request("GET", "https://example/status"),
        content=b"{}",
    )
    err = httpx.HTTPStatusError(
        message="boom", request=fake_response.request, response=fake_response,
    )

    monkeypatch.setattr(
        dataplane_api,
        "get_operation_status",
        lambda *a, **kw: (_ for _ in ()).throw(err),
    )

    with pytest.raises(httpx.HTTPStatusError):
        cancel_operation(
            "proj", "op-xyz", "https://workspace",
            api_version="2026-06-01", wait=True,
        )


def test_cancel_operation_wait_raises_timeout(monkeypatch):
    """If the operation never reaches a terminal state within budget, raise CancelWaitTimeoutError."""
    monkeypatch.setattr(dataplane_api, "_http_post", lambda **kw: {})
    monkeypatch.setattr(dataplane_api, "get_access_token", lambda *a, **kw: "tok")
    monkeypatch.setattr(dataplane_api, "time", _FakeTime(advance_per_call=10.0))
    monkeypatch.setattr(
        dataplane_api,
        "get_operation_status",
        lambda *a, **kw: _stub_response("Running"),
    )

    with pytest.raises(CancelWaitTimeoutError) as exc_info:
        cancel_operation(
            "proj", "op-xyz", "https://workspace",
            api_version="2026-06-01", wait=True, wait_timeout_seconds=5,
        )
    assert "op-xyz" in str(exc_info.value)
    assert "5s" in str(exc_info.value)


def test_cancel_operation_requires_project_and_id():
    with pytest.raises(PollError):
        cancel_operation("", "op", "https://w", api_version="2026-06-01")
    with pytest.raises(PollError):
        cancel_operation("proj", "", "https://w", api_version="2026-06-01")


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


class _FakeTime:
    """Module-replacement that lets the cancel-wait loop run without real sleeping.

    The cancel-wait loop calls ``time.time()`` for elapsed checks and ``time.sleep()``
    between polls. We replace the whole ``time`` module reference inside
    ``dataplane_api`` with this fake so tests stay deterministic and fast.
    """

    def __init__(self, advance_per_call: float = 0.0):
        self._now = 0.0
        self._advance = advance_per_call

    def time(self) -> float:
        result = self._now
        self._now += self._advance
        return result

    def sleep(self, seconds: float) -> None:
        # Bump the clock by the requested duration so timeouts can be reached
        # without real wall-clock delay. When the test sets advance_per_call > 0
        # the clock already moves on each time() read, so this is additive.
        self._now += seconds
