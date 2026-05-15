from datetime import datetime, timezone
from typing import Any, Dict, List

from ai_infrastructure_mcp.ssh_config import run_login_command

from .command_wrapper import (
    _validate_hosts,
    build_parallel_ssh_command,
    parse_parallel_ssh_output,
)

# Command to extract the physical hostname for an Azure VM.
# Made robust to handle edge cases:
# - Check if file exists first
# - Simplified approach using grep and cut instead of complex sed
_INNER_PHYSICAL_HOST_CMD = 'test -f /var/lib/hyperv/.kvp_pool_3 && tr -d "\\0" < /var/lib/hyperv/.kvp_pool_3 | grep -o "Qualified[^V]*VirtualMachineDynamic" | sed "s/Qualified//;s/VirtualMachineDynamic//" | head -1 || echo ""'

# Command to extract the VMSS ID from Azure Instance Metadata Service
# Uses curl to query the metadata endpoint and jq to extract the compute.name field
_INNER_VMSS_ID_CMD = 'curl -H "Metadata: true" "http://169.254.169.254/metadata/instance?api-version=2025-04-07&format=json" 2>/dev/null | jq -r .compute.name 2>/dev/null || echo ""'


def get_physical_hostnames(hosts: List[str]) -> Dict[str, Any]:
    """Retrieve the Azure physical hostnames for the given list of VM hosts via parallel-ssh.

    Reads the Hyper-V key/value pair (KVP) pool file that Azure populates inside the guest and
    extracts the 'Qualified*VirtualMachineDynamic' embedded physical host qualifier substring.

    Args:
        hosts: List of VM hostnames to query (must be non-empty, validated)

    Returns:
        Dict with version, timestamp, hosts[], summary similar to pkeys tool.
        Each host entry: { "host": <name>, "physical_hostname": <string or empty>, "error": <optional error> }
    """
    _validate_hosts(hosts)
    full_cmd = build_parallel_ssh_command(hosts, _INNER_PHYSICAL_HOST_CMD)

    try:
        raw = run_login_command(full_cmd)
        parsed = parse_parallel_ssh_output(raw)
        host_entries = []

        for h, lines in parsed.items():
            # Expect either one (possibly empty) line; join just in case multiple lines produced
            physical = "".join(lines).strip()
            entry = {
                "host": h,
                "physical_hostname": physical,
            }
            # If the result contains error indicators, note them
            if (
                "permission denied" in physical.lower()
                or physical.startswith("test:")
                or physical.startswith("tr:")
            ):
                entry["error"] = physical
                entry["physical_hostname"] = ""
            host_entries.append(entry)

        ts = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        return {
            "version": 1,
            "timestamp": ts,
            "hosts": host_entries,
            "summary": {"queried": len(parsed)},
        }
    except Exception as e:
        # If the command fails entirely, return error info
        ts = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        return {
            "version": 1,
            "timestamp": ts,
            "hosts": [
                {"host": h, "physical_hostname": "", "error": str(e)} for h in hosts
            ],
            "summary": {"queried": 0, "error": str(e)},
        }


def get_vmss_id(hosts: List[str]) -> Dict[str, Any]:
    """Retrieve the Azure VMSS (Virtual Machine Scale Set) ID for the given list of VM hosts via parallel-ssh.

    Queries the Azure Instance Metadata Service endpoint to extract the compute.name field,
    which contains the VMSS instance name that can be used to correlate with Azure Monitor data.

    Args:
        hosts: List of VM hostnames to query (must be non-empty, validated)

    Returns:
        Dict with version, timestamp, hosts[], summary similar to pkeys tool.
        Each host entry: { "host": <name>, "vmss_id": <string or empty>, "error": <optional error> }
    """
    _validate_hosts(hosts)
    full_cmd = build_parallel_ssh_command(hosts, _INNER_VMSS_ID_CMD)

    try:
        raw = run_login_command(full_cmd)
        parsed = parse_parallel_ssh_output(raw)
        host_entries = []

        for h, lines in parsed.items():
            # Expect either one (possibly empty) line; join just in case multiple lines produced
            vmss_id = "".join(lines).strip()
            entry = {
                "host": h,
                "vmss_id": vmss_id,
            }
            # If the result contains error indicators, note them
            if (
                "curl:" in vmss_id.lower()
                or "jq:" in vmss_id.lower()
                or vmss_id == "null"
            ):
                entry["error"] = (
                    vmss_id
                    if vmss_id != "null"
                    else "Failed to retrieve VMSS ID from metadata service"
                )
                entry["vmss_id"] = ""
            host_entries.append(entry)

        ts = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        return {
            "version": 1,
            "timestamp": ts,
            "hosts": host_entries,
            "summary": {"queried": len(parsed)},
        }
    except Exception as e:
        # If the command fails entirely, return error info
        ts = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        return {
            "version": 1,
            "timestamp": ts,
            "hosts": [{"host": h, "vmss_id": "", "error": str(e)} for h in hosts],
            "summary": {"queried": 0, "error": str(e)},
        }


__all__ = ["get_physical_hostnames", "get_vmss_id"]
