# ASE (Atomic Simulation Environment) Agent for Microsoft Discovery

> Workflow layer for atomistic simulations. Builds, manipulates, and optimizes atomic structures and orchestrates calculators, with a built-in EMT potential for fast CPU relaxations.

**Domain:** Atomistic Simulation  
**Upstream project:** [https://wiki.fysik.dtu.dk/ase/](https://wiki.fysik.dtu.dk/ase/)  
**License:** LGPL-2.1  
**Compute:** CPU-only (no GPU required)

## Capabilities

- Read/write dozens of atomic structure formats
- Geometry optimization with BFGS
- Compute energies with the EMT calculator

## Tool Actions

| Action | Description |
|---|---|
| `optimize_structure` | Relax an atomic structure using the EMT potential and BFGS optimizer. |

## Container Dependencies

- **pip:** ase

## Usage

This agent is invoked through Microsoft Discovery. Provide an input
directory with your data files and an output directory for results.
Each action writes `final_results.json` plus detailed artifacts.
