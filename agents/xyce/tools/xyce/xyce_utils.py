#!/usr/bin/env python3
"""Xyce SPICE simulation utilities for Discovery platform.

Provides:
  - Testbench auto-generation from subcircuit netlists
  - Noise testbench generation
  - Simulation output parsing (.prn, .mt0)
  - CLI entry points for shell script integration
"""
import os
import sys
import re
import argparse
from typing import Dict, List, Optional, Tuple, Any


# ============= CONSTANTS =============

PDK_CONFIGS = {
    "sky130": {
        "vdd": 1.8,
        # mkghub/skywater130_fd_pr_models layout: use sky130_tt.lib.spice
        # (focused tt-corner entry point) instead of sky130.lib.spice (multi-
        # corner aggregator). The tt-only file doesn't reference SONOS or HV
        # corner blocks that the repo doesn't fully ship, so we get a clean
        # parse on the standard 01v8 CMOS devices used by most digital designs.
        # Dockerfile sed pass rewrites relative includes to absolute paths.
        "include": '.lib "/app/pdk/sky130/sky130_fd_pr_models/sky130_tt.lib.spice" tt',
        "nfet": "sky130_fd_pr__nfet_01v8",
        "pfet": "sky130_fd_pr__pfet_01v8",
        "description": "SkyWater 130nm, 1.8V core (tt corner)",
    },
    "gf180mcu": {
        "vdd": 3.3,
        # Per efabless smoke_test/inv_xyce.spice (the canonical reference):
        # design.xyce MUST be .include'd BEFORE sm141064.xyce so its .PARAM
        # switches (FNOICOR, SW_STAT_GLOBAL, etc.) are defined when the
        # conditional model expressions in sm141064 evaluate. Use .lib + corner
        # for the model file.
        "include": (
            '.include "/app/pdk/gf180mcu/design.xyce"\n'
            '.lib "/app/pdk/gf180mcu/sm141064.xyce" typical'
        ),
        "nfet": "nfet_03v3",
        "pfet": "pfet_03v3",
        "description": "GlobalFoundries 180nm, 3.3V",
    },
}

POWER_PATTERNS = re.compile(
    r'^(vdd|vcc|avdd|dvdd|vpwr|supply)$', re.IGNORECASE
)
GROUND_PATTERNS = re.compile(
    r'^(vss|gnd|avss|dvss|vgnd|ground)$', re.IGNORECASE
)
CLOCK_PATTERNS = re.compile(
    r'^(clk|clock|ck|phi[12]?)$', re.IGNORECASE
)
RESET_PATTERNS = re.compile(
    r'^(rst|reset|rst_n|resetb|rstn|nrst)$', re.IGNORECASE
)
OUTPUT_PATTERNS = re.compile(
    r'^(out|output|q|qb|y|z|dout)', re.IGNORECASE
)


# ============= NETLIST PARSING =============

def parse_subcircuit(netlist_path: str) -> Optional[Dict[str, Any]]:
    """Parse a SPICE netlist and extract the first .subckt definition.

    Returns dict with: name, ports, body, pdk_hint
    """
    if not os.path.exists(netlist_path):
        return None

    with open(netlist_path, 'r', errors='replace') as f:
        content = f.read()

    # Check if netlist already has analysis commands
    has_analysis = bool(re.search(r'^\.(tran|dc|ac|noise)\b', content, re.MULTILINE | re.IGNORECASE))

    # Find .subckt
    m = re.search(
        r'^\.subckt\s+(\S+)\s+(.+?)$\n(.*?)^\.ends',
        content, re.MULTILINE | re.IGNORECASE | re.DOTALL
    )
    if not m:
        return {"name": None, "ports": [], "body": content,
                "has_analysis": has_analysis, "pdk_hint": detect_pdk(content)}

    name = m.group(1)
    ports = m.group(2).split()
    body = m.group(3)

    return {
        "name": name,
        "ports": ports,
        "body": body,
        "has_analysis": has_analysis,
        "pdk_hint": detect_pdk(content),
    }


def detect_pdk(content: str) -> Optional[str]:
    """Detect PDK from model references in netlist."""
    if re.search(r'sky130_fd_pr__', content, re.IGNORECASE):
        return "sky130"
    if re.search(r'gf180mcu|nfet_03v3|pfet_03v3', content, re.IGNORECASE):
        return "gf180mcu"
    return None


def classify_port(port_name: str) -> str:
    """Classify a port as power, ground, clock, reset, input, or output."""
    if POWER_PATTERNS.match(port_name):
        return "power"
    if GROUND_PATTERNS.match(port_name):
        return "ground"
    if CLOCK_PATTERNS.match(port_name):
        return "clock"
    if RESET_PATTERNS.match(port_name):
        return "reset"
    if OUTPUT_PATTERNS.match(port_name):
        return "output"
    return "input"


