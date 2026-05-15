from typing import Any, Dict, List, Optional

from ai_infrastructure_mcp.tools.command_wrapper import run_simple_command


def sacct(args: Optional[List[str]] = None) -> Dict[str, Any]:
    """Run sacct (job accounting).

    Enhancement: If a user specifies a state selector via -s/--state (or
    --state=STATE) but omits an explicit end time (-E/--endtime), we append
    '--endtime=now'. Rationale: on some clusters sacct with a state filter and
    no end time will return an empty result set (rather than the intuitive
    "current window"), leading users to think there are no matching jobs. The
    automatic end time makes the default behavior immediately useful while
    remaining overrideable by providing any -E/--endtime argument explicitly.
    """
    processed_args: List[str] = []
    if args:
        processed_args = list(args)  # shallow copy
        lowered = [a.lower() for a in processed_args]
        has_state = any(a in ("-s", "--state") for a in lowered)
        # Account for forms like '--state=RUNNING'
        if not has_state:
            has_state = any(a.startswith("--state=") for a in lowered)
        has_end = any(a in ("-e", "--endtime") for a in lowered) or any(
            a.startswith("--endtime=") for a in lowered
        )
        if has_state and not has_end:
            # Append explicit endtime=now
            processed_args.append("--endtime=now")
    return run_simple_command("sacct", processed_args or args)


def squeue(args: Optional[List[str]] = None) -> Dict[str, Any]:
    """Run squeue (job queue)."""
    return run_simple_command("squeue", args)


def sinfo(args: Optional[List[str]] = None) -> Dict[str, Any]:
    """Run sinfo (node/partition info)."""
    return run_simple_command("sinfo", args)


def scontrol(args: Optional[List[str]] = None) -> Dict[str, Any]:
    """Run scontrol (cluster control)."""
    return run_simple_command("scontrol", args)


def sreport(args: Optional[List[str]] = None) -> Dict[str, Any]:
    """Run sreport (accounting reports)."""
    return run_simple_command("sreport", args)


def sbatch(args: Optional[List[str]] = None) -> Dict[str, Any]:
    """Run sbatch (submit batch job)."""
    return run_simple_command("sbatch", args)
