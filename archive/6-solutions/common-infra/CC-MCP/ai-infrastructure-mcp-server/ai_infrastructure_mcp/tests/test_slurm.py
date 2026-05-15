import ai_infrastructure_mcp.tools.command_wrapper as command_wrapper
import ai_infrastructure_mcp.tools.slurm as slurm

"""Minimal tests for raw-args Slurm wrappers.

We keep only core behavior checks:
- No-arg invocation
- Passing argument list
- Error path
- Injection safety (argument with metacharacters remains single token)
"""


def test_sacct_no_args(monkeypatch):
    """Test sacct with no arguments."""

    def fake_run(cmd: str):
        assert cmd == "sacct"
        return "mock sacct output"

    monkeypatch.setattr(command_wrapper, "run_login_command", fake_run)
    result = slurm.sacct()

    assert result["success"] is True
    assert result["raw_output"] == "mock sacct output"
    assert result["command"] == "sacct"


def test_sacct_with_args(monkeypatch):
    """Test sacct with argument list (auto endtime)."""

    def fake_run(cmd: str):
        # --endtime=now should be auto-appended
        assert cmd == "sacct --user alice --state FAILED --endtime=now"
        return "mock sacct output"

    monkeypatch.setattr(command_wrapper, "run_login_command", fake_run)
    result = slurm.sacct(["--user", "alice", "--state", "FAILED"])

    assert result["success"] is True
    assert result["raw_output"] == "mock sacct output"


def test_sacct_error_path(monkeypatch):
    """Test sacct error handling."""

    def fake_run(cmd: str):
        raise Exception("Command failed")

    monkeypatch.setattr(command_wrapper, "run_login_command", fake_run)
    result = slurm.sacct()

    assert result["success"] is False
    assert result["error"] == "Command failed"
    assert result["raw_output"] == ""


def test_sacct_injection_safety(monkeypatch):
    """Test sacct command injection protection."""

    def fake_run(cmd: str):
        # Verify dangerous characters are properly quoted
        assert cmd == "sacct --user 'alice; rm -rf /'"
        return "mock output"

    monkeypatch.setattr(command_wrapper, "run_login_command", fake_run)
    result = slurm.sacct(["--user", "alice; rm -rf /"])

    assert result["success"] is True


def test_squeue_no_args(monkeypatch):
    """Test squeue with no arguments."""

    def fake_run(cmd: str):
        assert cmd == "squeue"
        return "mock squeue output"

    monkeypatch.setattr(command_wrapper, "run_login_command", fake_run)
    result = slurm.squeue()

    assert result["success"] is True
    assert result["raw_output"] == "mock squeue output"
    assert result["command"] == "squeue"


def test_squeue_with_args(monkeypatch):
    """Test squeue with argument list."""

    def fake_run(cmd: str):
        assert cmd == "squeue --user alice --states RUNNING"
        return "mock squeue output"

    monkeypatch.setattr(command_wrapper, "run_login_command", fake_run)
    result = slurm.squeue(["--user", "alice", "--states", "RUNNING"])

    assert result["success"] is True
    assert result["raw_output"] == "mock squeue output"


def test_squeue_error_path(monkeypatch):
    """Test squeue error handling."""

    def fake_run(cmd: str):
        raise Exception("squeue command failed")

    monkeypatch.setattr(command_wrapper, "run_login_command", fake_run)
    result = slurm.squeue()

    assert result["success"] is False
    assert result["error"] == "squeue command failed"
    assert result["raw_output"] == ""


def test_squeue_injection_safety(monkeypatch):
    """Test squeue command injection protection."""

    def fake_run(cmd: str):
        # Verify dangerous characters are properly quoted
        assert cmd == "squeue --format '%i; cat /etc/passwd'"
        return "mock output"

    monkeypatch.setattr(command_wrapper, "run_login_command", fake_run)
    result = slurm.squeue(["--format", "%i; cat /etc/passwd"])

    assert result["success"] is True


def test_sinfo_no_args(monkeypatch):
    """Test sinfo with no arguments."""

    def fake_run(cmd: str):
        assert cmd == "sinfo"
        return "mock sinfo output"

    monkeypatch.setattr(command_wrapper, "run_login_command", fake_run)
    result = slurm.sinfo()

    assert result["success"] is True
    assert result["raw_output"] == "mock sinfo output"
    assert result["command"] == "sinfo"