def classify_ports(ports: List[str]) -> Dict[str, List[str]]:
    """Classify all ports into categories."""
    result = {"power": [], "ground": [], "clock": [], "reset": [],
              "input": [], "output": []}
    for p in ports:
        cat = classify_port(p)
        result[cat].append(p)
    return result


# ============= TESTBENCH GENERATION =============

def generate_testbench(netlist_path: str, pdk: str = "sky130",
                       sim_type: str = "tran", sim_time: str = "100n",
                       sim_step: str = "0.1n") -> str:
    """Generate a SPICE testbench for a subcircuit netlist.

    Args:
        netlist_path: Path to the SPICE netlist with .subckt.
        pdk: Target PDK (sky130 or gf180mcu).
        sim_type: Simulation type (tran, noise, tran+noise).
        sim_time: Transient sim end time.
        sim_step: Transient sim step.

    Returns:
        Testbench SPICE content as string.
    """
    info = parse_subcircuit(netlist_path)
    if not info:
        return _generate_fallback_testbench(netlist_path, pdk, sim_time, sim_step)

    # If netlist already has analysis, return it with PDK include prepended
    if info["has_analysis"] and info["name"] is None:
        return _prepend_pdk_include(netlist_path, pdk)

    # Use detected PDK if available
    if info["pdk_hint"] and pdk == "sky130":
        pdk = info["pdk_hint"]

    config = PDK_CONFIGS.get(pdk, PDK_CONFIGS["sky130"])
    vdd = config["vdd"]
    classified = classify_ports(info["ports"])

    lines = []
    lines.append(f"* Auto-generated testbench for {info['name'] or 'circuit'}")
    lines.append(f"* Generated by Xyce Discovery agent")
    lines.append(f"*")
    lines.append(f"* ASSUMPTIONS:")
    lines.append(f"*   PDK: {pdk} ({config['description']})")
    lines.append(f"*   VDD: {vdd}V")
    lines.append(f"*   Simulation: {sim_type}, time={sim_time}, step={sim_step}")
    if classified["input"]:
        lines.append(f"*   Inputs: PULSE 0-{vdd}V, period=20ns")
    lines.append(f"*")
    lines.append("")

    # PDK include
    lines.append(config["include"])
    lines.append("")

    # Include the original netlist
    lines.append(f".include \"{netlist_path}\"")
    lines.append("")

    # Instantiate the subcircuit
    if info["name"]:
        port_str = " ".join(info["ports"])
        lines.append(f"XDUT {port_str} {info['name']}")
        lines.append("")

    # Power supplies
    if classified["power"]:
        for p in classified["power"]:
            lines.append(f"V_{p} {p} 0 {vdd}")
    else:
        lines.append(f"VVDD vdd 0 {vdd}")

    if classified["ground"]:
        for g in classified["ground"]:
            lines.append(f"V_{g} {g} 0 0")
    lines.append("")

    # Clock stimulus
    period_ns = 20
    for clk in classified["clock"]:
        half = period_ns / 2
        lines.append(f"V_{clk} {clk} 0 PULSE(0 {vdd} 0 0.1n 0.1n {half}n {period_ns}n)")
    lines.append("")

    # Reset stimulus (active-high: pulse high then low; active-low: pulse low then high)
    for rst in classified["reset"]:
        if "_n" in rst.lower() or "b" in rst.lower()[-1:]:
            # Active-low reset
            lines.append(f"V_{rst} {rst} 0 PULSE(0 {vdd} 5n 0.1n 0.1n 1000n 2000n)")
        else:
            lines.append(f"V_{rst} {rst} 0 PULSE({vdd} 0 5n 0.1n 0.1n 5n 1000n)")
    lines.append("")

    # Input stimulus (staggered pulses)
    for i, inp in enumerate(classified["input"]):
        offset = (i + 1) * 2  # stagger by 2ns
        lines.append(f"V_{inp} {inp} 0 PULSE(0 {vdd} {offset}n 0.1n 0.1n 10n 20n)")
    lines.append("")

    # Analysis
    if "tran" in sim_type or sim_type == "tran+noise":
        lines.append(f".tran {sim_step} {sim_time}")
        lines.append("")

        # Print all interesting nodes
        print_nodes = []
        for cat in ["clock", "reset", "input", "output"]:
            for p in classified[cat]:
                print_nodes.append(f"V({p})")
        if classified["power"]:
            print_nodes.append(f"I(V_{classified['power'][0]})")
        if print_nodes:
            lines.append(f".print tran {' '.join(print_nodes)}")
        lines.append("")

        # Measurements
        lines.append("* === Voltage Measurements ===")
        for p in classified["output"]:
            lines.append(f".measure tran {p}_max MAX V({p})")
            lines.append(f".measure tran {p}_min MIN V({p})")
            lines.append(f".measure tran {p}_trise TRIG V({p}) VAL={vdd*0.1} RISE=1 TARG V({p}) VAL={vdd*0.9} RISE=1")
            lines.append(f".measure tran {p}_tfall TRIG V({p}) VAL={vdd*0.9} FALL=1 TARG V({p}) VAL={vdd*0.1} FALL=1")

        # Propagation delay (first input → first output)
        if classified["input"] and classified["output"]:
            inp0 = classified["input"][0]
            out0 = classified["output"][0]
            lines.append("")
            lines.append("* === Propagation Delay ===")
            lines.append(f".measure tran tpd_rise TRIG V({inp0}) VAL={vdd/2} RISE=1 TARG V({out0}) VAL={vdd/2} FALL=1")
            lines.append(f".measure tran tpd_fall TRIG V({inp0}) VAL={vdd/2} FALL=1 TARG V({out0}) VAL={vdd/2} RISE=1")

        # Power measurements
        lines.append("")
        lines.append("* === Power Measurements ===")
        if classified["power"]:
            vname = f"V_{classified['power'][0]}"
            lines.append(f".measure tran i_supply_avg AVG I({vname})")
            lines.append(f".measure tran i_supply_peak MAX I({vname})")
            lines.append(f".measure tran p_avg AVG {{V({classified['power'][0]})*I({vname})}}")
            lines.append(f".measure tran energy INTEG {{V({classified['power'][0]})*I({vname})}}")

        # Frequency measurements
        if classified["output"]:
            out0 = classified["output"][0]
            lines.append("")
            lines.append("* === Frequency Measurements ===")
            lines.append(f".measure tran period TRIG V({out0}) VAL={vdd/2} RISE=1 TARG V({out0}) VAL={vdd/2} RISE=2")
            lines.append(f".measure tran frequency PARAM={{1/period}}")
            lines.append(f".measure tran duty_cycle_high TRIG V({out0}) VAL={vdd/2} RISE=1 TARG V({out0}) VAL={vdd/2} FALL=1")

        # Signal quality
        if classified["output"]:
            lines.append("")
            lines.append("* === Signal Quality ===")
            for p in classified["output"]:
                lines.append(f".measure tran {p}_overshoot MAX V({p})")
                lines.append(f".measure tran {p}_undershoot MIN V({p})")

    lines.append("")
    lines.append(".end")
    return "\n".join(lines)


