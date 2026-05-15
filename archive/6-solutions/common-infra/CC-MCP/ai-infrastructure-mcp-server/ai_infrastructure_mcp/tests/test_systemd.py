import ai_infrastructure_mcp.tools.systemd as systemd
import pytest

"""Tests for systemd command wrappers (systemctl and journalctl).

These tests follow the same pattern as the slurm tests to ensure consistent behavior.
"""


def test_systemctl_requires_hosts():
    with pytest.raises(ValueError):
        systemd.systemctl([])


def test_systemctl_multi_hosts(monkeypatch):
    """Test systemctl with hosts list uses parallel-ssh."""
    import ai_infrastructure_mcp.tools.command_wrapper as cw

    sample_output = """[1] 12:00:00 [SUCCESS] node1
active
[2] 12:00:00 [SUCCESS] node2
inactive
"""

    def fake_run(cmd: str):
        assert cmd.startswith(
            'parallel-ssh -i -H "node1 node2" "systemctl is-active sshd"'
        )
        return sample_output

    monkeypatch.setattr(cw, "run_login_command", fake_run)
    result = systemd.systemctl(["node1", "node2"], ["is-active", "sshd"])
    assert result["success"] is True
    assert result["summary"]["queried"] == 2
    hosts = {h["host"]: h for h in result["hosts"]}
    assert hosts["node1"]["lines"] == ["active"]
    assert hosts["node2"]["lines"] == ["inactive"]


def test_systemctl_with_args(monkeypatch):
    """Test systemctl with argument list."""

    def fake_run(cmd: str):
        assert cmd.startswith('parallel-ssh -i -H "h1" "systemctl status ssh"')
        return "● ssh.service - OpenBSD Secure Shell server"

    import ai_infrastructure_mcp.tools.command_wrapper as cw

    monkeypatch.setattr(cw, "run_login_command", fake_run)
    result = systemd.systemctl(["h1"], ["status", "ssh"])

    assert result["success"] is True
    assert result["raw_output"] == "● ssh.service - OpenBSD Secure Shell server"


def test_systemctl_error_path(monkeypatch):
    """Test systemctl error handling."""

    def fake_run(cmd: str):
        raise Exception("systemctl command failed")

    import ai_infrastructure_mcp.tools.command_wrapper as cw

    monkeypatch.setattr(cw, "run_login_command", fake_run)
    result = systemd.systemctl(["h1"])
    assert result["success"] is False


def test_systemctl_injection_safety(monkeypatch):
    """Test systemctl command injection protection."""

    def fake_run(cmd: str):
        assert "systemctl status 'ssh; rm -rf /'" in cmd
        return "mock output"

    import ai_infrastructure_mcp.tools.command_wrapper as cw

    monkeypatch.setattr(cw, "run_login_command", fake_run)
    result = systemd.systemctl(["h1"], ["status", "ssh; rm -rf /"])

    assert result["success"] is True


def test_systemctl_list_units(monkeypatch):
    """Test systemctl list-units command."""

    def fake_run(cmd: str):
        assert "systemctl list-units --type=service --state=active" in cmd
        return "UNIT                     LOAD   ACTIVE SUB     DESCRIPTION"

    import ai_infrastructure_mcp.tools.command_wrapper as cw

    monkeypatch.setattr(cw, "run_login_command", fake_run)
    result = systemd.systemctl(
        ["h1"], ["list-units", "--type=service", "--state=active"]
    )

    assert result["success"] is True
    assert (
        result["raw_output"]
        == "UNIT                     LOAD   ACTIVE SUB     DESCRIPTION"
    )


def test_systemctl_is_active(monkeypatch):
    """Test systemctl is-active command."""

    def fake_run(cmd: str):
        assert "systemctl is-active nginx" in cmd
        return "active"

    import ai_infrastructure_mcp.tools.command_wrapper as cw

    monkeypatch.setattr(cw, "run_login_command", fake_run)
    result = systemd.systemctl(["h1"], ["is-active", "nginx"])

    assert result["success"] is True
    assert result["raw_output"] == "active"


def test_systemctl_show_properties(monkeypatch):
    """Test systemctl show command with properties."""

    def fake_run(cmd: str):
        assert "systemctl show mysql --property=ActiveState,SubState" in cmd
        return "ActiveState=active\nSubState=running"

    import ai_infrastructure_mcp.tools.command_wrapper as cw

    monkeypatch.setattr(cw, "run_login_command", fake_run)
    result = systemd.systemctl(
        ["h1"], ["show", "mysql", "--property=ActiveState,SubState"]
    )

    assert result["success"] is True
    assert result["raw_output"] == "ActiveState=active\nSubState=running"


