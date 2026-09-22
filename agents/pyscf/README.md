# PySCF Agent for Microsoft Discovery

> Python-based ab initio quantum chemistry. Runs Hartree-Fock and DFT single-point energies and geometry properties for small molecules on CPU.

**Domain:** Quantum Chemistry  
**Upstream project:** [https://pyscf.org](https://pyscf.org)  
**License:** Apache-2.0  
**Compute:** CPU-only (no GPU required)

## Overview

This agent packages the upstream project referenced above as a set of Discovery
tool actions. You describe your task in natural language and the agent selects and
runs the appropriate action, returning a structured summary of the results. See the
**Capabilities** and **Tools** sections below for the specific operations it supports.

## Capabilities

- Restricted Hartree-Fock (RHF) single-point energies
- DFT energies with selectable exchange-correlation functional
- Reads XYZ geometries

## Architecture

The chat model interprets your request and invokes one of the containerized tool
actions listed under **Tools**. Each action reads files from the input directory,
runs the requested operation inside an isolated container, and writes
`final_results.json` plus any detailed artifacts to the output directory. Runs are
stateless — no data is retained between invocations.

## Tools

| Action | Description |
|---|---|
| `run_scf` | Run an RHF single-point energy calculation on an XYZ geometry. |
| `run_dft` | Run a DFT single-point energy calculation on an XYZ geometry. |

## Container Dependencies

- **conda-forge:** pyscf

## Usage

This agent is invoked through Microsoft Discovery. Provide an input
directory with your data files and an output directory for results.
Each action writes `final_results.json` plus detailed artifacts.

## Prerequisites

- Access to a Microsoft Discovery workspace with permission to deploy and run agents.
- A compute nodepool that satisfies the **Compute** requirement listed at the top of this document.
- A chat model deployment whose name is substituted for `{{CHAT-MODEL}}` at publish time.

## Configuration

| Parameter | Description | Example |
|---|---|---|
| `{{CHAT-MODEL}}` | Chat model deployment used to plan and drive the tool actions. | `gpt-5-deployment` |
| `input_directory` | Directory containing the input files for a run. | `/data/in` |
| `output_directory` | Directory where `final_results.json` and artifacts are written. | `/data/out` |

## Known Limitations

No known limitations at this time. Please report any issues through the repository's issue tracker.

## Contributing

See the repository [`CONTRIBUTING.md`](../../CONTRIBUTING.md) for the catalog's contribution workflow.
