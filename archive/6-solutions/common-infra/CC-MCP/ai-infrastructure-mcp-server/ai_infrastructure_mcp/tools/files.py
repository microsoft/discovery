"""File access tools for cluster nodes."""

import shlex
from typing import Any, Dict, Union

from ai_infrastructure_mcp.ssh_config import run_login_command


def head_file(path: str, offset: int = 0, length: int = 10) -> Dict[str, Any]:
    """Read lines from the beginning of a file with offset and length.

    Args:
        path: Path to the file on the cluster
        offset: Number of lines to skip from the beginning (default: 0)
        length: Number of lines to read (default: 10)

    Returns:
        Structured JSON dict with version, lines[], line_count, etc.
    """
    if length <= 0:
        return {
            "version": 1,
            "success": False,
            "error": "Length must be greater than 0",
            "lines": [],
            "line_count": 0,
        }

    if offset < 0:
        return {
            "version": 1,
            "success": False,
            "error": "Offset must be non-negative",
            "lines": [],
            "line_count": 0,
        }

    # Escape the file path for shell safety
    escaped_path = shlex.quote(path)

    try:
        if offset == 0:
            # Simple case: just head
            cmd = f"head -n {length} {escaped_path}"
        else:
            # Skip offset lines, then take length lines
            cmd = f"tail -n +{offset + 1} {escaped_path} | head -n {length}"

        output = run_login_command(cmd)

        # Check if there was an error (stderr is appended to output)
        if "[stderr]" in output:
            error_part = output.split("[stderr]", 1)[1].strip()
            if error_part and "No such file or directory" in error_part:
                return {
                    "version": 1,
                    "success": False,
                    "error": f"File not found: {path}",
                    "lines": [],
                    "line_count": 0,
                }
            elif error_part:
                return {
                    "version": 1,
                    "success": False,
                    "error": f"Command error: {error_part}",
                    "lines": [],
                    "line_count": 0,
                }

        # Split output into lines, preserving empty lines but removing final empty line if present
        lines = output.rstrip("\n").split("\n") if output.strip() else []

        return {
            "version": 1,
            "success": True,
            "path": path,
            "offset": offset,
            "length": length,
            "lines": lines,
            "line_count": len(lines),
            "error": None,
        }

    except Exception as e:
        return {
            "version": 1,
            "success": False,
            "error": f"Unexpected error: {str(e)}",
            "lines": [],
            "line_count": 0,
        }