def test_sinfo_with_args(monkeypatch):
    """Test sinfo with argument list."""

    def fake_run(cmd: str):
        assert cmd == "sinfo --partition gpu --format '%P %a %l %D'"
        return "mock sinfo output"

    monkeypatch.setattr(command_wrapper, "run_login_command", fake_run)
    result = slurm.sinfo(["--partition", "gpu", "--format", "%P %a %l %D"])

    assert result["success"] is True
    assert result["raw_output"] == "mock sinfo output"


def test_sinfo_error_path(monkeypatch):
    """Test sinfo error handling."""

    def fake_run(cmd: str):
        raise Exception("sinfo command failed")

    monkeypatch.setattr(command_wrapper, "run_login_command", fake_run)
    result = slurm.sinfo()

    assert result["success"] is False
    assert result["error"] == "sinfo command failed"
    assert result["raw_output"] == ""


def test_sinfo_injection_safety(monkeypatch):
    """Test sinfo command injection protection."""

    def fake_run(cmd: str):
        # Verify dangerous characters are properly quoted
        assert cmd == "sinfo --nodes 'node1 && rm -rf /'"
        return "mock output"

    monkeypatch.setattr(command_wrapper, "run_login_command", fake_run)
    result = slurm.sinfo(["--nodes", "node1 && rm -rf /"])

    assert result["success"] is True


def test_scontrol_no_args(monkeypatch):
    """Test scontrol with no arguments."""

    def fake_run(cmd: str):
        assert cmd == "scontrol"
        return "mock scontrol output"

    monkeypatch.setattr(command_wrapper, "run_login_command", fake_run)
    result = slurm.scontrol()

    assert result["success"] is True
    assert result["raw_output"] == "mock scontrol output"
    assert result["command"] == "scontrol"


def test_scontrol_with_args(monkeypatch):
    """Test scontrol with argument list."""

    def fake_run(cmd: str):
        assert cmd == "scontrol show job 123"
        return "mock scontrol output"

    monkeypatch.setattr(command_wrapper, "run_login_command", fake_run)
    result = slurm.scontrol(["show", "job", "123"])

    assert result["success"] is True
    assert result["raw_output"] == "mock scontrol output"


def test_scontrol_ping(monkeypatch):
    """Test scontrol ping command."""

    def fake_run(cmd: str):
        assert cmd == "scontrol ping"
        return "Slurmctld(primary) at host1 is UP"

    monkeypatch.setattr(command_wrapper, "run_login_command", fake_run)
    result = slurm.scontrol(["ping"])

    assert result["success"] is True
    assert result["raw_output"] == "Slurmctld(primary) at host1 is UP"


def test_scontrol_error_path(monkeypatch):
    """Test scontrol error handling."""

    def fake_run(cmd: str):
        raise Exception("scontrol command failed")

    monkeypatch.setattr(command_wrapper, "run_login_command", fake_run)
    result = slurm.scontrol()

    assert result["success"] is False
    assert result["error"] == "scontrol command failed"
    assert result["raw_output"] == ""


def test_scontrol_injection_safety(monkeypatch):
    """Test scontrol command injection protection."""

    def fake_run(cmd: str):
        # Verify dangerous characters are properly quoted
        assert cmd == "scontrol update 'JobId=123; killall slurmctld'"
        return "mock output"

    monkeypatch.setattr(command_wrapper, "run_login_command", fake_run)
    result = slurm.scontrol(["update", "JobId=123; killall slurmctld"])

    assert result["success"] is True


def test_sreport_no_args(monkeypatch):
    """Test sreport with no arguments."""

    def fake_run(cmd: str):
        assert cmd == "sreport"
        return "mock sreport output"

    monkeypatch.setattr(command_wrapper, "run_login_command", fake_run)
    result = slurm.sreport()

    assert result["success"] is True
    assert result["raw_output"] == "mock sreport output"
    assert result["command"] == "sreport"


def test_sreport_with_args(monkeypatch):
    """Test sreport with argument list."""

    def fake_run(cmd: str):
        assert cmd == "sreport cluster Utilization Start=now-7days"
        return "mock sreport output"

    monkeypatch.setattr(command_wrapper, "run_login_command", fake_run)
    result = slurm.sreport(["cluster", "Utilization", "Start=now-7days"])

    assert result["success"] is True
    assert result["raw_output"] == "mock sreport output"


def test_sreport_user_top_usage(monkeypatch):
    """Test sreport user TopUsage command."""

    def fake_run(cmd: str):
        assert cmd == "sreport user TopUsage Start=now-30days"
        return "Top Usage report..."

    monkeypatch.setattr(command_wrapper, "run_login_command", fake_run)
    result = slurm.sreport(["user", "TopUsage", "Start=now-30days"])

    assert result["success"] is True
    assert result["raw_output"] == "Top Usage report..."


