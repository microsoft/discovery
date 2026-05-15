from typing import Any, Dict, List, Optional

from ai_infrastructure_mcp.tools.command_wrapper import (
    _validate_hosts,
    run_parallel_ssh,
)


def systemctl(hosts: List[str], args: Optional[List[str]] = None) -> Dict[str, Any]:
    """Run systemctl across multiple hosts via parallel-ssh (hosts required).

    Args:
        args: Optional list of systemctl arguments
        hosts: List of hostnames (required). If None or empty a ValueError is raised.
    """
    if not hosts:
        raise ValueError("hosts list must not be empty")
    _validate_hosts(hosts)
    arg_list = args or []
    return run_parallel_ssh(hosts, ["systemctl", *arg_list])


def journalctl(hosts: List[str], args: Optional[List[str]] = None) -> Dict[str, Any]:
    """Run journalctl across multiple hosts via parallel-ssh (hosts required)."""
    if not hosts:
        raise ValueError("hosts list must not be empty")
    _validate_hosts(hosts)
    arg_list = args or []
    return run_parallel_ssh(hosts, ["journalctl", *arg_list])