def _generate_fallback_testbench(netlist_path: str, pdk: str,
                                  sim_time: str, sim_step: str) -> str:
    """Fallback: just add .tran and .print to existing netlist."""
    config = PDK_CONFIGS.get(pdk, PDK_CONFIGS["sky130"])
    with open(netlist_path, 'r', errors='replace') as f:
        content = f.read()

    # Remove any existing .end
    content = re.sub(r'^\s*\.end\s*$', '', content, flags=re.MULTILINE | re.IGNORECASE)

    lines = [content.rstrip(), ""]
    lines.append(f".tran {sim_step} {sim_time}")
    lines.append(f".print tran V(*)")
    lines.append(".end")
    return "\n".join(lines)


def _prepend_pdk_include(netlist_path: str, pdk: str) -> str:
    """Prepend PDK include to existing netlist."""
    config = PDK_CONFIGS.get(pdk, PDK_CONFIGS["sky130"])
    with open(netlist_path, 'r', errors='replace') as f:
        content = f.read()

    # Insert include after first comment/title line
    lines = content.split('\n')
    insert_idx = 0
    for i, line in enumerate(lines):
        if line.strip() and not line.startswith('*'):
            insert_idx = i
            break

    lines.insert(insert_idx, config["include"])
    return "\n".join(lines)


