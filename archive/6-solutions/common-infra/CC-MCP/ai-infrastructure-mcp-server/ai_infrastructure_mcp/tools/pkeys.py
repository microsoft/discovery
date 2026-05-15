from datetime import datetime, timezone
from typing import Any, Dict, List

from ai_infrastructure_mcp.ssh_config import run_login_command

from .command_wrapper import (
    _validate_hosts,
    build_parallel_ssh_command,
    parse_parallel_ssh_output,
)

_INNER_PKEY_CMD = (
    "cat /sys/class/infiniband/mlx5_*/ports/1/pkeys/* 2>/dev/null | grep 0x8 | sort -u"
)


def get_infiniband_pkeys(hosts: List[str]) -> Dict[str, Any]:
    """Retrieve InfiniBand partition keys (matching 0x8) across multiple hosts via parallel-ssh."""
    _validate_hosts(hosts)
    full_cmd = build_parallel_ssh_command(hosts, _INNER_PKEY_CMD)
    raw = run_login_command(full_cmd)
    parsed = parse_parallel_ssh_output(raw)
    host_entries = []
    for h, pks in parsed.items():
        host_entries.append(
            {
                "host": h,
                "pkeys": sorted({pk.lower() for pk in pks}),
            }
        )
    ts = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return {
        "version": 1,
        "timestamp": ts,
        "hosts": host_entries,
        "summary": {"queried": len(parsed)},
    }


def _parse_parallel_ssh_output(output: str) -> Dict[str, List[str]]:
    return parse_parallel_ssh_output(output)