def test_sreport_error_path(monkeypatch):
    """Test sreport error handling."""

    def fake_run(cmd: str):
        raise Exception("sreport command failed")

    monkeypatch.setattr(command_wrapper, "run_login_command", fake_run)
    result = slurm.sreport()

    assert result["success"] is False
    assert result["error"] == "sreport command failed"
    assert result["raw_output"] == ""


def test_sreport_injection_safety(monkeypatch):
    """Test sreport command injection protection."""

    def fake_run(cmd: str):
        # Verify dangerous characters are properly quoted
        assert cmd == "sreport cluster 'Utilization; rm -rf /'"
        return "mock output"

    monkeypatch.setattr(command_wrapper, "run_login_command", fake_run)
    result = slurm.sreport(["cluster", "Utilization; rm -rf /"])

    assert result["success"] is True


def test_all_functions_return_correct_structure():
    """Test that all functions return the expected dictionary structure."""
    # We'll test the structure without mocking to ensure the error path works

    # Test each function with no arguments (they will fail but return correct structure)
    functions = [slurm.sacct, slurm.squeue, slurm.sinfo, slurm.scontrol, slurm.sreport]

    for func in functions:
        result = func()

        # All should return a dictionary with these keys
        assert isinstance(result, dict)
        assert "version" in result
        assert "success" in result
        assert "command" in result
        assert "raw_output" in result
        assert "error" in result

        # Version should be 1
        assert result["version"] == 1

        # Success should be boolean
        assert isinstance(result["success"], bool)


def test_complex_argument_combinations(monkeypatch):
    """Test complex argument combinations with multiple flags."""

    def fake_run(cmd: str):
        # Should properly quote and join all arguments
        expected = "squeue --user alice --states RUNNING,PENDING --format '%i %t %j %u %T %M %l %D %R'"
        assert cmd == expected
        return "mock complex output"

    monkeypatch.setattr(command_wrapper, "run_login_command", fake_run)
    result = slurm.squeue(
        [
            "--user",
            "alice",
            "--states",
            "RUNNING,PENDING",
            "--format",
            "%i %t %j %u %T %M %l %D %R",
        ]
    )

    assert result["success"] is True
    assert result["raw_output"] == "mock complex output"


def test_special_characters_in_arguments(monkeypatch):
    """Test arguments containing spaces and special characters are properly handled."""

    def fake_run(cmd: str):
        # Should quote arguments with spaces and special characters
        assert cmd == "sacct --format JobID,JobName%30,State,ExitCode"
        return "mock output"

    monkeypatch.setattr(command_wrapper, "run_login_command", fake_run)
    result = slurm.sacct(["--format", "JobID,JobName%30,State,ExitCode"])

    assert result["success"] is True


def test_empty_argument_list(monkeypatch):
    """Test all functions with empty argument lists."""

    def fake_run(cmd: str):
        return f"mock output for {cmd}"

    monkeypatch.setattr(command_wrapper, "run_login_command", fake_run)

    # Test each function with empty list (should be same as no args)
    functions = [
        (slurm.sacct, "sacct"),
        (slurm.squeue, "squeue"),
        (slurm.sinfo, "sinfo"),
        (slurm.scontrol, "scontrol"),
        (slurm.sreport, "sreport"),
    ]

    for func, expected_cmd in functions:
        result = func([])
        assert result["success"] is True
        assert result["command"] == expected_cmd
        assert result["raw_output"] == f"mock output for {expected_cmd}"


def test_single_arguments(monkeypatch):
    """Test functions with single arguments."""

    def fake_run(cmd: str):
        return f"output: {cmd}"

    monkeypatch.setattr(command_wrapper, "run_login_command", fake_run)

    # Test single argument for each function
    test_cases = [
        (slurm.sacct, ["--help"], "sacct --help"),
        (slurm.squeue, ["--version"], "squeue --version"),
        (slurm.sinfo, ["--help"], "sinfo --help"),
        (slurm.scontrol, ["ping"], "scontrol ping"),
        (slurm.sreport, ["--help"], "sreport --help"),
    ]

    for func, args, expected_cmd in test_cases:
        result = func(args)
        assert result["success"] is True
        assert result["command"] == expected_cmd


