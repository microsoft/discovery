# P2Rank Agent for Microsoft Discovery

> Machine-learning prediction of ligand-binding sites from protein structure. Fast, template-free, and CPU-only (Java).

**Domain:** Structural Biology  
**Upstream project:** [https://github.com/rdk/p2rank](https://github.com/rdk/p2rank)  
**License:** MIT  
**Compute:** CPU-only (no GPU required)

## Capabilities

- Predict and rank ligand-binding sites
- Output residue-level pocket scores

## Tool Actions

| Action | Description |
|---|---|
| `predict_sites` | Predict ligand-binding sites for each PDB structure with P2Rank. |

## Container Dependencies

- **conda-forge:** openjdk=17

## Usage

This agent is invoked through Microsoft Discovery. Provide an input
directory with your data files and an output directory for results.
Each action writes `final_results.json` plus detailed artifacts.
