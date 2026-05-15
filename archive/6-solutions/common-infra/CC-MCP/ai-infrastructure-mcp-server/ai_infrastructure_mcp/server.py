import argparse
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastmcp.server import FastMCP

from .tools.azure_vm import get_physical_hostnames as _get_physical_hostnames_impl
from .tools.azure_vm import get_vmss_id as _get_vmss_instance_name_impl
from .tools.files import count_file as _count_file_impl
from .tools.files import head_file as _head_file_impl
from .tools.files import search_file as _search_file_impl
from .tools.files import tail_file as _tail_file_impl
from .tools.pkeys import get_infiniband_pkeys as _get_infiniband_pkeys_impl
from .tools.slurm import sacct as _sacct_impl
from .tools.slurm import scontrol as _scontrol_impl
from .tools.slurm import sinfo as _sinfo_impl
from .tools.slurm import squeue as _squeue_impl
from .tools.slurm import sreport as _sreport_impl
from .tools.systemd import journalctl as _journalctl_impl
from .tools.systemd import systemctl as _systemctl_impl


def build_server() -> FastMCP:
    server = FastMCP(name="ai-infrastructure-mcp")

    @server.tool()
    def get_infiniband_pkeys(hosts: List[str]) -> Dict[str, Any]:  # type: ignore
        """Retrieve InfiniBand partition keys (P_Keys) for each requested host.

        Args:
            hosts: Hostnames to query for InfiniBand P_Keys.
        Returns:
            Structured JSON dict with version, timestamp, hosts[], summary.
        """
        return _get_infiniband_pkeys_impl(hosts)

    @server.tool()
    def get_physical_hostnames(hosts: List[str]) -> Dict[str, Any]:  # type: ignore
        """Retrieve underlying Azure physical hostnames for VMs.

        Extracts the physical host identifier by reading the Hyper-V KVP pool file
        (/var/lib/hyperv/.kvp_pool_3) and applying the provided sed extraction.

        Args:
            hosts: VM hostnames to query (required, non-empty)

        Returns:
            Structured JSON dict with version, timestamp, hosts[], summary.

        Notes:
            - Uses parallel-ssh across provided hosts (same pattern as get_infiniband_pkeys)
            - physical_hostname field may be empty if pattern not present
        """
        return _get_physical_hostnames_impl(hosts)

    @server.tool()
    def get_vmss_instance_name(hosts: List[str]) -> Dict[str, Any]:  # type: ignore
        """Retrieve Azure VMSS (Virtual Machine Scale Set) instance names for VMs.

        Extracts the VMSS instance name from the compute.name field, which is used
        to correlate VM hostnames with Azure Monitor metrics data.

        Args:
            hosts: VM hostnames to query (required, non-empty)

        Returns:
            Structured JSON dict with version, timestamp, hosts[], summary.

        Notes:
            - Uses parallel-ssh across provided hosts (same pattern as get_infiniband_pkeys)
            - vmss_id field may be empty if Azure instance metadata is not accessible
            - VMSS instance names are specifically for Azure Monitor metrics correlation
            - This is NOT the Azure VM ID - use get_physical_hostnames + Kusto for VM IDs
        """
        return _get_vmss_instance_name_impl(hosts)

    @server.tool()
    def sacct(args: Optional[List[str]] = None) -> Dict[str, Any]:  # type: ignore
        """Wrapper for the Slurm sacct command - displays accounting data for all jobs and job steps in the Slurm job accounting log or Slurm database.

        This tool provides a direct interface to the sacct command, allowing you to query historical job information,
        resource usage, and accounting data from completed and running jobs.

        *Always use a time range to limit data.*
        *Use --parsable for easier parsing.*

        Args:
            args: Optional list of command-line arguments to pass to sacct

        Examples:
            sacct(['--format=JobID,JobName,StdOut,StdErr,State,ExitCode,Elapsed','--starttime=now-1day','--endtime==now','--parsable']) - Custom output format
            sacct(['--allusers','--allocations','--format=JobID,User','--starttime=now-1day','--endtime==now','--parsable']) - Lists the JobID and User for all jobs from the last 24 hours.
            sacct(['--state=FAILED','--format=JobID,JobName,StdOut,StdErr','--starttime=now-1day','--endtime=now','--parsable']) - Lists the JobID, JobName, StdOut, and StdErr for all failed jobs from the last 24 hours.
        """
        return _sacct_impl(args)

    @server.tool()
    def squeue(args: Optional[List[str]] = None) -> Dict[str, Any]:  # type: ignore
        """
        Wrapper for the Slurm `squeue` command – query jobs in the scheduling queue.

        This tool provides access to real-time information about jobs, including
        running, pending, and recently completed jobs. It is commonly used to
        monitor job status, resource allocation, and queue state.

        ⚠️ Important:
        Always use the short format specifiers (`--format=%...`) instead of long
        field names. The `%` codes prevent column truncation and ensure consistent
        machine-readable output.

        Args:
            args: Optional list of command-line arguments to pass to `squeue`.

        Available format fields (long name → short % code):
            Account: %a, AccrueTime: %F, AdminComment: %K, AllocNodes: %B, AllocSID: %o
            ArrayJobId: %k, ArrayTaskId: %O, AssocId: %I, BatchFlag: %X, BatchHost: %E
            BoardsPerNode: %e, BurstBuffer: %x, BurstBufferState: %f, Cluster: %G, ClusterFeature: %g
            Command: %i, Comment: %A, Container: %W, ContainerId: %c, Contiguous: %m
            Cores: %d, CoreSpec: %j, CPUsPerTask: %y, cpus-per-task: %N, cpus-per-tres: %C
            Deadline: %D, DelayBoot: %h, Dependency: %P, DerivedEC: %p, EligibleTime: %Q
            EndTime: %q, ExcNodes: %r, ExitCode: %R, Feature: %n, GroupId: %v
            GroupName: %Y, HetJobId: %z, HetJobIdSet: %H, HetJobOffset: %S, JobArrayId: %T
            JobId: %t, LastSchedEval: %V, Licenses: %J, MaxCPUs: %L, MaxNodes: %l
            mem-per-tres: %M, MCSLabel: %U, MinCPUs: %u, MinMemory: %w, MinTime: %Z
            Name: %j, NodeList: %N, NumCPUs: %c, NumNodes: %D, NumTasks: %W
            Partition: %P, Priority: %p, QOS: %q, Reason: %Q/%r, ReqNodes: %R
            Sockets: %X, StartTime: %S, State: %T, StateCompact: %t, SubmitTime: %V
            TimeLeft: %L, TimeLimit: %l, TimeUsed: %M, UserId: %u, UserName: %U
            WCKey: %k/%K, WorkDir: %w

        Examples:
            squeue(['--format=%t,%j,%u,%T,%M,%D,%R'])
            # Show all jobs with Job ID, Name, User, State, Time Used, Num Nodes, and Reason

            squeue(['--user', 'alice', '--format=%t,%j,%T,%M'])
            # Show jobs submitted by user 'alice' with Job ID, Name, State, and Time Used

            squeue(['--states=RUNNING', '--format=%t,%j,%u,%T,%M'])
            # Show only running jobs with Job ID, Name, User, State, and Time Used

            squeue(['--partition=gpu', '--format=%t,%j,%u,%T,%N'])
            # Show jobs in the 'gpu' partition with Job ID, Name, User, State, and NodeList

            squeue(['--format=%t,%j,%P,%T,%L,%D,%R'])
            # Show all jobs with Job ID, Name, Partition, State, Time Left, Num Nodes, and Reason
        """
        return _squeue_impl(args)

    @server.tool()
    def sinfo(args: Optional[List[str]] = None) -> Dict[str, Any]:  # type: ignore
        """Wrapper for the Slurm sinfo command - view information about Slurm nodes and partitions.

        This tool provides information about the cluster's compute resources, including node states,
        partition configurations, and hardware specifications. Use it to understand cluster topology
        and resource availability.

        Args:
            args: Optional list of command-line arguments to pass to sinfo

        Examples:
            sinfo() - Show partition and node summary with default format
            sinfo(['--partition', 'gpu']) - Show information for the 'gpu' partition
            sinfo(['--Format', 'NodeList,CPUs,Memory,State']) - Custom format showing node details
            sinfo(['--nodes']) - Show detailed node information instead of partition summary
            sinfo(['--states=idle,alloc']) - Show nodes in idle or allocated states
        """
        return _sinfo_impl(args)

    @server.tool()
    def scontrol(args: Optional[List[str]] = None) -> Dict[str, Any]:  # type: ignore
        """Wrapper for the Slurm scontrol command - view or modify Slurm configuration and state.

        This tool provides administrative access to view and modify Slurm cluster configuration,
        job states, and system information. Use it for detailed job inspection and cluster management.

        Args:
            args: Optional list of command-line arguments to pass to scontrol

        Examples:
            scontrol(['ping']) - Test communication with Slurm controller
            scontrol(['show', 'job', '123']) - Show detailed information for job ID 123
            scontrol(['show', 'node', 'compute-01']) - Show detailed node information
            scontrol(['show', 'partition']) - Show all partition configurations
            scontrol(['show', 'config']) - Display Slurm configuration parameters
        """
        return _scontrol_impl(args)

    @server.tool()
    def sreport(args: Optional[List[str]] = None) -> Dict[str, Any]:  # type: ignore
        """Wrapper for the Slurm sreport command - generate reports from the Slurm accounting data.

        This tool generates various reports and statistics from historical Slurm accounting data,
        including cluster utilization, user usage patterns, and resource consumption analytics.

        Args:
            args: Optional list of command-line arguments to pass to sreport

        Examples:
            sreport(['cluster', 'Utilization']) - Generate cluster utilization report
            sreport(['user', 'TopUsage']) - Show top users by resource usage
            sreport(['job', 'SizesByAccount']) - Job size distribution by account
            sreport(['cluster', 'AccountUtilizationByUser', 'Start=2024-01-01']) - User utilization with date filter
            sreport(['reservation', 'Utilization']) - Reservation usage statistics
        """
        return _sreport_impl(args)

    @server.tool()
    def systemctl(hosts: List[str], args: Optional[List[str]] = None) -> Dict[str, Any]:  # type: ignore
        """Wrapper for the systemctl command - control systemd services and other units.

        This tool provides access to systemctl functionality for managing systemd services,
        checking service status, and controlling system units on the cluster.

        Args:
            args: Optional list of command-line arguments to pass to systemctl
            hosts: List of hostnames to run the command on (required)

        Examples:
            systemctl(['status', 'ssh']) - Show status of the SSH service
            systemctl(['list-units', '--type=service']) - List all service units
            systemctl(['is-active', 'nginx']) - Check if nginx service is active
            systemctl(['show', 'mysql', '--property=ActiveState']) - Show specific properties
            systemctl(['list-units', '--failed']) - Show only failed units
        """
        return _systemctl_impl(hosts, args)

    @server.tool()
    def journalctl(hosts: List[str], args: Optional[List[str]] = None) -> Dict[str, Any]:  # type: ignore
        """Wrapper for the journalctl command - query and display messages from the journal.

        This tool provides access to systemd journal logs for debugging and monitoring
        system and service activity on the cluster.

        Args:
            args: Optional list of command-line arguments to pass to journalctl
            hosts: List of hostnames to run the command on (required)

        Examples:
            journalctl(['-u', 'ssh', '-n', '10']) - Show last 10 log entries for SSH service
            journalctl(['--since', 'today']) - Show logs since today
            journalctl(['-f', '-u', 'nginx']) - Follow logs for nginx service
            journalctl(['--priority=err']) - Show only error level logs
            journalctl(['--since', '2024-01-01', '--until', '2024-01-02']) - Logs from date range
        """
        return _journalctl_impl(hosts, args)

    @server.tool()
    def head_file(path: str, offset: int = 0, length: int = 10) -> Dict[str, Any]:  # type: ignore
        """Read lines from the beginning of a file with offset and length.

        Args:
            path: Path to the file on the cluster
            offset: Number of lines to skip from the beginning (default: 0)
            length: Number of lines to read (default: 10)

        Returns:
            Structured JSON dict with lines[], line_count, success status, etc.
        """
        return _head_file_impl(path, offset, length)

    @server.tool()
    def tail_file(path: str, offset: int = 0, length: int = 10) -> Dict[str, Any]:  # type: ignore
        """Read lines from the end of a file with offset and length.

        Args:
            path: Path to the file on the cluster
            offset: Number of lines to skip from the end (default: 0)
            length: Number of lines to read (default: 10)

        Returns:
            Structured JSON dict with lines[], line_count, success status, etc.
        """
        return _tail_file_impl(path, offset, length)

    @server.tool()
    def count_file(path: str, mode: str = "lines") -> Dict[str, Any]:  # type: ignore
        """Count lines or bytes in a file.

        Args:
            path: Path to the file on the cluster
            mode: "lines" to count lines, "bytes" to count bytes (default: "lines")

        Returns:
            Structured JSON dict with count, mode, success status, etc.
        """
        return _count_file_impl(path, mode)

    @server.tool()
    def search_file(path: str, pattern: str, before: int = 0, after: int = 0, max_matches: int = 100) -> Dict[str, Any]:  # type: ignore
        """Search for a pattern in a file with context lines.

        Args:
            path: Path to the file on the cluster
            pattern: Regular expression pattern to search for
            before: Number of lines to include before each match (default: 0)
            after: Number of lines to include after each match (default: 0)
            max_matches: Maximum number of matches to return (default: 100)

        Returns:
            Structured JSON dict with matches[], match_count, success status, etc.
        """
        return _search_file_impl(path, pattern, before, after, max_matches)

    return server


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run ai-infrastructure-mcp server in HTTP or stdio mode."
    )
    parser.add_argument(
        "--mode",
        choices=["http", "stdio"],
        default="http",
        help="Server mode: http or stdio (default: stdio)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8080,
        help="Port to run HTTP server on (default: 8080)",
    )
    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Host address to bind HTTP server to (default: 127.0.0.1)",
    )
    args = parser.parse_args()
    server = build_server()
    if args.mode == "stdio":
        server.run()
    else:
        server.run(transport="http", host=args.host, port=args.port)
