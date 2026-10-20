# DSSP Agent for Microsoft Discovery

> Assign protein secondary structure (helices, sheets, turns) from 3D coordinates using the classic Kabsch-Sander DSSP algorithm.

**Domain:** Structural Biology  
**Upstream project:** [https://github.com/PDB-REDO/dssp](https://github.com/PDB-REDO/dssp)  
**License:** BSD-2-Clause  
**Compute:** CPU-only (no GPU required)

## Overview

This agent packages the upstream project referenced above as a set of Discovery
tool actions. You describe your task in natural language and the agent selects and
runs the appropriate action, returning a structured summary of the results. See the
**Capabilities** and **Tools** sections below for the specific operations it supports.

## Capabilities

- Assign per-residue secondary structure
- Summarize helix / sheet / coil content

## Architecture

The chat model interprets your request and invokes one of the containerized tool
actions listed under **Tools**. Each action reads files from the input directory,
runs the requested operation inside an isolated container, and writes
`final_results.json` plus any detailed artifacts to the output directory. Runs are
stateless — no data is retained between invocations.

## Tools

| Action | Description |
|---|---|
| `assign_secondary_structure` | Run DSSP on each PDB/mmCIF structure and produce per-residue secondary-structure assignments. |

## Container Dependencies

- **conda-forge:** dssp

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
