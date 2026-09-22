# rDock Agent for Microsoft Discovery

> Open-source molecular docking for protein-ligand and protein-nucleic acid complexes, with fast CPU-based scoring and pose generation.

**Domain:** Molecular Docking  
**Upstream project:** [https://rdock.github.io](https://rdock.github.io)  
**License:** LGPL-3.0  
**Compute:** CPU-only (no GPU required)

## Capabilities

- Cavity-based ligand docking
- Score and rank docked poses

## Tool Actions

| Action | Description |
|---|---|
| `dock_ligands` | Dock ligands (SD file) into a receptor cavity defined by an rDock prm file. |

## Container Dependencies

- **conda-forge:** rdock

## Usage

This agent is invoked through Microsoft Discovery. Provide an input
directory with your data files and an output directory for results.
Each action writes `final_results.json` plus detailed artifacts.