def test_journalctl_requires_hosts():
    with pytest.raises(ValueError):
        systemd.journalctl([])


def test_journalctl_multi_hosts(monkeypatch):
    """Test journalctl multi-host usage."""
    import ai_infrastructure_mcp.tools.command_wrapper as cw

    sample_output = """[1] 12:00:00 [SUCCESS] nodeA
logA1
[2] 12:00:00 [SUCCESS] nodeB
logB1
logB2
"""

    def fake_run(cmd: str):
        assert cmd.startswith(
            'parallel-ssh -i -H "nodeA nodeB" "journalctl -u sshd -n 1"'
        )
        return sample_output

    monkeypatch.setattr(cw, "run_login_command", fake_run)
    result = systemd.journalctl(["nodeA", "nodeB"], ["-u", "sshd", "-n", "1"])
    assert result["success"] is True
    assert result["summary"]["queried"] == 2
    hosts = {h["host"]: h for h in result["hosts"]}
    assert hosts["nodeA"]["lines"] == ["logA1"]
    assert hosts["nodeB"]["lines"] == ["logB1", "logB2"]


def test_journalctl_with_args(monkeypatch):
    """Test journalctl with argument list."""

    def fake_run(cmd: str):
        assert "journalctl -u ssh -n 10" in cmd
        return "mock journalctl ssh logs"

    import ai_infrastructure_mcp.tools.command_wrapper as cw

    monkeypatch.setattr(cw, "run_login_command", fake_run)
    result = systemd.journalctl(["h1"], ["-u", "ssh", "-n", "10"])

    assert result["success"] is True
    assert result["raw_output"] == "mock journalctl ssh logs"


def test_journalctl_error_path(monkeypatch):
    """Test journalctl error handling."""

    def fake_run(cmd: str):
        raise Exception("journalctl command failed")

    import ai_infrastructure_mcp.tools.command_wrapper as cw

    monkeypatch.setattr(cw, "run_login_command", fake_run)
    result = systemd.journalctl(["h1"])
    assert result["success"] is False


def test_journalctl_injection_safety(monkeypatch):
    """Test journalctl command injection protection."""

    def fake_run(cmd: str):
        assert "journalctl -u 'nginx; cat /etc/passwd'" in cmd
        return "mock output"

    import ai_infrastructure_mcp.tools.command_wrapper as cw

    monkeypatch.setattr(cw, "run_login_command", fake_run)
    result = systemd.journalctl(["h1"], ["-u", "nginx; cat /etc/passwd"])

    assert result["success"] is True


def test_journalctl_since_today(monkeypatch):
    """Test journalctl since today."""

    def fake_run(cmd: str):
        assert "journalctl --since today" in cmd
        return "-- Logs begin at..."

    import ai_infrastructure_mcp.tools.command_wrapper as cw

    monkeypatch.setattr(cw, "run_login_command", fake_run)
    result = systemd.journalctl(["h1"], ["--since", "today"])

    assert result["success"] is True
    assert result["raw_output"] == "-- Logs begin at..."


def test_journalctl_follow_unit(monkeypatch):
    """Test journalctl follow with unit."""

    def fake_run(cmd: str):
        assert "journalctl -f -u nginx" in cmd
        return "-- Logs begin at..."

    import ai_infrastructure_mcp.tools.command_wrapper as cw

    monkeypatch.setattr(cw, "run_login_command", fake_run)
    result = systemd.journalctl(["h1"], ["-f", "-u", "nginx"])

    assert result["success"] is True
    assert result["raw_output"] == "-- Logs begin at..."


def test_journalctl_priority_filter(monkeypatch):
    """Test journalctl with priority filter."""

    def fake_run(cmd: str):
        assert "journalctl --priority=err" in cmd
        return "-- Logs begin at..."

    import ai_infrastructure_mcp.tools.command_wrapper as cw

    monkeypatch.setattr(cw, "run_login_command", fake_run)
    result = systemd.journalctl(["h1"], ["--priority=err"])

    assert result["success"] is True
    assert result["raw_output"] == "-- Logs begin at..."


