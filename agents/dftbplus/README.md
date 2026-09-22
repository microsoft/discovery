# DFTB+ Agent for Microsoft Discovery

> Density-functional tight-binding: fast approximate quantum simulations of large molecular and periodic systems on CPU.

**Domain:** Quantum Chemistry  
**Upstream project:** [https://dftbplus.org](https://dftbplus.org)  
**License:** LGPL-3.0  
**Compute:** CPU-only (no GPU required)

## Capabilities

- DFTB total-energy and geometry calculations
- Supports molecular and periodic systems

## Tool Actions

| Action | Description |
|---|---|
| `run_dftb` | Run DFTB+ using an hsd input file placed in the input directory. |

## Container Dependencies

- **conda-forge:** dftbplus

## Notes

DFTB+ requires Slater-Koster parameter files for the elements in your system; supply them in the input directory.

## Usage

This agent is invoked through Microsoft Discovery. Provide an input
directory with your data files and an output directory for results.
Each action writes `final_results.json` plus detailed artifacts.
