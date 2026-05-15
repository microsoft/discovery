import ai_infrastructure_mcp.tools.command_wrapper as command_wrapper

"""Tests for the shared command wrapper functionality.

This tests the common run_simple_command function that is used by both
slurm and systemd tools.
"""


def test_run_simple_command_no_args(monkeypatch):
    """Test run_simple_command with no arguments."""

    def fake_run(cmd: str):
        assert cmd == "test_command"
        return "mock output"

    monkeypatch.setattr(command_wrapper, "run_login_command", fake_run)
    result = command_wrapper.run_simple_command("test_command")

    assert result["success"] is True
    assert result["raw_output"] == "mock output"
    assert result["command"] == "test_command"
    assert result["version"] == 1
    assert result["error"] is None


def test_run_simple_command_with_args(monkeypatch):
    """Test run_simple_command with argument list."""

    def fake_run(cmd: str):
        assert cmd == "test_command arg1 arg2"
        return "mock output with args"

    monkeypatch.setattr(command_wrapper, "run_login_command", fake_run)
    result = command_wrapper.run_simple_command("test_command", ["arg1", "arg2"])

    assert result["success"] is True
    assert result["raw_output"] == "mock output with args"
    assert result["command"] == "test_command arg1 arg2"


def test_run_simple_command_error_path(monkeypatch):
    """Test run_simple_command error handling."""

    def fake_run(cmd: str):
        raise Exception("Command execution failed")

    monkeypatch.setattr(command_wrapper, "run_login_command", fake_run)
    result = command_wrapper.run_simple_command("test_command")

    assert result["success"] is False
    assert result["error"] == "Command execution failed"
    assert result["raw_output"] == ""
    assert result["version"] == 1


def test_run_simple_command_injection_safety(monkeypatch):
    """Test run_simple_command command injection protection."""

    def fake_run(cmd: str):
        # Verify dangerous characters are properly quoted
        assert cmd == "test_command 'dangerous; rm -rf /'"
        return "mock output"

    monkeypatch.setattr(command_wrapper, "run_login_command", fake_run)
    result = command_wrapper.run_simple_command("test_command", ["dangerous; rm -rf /"])

    assert result["success"] is True


def test_run_simple_command_empty_args(monkeypatch):
    """Test run_simple_command with empty argument list."""

    def fake_run(cmd: str):
        assert cmd == "test_command"
        return "mock output"

    monkeypatch.setattr(command_wrapper, "run_login_command", fake_run)
    result = command_wrapper.run_simple_command("test_command", [])

    assert result["success"] is True
    assert result["command"] == "test_command"


def test_run_simple_command_none_args(monkeypatch):
    """Test run_simple_command with None arguments."""

    def fake_run(cmd: str):
        assert cmd == "test_command"
        return "mock output"

    monkeypatch.setattr(command_wrapper, "run_login_command", fake_run)
    result = command_wrapper.run_simple_command("test_command", None)

    assert result["success"] is True
    assert result["command"] == "test_command"


def test_run_simple_command_complex_args(monkeypatch):
    """Test run_simple_command with complex arguments."""

    def fake_run(cmd: str):
        assert cmd == "test_command --option=value 'arg with spaces' --flag"
        return "complex output"

    monkeypatch.setattr(command_wrapper, "run_login_command", fake_run)
    result = command_wrapper.run_simple_command(
        "test_command", ["--option=value", "arg with spaces", "--flag"]
    )

    assert result["success"] is True
    assert result["raw_output"] == "complex output"


def test_run_simple_command_special_characters(monkeypatch):
    """Test run_simple_command with various special characters."""

    def fake_run(cmd: str):
        # Each argument should be individually quoted
        assert (
            cmd
            == "test_command 'arg|with|pipes' 'arg>with>redirects' 'arg&with&ampersands'"
        )
        return "special output"

    monkeypatch.setattr(command_wrapper, "run_login_command", fake_run)
    result = command_wrapper.run_simple_command(
        "test_command", ["arg|with|pipes", "arg>with>redirects", "arg&with&ampersands"]
    )

    assert result["success"] is True
    assert result["raw_output"] == "special output"


def test_run_simple_command_unicode(monkeypatch):
    """Test run_simple_command with unicode characters."""

    def fake_run(cmd: str):
        assert cmd == "test_command 'unicode测试' 'émojis😀'"
        return "unicode output with 测试 and 😀"

    monkeypatch.setattr(command_wrapper, "run_login_command", fake_run)
    result = command_wrapper.run_simple_command(
        "test_command", ["unicode测试", "émojis😀"]
    )

    assert result["success"] is True
    assert "测试" in result["raw_output"]
    assert "😀" in result["raw_output"]