def tail_file(path: str, offset: int = 0, length: int = 10) -> Dict[str, Any]:
    """Read lines from the end of a file with offset and length.

    Args:
        path: Path to the file on the cluster
        offset: Number of lines to skip from the end (default: 0)
        length: Number of lines to read (default: 10)

    Returns:
        Structured JSON dict with version, lines[], line_count, etc.
    """
    if length <= 0:
        return {
            "version": 1,
            "success": False,
            "error": "Length must be greater than 0",
            "lines": [],
            "line_count": 0,
        }

    if offset < 0:
        return {
            "version": 1,
            "success": False,
            "error": "Offset must be non-negative",
            "lines": [],
            "line_count": 0,
        }

    # Escape the file path for shell safety
    escaped_path = shlex.quote(path)

    try:
        if offset == 0:
            # Simple case: just tail
            cmd = f"tail -n {length} {escaped_path}"
        else:
            # Get total lines, then calculate how many lines to take
            # First get total line count
            count_cmd = f"wc -l < {escaped_path}"
            count_output = run_login_command(count_cmd)

            if "[stderr]" in count_output:
                error_part = count_output.split("[stderr]", 1)[1].strip()
                if "No such file or directory" in error_part:
                    return {
                        "version": 1,
                        "success": False,
                        "error": f"File not found: {path}",
                        "lines": [],
                        "line_count": 0,
                    }
                elif error_part:
                    return {
                        "version": 1,
                        "success": False,
                        "error": f"Command error: {error_part}",
                        "lines": [],
                        "line_count": 0,
                    }

            try:
                total_lines = int(count_output.strip())
                if total_lines <= offset:
                    return {
                        "version": 1,
                        "success": True,
                        "path": path,
                        "offset": offset,
                        "length": length,
                        "lines": [],
                        "line_count": 0,
                        "error": None,
                    }

                # Take from (total_lines - offset - length) to (total_lines - offset)
                start_line = max(1, total_lines - offset - length + 1)
                end_line = total_lines - offset

                if start_line > end_line:
                    return {
                        "version": 1,
                        "success": True,
                        "path": path,
                        "offset": offset,
                        "length": length,
                        "lines": [],
                        "line_count": 0,
                        "error": None,
                    }

                cmd = f"sed -n '{start_line},{end_line}p' {escaped_path}"

            except ValueError:
                return {
                    "version": 1,
                    "success": False,
                    "error": "Could not determine file line count",
                    "lines": [],
                    "line_count": 0,
                }

        output = run_login_command(cmd)

        # Check if there was an error (stderr is appended to output)
        if "[stderr]" in output:
            error_part = output.split("[stderr]", 1)[1].strip()
            if error_part and "No such file or directory" in error_part:
                return {
                    "version": 1,
                    "success": False,
                    "error": f"File not found: {path}",
                    "lines": [],
                    "line_count": 0,
                }
            elif error_part:
                return {
                    "version": 1,
                    "success": False,
                    "error": f"Command error: {error_part}",
                    "lines": [],
                    "line_count": 0,
                }

        # Split output into lines, preserving empty lines but removing final empty line if present
        lines = output.rstrip("\n").split("\n") if output.strip() else []

        return {
            "version": 1,
            "success": True,
            "path": path,
            "offset": offset,
            "length": length,
            "lines": lines,
            "line_count": len(lines),
            "error": None,
        }

    except Exception as e:
        return {
            "version": 1,
            "success": False,
            "error": f"Unexpected error: {str(e)}",
            "lines": [],
            "line_count": 0,
        }


def count_file(path: str, mode: str = "lines") -> Dict[str, Any]:
    """Count lines or bytes in a file.

    Args:
        path: Path to the file on the cluster
        mode: "lines" to count lines, "bytes" to count bytes (default: "lines")

    Returns:
        Structured JSON dict with version, count, mode, etc.
    """
    if mode not in ["lines", "bytes"]:
        return {
            "version": 1,
            "success": False,
            "error": "Mode must be 'lines' or 'bytes'",
            "count": 0,
            "mode": mode,
        }

    # Escape the file path for shell safety
    escaped_path = shlex.quote(path)

    try:
        if mode == "lines":
            cmd = f"wc -l < {escaped_path}"
        else:  # mode == "bytes"
            cmd = f"wc -c < {escaped_path}"

        output = run_login_command(cmd)

        # Check if there was an error (stderr is appended to output)
        if "[stderr]" in output:
            error_part = output.split("[stderr]", 1)[1].strip()
            if error_part and "No such file or directory" in error_part:
                return {
                    "version": 1,
                    "success": False,
                    "error": f"File not found: {path}",
                    "count": 0,
                    "mode": mode,
                }
            elif error_part:
                return {
                    "version": 1,
                    "success": False,
                    "error": f"Command error: {error_part}",
                    "count": 0,
                    "mode": mode,
                }

        try:
            count = int(output.strip())
            return {
                "version": 1,
                "success": True,
                "path": path,
                "mode": mode,
                "count": count,
                "error": None,
            }
        except ValueError:
            return {
                "version": 1,
                "success": False,
                "error": f"Could not parse count from output: {output.strip()}",
                "count": 0,
                "mode": mode,
            }

    except Exception as e:
        return {
            "version": 1,
            "success": False,
            "error": f"Unexpected error: {str(e)}",
            "count": 0,
            "mode": mode,
        }


