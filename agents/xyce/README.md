# sim-xyce — Xyce SPICE Circuit Simulator Agent

Run transistor-level SPICE simulations using [Sandia Xyce](https://xyce.sandia.gov/) on the Microsoft Discovery platform. Supports transient, DC, AC, and noise analyses with built-in **SKY130** and **GF180MCU** PDK models.

## Overview

`sim-xyce` is a containerized circuit simulation agent that lets you run transistor-level SPICE analyses without managing simulator installs, PDK setup, or model paths. You upload a SPICE netlist, optionally describe what you want measured in natural language, and the agent runs the simulation using Sandia National Laboratories' open-source [Xyce](https://xyce.sandia.gov/) simulator and returns waveforms, measurements, and logs.

The agent handles the full end-to-end flow:

- **PDK integration** — Bundles SKY130 (1.8V) and GF180MCU (3.3V) open-source process models so netlists can reference standard device names without any `.include` or `.lib` statements.
- **Testbench auto-generation** — If you upload a bare `.subckt` definition with no analysis directives, the agent synthesizes a transient testbench (supply, stimulus, probes, `.tran` and `.measure` statements) appropriate for the circuit type (inverter, ring oscillator, amplifier, etc.).
- **Multiple analysis types** — Transient (`.tran`), DC sweep (`.dc`), AC small-signal (`.ac`), and noise (`.noise`) analyses are all supported, including combined runs (e.g. `tran+noise`).
- **Structured outputs** — Each run produces parsed waveform data (`.prn`), measurement results (`.mt0`), a human-readable summary, the full simulator log, and the generated testbench (if any), all written to `/output/`.

Typical use cases include characterizing standard cells, verifying analog blocks, sweeping bias points, comparing PDK corners, and quickly sanity-checking netlists exported from schematic or synthesis tools.

## Architecture

`sim-xyce` is packaged as a single Linux container that bundles the Xyce simulator, the open-source PDK model libraries, and a thin orchestration layer that the Discovery platform invokes per action.

```
                ┌──────────────────────────────────────────────────────────┐
                │                  Microsoft Discovery                     │
                │                                                          │
   user prompt  │   ┌─────────────┐        ┌──────────────────────────┐    │
   + netlist  ──┼──▶│   Agent     │──────▶ │  sim-xyce container      │    │
                │   │  (agent.yaml)        │                          │    │
                │   └─────────────┘        │  ┌────────────────────┐  │    │
                │          │               │  │  entrypoint /      │  │    │
                │          │  /input/      │  │  xyce_run.sh       │  │    │
                │          ├──────────────▶│  └─────────┬──────────┘  │    │
                │          │               │            │             │    │
                │          │               │  ┌─────────▼──────────┐  │    │
                │          │               │  │  xyce_utils.py     │  │    │
                │          │               │  │  - PDK selection   │  │    │
                │          │               │  │  - testbench gen   │  │    │
                │          │               │  │  - log parsing     │  │    │
                │          │               │  └─────────┬──────────┘  │    │
                │          │               │            │             │    │
                │          │               │  ┌─────────▼──────────┐  │    │
                │          │               │  │   Xyce simulator   │  │    │
                │          │               │  │  + SKY130 models   │  │    │
                │          │               │  │  + GF180MCU models │  │    │
                │          │               │  └─────────┬──────────┘  │    │
                │          │  /output/     │            │             │    │
                │          │◀──────────────┤  .prn / .mt0 / logs /    │    │
                │          │               │  summary / testbench     │    │
                │          ▼               └──────────────────────────┘    │
                │     results to user                                      │
                └──────────────────────────────────────────────────────────┘
```

**Components**

- **`agent.yaml`** — Declares the agent's actions, parameters, and the tool image to run for each action. The Discovery platform reads this to route user requests.
- **`tools/xyce/tool.yaml`** — Defines the tool image, its entrypoints, and the `/input` / `/output` mount contracts.
- **`Dockerfile`** — Builds a Linux image containing the Xyce binary, the SKY130 (`sky130_fd_pr`) and GF180MCU (`gf180mcu_fd_pr`) model libraries, Python 3, and the orchestration scripts. Alternate Dockerfiles (`Dockerfile.debian12`, `Dockerfile.ubuntu2404`) target specific base distributions.
- **`xyce_run.sh` / `xyce_run_from_work.sh`** — Shell entrypoints that locate the user-supplied netlist, invoke `xyce_utils.py`, then run Xyce against the resolved netlist.
- **`xyce_utils.py`** — The orchestration core: detects whether the netlist needs a testbench, generates one if so, injects the appropriate PDK `.lib` include, runs the simulator, parses `.log`/`.mt0`/`.prn` outputs into a summary report, and writes everything to `/output/`.
- **`test_xyce_utils.py`** — Unit tests for testbench generation and log parsing.

**Execution flow per action**

1. Discovery mounts the user's uploaded files into `/input/` (or `/work/` for `xyce_run_from_work`).
2. The selected entrypoint script invokes `xyce_utils.py` with the requested action parameters (`file`, `pdk`, `sim_type`, `sim_time`, `sim_step`, etc.).
3. `xyce_utils.py` resolves the PDK, generates a testbench if needed, and shells out to `Xyce`.
4. Xyce writes raw `.prn`, `.mt0`, and `.log` artifacts.
5. `xyce_utils.py` post-processes the artifacts into a `_summary.txt` report and copies all outputs to `/output/`.
6. The agent returns the output bundle to the user.

## Prerequisites

Before invoking the `sim-xyce` agent, the following must be in place.

### Platform prerequisites

- **Microsoft Discovery workspace** — The agent runs on Discovery's container-based agent platform. You need access to a workspace where the `sim-xyce` agent is registered (either via the public marketplace or by side-loading the image into your private registry).
- **Container runtime / pool** — A worker pool capable of running the agent image (see [Compute Requirements](#compute-requirements)). The recommended SKU is `Standard_E4as_v6` with 2–4 vCPU and 8–16 GiB of RAM. No GPU is required.
- **Storage mounts** — Either an `inputMounts` configuration that exposes your netlist directory at `/mnt/input` (for `xyce_run`), or a Discovery Studio storage asset attachment that materialises at `/mnt/work` (for `xyce_run_from_work`). An `outputMount` at `/output/` is required for result retrieval.
- **Network egress** — None. The image is fully self-contained; the worker does not need outbound internet access at runtime.

### User / asset prerequisites

- **A SPICE netlist** in one of the supported formats: `.cir`, `.spice`, or `.sp`. The file must be valid SPICE-3 / Xyce syntax. Either:
  - a complete testbench with `.tran` / `.dc` / `.ac` / `.noise` analysis statements, **or**
  - a `.subckt` subcircuit definition (the agent auto-generates a testbench — see [Testbench Auto-Generation](#testbench-auto-generation)).
- **PDK consistency** — Device instantiations must reference models from one of the bundled PDKs (`sky130` or `gf180mcu`). See [SKY130 Device Names](#sky130-device-names) and [GF180MCU Device Names](#gf180mcu-device-names). Custom PDKs require rebuilding the image.
- **Subcircuit instantiation prefix** — Because SKY130 and GF180MCU devices are `.subckt`-based, instantiations must use the `X` prefix (e.g. `XM1 ... sky130_fd_pr__nfet_01v8 ...`), not bare `M`.
- **No external `.include` / `.lib` statements needed** — PDK model libraries are injected automatically. User netlists should **not** contain `.include` or `.lib` directives pointing at PDK files; doing so will cause "file not found" elaboration errors.

### Local development prerequisites *(only if rebuilding the image)*

- **Docker** (or a compatible OCI builder) — required to build `tools/xyce/Dockerfile`.
- **Container registry access** — push permissions on the target ACR (or equivalent) referenced by `tool.yaml`'s `image.acr` field.
- **Python 3.10+** and **pytest** — required to run `tools/xyce/test_xyce_utils.py` locally before publishing a new image.
- **~6 GiB of free disk space** for the image build (Xyce, Trilinos, and both PDK model libraries).

### Knowledge prerequisites

- Basic familiarity with SPICE netlists, subcircuit conventions, and transient/DC/AC analysis.
- Awareness of which PDK your circuit targets (the agent will attempt to auto-detect, but explicit selection via the `pdk` parameter is more reliable for mixed or ambiguous netlists).

## Getting Started

Upload a SPICE netlist (`.cir`, `.spice`, `.sp`) and tell the agent what to simulate:

> "Simulate this inverter circuit for SKY130"
> "Run transient analysis on my ring oscillator with GF180MCU"
> "Simulate with a 5ns clock and measure propagation delay"

The agent auto-generates a testbench if your netlist is a bare `.subckt` definition (no analysis statements). If your netlist already contains `.tran`/`.dc`/`.ac`, it runs directly.

## Supported Technology Nodes

| PDK | VDD | Process | Corner | Model Source |
|-----|-----|---------|--------|--------------|
| **sky130** | 1.8V | SkyWater 130nm | tt | [mkghub/skywater130_fd_pr_models](https://github.com/mkghub/skywater130_fd_pr_models) |
| **gf180mcu** | 3.3V | GlobalFoundries 180nm | typical | [efabless/gf180mcu_fd_pr](https://github.com/efabless/globalfoundries-pdk-libs-gf180mcu_fd_pr) |

Default PDK is `sky130` if not specified.

## Actions

| Action | Description | Required Params |
|--------|-------------|-----------------|
| `xyce_version` | Show Xyce version and capabilities | none |
| `xyce_help` | Show CLI help | none |
| `xyce_run` | Run simulation from `/input/` mount | `file` |
| `xyce_run_from_work` | Run from Studio attachment | `file` |

## Parameters

The `xyce_run` and `xyce_run_from_work` actions accept the same parameter schema. `xyce_version` and `xyce_help` take no parameters.

| Parameter | Type | Required | Default | Allowed Values | Description |
|-----------|------|----------|---------|----------------|-------------|
| `file` | string | **yes** | — | any filename | SPICE netlist filename. Resolved relative to `/mnt/input` for `xyce_run` or `/mnt/work` for `xyce_run_from_work`. Can be a full testbench or a bare `.subckt` definition (in which case a testbench is auto-generated). Supported extensions: `.cir`, `.spice`, `.sp`. |
| `testbench` | string | no | auto-generated | any filename | Optional separate testbench file. If provided, used as-is instead of generating one. Should reference the subcircuit defined in `file`. |
| `pdk` | string | no | `sky130` | `sky130`, `gf180mcu` | Target process design kit. The matching PDK model `.lib` is auto-included; the user does not write `.include` statements. Auto-detected from netlist model references when possible. |
| `sim_type` | string | no | `tran` | `tran`, `noise`, `tran+noise` | Analysis type. `tran` runs a transient analysis; `noise` runs a small-signal noise analysis; `tran+noise` runs both back-to-back and bundles their outputs. |
| `sim_time` | string | no | `100n` | SPICE time literal | Transient end time. Accepts standard SPICE suffixes: `p` (1e-12), `n` (1e-9), `u` (1e-6), `m` (1e-3). Example: `5u` = 5 microseconds. |
| `sim_step` | string | no | `0.1n` | SPICE time literal | Transient time step. Should be a small fraction of `sim_time` and significantly smaller than the fastest signal edge. Example: `0.01n` for sub-nanosecond edges. |

### Parameter Notes

- **`file` discovery** — If only one `.cir`/`.spice`/`.sp` exists in the input mount, the agent will use it even if `file` is omitted in a natural-language prompt; explicit `file` always wins.
- **PDK auto-detection** — If the netlist references `sky130_fd_pr__*` device models, `pdk=sky130` is inferred; if it references `nfet_03v3` / `pfet_03v3` / `*_06v0`, `pdk=gf180mcu` is inferred. An explicit `pdk` parameter overrides detection.
- **`sim_type` interactions** — Noise analysis requires AC-relevant stimulus; for purely digital netlists prefer `tran`. `tran+noise` is convenient when you want both characterization runs in one invocation.

## Tools

`sim-xyce` exposes a single tool image (`xyce`) defined in [`tools/xyce/tool.yaml`](tools/xyce/tool.yaml). The image surfaces four actions; each is implemented either as an inline shell command or via one of the bundled scripts.

| Tool / Script | Implements Action(s) | Description |
|---------------|----------------------|-------------|
| `Xyce -v` / `Xyce -capabilities` *(inline)* | `xyce_version` | Prints the installed Xyce version string and the list of compiled-in capabilities (parallel support, ADMS device models, etc.). No I/O mounts needed. |
| `Xyce -h` *(inline)* | `xyce_help` | Prints the Xyce CLI help text — all command-line options, file formats, and analysis flags supported by the bundled simulator build. Useful as a quick reference. |
| [`xyce_run.sh`](tools/xyce/xyce_run.sh) | `xyce_run` | Orchestrates a full simulation from the `/mnt/input` mount: discovers the netlist, exports the user parameters, and invokes `xyce_utils.py` to handle PDK injection, testbench generation, simulator execution, and post-processing. Writes results to `/output/`. |
| [`xyce_run_from_work.sh`](tools/xyce/xyce_run_from_work.sh) | `xyce_run_from_work` | Studio-integration variant of `xyce_run`. Copies attached `.cir`/`.spice`/`.sp` files from `/mnt/work` (Studio attachment mount) into `/input/`, then delegates to the same `xyce_utils.py` pipeline. Lets users invoke the agent on files attached in the Discovery Studio UI without uploading them separately. |
| [`xyce_utils.py`](tools/xyce/xyce_utils.py) | *(library)* | Python orchestration core invoked by both run scripts. Responsibilities: resolving the requested PDK and emitting the appropriate `.lib` include, classifying subcircuit ports and synthesizing a testbench when needed, shelling out to `Xyce` with the correct flags for `tran`/`noise`/`tran+noise`, and parsing `.log` / `.mt0` / `.prn` artifacts into a human-readable `_summary.txt` report. |
| [`test_xyce_utils.py`](tools/xyce/test_xyce_utils.py) | *(tests)* | Pytest suite covering testbench generation, PDK resolution, and log/measurement parsing. Run during image build to catch regressions in the orchestration layer. |
| [`Dockerfile`](tools/xyce/Dockerfile) | *(build)* | Default image build. Installs Xyce, Trilinos, the SKY130 and GF180MCU model libraries, Python, and the orchestration scripts. Variants `Dockerfile.debian12` and `Dockerfile.ubuntu2404` pin to specific base distributions; `Dockerfile.probe-aptupgrade` is used to inventory available package upgrades during security review. |

## Output Files

Each simulation produces in `/output/`:

| File | Description |
|------|-------------|
| `{name}.prn` | Waveform data (time + node voltages/currents) |
| `{name}.mt0` | Measurement results (`.measure` values) |
| `{name}_sim.log` | Full Xyce simulation log |
| `{name}_testbench.cir` | Auto-generated testbench (if applicable) |
| `{name}_summary.txt` | Parsed summary report |

## Netlist Format

Xyce accepts standard SPICE netlists. **Important**: SKY130 and GF180MCU models are defined as `.subckt`, so device instantiation requires the **`X` prefix** (not `M`):

```spice
* SKY130 inverter
.subckt inverter in out vdd vss
XM1 out in vdd vdd sky130_fd_pr__pfet_01v8 w=1u l=0.15u
XM2 out in vss vss sky130_fd_pr__nfet_01v8 w=0.5u l=0.15u
.ends inverter
```

```spice
* GF180MCU inverter
.subckt inverter in out vdd vss
XM1 out in vdd vdd pfet_03v3 w=2u l=0.28u
XM2 out in vss vss nfet_03v3 w=1u l=0.28u
.ends inverter
```

PDK model includes are added automatically -- users do NOT need `.include` or `.lib` statements.

## SKY130 Device Names

| Device | Model Name | Description |
|--------|-----------|-------------|
| NMOS 1.8V | `sky130_fd_pr__nfet_01v8` | Core NMOS |
| PMOS 1.8V | `sky130_fd_pr__pfet_01v8` | Core PMOS |
| NMOS 1.8V LVT | `sky130_fd_pr__nfet_01v8_lvt` | Low-Vt NMOS |
| PMOS 1.8V LVT | `sky130_fd_pr__pfet_01v8_lvt` | Low-Vt PMOS |
| PMOS 1.8V HVT | `sky130_fd_pr__pfet_01v8_hvt` | High-Vt PMOS |
| NMOS 5V | `sky130_fd_pr__nfet_g5v0d10v5` | I/O NMOS |
| PMOS 5V | `sky130_fd_pr__pfet_g5v0d10v5` | I/O PMOS |

## GF180MCU Device Names

| Device | Model Name | Description |
|--------|-----------|-------------|
| NMOS 3.3V | `nfet_03v3` | Core 3.3V NMOS |
| PMOS 3.3V | `pfet_03v3` | Core 3.3V PMOS |
| NMOS 6V | `nfet_06v0` | I/O 6V NMOS |
| PMOS 6V | `pfet_06v0` | I/O 6V PMOS |

## Testbench Auto-Generation

When the netlist is a `.subckt` without analysis statements, the tool auto-generates a testbench with:

- **Supply voltages** at PDK-appropriate levels (1.8V / 3.3V)
- **PULSE stimulus** on input ports (0 to VDD, 20ns period)
- **Measurements**: voltage max/min, rise/fall time, propagation delay, supply current, power, frequency, overshoot/undershoot
- **Port classification** (heuristic): `vdd/vcc` -> power, `gnd/vss` -> ground, `clk` -> clock, `rst` -> reset, `out/q/y` -> output, everything else -> input

## Compute Requirements

| Resource | Value |
|----------|-------|
| Recommended SKU | Standard_E4as_v6 |
| CPU | 2-4 vCPU |
| Memory | 8-16 GiB |
| GPU | Not required |

## Image Details

| Property | Value |
|----------|-------|
| Base | Ubuntu 24.04 |
| Xyce | 7.8 (serial, open-source) |
| Trilinos | 14.4.0 |
| Security | CRITICAL=0, HIGH=0 (Trivy scan) |
| License | GPL-3.0 (Xyce), Apache-2.0 (PDK models) |

## Known Limitations

The following limitations apply to the current release. Several are inherent to the bundled open-source toolchain; others are scoping decisions for the first version of the agent.

### PDK and device support

- **Only two PDKs are bundled** — `sky130` (SkyWater 130 nm, 1.8 V core) and `gf180mcu` (GlobalFoundries 180 nm, 3.3 V core). Commercial PDKs (TSMC, Intel, Samsung, etc.) are not included and cannot be added at runtime — the user would need to fork the image and add the model `.lib` files at build time.
- **Single corner per PDK** — Only the typical (`tt` / `typical`) corner is included. SS, FF, SF, FS, and skew corners require rebuilding the image with the full corner model set.
- **No bipolar / no analog-specialty devices** — Bipolar transistors, diodes beyond the PDK defaults, varactors, MIM caps with non-default geometries, and inductors are not pre-configured. Custom `.model` statements in the netlist will still work, but no convenience helpers are provided.
- **Subcircuit instantiation must use `X` prefix** — The SKY130 and GF180MCU models are `.subckt` definitions, not primitive `.model`s. Netlists using bare `M` MOSFET instances against PDK model names will fail to elaborate.

### Simulator capabilities

- **Serial Xyce only** — The image ships the serial build (`Xyce`), not the MPI parallel build (`Xyce_PARALLEL`). Large netlists (>~50k devices) will be CPU-bound and slow.
- **No GPU acceleration** — Xyce does not support GPU simulation; the recommended SKU is CPU-only.
- **Limited analysis set** — Transient (`.tran`), DC sweep (`.dc`), AC (`.ac`), and noise (`.noise`) analyses are supported. Harmonic balance (`.hb`), shooting Newton, and envelope-following analyses are not exposed through agent parameters even when supported by the underlying Xyce build.
- **No mixed-signal / digital event-driven simulation** — Xyce's `.options DIGINIT` and Verilog-A digital primitives are not surfaced; this is a pure analog/transistor-level simulator.

### Testbench auto-generation

- **Heuristic port classification** — Inputs/outputs/power/ground are inferred from port names (`vdd`, `gnd`, `clk`, `rst`, `out`, `q`, `y`, etc.). Non-standard port names may be mis-classified, in which case the user should supply a hand-written `testbench` file.
- **Single-supply assumption** — Auto-generated testbenches use one supply rail at the PDK-default voltage. Dual-supply, level-shifted, or multi-rail circuits need a manual testbench.
- **Fixed stimulus pattern** — Inputs are driven with a 20 ns period `PULSE` from 0 to VDD. Custom waveforms (`PWL`, `SIN`, `EXP`) require a manual testbench.
- **No process / mismatch / Monte Carlo sweeps** — The agent does not generate `.sample` / `.step` / Monte Carlo sweeps; only single-shot simulations are auto-built.

### Input / output

- **File size and count** — Practical limits are governed by the worker pool's storage (20–40 GiB). Very large netlists or massive waveform outputs may exhaust `/output/`.
- **`.raw` binary waveforms not produced** — Outputs are written in Xyce's `.prn` (text-column) format. Binary `nutmeg` / `.raw` formats are not generated; downstream tools that expect them will need a conversion step.
- **Single netlist per invocation** — Each action runs one simulation. Parameter sweeps require multiple agent calls or a hand-written testbench using `.step`.

### Security and licensing

- **Xyce is GPL-3.0** — Outputs (waveforms, measurements, logs) are user data and not GPL-encumbered, but the image itself is GPL-3.0 and must be redistributed under those terms if forked.
- **No network egress from the worker** — All PDK files are baked into the image; the simulator does not (and cannot) reach external endpoints at runtime.

## Support

- Issues: https://github.com/microsoft/microsoft-discovery-samples/issues
- Contact: discovery-team@microsoft.com

## Contributing

See [CONTRIBUTING.md](https://github.com/microsoft/microsoft-discovery-samples/blob/main/CONTRIBUTING.md).
