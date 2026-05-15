import pytest
from ai_infrastructure_mcp.tools.azure_vm import get_physical_hostnames, get_vmss_id


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


def test_get_physical_hostnames_multi(monkeypatch):
    from ai_infrastructure_mcp import ssh_config as mod

    sample_output = """[1] 12:00:00 [SUCCESS] vmA
PHYS_HOST_A
[2] 12:00:00 [SUCCESS] vmB
PHYS_HOST_B
[3] 12:00:00 [SUCCESS] vmC
"""
    dummy_client = DummyClient(
        expected_fragment='parallel-ssh -i -H "vmA vmB vmC"',
        output=sample_output,
    )
    monkeypatch.setattr(mod, "get_ssh_client", lambda: dummy_client)
    result = get_physical_hostnames(["vmA", "vmB", "vmC"])
    assert result["version"] == 1
    assert "timestamp" in result
    hosts = {h["host"]: h for h in result["hosts"]}
    assert hosts["vmA"]["physical_hostname"] == "PHYS_HOST_A"
    assert hosts["vmB"]["physical_hostname"] == "PHYS_HOST_B"
    # vmC produced no line -> empty string
    assert hosts["vmC"]["physical_hostname"] == ""
    assert result["summary"]["queried"] == 3
    assert dummy_client.closed


def test_get_physical_hostnames_with_permission_error(monkeypatch):
    """Test handling of permission errors in the command output."""
    from ai_infrastructure_mcp import ssh_config as mod

    sample_output = """[1] 12:00:00 [SUCCESS] vmA
tr: /var/lib/hyperv/.kvp_pool_3: Permission denied
[2] 12:00:00 [SUCCESS] vmB
PHYS_HOST_B
"""
    dummy_client = DummyClient(
        expected_fragment='parallel-ssh -i -H "vmA vmB"',
        output=sample_output,
    )
    monkeypatch.setattr(mod, "get_ssh_client", lambda: dummy_client)
    result = get_physical_hostnames(["vmA", "vmB"])
    hosts = {h["host"]: h for h in result["hosts"]}
    # vmA should have empty physical_hostname and an error field
    assert hosts["vmA"]["physical_hostname"] == ""
    assert "error" in hosts["vmA"]
    assert "permission denied" in hosts["vmA"]["error"].lower()
    # vmB should work normally
    assert hosts["vmB"]["physical_hostname"] == "PHYS_HOST_B"
    assert "error" not in hosts["vmB"]


def test_get_physical_hostnames_ssh_exception(monkeypatch):
    """Test handling of SSH connection failures."""
    from ai_infrastructure_mcp import ssh_config as mod

    def failing_client():
        raise Exception("SSH connection failed")

    monkeypatch.setattr(mod, "get_ssh_client", failing_client)
    result = get_physical_hostnames(["vmA"])
    assert result["version"] == 1
    assert "error" in result["summary"]
    assert len(result["hosts"]) == 1
    assert result["hosts"][0]["host"] == "vmA"
    assert result["hosts"][0]["physical_hostname"] == ""
    assert "error" in result["hosts"][0]


def test_get_physical_hostnames_empty_hosts():
    with pytest.raises(ValueError):
        get_physical_hostnames([])


def test_get_vmss_id_multi(monkeypatch):
    """Test get_vmss_id with multiple hosts returning VMSS IDs."""
    from ai_infrastructure_mcp import ssh_config as mod

    sample_output = """[1] 12:00:00 [SUCCESS] vmA
login-sinvqvly6zhmb_0
[2] 12:00:00 [SUCCESS] vmB
compute-abc123_5
[3] 12:00:00 [SUCCESS] vmC
"""
    dummy_client = DummyClient(
        expected_fragment='parallel-ssh -i -H "vmA vmB vmC"',
        output=sample_output,
    )
    monkeypatch.setattr(mod, "get_ssh_client", lambda: dummy_client)
    result = get_vmss_id(["vmA", "vmB", "vmC"])
    assert result["version"] == 1
    assert "timestamp" in result
    hosts = {h["host"]: h for h in result["hosts"]}
    assert hosts["vmA"]["vmss_id"] == "login-sinvqvly6zhmb_0"
    assert hosts["vmB"]["vmss_id"] == "compute-abc123_5"
    # vmC produced no line -> empty string
    assert hosts["vmC"]["vmss_id"] == ""
    assert result["summary"]["queried"] == 3
    assert dummy_client.closed


def test_get_vmss_id_with_curl_error(monkeypatch):
    """Test handling of curl errors in the command output."""
    from ai_infrastructure_mcp import ssh_config as mod

    sample_output = """[1] 12:00:00 [SUCCESS] vmA
curl: (7) Failed to connect to 169.254.169.254
[2] 12:00:00 [SUCCESS] vmB
compute-abc123_1
"""
    dummy_client = DummyClient(
        expected_fragment='parallel-ssh -i -H "vmA vmB"',
        output=sample_output,
    )
    monkeypatch.setattr(mod, "get_ssh_client", lambda: dummy_client)
    result = get_vmss_id(["vmA", "vmB"])
    hosts = {h["host"]: h for h in result["hosts"]}
    # vmA should have empty vmss_id and an error field
    assert hosts["vmA"]["vmss_id"] == ""
    assert "error" in hosts["vmA"]
    assert "curl:" in hosts["vmA"]["error"]
    # vmB should work normally
    assert hosts["vmB"]["vmss_id"] == "compute-abc123_1"
    assert "error" not in hosts["vmB"]


def test_get_vmss_id_with_jq_null(monkeypatch):
    """Test handling of jq returning null (metadata field not found)."""
    from ai_infrastructure_mcp import ssh_config as mod

    sample_output = """[1] 12:00:00 [SUCCESS] vmA
null
[2] 12:00:00 [SUCCESS] vmB
compute-def456_2
"""
    dummy_client = DummyClient(
        expected_fragment='parallel-ssh -i -H "vmA vmB"',
        output=sample_output,
    )
    monkeypatch.setattr(mod, "get_ssh_client", lambda: dummy_client)
    result = get_vmss_id(["vmA", "vmB"])
    hosts = {h["host"]: h for h in result["hosts"]}
    # vmA should have empty vmss_id and an error field due to null result
    assert hosts["vmA"]["vmss_id"] == ""
    assert "error" in hosts["vmA"]
    assert "Failed to retrieve VMSS ID" in hosts["vmA"]["error"]
    # vmB should work normally
    assert hosts["vmB"]["vmss_id"] == "compute-def456_2"
    assert "error" not in hosts["vmB"]


def test_get_vmss_id_ssh_exception(monkeypatch):
    """Test handling of SSH connection failures for get_vmss_id."""
    from ai_infrastructure_mcp import ssh_config as mod

    def failing_client():
        raise Exception("SSH connection failed")

    monkeypatch.setattr(mod, "get_ssh_client", failing_client)
    result = get_vmss_id(["vmA"])
    assert result["version"] == 1
    assert "error" in result["summary"]
    assert len(result["hosts"]) == 1
    assert result["hosts"][0]["host"] == "vmA"
    assert result["hosts"][0]["vmss_id"] == ""
    assert "error" in result["hosts"][0]


def test_get_vmss_id_empty_hosts():
    """Test that get_vmss_id raises ValueError for empty host list."""
    with pytest.raises(ValueError):
        get_vmss_id([])