def test_arguments_with_spaces(monkeypatch):
    """Test arguments that contain spaces are properly quoted."""

    def fake_run(cmd: str):
        assert cmd == "scontrol update 'JobId=123 Comment=my test job'"
        return "JobId=123 updated"

    monkeypatch.setattr(command_wrapper, "run_login_command", fake_run)
    result = slurm.scontrol(["update", "JobId=123 Comment=my test job"])

    assert result["success"] is True
    assert result["raw_output"] == "JobId=123 updated"


def test_unicode_characters(monkeypatch):
    """Test handling of unicode characters in arguments (auto endtime)."""

    def fake_run(cmd: str):
        assert (
            cmd
            == "sacct --format JobID,JobName,Comment --state COMPLETED --endtime=now"
        )
        return "JobID|JobName|Comment\n123|test_job|测试作业"

    monkeypatch.setattr(command_wrapper, "run_login_command", fake_run)
    result = slurm.sacct(["--format", "JobID,JobName,Comment", "--state", "COMPLETED"])

    assert result["success"] is True
    assert "测试作业" in result["raw_output"]


def test_sacct_auto_endtime_when_state_without_end(monkeypatch):
    """If --state is set without --endtime/-E, wrapper should append --endtime=now."""

    def fake_run(cmd: str):
        # Order: sacct --state COMPLETED --endtime=now
        assert (
            cmd == "sacct --state COMPLETED --endtime=now"
            or cmd == "sacct --state COMPLETED --endtime=now"
        )
        return "mock output"

    monkeypatch.setattr(command_wrapper, "run_login_command", fake_run)
    result = slurm.sacct(["--state", "COMPLETED"])
    assert result["success"] is True

    # Also test combined form --state=RUNNING
    def fake_run2(cmd: str):
        assert cmd == "sacct --state=RUNNING --endtime=now"
        return "mock output2"

    monkeypatch.setattr(command_wrapper, "run_login_command", fake_run2)
    result2 = slurm.sacct(["--state=RUNNING"])
    assert result2["success"] is True

    # When endtime explicitly provided, should not add
    def fake_run3(cmd: str):
        assert cmd == "sacct --state FAILED --endtime 2024-01-01T12:00:00"
        return "mock output3"

    monkeypatch.setattr(command_wrapper, "run_login_command", fake_run3)
    result3 = slurm.sacct(["--state", "FAILED", "--endtime", "2024-01-01T12:00:00"])
    assert result3["success"] is True


def test_multiple_equal_signs(monkeypatch):
    """Test arguments with multiple equal signs."""

    def fake_run(cmd: str):
        assert (
            cmd
            == "sreport cluster Utilization Start=2024-01-01T00:00:00 End=2024-01-31T23:59:59"
        )
        return "Cluster utilization report"

    monkeypatch.setattr(command_wrapper, "run_login_command", fake_run)
    result = slurm.sreport(
        [
            "cluster",
            "Utilization",
            "Start=2024-01-01T00:00:00",
            "End=2024-01-31T23:59:59",
        ]
    )

    assert result["success"] is True


def test_command_with_pipes_and_redirects(monkeypatch):
    """Test that pipe and redirect characters in arguments are properly escaped."""

    def fake_run(cmd: str):
        # The dangerous input should be escaped as a single argument
        assert cmd == "squeue --format '%i | %j > /tmp/output'"
        return "mock output"

    monkeypatch.setattr(command_wrapper, "run_login_command", fake_run)
    result = slurm.squeue(["--format", "%i | %j > /tmp/output"])

    assert result["success"] is True


def test_very_long_arguments(monkeypatch):
    """Test handling of very long argument strings."""
    long_format = ",".join([f"field{i}" for i in range(50)])

    def fake_run(cmd: str):
        assert cmd.startswith("sacct --format")
        assert long_format in cmd
        return "long output"

    monkeypatch.setattr(command_wrapper, "run_login_command", fake_run)
    result = slurm.sacct(["--format", long_format])

    assert result["success"] is True
    assert result["raw_output"] == "long output"


def test_none_args_handling():
    """Test that None args are handled correctly (same as no args)."""
    # This should work without mocking since it will call the actual function
    # which will likely fail but return proper error structure

    functions = [
        slurm.sacct,
        slurm.squeue,
        slurm.sinfo,
        slurm.scontrol,
        slurm.sreport,
        slurm.sbatch,
    ]

    for func in functions:
        result = func(None)
        assert isinstance(result, dict)
        assert "success" in result
        assert "version" in result
        assert result["version"] == 1
