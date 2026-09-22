# MDAnalysis Agent for Microsoft Discovery

> Analyze molecular dynamics trajectories from GROMACS, AMBER, NAMD, LAMMPS and more. Computes RMSD, RMSF, radius of gyration, and structural properties over time.

**Domain:** MD Analysis  
**Upstream project:** [https://www.mdanalysis.org](https://www.mdanalysis.org)  
**License:** GPL-2.0  
**Compute:** CPU-only (no GPU required)

## Capabilities

- Read trajectories from all major MD engines
- Compute RMSD, RMSF, and radius of gyration
- Selection-based structural analysis

## Tool Actions

| Action | Description |
|---|---|
| `analyze_trajectory` | Compute RMSD, radius of gyration, and RMSF for a trajectory given a topology and coordinate file. |

## Container Dependencies

- **pip:** MDAnalysis

## Usage

This agent is invoked through Microsoft Discovery. Provide an input
directory with your data files and an output directory for results.
Each action writes `final_results.json` plus detailed artifacts.
