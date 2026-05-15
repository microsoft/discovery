import pytest
from ai_infrastructure_mcp import ssh_config as sc
from ai_infrastructure_mcp.tools.pkeys import (
    _parse_parallel_ssh_output,
    get_infiniband_pkeys,
)


class DummyStd:

    def __init__(self, data: str):
        self._data = data

    def read(self):
        return self._data.encode()


class DummyClient:

    def __init__(self, expected_fragment: str, output: str):
        self.expected_fragment = expected_fragment
        self.output = output
        self.closed = False

    def set_missing_host_key_policy(self, *_):
        pass

    def connect(self, **kwargs):
        pass

    def exec_command(self, cmd):
        assert self.expected_fragment in cmd
        return (None, DummyStd(self.output), DummyStd(""))

    def close(self):
        self.closed = True


@pytest.fixture
def mock_env(monkeypatch):
    monkeypatch.setenv(sc.ENV_CLUSTER_HOST, "test-host")
    monkeypatch.setenv(sc.ENV_CLUSTER_USER, "test-user")
    return True


def test_get_infiniband_pkeys_multi(monkeypatch, mock_env):
    from ai_infrastructure_mcp import ssh_config as mod

    sample_output = """[1] 12:00:00 [SUCCESS] hostA
0x801b
0x801c
[2] 12:00:00 [SUCCESS] hostB
[3] 12:00:00 [SUCCESS] hostC
0x801d
"""
    dummy_client = DummyClient(
        expected_fragment='parallel-ssh -i -H "hostA hostB hostC"', output=sample_output
    )
    monkeypatch.setattr(mod, "get_ssh_client", lambda: dummy_client)
    result = get_infiniband_pkeys(["hostA", "hostB", "hostC"])
    assert result["version"] == 1
    assert "timestamp" in result
    hosts = {h["host"]: h for h in result["hosts"]}
    assert hosts["hostA"]["pkeys"] == ["0x801b", "0x801c"]
    assert hosts["hostB"]["pkeys"] == []
    assert hosts["hostC"]["pkeys"] == ["0x801d"]
    assert result["summary"]["queried"] == 3
    assert dummy_client.closed


def test_empty_hosts():
    with pytest.raises(ValueError):
        get_infiniband_pkeys([])


def test_parse_output_edge_cases():
    parsed = _parse_parallel_ssh_output("[1] t [SUCCESS] h1\n[2] t [SUCCESS] h2\nval\n")
    assert parsed == {"h1": [], "h2": ["val"]}


def test_missing_env(monkeypatch):
    monkeypatch.delenv(sc.ENV_CLUSTER_HOST, raising=False)
    monkeypatch.delenv(sc.ENV_CLUSTER_USER, raising=False)
    with pytest.raises(sc.SSHConfigError):
        sc.load_ssh_config()


def test_bad_path(monkeypatch):
    monkeypatch.setenv(sc.ENV_CLUSTER_HOST, "host")
    monkeypatch.setenv(sc.ENV_CLUSTER_USER, "user")
    monkeypatch.setenv(sc.ENV_CLUSTER_PRIVATE_KEY, "/does/not/exist")
    with pytest.raises(sc.SSHConfigError):
        sc.load_ssh_config()
