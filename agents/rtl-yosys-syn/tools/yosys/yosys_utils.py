#!/usr/bin/env python3
"""Yosys synthesis utilities library for Discovery platform workflows.

Provides:
  - Yosys log parsing (cell counts, area, flip-flop counts)
  - Synthesis report generation
  - TCL/Yosys script generation
  - CLI entry point for parse-log command (used by yosys_synth.sh)
"""
import os
import sys
import re
import json
import logging
import subprocess
import shutil
import glob
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

# ============= CONSTANTS =============
INPUT_DIR = "/input"
OUTPUT_DIR = "/output"
WORK_DIR = "/workdir"
SCRATCH_DIR = "/tmp/yosys_scratch"
PDK_DIR = "/app/pdk"

SUPPORTED_PDKS = {
    "sky130": "sky130_fd_sc_hd__tt_025C_1v80.lib",
    "gf180mcu": "gf180mcu_fd_sc_mcu7t5v0__tt_025C_3v30.lib",
}

# ============= SETUP FUNCTIONS =============

def quick_setup(input_dir: str = '/input', output_dir: str = '/output',
                work_dir: str = '/workdir') -> None:
    """Initialize logging, create directories, copy input files."""
    global INPUT_DIR, OUTPUT_DIR, WORK_DIR
    INPUT_DIR, OUTPUT_DIR, WORK_DIR = input_dir, output_dir, work_dir

    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s - %(levelname)s - %(message)s')
    os.makedirs(WORK_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.chdir(WORK_DIR)
    _copy_input_files()
    logging.info(f"Working directory: {WORK_DIR}")
    logging.info(f"Files: {os.listdir('.')}")


def _copy_input_files() -> None:
    """Copy input files to working directory."""
    if os.path.realpath(INPUT_DIR) == os.path.realpath(WORK_DIR):
        return
    if os.path.exists(INPUT_DIR):
        for f in glob.glob(os.path.join(INPUT_DIR, '*')):
            if os.path.isfile(f):
                shutil.copy(f, WORK_DIR)


def quick_finish() -> None:
    """Copy relevant output files to output directory."""
    if os.path.realpath(WORK_DIR) == os.path.realpath(OUTPUT_DIR):
        return
    patterns = ['*.v', '*.sv', '*.log', '*.txt', '*.json', '*.png', '*.csv']
    for pattern in patterns:
        for f in glob.glob(pattern):
            shutil.copy(f, OUTPUT_DIR)
    logging.info("Outputs copied to /output")


def save_final_results(results: Dict, output_files: Optional[Dict] = None,
                       file_descriptions: Optional[Dict] = None,
                       status: str = "completed") -> None:
    """Save final results to JSON (MANDATORY for every script)."""
    final_data = {"status": status, "summary": results}
    if output_files:
        final_data["output_files"] = output_files
    if file_descriptions:
        final_data["file_descriptions"] = file_descriptions
    out_path = os.path.join(OUTPUT_DIR, 'final_results.json')
    with open(out_path, 'w') as f:
        json.dump(final_data, f, indent=2)
    logging.info(f"Saved final_results.json")


# ============= LOG PARSING =============

def parse_yosys_log(log_path: str) -> Dict[str, Any]:
    """Parse a Yosys synthesis log file and extract key statistics.

    Args:
        log_path: Path to the Yosys .log file.

    Returns:
        Dict with keys:
          - cells: Dict[str, int] mapping cell type to count
          - total_cells: int
          - wires: int
          - wire_bits: int
          - memories: int
          - memory_bits: int
          - processes: int
          - area: float (if Liberty-based stat was run)
          - flip_flops: int (count of sequential cells)
          - raw_stat: str (raw stat section text)
    """
    if not os.path.exists(log_path):
        raise FileNotFoundError(f"Log file not found: {log_path}")

    text = Path(log_path).read_text(encoding='utf-8', errors='replace')
    return parse_yosys_log_text(text)


def parse_yosys_log_text(text: str) -> Dict[str, Any]:
    """Parse Yosys log text (not from file) and extract statistics.

    Args:
        text: Raw Yosys log content as string.

    Returns:
        Same dict structure as parse_yosys_log.
    """
    result: Dict[str, Any] = {
        "cells": {},
        "total_cells": 0,
        "wires": 0,
        "wire_bits": 0,
        "memories": 0,
        "memory_bits": 0,
        "processes": 0,
        "area": 0.0,
        "flip_flops": 0,
        "raw_stat": "",
    }

    # Extract the stat section(s) -- take the last one (post-mapping)
    stat_sections = re.findall(
        r'(=== .*? ===\n.*?)(?=\n=== |\nEnd of script\.|$)',
        text, re.DOTALL
    )
    if stat_sections:
        stat_text = stat_sections[-1]
        result["raw_stat"] = stat_text.strip()

    # Parse stats -- use findall and take LAST match (post-mapping values)
    def _last_int(pattern: str, txt: str) -> int:
        matches = re.findall(pattern, txt)
        return int(matches[-1]) if matches else 0

    # Try standard stat format first: "Number of cells: N"
    result["wires"] = _last_int(r'Number of wires:\s+(\d+)', text)
    result["wire_bits"] = _last_int(r'Number of wire bits:\s+(\d+)', text)
    result["memories"] = _last_int(r'Number of memories:\s+(\d+)', text)
    result["memory_bits"] = _last_int(r'Number of memory bits:\s+(\d+)', text)
    result["processes"] = _last_int(r'Number of processes:\s+(\d+)', text)
    result["total_cells"] = _last_int(r'Number of cells:\s+(\d+)', text)

    cell_lines = re.findall(r'^\s+(\$?\w[\w$]*)\s+(\d+)\s*$', text, re.MULTILINE)
    cells: Dict[str, int] = {}
    ff_count = 0
    for name, count_str in cell_lines:
        count = int(count_str)
        cells[name] = cells.get(name, 0) + count
        lower = name.lower()
        if any(k in lower for k in ['dff', 'dlatch', 'sdff', 'adff', 'dffe']):
            ff_count += count

    # If no cells found via standard format, try liberty stat format.
    # Liberty stat: "       24  310.298 cells" and "        8  200.192   sky130_fd_sc_hd__dfrtp_1"
    if not cells:
        m_summary = re.findall(r'^\s+(\d+)\s+[\d.]+\s+cells\s*$', text, re.MULTILINE)
        if m_summary:
            result["total_cells"] = int(m_summary[-1])

        liberty_cells = re.findall(r'^\s+(\d+)\s+([\d.]+)\s+([\w]+)\s*$', text, re.MULTILINE)
        for count_str, _area, name in liberty_cells:
            if name == 'cells':
                continue
            count = int(count_str)
            cells[name] = cells.get(name, 0) + count
            lower = name.lower()
            if any(k in lower for k in ['dff', 'dlatch', 'sdff', 'adff', 'dffe', 'dfrtp', 'dfxtp']):
                ff_count += count

        result["wires"] = _last_int(r'^\s+(\d+)\s+-\s+wires\s*$', text)
        result["wire_bits"] = _last_int(r'^\s+(\d+)\s+-\s+wire bits\s*$', text)

    if cells:
        result["cells"] = cells
        result["flip_flops"] = ff_count


    # Parse area
    m = re.search(r"Chip area for (?:module|top module)\s+[\'\"]?\S+[\'\"]?\s*:\s+([\d.]+)", text)
    if m:
        result["area"] = float(m.group(1))

    return result

def format_synth_report(stats: Dict[str, Any], pdk: str = "",
                        source: str = "", top: str = "") -> str:
    """Format parsed stats into a human-readable report.

    Args:
        stats: Dict from parse_yosys_log or parse_yosys_log_text.
        pdk: PDK name for the header.
        source: Source Verilog filename.
        top: Top module name.

    Returns:
        Multi-line string report.
    """
    lines = []
    lines.append("=" * 60)
    lines.append("YOSYS SYNTHESIS REPORT")
    lines.append("=" * 60)
    if source:
        lines.append(f"Source:     {source}")
    if top:
        lines.append(f"Top module: {top}")
    if pdk:
        lines.append(f"PDK:        {pdk}")
    lines.append("")
    lines.append("--- Summary ---")
    lines.append(f"  Total cells:   {stats.get('total_cells', 0)}")
    lines.append(f"  Flip-flops:    {stats.get('flip_flops', 0)}")
    lines.append(f"  Wires:         {stats.get('wires', 0)}")
    lines.append(f"  Wire bits:     {stats.get('wire_bits', 0)}")
    lines.append(f"  Memories:      {stats.get('memories', 0)}")
    lines.append(f"  Memory bits:   {stats.get('memory_bits', 0)}")
    area = stats.get('area', 0.0)
    if area > 0:
        lines.append(f"  Chip area:     {area:.2f}")
    lines.append("")

    cells = stats.get("cells", {})
    if cells:
        lines.append("--- Cell Breakdown ---")
        max_name = max(len(n) for n in cells) if cells else 10
        for name in sorted(cells.keys()):
            lines.append(f"  {name:<{max_name}}  {cells[name]:>6}")
        lines.append("")

    return "\n".join(lines)


# ============= YOSYS SCRIPT GENERATION =============

def generate_synth_script(verilog_files: List[str], output_netlist: str,
                          pdk: str = "sky130", top: Optional[str] = None,
                          extra_commands: Optional[List[str]] = None) -> str:
    """Generate a Yosys synthesis TCL/command script.

    Args:
        verilog_files: List of Verilog source file paths.
        output_netlist: Path for the output gate-level netlist.
        pdk: Target PDK name (sky130 or gf180mcu).
        top: Top module name. None for auto-detect.
        extra_commands: Additional Yosys commands to insert after synth.

    Returns:
        Yosys script content as string.
    """
    if pdk not in SUPPORTED_PDKS:
        raise ValueError(f"Unsupported PDK '{pdk}'. Supported: {list(SUPPORTED_PDKS.keys())}")

    lib_file = os.path.join(PDK_DIR, SUPPORTED_PDKS[pdk])
    lines = []
    for vf in verilog_files:
        lines.append(f"read_verilog {vf}")
    top_arg = f" -top {top}" if top else ""
    lines.append(f"synth{top_arg}")
    lines.append(f"dfflibmap -liberty {lib_file}")
    lines.append(f"abc -liberty {lib_file}")
    if extra_commands:
        lines.extend(extra_commands)
    lines.append("clean")
    lines.append(f"write_verilog -noattr {output_netlist}")
    lines.append(f"stat -liberty {lib_file}")
    return "\n".join(lines)


# ============= EXECUTION =============

def run_yosys(script_path: str, log_path: str,
              timeout: int = 600) -> subprocess.CompletedProcess:
    """Run Yosys with a script file.

    Args:
        script_path: Path to .ys script file.
        log_path: Path for the Yosys log output.
        timeout: Max seconds to allow (default 600).

    Returns:
        subprocess.CompletedProcess
    """
    cmd = ["yosys", "-s", script_path, "-l", log_path]
    logging.info(f"Running: {' '.join(cmd)}")
    try:
        result = subprocess.run(cmd, check=True, capture_output=True,
                                text=True, timeout=timeout)
        logging.info("Yosys completed successfully")
        return result
    except subprocess.CalledProcessError as e:
        logging.error(f"Yosys failed:\nstdout: {e.stdout}\nstderr: {e.stderr}")
        raise
    except subprocess.TimeoutExpired:
        logging.error(f"Yosys timed out after {timeout}s")
        raise


def run_synthesis(verilog_files: List[str], pdk: str = "sky130",
                  top: Optional[str] = None,
                  output_dir: str = "/output",
                  timeout: int = 600) -> Dict[str, Any]:
    """Full synthesis pipeline: generate script, run Yosys, parse results.

    Args:
        verilog_files: Verilog source files.
        pdk: Target PDK.
        top: Top module name.
        output_dir: Directory for outputs.
        timeout: Max seconds.

    Returns:
        Dict with keys: stats, netlist_path, report_path, log_path
    """
    os.makedirs(output_dir, exist_ok=True)
    basename = Path(verilog_files[0]).stem if verilog_files else "design"
    netlist_path = os.path.join(output_dir, f"{basename}_netlist.v")
    log_path = os.path.join(output_dir, f"{basename}_synth.log")
    report_path = os.path.join(output_dir, f"{basename}_synth_report.txt")

    # Generate and write script
    script = generate_synth_script(verilog_files, netlist_path, pdk=pdk, top=top)
    script_path = os.path.join(SCRATCH_DIR, "synth.ys")
    os.makedirs(SCRATCH_DIR, exist_ok=True)
    with open(script_path, 'w') as f:
        f.write(script)
    logging.info(f"Yosys script:\n{script}")

    # Run
    run_yosys(script_path, log_path, timeout=timeout)

    # Parse
    stats = parse_yosys_log(log_path)
    report_text = format_synth_report(
        stats, pdk=pdk,
        source=", ".join(os.path.basename(v) for v in verilog_files),
        top=top or "auto-detect"
    )
    with open(report_path, 'w') as f:
        f.write(report_text)
    logging.info(f"Report written to {report_path}")

    return {
        "stats": stats,
        "netlist_path": netlist_path,
        "report_path": report_path,
        "log_path": log_path,
    }


# ============= BATCH SYNTHESIS =============

def batch_synthesize(designs: List[Dict[str, Any]],
                     output_dir: str = "/output",
                     pdk: str = "sky130",
                     timeout_per_design: int = 600) -> Tuple[List[Dict], List[Dict]]:
    """Synthesize multiple designs sequentially.

    Args:
        designs: List of dicts, each with keys:
            - files: List[str] (Verilog file paths)
            - top: str (optional top module name)
            - name: str (optional design label)
        output_dir: Output directory.
        pdk: Target PDK.
        timeout_per_design: Timeout per design in seconds.

    Returns:
        (successes, failures) tuple.
    """
    successes = []
    failures = []
    for i, design in enumerate(designs):
        name = design.get("name", f"design_{i}")
        files = design.get("files", [])
        top = design.get("top")
        logging.info(f"Synthesizing {name} ({i+1}/{len(designs)})")
        try:
            result = run_synthesis(
                files, pdk=pdk, top=top,
                output_dir=os.path.join(output_dir, name),
                timeout=timeout_per_design
            )
            result["name"] = name
            successes.append(result)
        except Exception as e:
            logging.error(f"Failed to synthesize {name}: {e}")
            failures.append({"name": name, "error": str(e)})
    logging.info(f"Batch: {len(successes)} succeeded, {len(failures)} failed")
    return successes, failures


# ============= CLI ENTRY POINT =============

def _cli_parse_log():
    """CLI: parse a Yosys log and print formatted report to stdout."""
    if len(sys.argv) < 3:
        print("Usage: python3 yosys_utils.py parse-log <log_file>", file=sys.stderr)
        sys.exit(1)
    log_path = sys.argv[2]
    stats = parse_yosys_log(log_path)
    report = format_synth_report(stats)
    print(report)


if __name__ == "__main__":
    if len(sys.argv) >= 2:
        cmd = sys.argv[1]
        if cmd == "parse-log":
            _cli_parse_log()
        else:
            print(f"Unknown command: {cmd}", file=sys.stderr)
            print("Available: parse-log", file=sys.stderr)
            sys.exit(1)
    else:
        print("Yosys utilities library. Use: python3 yosys_utils.py <command>")
        print("Commands: parse-log")
