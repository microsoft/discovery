# spglib Agent for Microsoft Discovery

> Crystal symmetry analysis: find space groups, symmetry operations, standardized cells, and Wyckoff positions.

**Domain:** Materials Science  
**Upstream project:** [https://spglib.readthedocs.io](https://spglib.readthedocs.io)  
**License:** BSD-3-Clause  
**Compute:** CPU-only (no GPU required)

## Capabilities

- Determine space group and international symbol
- Count symmetry operations and standardize cells

## Tool Actions

| Action | Description |
|---|---|
| `analyze_symmetry` | Determine the space group and symmetry operations for each crystal structure. |

## Container Dependencies

- **pip:** spglib, ase

## Usage

This agent is invoked through Microsoft Discovery. Provide an input
directory with your data files and an output directory for results.
Each action writes `final_results.json` plus detailed artifacts.
