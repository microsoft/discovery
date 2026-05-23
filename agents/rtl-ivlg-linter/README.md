# RTL Verilog Linter & Auto-Fixer (Icarus Verilog)

Agent that checks Verilog RTL syntax with the iverilog tool and, when errors
are found, automatically fixes them while preserving design intent. Powered
by [Icarus Verilog](https://github.com/steveicarus/iverilog) v12 inside a
Microsoft Discovery agent.

## Overview

- **Problem solved**: catching and auto-repairing common RTL defects (syntax
  errors, undeclared identifiers, width mismatches, inferred latches,
  port-binding mistakes, blocking vs. nonblocking misuse) before the design
  hits synthesis.
- **Intended user**: hardware design and verification engineers reviewing
  Verilog / SystemVerilog modules.
- **Successful outcome**: the agent runs `iverilog -Wall -t null` against
  the source, parses diagnostics, applies minimal surgical fixes adhering to
  Verilog IEEE 1364-2005, and re-checks until the file passes or 5 iterations
  are exhausted.

## Architecture

`mermaid
flowchart LR
    A[User uploads .v file] --> B[Mounted at /mnt/input/]
    B --> C[Agent calls iverilog_syntax_check]
    C --> D{Errors?}
    D -- No --> E[PASS - report]
    D -- Yes --> F[Agent fixes code]
    F --> G[WriteResource + re-mount]
    G --> C
`

The container ships with `iverilog`, `vvp`, and standard EDA shell
userland (bash, make, find, grep, sed, awk). Actions are bash-native.

## Prerequisites

- Microsoft Discovery workspace with access to a CPU nodepool (no GPU).
- An Azure Container Registry that the published image can be pushed to.
- A model deployment to substitute for the `{{CHAT-MODEL}}` placeholder.

## Configuration

| Parameter | Description | Example |
|---|---|---|
| `{{CHAT-MODEL}}` | Chat model deployment name (resolved at deploy time) | `gpt-5-2` |
| `{{corePythonToolId}}` | ARM resource ID of the deployed `iverilog-tool` tool | `/subscriptions/.../tools/iverilog-tool` |

## Tools

| Tool | Description |
|---|---|
| [`iverilog-tool`](tools/iverilog-tool/tool.yaml) | Icarus Verilog v12 wrapper. Bash-native actions: `iverilog_syntax_check`, `iverilog_simulate`, `iverilog_version`, `iverilog_help`. CPU-only container. Image: `siphyeast2acr.azurecr.io/siphys2r.5-iverilog:latest`. |

**Compute requirements**: 2-4 CPU, 8-16 GB RAM (Standard_E4as_v6).

Inputs are mounted at `/mnt/input/`; artefacts are written to `/mnt/output/`.

## Usage

1. Upload a Verilog source file as session input.
2. Ask the agent to check syntax. Examples:
   - *"Check mux2.v for syntax errors and fix any issues."*
   - *"Lint my ALU module and auto-repair problems."*
   - *"Syntax-check top.v -- fix errors but keep the module name."*
3. The agent will:
   - Call `iverilog_syntax_check` via inputMounts
   - Parse diagnostics into a structured error table
   - Apply minimal fixes following Verilog-2005 coding standards
   - Re-check until clean or 5 iterations exhausted
   - Report final status (PASSED/FAILED) with change summary

## Support

For issues, contact the Discovery catalog team at
[discovery-catalog@microsoft.com](mailto:discovery-catalog@microsoft.com)
or open an issue at the
[discovery-catalog repository](https://github.com/microsoft/discovery-catalog/issues).

## Known Limitations

- iverilog's lint coverage is good but not as exhaustive as commercial
  linters (Synopsys SpyGlass, Cadence HAL).
- SystemVerilog assertion (SVA) coverage is limited by iverilog itself.
- Auto-fix is scoped to Verilog IEEE 1364-2005; SystemVerilog constructs
  are lowered to plain Verilog equivalents.
- Maximum 5 fix iterations per check cycle.

## Contributing

See the repository's CONTRIBUTING guidelines.

## License

This Discovery wrapper (agent definition, tool definition, Dockerfile) is
licensed under the MIT License -- see [`LICENSE`](LICENSE).

## Third-Party Components

See [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) for full attribution.

| Component | Version | License | Source |
|---|---|---|---|
| Icarus Verilog | v12_0 | GPL-2.0 | https://github.com/steveicarus/iverilog |
| Ubuntu | 24.04 LTS | various | https://ubuntu.com |