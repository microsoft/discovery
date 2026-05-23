# Yosys RTL Synthesis Agent

An AI-powered agent for synthesizing Verilog RTL designs to gate-level netlists
using the open-source Yosys synthesis suite. Targets SKY130 (130nm) and GF180MCU
(180nm) ASIC technology nodes. Produces technology-mapped netlists and synthesis
reports with cell count and area statistics.

## Overview

- **Scenario**: ASIC RTL synthesis -- converting behavioral Verilog to a
  technology-mapped gate-level netlist
- **Intended user**: Digital design engineers, VLSI students, researchers
  exploring open-source ASIC flows
- **Successful outcome**: A valid gate-level Verilog netlist and a report
  showing cell counts, flip-flop counts, and chip area

## Architecture

```
User (Verilog RTL) --> Yosys Agent --> yosys_synth action
                                          |
                                    Yosys binary + Liberty .lib
                                          |
                                    gate-level netlist + report
```

- **Model**: GPT-4o (or configured chat model)
- **External dependencies**: None (Yosys + PDK libraries bundled in container)
- **Data flow**: Verilog in --> netlist + report out

## Prerequisites

- Azure subscription with Discovery workspace
- Chat model deployment (GPT-4o recommended)
- No external API keys or services required

## Configuration

| Parameter | Description | Example |
|---|---|---|
| `{{CHAT-MODEL}}` | Model deployment name | `gpt-4o-deployment` |

## Tools

| Tool | Description |
|---|---|
| `yosys` | Yosys open-source synthesis suite (v0.45). Container image: `siphyeast2acr.azurecr.io/yosys:latest`. Bundles SKY130 and GF180MCU Liberty timing libraries. CPU-only, 2-4 vCPU, 8-16 GB RAM. |

### Supported input formats
- Verilog (.v)
- SystemVerilog (.sv) -- basic support

### Supported output formats
- Gate-level Verilog netlist (.v)
- Synthesis report (.txt)
- Full Yosys log (.log)

## Usage

### From Discovery Studio
1. Deploy the agent with your chat model
2. Attach a Verilog file as a storage asset
3. Ask: "Synthesize this design for SKY130"
4. Agent calls `yosys_synth_from_work` automatically

### From Workbench
1. Provide Verilog source (paste or reference a file)
2. Specify target PDK (sky130 or gf180mcu) and top module
3. Agent mounts files and calls `yosys_synth`
4. Review the synthesis report

### Sample prompts
1. "Synthesize this 16-bit counter targeting SKY130"
2. "Run synthesis on my ALU design for GF180MCU with top module alu_top"
3. "What is the cell count and area for this design on SKY130?"

## Support

- Issues: https://github.com/microsoft/microsoft-discovery-samples/issues
- Contact: discovery-team@microsoft.com

## Known Limitations

- **No timing analysis**: Yosys provides area/cell stats but not timing (STA).
  Use OpenSTA for timing closure.
- **Limited SystemVerilog**: Yosys supports basic SV constructs but not full
  SV-2017. Complex SV may require preprocessing.
- **Single-clock designs**: Multi-clock domain handling requires manual
  constraint specification not currently supported.
- **No power analysis**: Power estimation requires additional tools (e.g.,
  OpenROAD power analysis).

## Contributing

See [CONTRIBUTING.md](https://github.com/microsoft/microsoft-discovery-samples/blob/main/CONTRIBUTING.md).