def generate_noise_testbench(netlist_path: str, pdk: str = "sky130") -> str:
    """Generate a noise analysis testbench."""
    info = parse_subcircuit(netlist_path)
    if not info or not info["name"]:
        return ""

    config = PDK_CONFIGS.get(pdk, PDK_CONFIGS["sky130"])
    vdd = config["vdd"]
    classified = classify_ports(info["ports"])

    if not classified["input"] or not classified["output"]:
        return ""

    inp0 = classified["input"][0]
    out0 = classified["output"][0]

    lines = [
        f"* Noise analysis testbench for {info['name']}",
        f"* Generated by Xyce Discovery agent",
        "",
        config["include"],
        "",
        f'.include "{netlist_path}"',
        "",
        f"XDUT {' '.join(info['ports'])} {info['name']}",
        "",
    ]

    # DC bias for noise analysis
    for p in classified["power"]:
        lines.append(f"V_{p} {p} 0 {vdd}")
    for g in classified["ground"]:
        lines.append(f"V_{g} {g} 0 0")

    # AC source on input
    lines.append(f"V_{inp0} {inp0} 0 DC {vdd/2} AC 1")
    lines.append("")

    # Noise analysis
    lines.append(f".noise V({out0}) V_{inp0} dec 10 1 1G")
    lines.append(f".print noise INOISE ONOISE")
    lines.append("")
    lines.append(f".measure noise inoise_1k FIND INOISE AT=1e3")
    lines.append(f".measure noise inoise_1M FIND INOISE AT=1e6")
    lines.append(f".measure noise onoise_1k FIND ONOISE AT=1e3")
    lines.append(f".measure noise onoise_1M FIND ONOISE AT=1e6")
    lines.append("")
    lines.append(".end")
    return "\n".join(lines)


# ============= OUTPUT PARSING =============

def parse_prn_file(prn_path: str) -> Dict[str, Any]:
    """Parse a Xyce .prn waveform file.

    Returns dict with column names and basic statistics.
    """
    if not os.path.exists(prn_path):
        return {"error": f"File not found: {prn_path}"}

    with open(prn_path, 'r', errors='replace') as f:
        lines = f.readlines()

    if not lines:
        return {"error": "Empty file"}

    # Skip header lines (lines starting with "Index" or containing column names)
    header_line = None
    data_start = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("Index") or stripped.startswith("{"):
            header_line = stripped
            data_start = i + 1
            break
        if stripped.startswith("End of"):
            break

    if header_line is None:
        return {"error": "Could not find header in .prn file", "lines": len(lines)}

    # Parse column names
    columns = header_line.split()
    data_lines = [l.strip() for l in lines[data_start:] if l.strip() and not l.startswith("End")]

    result = {
        "columns": columns,
        "num_points": len(data_lines),
        "stats": {},
    }

    # Parse numeric data for statistics
    if data_lines:
        try:
            values = []
            for dl in data_lines:
                vals = [float(x) for x in dl.split()]
                values.append(vals)

            for col_idx, col_name in enumerate(columns):
                if col_idx < len(values[0]):
                    col_vals = [v[col_idx] for v in values if col_idx < len(v)]
                    result["stats"][col_name] = {
                        "min": min(col_vals),
                        "max": max(col_vals),
                        "mean": sum(col_vals) / len(col_vals),
                    }
        except (ValueError, IndexError):
            pass

    return result


def parse_mt0_file(mt0_path: str) -> Dict[str, float]:
    """Parse a Xyce .mt0 measurement results file.

    Returns dict mapping measurement name to value.
    """
    if not os.path.exists(mt0_path):
        return {}

    with open(mt0_path, 'r', errors='replace') as f:
        content = f.read()

    measurements = {}
    # Xyce .mt0 format: header line with names, data line with values
    lines = [l.strip() for l in content.split('\n') if l.strip()]
    if len(lines) >= 2:
        names = lines[0].split()
        values = lines[1].split()
        for name, val in zip(names, values):
            try:
                measurements[name] = float(val)
            except ValueError:
                measurements[name] = val

    return measurements


