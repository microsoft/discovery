# Mordred Agent for Microsoft Discovery

> Compute over 1800 2D and 3D molecular descriptors from SMILES for QSAR and machine-learning feature generation.

**Domain:** Cheminformatics  
**Upstream project:** [https://github.com/mordred-descriptor/mordred](https://github.com/mordred-descriptor/mordred)  
**License:** BSD-3-Clause  
**Compute:** CPU-only (no GPU required)

## Capabilities

- 1800+ 2D/3D molecular descriptors
- Batch descriptor calculation to CSV/JSON

## Tool Actions

| Action | Description |
|---|---|
| `compute_descriptors` | Compute Mordred 2D descriptors for each SMILES in the input files. |

## Container Dependencies

- **conda-forge:** rdkit
- **pip:** mordredcommunity

## Usage

This agent is invoked through Microsoft Discovery. Provide an input
directory with your data files and an output directory for results.
Each action writes `final_results.json` plus detailed artifacts.
