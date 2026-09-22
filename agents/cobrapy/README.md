# COBRApy Agent for Microsoft Discovery

> Constraint-based reconstruction and analysis of genome-scale metabolic models: flux-balance analysis, FVA, and gene knockouts.

**Domain:** Systems Biology  
**Upstream project:** [https://opencobra.github.io/cobrapy/](https://opencobra.github.io/cobrapy/)  
**License:** LGPL-2.0/GPL-2.0  
**Compute:** CPU-only (no GPU required)

## Capabilities

- Flux-balance analysis (FBA)
- Flux variability analysis and single-gene knockouts

## Tool Actions

| Action | Description |
|---|---|
| `flux_balance_analysis` | Load SBML metabolic models and run flux-balance analysis, reporting the objective value. |

## Container Dependencies

- **pip:** cobra

## Usage

This agent is invoked through Microsoft Discovery. Provide an input
directory with your data files and an output directory for results.
Each action writes `final_results.json` plus detailed artifacts.