def generate_summary(basename: str, log_path: str) -> str:
    """Generate a summary report from Xyce output files.

    Args:
        basename: Base path for output files (e.g., /output/circuit).
        log_path: Path to the simulation log.

    Returns:
        Formatted summary string.
    """
    lines = []
    lines.append("=" * 60)
    lines.append("XYCE SPICE SIMULATION SUMMARY")
    lines.append("=" * 60)
    lines.append("")

    # Parse simulation status from log
    if os.path.exists(log_path):
        with open(log_path, 'r', errors='replace') as f:
            log_content = f.read()

        if "Simulation Complete" in log_content or "End of Xyce" in log_content:
            lines.append("Status: COMPLETED SUCCESSFULLY")
        elif "error" in log_content.lower():
            lines.append("Status: COMPLETED WITH ERRORS")
        else:
            lines.append("Status: UNKNOWN")

        # Extract device count
        m = re.search(r'Total Devices\s+(\d+)', log_content)
        if m:
            lines.append(f"Total devices: {m.group(1)}")

        # Extract simulation time
        m = re.search(r'Total Simulation Solvers Run Time\s+=\s+([\d.]+)', log_content)
        if m:
            lines.append(f"Simulation time: {m.group(1)} seconds")
    else:
        lines.append("Status: NO LOG FILE")
    lines.append("")

    # Parse waveform statistics
    prn_path = f"{basename}.prn"
    if os.path.exists(prn_path):
        prn_data = parse_prn_file(prn_path)
        lines.append(f"--- Waveform Data ---")
        lines.append(f"  Data points: {prn_data.get('num_points', 0)}")
        lines.append(f"  Columns: {', '.join(prn_data.get('columns', []))}")
        for col, stats in prn_data.get("stats", {}).items():
            if col.lower() not in ("index", "time"):
                lines.append(f"  {col}: min={stats['min']:.6g}, max={stats['max']:.6g}")
        lines.append("")

    # Parse measurements
    mt0_path = f"{basename}.mt0"
    if os.path.exists(mt0_path):
        measurements = parse_mt0_file(mt0_path)
        if measurements:
            lines.append("--- Measurements ---")
            for name, val in measurements.items():
                if isinstance(val, float):
                    lines.append(f"  {name}: {val:.6g}")
                else:
                    lines.append(f"  {name}: {val}")
            lines.append("")

    # List output files
    lines.append("--- Output Files ---")
    dirname = os.path.dirname(basename)
    if os.path.isdir(dirname):
        for f in sorted(os.listdir(dirname)):
            fpath = os.path.join(dirname, f)
            if os.path.isfile(fpath):
                size = os.path.getsize(fpath)
                lines.append(f"  {f} ({size} bytes)")

    return "\n".join(lines)


# ============= CLI ENTRY POINTS =============

def cli_generate_testbench():
    """CLI: Generate testbench from netlist."""
    parser = argparse.ArgumentParser(description="Generate Xyce testbench")
    parser.add_argument("--netlist", required=True)
    parser.add_argument("--pdk", default="sky130")
    parser.add_argument("--sim-type", default="tran")
    parser.add_argument("--sim-time", default="100n")
    parser.add_argument("--sim-step", default="0.1n")
    parser.add_argument("--output", required=True)
    args = parser.parse_args(sys.argv[2:])

    tb = generate_testbench(args.netlist, args.pdk, args.sim_type,
                            args.sim_time, args.sim_step)
    with open(args.output, 'w') as f:
        f.write(tb)
    print(f"Testbench written to {args.output}")


def cli_generate_noise():
    """CLI: Generate noise testbench."""
    parser = argparse.ArgumentParser(description="Generate noise testbench")
    parser.add_argument("--netlist", required=True)
    parser.add_argument("--pdk", default="sky130")
    parser.add_argument("--output", required=True)
    args = parser.parse_args(sys.argv[2:])

    tb = generate_noise_testbench(args.netlist, args.pdk)
    if tb:
        with open(args.output, 'w') as f:
            f.write(tb)
        print(f"Noise testbench written to {args.output}")
    else:
        print("Could not generate noise testbench (no subcircuit or missing I/O ports)")
        sys.exit(1)


def cli_parse_results():
    """CLI: Parse simulation results."""
    parser = argparse.ArgumentParser(description="Parse Xyce results")
    parser.add_argument("--basename", required=True)
    parser.add_argument("--log", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(sys.argv[2:])

    summary = generate_summary(args.basename, args.log)
    with open(args.output, 'w') as f:
        f.write(summary)
    print(summary)


def cli_prepend_pdk():
    """CLI: Prepend PDK includes to a netlist that has analysis statements."""
    parser = argparse.ArgumentParser(description="Prepend PDK includes")
    parser.add_argument("--netlist", required=True)
    parser.add_argument("--pdk", default="sky130")
    parser.add_argument("--output", required=True)
    args = parser.parse_args(sys.argv[2:])

    result = _prepend_pdk_include(args.netlist, args.pdk)
    with open(args.output, 'w') as f:
        f.write(result)
    print(f"PDK-prepended netlist written to {args.output}")


if __name__ == "__main__":
    if len(sys.argv) >= 2:
        cmd = sys.argv[1]
        if cmd == "generate-testbench":
            cli_generate_testbench()
        elif cmd == "generate-noise-testbench":
            cli_generate_noise()
        elif cmd == "parse-results":
            cli_parse_results()
        elif cmd == "prepend-pdk":
            cli_prepend_pdk()
        else:
            print(f"Unknown command: {cmd}", file=sys.stderr)
            print("Available: generate-testbench, generate-noise-testbench, parse-results", file=sys.stderr)
            sys.exit(1)
    else:
        print("Xyce utilities. Commands: generate-testbench, generate-noise-testbench, parse-results")
