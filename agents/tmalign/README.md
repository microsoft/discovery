# TM-align / US-align Agent for Microsoft Discovery

> Sequence-order-independent protein structural superposition returning TM-score and RMSD for pairwise structure comparison.

**Domain:** Structural Biology  
**Upstream project:** [https://zhanggroup.org/TM-align/](https://zhanggroup.org/TM-align/)  
**License:** Free for academic use  
**Compute:** CPU-only (no GPU required)

## Capabilities

- Pairwise structural superposition
- TM-score and RMSD reporting

## Tool Actions

| Action | Description |
|---|---|
| `align_structures` | Structurally align a query PDB against one or more reference PDBs with TM-align. |

## Container Dependencies

- **conda-forge:** tmalign

## Usage

This agent is invoked through Microsoft Discovery. Provide an input
directory with your data files and an output directory for results.
Each action writes `final_results.json` plus detailed artifacts.
