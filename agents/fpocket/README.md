# fpocket Agent for Microsoft Discovery

> Geometry-based detection of ligand-binding pockets and cavities on protein structures using Voronoi tessellation and alpha spheres.

**Domain:** Structural Biology  
**Upstream project:** [https://github.com/Discngine/fpocket](https://github.com/Discngine/fpocket)  
**License:** MIT  
**Compute:** CPU-only (no GPU required)

## Capabilities

- Detect and rank binding pockets on PDB structures
- Report pocket volume and druggability score

## Tool Actions

| Action | Description |
|---|---|
| `detect_pockets` | Run fpocket on each PDB structure and collect detected pocket information. |

## Container Dependencies

- **conda-forge:** fpocket

## Usage

This agent is invoked through Microsoft Discovery. Provide an input
directory with your data files and an output directory for results.
Each action writes `final_results.json` plus detailed artifacts.
