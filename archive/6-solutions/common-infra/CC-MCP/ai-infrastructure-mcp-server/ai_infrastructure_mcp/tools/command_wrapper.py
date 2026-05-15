import re
import shlex
from typing import Any, Dict, List, Optional

from ai_infrastructure_mcp.ssh_config import run_login_command

_HOST_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def _validate_hosts(hosts: List[str]) -> List[str]:
    if not hosts:
        raise ValueError("hosts list must not be empty")
    cleaned = []
    for h in hosts:
        if not _HOST_RE.match(h):
            raise ValueError(f"invalid host name: {h}")
        cleaned.append(h)
    return cleaned


def parse_parallel_ssh_output(output: str) -> Dict[str, List[str]]:
    """Parse output from `parallel-ssh -i` collecting per-host lines.

    Format expected (subset):
        [1] 12:00:00 [SUCCESS] hostA
        line1
        line2
        [2] 12:00:00 [SUCCESS] hostB

    Returns mapping host -> list of (non-empty) lines.
    """
    result: Dict[str, List[str]] = {}
    current_host: Optional[str] = None
    for line in output.splitlines():
        ls = line.strip()
        if not ls:
            continue
        if ls.startswith("[") and "SUCCESS" in ls:
            parts = ls.split()
            if parts:
                host = parts[-1]
                current_host = host
                result.setdefault(host, [])
            continue
        if current_host and not ls.startswith("["):
            result[current_host].append(ls)
    return result


def build_parallel_ssh_command(hosts: List[str], inner_command: str) -> str:
    """Build a safe parallel-ssh invocation string.

    Hosts are validated against a conservative regex. The inner command is assumed
    to be a trusted string (callers should not pass user input that includes shell
    metacharacters unless it is from a constant).
    """
    safe_hosts = _validate_hosts(hosts)
    host_str = " ".join(safe_hosts)
    # Escape any embedded double quotes in inner command
    inner_escaped = inner_command.replace('"', '\\"')
    return f'parallel-ssh -i -H "{host_str}" "{inner_escaped}"'


def run_parallel_ssh(hosts: List[str], cmd_parts: List[str]) -> Dict[str, Any]:
    """Execute a simple command (no pipelines) across hosts via parallel-ssh.

    cmd_parts: e.g., ['systemctl', 'status', 'ssh']
    Each element is shell-quoted and combined; no additional interpretation is allowed.
    """
    if not cmd_parts:
        raise ValueError("cmd_parts must not be empty")
    for part in cmd_parts:
        if any(c in part for c in ["\n", "\r"]):
            raise ValueError("invalid newline in argument")
    inner_cmd = " ".join(shlex.quote(p) for p in cmd_parts)
    full_cmd = build_parallel_ssh_command(hosts, inner_cmd)
    try:
        raw = run_login_command(full_cmd)
        parsed = parse_parallel_ssh_output(raw)
        host_entries = [{"host": h, "lines": v} for h, v in parsed.items()]
        return {
            "version": 1,
            "success": True,
            "command": full_cmd,
            "hosts": host_entries,
            "raw_output": raw,
            "error": None,
            "summary": {"queried": len(parsed)},
        }
    except Exception as e:
        return {
            "version": 1,
            "success": False,
            "command": full_cmd,
            "hosts": [],
            "raw_output": "",
            "error": str(e),
            "summary": {"queried": 0},
        }


def run_simple_command(
    command: str, args: Optional[List[str]] = None
) -> Dict[str, Any]:
    """Helper to run a command with a raw list of args.

    Args:
        command: The base command to run (e.g., 'sacct', 'systemctl')
        args: Optional list of command-line arguments

    Returns:
        Standardized dict with version, success, command, raw_output, error fields
    """
    cmd_parts = [command]
    if args:
        # treat each element as a literal argument; caller supplies flags & values already split
        cmd_parts.extend(args)
    cmd = " ".join(shlex.quote(p) for p in cmd_parts)
    try:
        raw = run_login_command(cmd)
        return {
            "version": 1,
            "success": True,
            "command": cmd,
            "raw_output": raw,
            "error": None,
        }
    except Exception as e:
        return {
            "version": 1,
            "success": False,
            "command": cmd,
            "raw_output": "",
            "error": str(e),
        }
