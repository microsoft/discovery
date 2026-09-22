# Foldseek Agent for Microsoft Discovery

> Ultra-fast protein structure search and structural alignment, scaling structural comparison to millions of entries on CPU.

**Domain:** Structural Search  
**Upstream project:** [https://github.com/steineggerlab/foldseek](https://github.com/steineggerlab/foldseek)  
**License:** GPL-3.0  
**Compute:** CPU-only (no GPU required)

## Overview

This agent packages the upstream project referenced above as a set of Discovery
tool actions. You describe your task in natural language and the agent selects and
runs the appropriate action, returning a structured summary of the results. See the
**Capabilities** and **Tools** sections below for the specific operations it supports.

## Capabilities

- Structure-to-structure search (easy-search)
- All-vs-all structural comparison

## Architecture

The chat model interprets your request and invokes one of the containerized tool
actions listed under **Tools**. Each action reads files from the input directory,
runs the requested operation inside an isolated container, and writes
`final_results.json` plus any detailed artifacts to the output directory. Runs are
stateless — no data is retained between invocations.

## Tools

| Action | Description |
|---|---|
| `structure_search` | Run Foldseek easy-search of query structures against a target set of structures. |

## Container Dependencies

- **conda-forge:** foldseek

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