def search_file(
    path: str, pattern: str, before: int = 0, after: int = 0, max_matches: int = 100
) -> Dict[str, Any]:
    """Search for a pattern in a file with context lines.

    Args:
        path: Path to the file on the cluster
        pattern: Regular expression pattern to search for
        before: Number of lines to include before each match (default: 0)
        after: Number of lines to include after each match (default: 0)
        max_matches: Maximum number of matches to return (default: 100)

    Returns:
        Structured JSON dict with version, matches[], match_count, etc.
    """
    if max_matches <= 0:
        return {
            "version": 1,
            "success": False,
            "error": "max_matches must be greater than 0",
            "matches": [],
            "match_count": 0,
        }

    if before < 0 or after < 0:
        return {
            "version": 1,
            "success": False,
            "error": "before and after must be non-negative",
            "matches": [],
            "match_count": 0,
        }

    # Escape the file path and pattern for shell safety
    escaped_path = shlex.quote(path)
    escaped_pattern = shlex.quote(pattern)

    try:
        # Build grep command with context and line numbers
        cmd_parts = ["grep", "-n"]  # -n for line numbers

        if before > 0:
            cmd_parts.extend(["-B", str(before)])
        if after > 0:
            cmd_parts.extend(["-A", str(after)])

        # Limit number of matches
        cmd_parts.extend(["-m", str(max_matches)])

        cmd_parts.extend([escaped_pattern, escaped_path])

        cmd = " ".join(cmd_parts)

        output = run_login_command(cmd)

        # Check if there was an error (stderr is appended to output)
        if "[stderr]" in output:
            stdout_part, stderr_part = output.split("[stderr]", 1)
            stderr_part = stderr_part.strip()

            if "No such file or directory" in stderr_part:
                return {
                    "version": 1,
                    "success": False,
                    "error": f"File not found: {path}",
                    "matches": [],
                    "match_count": 0,
                }
            elif stderr_part and "Binary file" not in stderr_part:
                # Ignore "Binary file" warnings but report other errors
                return {
                    "version": 1,
                    "success": False,
                    "error": f"Command error: {stderr_part}",
                    "matches": [],
                    "match_count": 0,
                }

            # Use stdout part if stderr only contained warnings
            output = stdout_part

        # Parse grep output - need to handle context lines properly
        lines = output.strip().split("\n") if output.strip() else []
        matches = []
        i = 0

        while i < len(lines):
            line = lines[i]
            if not line or line == "--":
                i += 1
                continue

            # Look for match lines (contain ':')
            if ":" in line:
                try:
                    line_num_str, content = line.split(":", 1)
                    line_num = int(line_num_str)

                    match = {
                        "line_number": line_num,
                        "line": content,
                        "context_before": [],
                        "context_after": [],
                    }

                    # Look backwards for context before this match
                    j = i - 1
                    while j >= 0 and lines[j] != "--" and lines[j]:
                        if "-" in lines[j]:
                            try:
                                ctx_line_num_str, ctx_content = lines[j].split("-", 1)
                                ctx_line_num = int(ctx_line_num_str)
                                if ctx_line_num < line_num:
                                    match["context_before"].insert(
                                        0,
                                        {
                                            "line_number": ctx_line_num,
                                            "line": ctx_content,
                                        },
                                    )
                                else:
                                    break
                            except ValueError:
                                break
                        else:
                            break
                        j -= 1

                    # Look forwards for context after this match
                    j = i + 1
                    while j < len(lines) and lines[j] != "--" and lines[j]:
                        if "-" in lines[j]:
                            try:
                                ctx_line_num_str, ctx_content = lines[j].split("-", 1)
                                ctx_line_num = int(ctx_line_num_str)
                                if ctx_line_num > line_num:
                                    match["context_after"].append(
                                        {
                                            "line_number": ctx_line_num,
                                            "line": ctx_content,
                                        }
                                    )
                                else:
                                    break
                            except ValueError:
                                break
                        elif ":" in lines[j]:
                            # Hit another match, stop looking for context
                            break
                        j += 1

                    matches.append(match)

                except ValueError:
                    # Couldn't parse line number, skip this line
                    pass

            i += 1

        return {
            "version": 1,
            "success": True,
            "path": path,
            "pattern": pattern,
            "before": before,
            "after": after,
            "max_matches": max_matches,
            "matches": matches,
            "match_count": len(matches),
            "error": None,
        }

    except Exception as e:
        return {
            "version": 1,
            "success": False,
            "error": f"Unexpected error: {str(e)}",
            "matches": [],
            "match_count": 0,
        }
