# DSSP Agent for Microsoft Discovery

> Assign protein secondary structure (helices, sheets, turns) from 3D coordinates using the classic Kabsch-Sander DSSP algorithm.

**Domain:** Structural Biology  
**Upstream project:** [https://github.com/PDB-REDO/dssp](https://github.com/PDB-REDO/dssp)  
**License:** BSD-2-Clause  
**Compute:** CPU-only (no GPU required)

## Capabilities

- Assign per-residue secondary structure
- Summarize helix / sheet / coil content

## Tool Actions

| Action | Description |
|---|---|
| `assign_secondary_structure` | Run DSSP on each PDB/mmCIF structure and produce per-residue secondary-structure assignments. |

## Container Dependencies

- **conda-forge:** dssp

## Usage

This agent is invoked through Microsoft Discovery. Provide an input
directory with your data files and an output directory for results.
Each action writes `final_results.json` plus detailed artifacts.
