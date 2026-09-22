# FreeSASA Agent for Microsoft Discovery

> Compute solvent-accessible surface area (SASA) of proteins with the Shrake-Rupley and Lee-Richards algorithms, per-atom and per-residue.

**Domain:** Structural Biology  
**Upstream project:** [https://freesasa.github.io](https://freesasa.github.io)  
**License:** MIT  
**Compute:** CPU-only (no GPU required)

## Capabilities

- Total and per-residue SASA
- Polar / apolar decomposition

## Tool Actions

| Action | Description |
|---|---|
| `compute_sasa` | Compute solvent-accessible surface area for each protein structure. |

## Container Dependencies

- **conda-forge:** freesasa

## Usage

This agent is invoked through Microsoft Discovery. Provide an input
directory with your data files and an output directory for results.
Each action writes `final_results.json` plus detailed artifacts.
