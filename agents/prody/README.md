# ProDy Agent for Microsoft Discovery

> Protein dynamics analysis: elastic network models and normal-mode analysis (ANM/GNM) to study collective motions without MD.

**Domain:** Structural Biology  
**Upstream project:** [http://prody.csb.pitt.edu](http://prody.csb.pitt.edu)  
**License:** MIT  
**Compute:** CPU-only (no GPU required)

## Capabilities

- Anisotropic Network Model (ANM) normal modes
- Gaussian Network Model (GNM) fluctuations

## Tool Actions

| Action | Description |
|---|---|
| `normal_mode_analysis` | Compute ANM normal modes and predicted residue fluctuations for each protein. |

## Container Dependencies

- **conda-forge:** prody

## Usage

This agent is invoked through Microsoft Discovery. Provide an input
directory with your data files and an output directory for results.
Each action writes `final_results.json` plus detailed artifacts.