def test_all_systemd_functions_return_correct_structure():
    """Test that all systemd functions return the expected dictionary structure."""
    # Test each function with no arguments (they will fail but return correct structure)
    functions = [lambda: systemd.systemctl(["h1"]), lambda: systemd.journalctl(["h1"])]
    for call in functions:
        result = call()
        assert isinstance(result, dict)
        assert "version" in result


def test_systemctl_complex_arguments(monkeypatch):
    """Test systemctl with complex argument combinations."""

    def fake_run(cmd: str):
        assert "systemctl list-units --type=service --state=failed --no-pager" in cmd
        return "mock complex output"

    import ai_infrastructure_mcp.tools.command_wrapper as cw

    monkeypatch.setattr(cw, "run_login_command", fake_run)
    result = systemd.systemctl(
        ["h1"], ["list-units", "--type=service", "--state=failed", "--no-pager"]
    )

    assert result["success"] is True
    assert result["raw_output"] == "mock complex output"


def test_journalctl_complex_arguments(monkeypatch):
    """Test journalctl with complex argument combinations."""

    def fake_run(cmd: str):
        assert (
            "journalctl -u apache2 --since '2024-01-01 00:00:00' --until '2024-01-31 23:59:59' --no-pager"
            in cmd
        )
        return "mock complex log output"

    import ai_infrastructure_mcp.tools.command_wrapper as cw

    monkeypatch.setattr(cw, "run_login_command", fake_run)
    result = systemd.journalctl(
        ["h1"],
        [
            "-u",
            "apache2",
            "--since",
            "2024-01-01 00:00:00",
            "--until",
            "2024-01-31 23:59:59",
            "--no-pager",
        ],
    )

    assert result["success"] is True
    assert result["raw_output"] == "mock complex log output"


def test_systemctl_empty_argument_list(monkeypatch):
    """Test systemctl with empty argument list."""

    def fake_run(cmd: str):
        assert "systemctl" in cmd
        return "mock output for systemctl"

    import ai_infrastructure_mcp.tools.command_wrapper as cw

    monkeypatch.setattr(cw, "run_login_command", fake_run)
    result = systemd.systemctl(["h1"], [])
    assert result["success"] is True
    assert result["raw_output"] == "mock output for systemctl"


def test_journalctl_empty_argument_list(monkeypatch):
    """Test journalctl with empty argument list."""

    def fake_run(cmd: str):
        assert "journalctl" in cmd
        return "mock output for journalctl"

    import ai_infrastructure_mcp.tools.command_wrapper as cw

    monkeypatch.setattr(cw, "run_login_command", fake_run)
    result = systemd.journalctl(["h1"], [])
    assert result["success"] is True
    assert result["raw_output"] == "mock output for journalctl"


def test_systemctl_arguments_with_spaces(monkeypatch):
    """Test systemctl arguments that contain spaces are properly quoted."""

    def fake_run(cmd: str):
        assert "systemctl show 'my service with spaces' --property=Description" in cmd
        return "Description=My Service"

    import ai_infrastructure_mcp.tools.command_wrapper as cw

    monkeypatch.setattr(cw, "run_login_command", fake_run)
    result = systemd.systemctl(
        ["h1"], ["show", "my service with spaces", "--property=Description"]
    )

    assert result["success"] is True
    assert result["raw_output"] == "Description=My Service"


def test_journalctl_arguments_with_spaces(monkeypatch):
    """Test journalctl arguments that contain spaces are properly quoted."""

    def fake_run(cmd: str):
        assert (
            "journalctl --since '2024-01-01 12:00:00' --until '2024-01-01 13:00:00'"
            in cmd
        )
        return "-- Logs begin at..."

    import ai_infrastructure_mcp.tools.command_wrapper as cw

    monkeypatch.setattr(cw, "run_login_command", fake_run)
    result = systemd.journalctl(
        ["h1"], ["--since", "2024-01-01 12:00:00", "--until", "2024-01-01 13:00:00"]
    )

    assert result["success"] is True
    assert result["raw_output"] == "-- Logs begin at..."


def test_none_args_handling():
    """Test that None args are handled correctly (same as no args)."""
    # This should work without mocking since it will call the actual function
    # which will likely fail but return proper error structure

    with pytest.raises(ValueError):
        systemd.systemctl(None)  # type: ignore
    with pytest.raises(ValueError):
        systemd.journalctl(None)  # type: ignore
