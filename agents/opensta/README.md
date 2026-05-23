# OpenSTA Static Timing Analysis Agent

An AI-powered agent for running static timing analysis (STA) on gate-level
Verilog netlists using the open-source OpenSTA engine. Supports SKY130 (130nm)
and GF180MCU (180nm) ASIC technology nodes with built-in Liberty timing models.
Auto-generates SDC timing constraints when not provided by the user.

## Overview

- **Scenario**: Post-synthesis static timing analysis -- verifying setup/hold
  timing, identifying critical paths, and checking timing violations
- **Intended user**: Digital design engineers, VLSI students, researchers
  exploring open-source ASIC timing flows
- **Successful outcome**: A detailed timing report showing setup/hold slack,
  critical path details, and violation status (MET or VIOLATED)

## Architecture

```
User (gate-level netlist + optional SDC) --> OpenSTA Agent --> sta_run action
                                                                   |
                                                     OpenSTA binary + Liberty .lib
                                                                   |
                                                     timing report + auto SDC
```

- **Model**: GPT-5-2 (or configured chat model)
- **External dependencies**: None (OpenSTA + PDK libraries bundled in container)
- **Data flow**: Netlist + SDC in --> timing report out
- **Pairs with**: YosysSynth agent (Yosys synthesizes RTL → OpenSTA analyzes timing)

## Prerequisites

- A gate-level Verilog netlist (e.g., from Yosys synthesis)

## Configuration

| Parameter | Description | Example |
|---|---|---|
| `{{CHAT-MODEL}}` | Model deployment name | `gpt-5-2` |

## Tools

| Tool | Description |
|---|---|
| `opensta` | OpenSTA static timing analysis engine (v3.1.0). Container image: `<name>opensta:latest`. Bundles SKY130 and GF180MCU Liberty timing libraries. CPU-only, 2-4 vCPU, 8-16 GB RAM. |

### Actions

| Action | Description | Required Params |
|---|---|---|
| `sta_version` | Display OpenSTA version | none |
| `sta_help` | Show help and available TCL commands | none |
| `sta_run` | Run STA on a netlist (workbench + inputMounts) | `file` |
| `sta_run_from_work` | Run STA from Studio storage asset | `file` |

### Parameters for `sta_run` / `sta_run_from_work`

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `file` | string | yes | -- | Gate-level Verilog netlist filename |
| `sdc` | string | no | auto-generate | SDC timing constraints filename |
| `pdk` | string | no | `sky130` | Target PDK: `sky130` or `gf180mcu` |
| `clk_port` | string | no | `clk` | Clock port name (for auto-SDC) |
| `clk_period` | string | no | `10` | Clock period in ns (for auto-SDC) |

### Supported Technology Nodes

| PDK | Library | Corner | Voltage | Description |
|---|---|---|---|---|
| `sky130` | sky130_fd_sc_hd | tt_025C_1v80 | 1.8V | SkyWater 130nm, 428 cells |
| `gf180mcu` | gf180mcu_fd_sc_mcu7t5v0 | tt_025C_3v30 | 3.3V | GlobalFoundries 180nm |

### Supported input formats
- Gate-level Verilog netlist (.v)
- SDC timing constraints (.sdc) -- optional

### Supported output formats
- Timing report (.txt) with setup/hold slack, critical paths, violations
- Full OpenSTA log (.log)
- Auto-generated SDC (.sdc) -- when no user SDC is provided

## SDC Auto-Generation

When no SDC file is provided, the agent automatically generates timing
constraints with the following assumptions:

- Clock on the specified port (default: `clk`) with the specified period
  (default: 10 ns / 100 MHz)
- Input delay: 20% of clock period on all non-clock inputs
- Output delay: 20% of clock period on all outputs
- Input transition: 0.1 ns on all inputs
- No multi-cycle paths or false paths

The auto-generated SDC is saved to the output directory for reference.
The agent always documents its assumptions in the report when SDC is
auto-generated.

## Usage

### Sample prompts
1. "Run timing analysis on the attached netlist for SKY130"
2. "Check setup and hold timing for my design at 200 MHz"
3. "Analyze timing with a 5ns clock targeting GF180MCU"
4. "Run STA with my SDC constraints file"

## Report Interpretation

| Metric | Meaning | Action |
|---|---|---|
| Setup slack > 0 | Timing met | Design can run at the specified frequency |
| Setup slack < 0 | Setup violation | Reduce frequency or optimize critical paths |
| Hold slack > 0 | Hold timing met | No hold violations |
| Hold slack < 0 | Hold violation | Insert buffers or balance delays |

### Example report output
```
============================================================
OPENSTA STATIC TIMING ANALYSIS REPORT
============================================================

--- Timing Summary ---
  Setup (worst slack): 5.2727 ns  [MET]
  Hold  (worst slack): 0.4349 ns  [MET]

--- Setup Timing ---
Startpoint: en (input port clocked by clk)
Endpoint: overflow (output port clocked by clk)
Path Group: clk
Path Type: max

  Delay    Time   Description
---------------------------------------------------------
   0.00    0.00   clock clk (rise edge)
   ...
           2.73   data arrival time
           8.00   data required time
---------------------------------------------------------
           5.27   slack (MET)
```

## Security

- **Base image**: Azure Linux 3.0 
- **Last scan**: 0 vulnerabilities (CRITICAL: 0, HIGH: 0, MEDIUM: 0, LOW: 0)
- **No network access required**: All liberty models bundled in container

## Build Dependencies

OpenSTA is compiled from source with these dependencies:
- **CUDD 3.0.0** -- BDD library (built from source)
- **Eigen3 3.4.0** -- Linear algebra headers (cmake install from source)
- **GTest 1.14.0** -- Google Test (cmake install from source)
- **TCL** -- Tool Command Language runtime
- **SWIG** -- Simplified Wrapper and Interface Generator

## Known Limitations

- **No parasitics**: SPEF/SPF parasitics not currently supported as input
  (planned for future release)
- **Single-corner analysis**: Only typical corner (tt_025C) is bundled.
  Multi-corner analysis requires additional liberty files.
- **Ideal clocks**: Clock tree delays are not modeled (ideal clock assumption).
  For accurate clock analysis, use `set_propagated_clock` with clock tree data.
- **No power analysis**: Power estimation requires VCD/SAIF activity data
  not currently supported as input.

  ## Contributing

See [CONTRIBUTING.md](https://github.com/microsoft/microsoft-discovery-samples/blob/main/CONTRIBUTING.md).

