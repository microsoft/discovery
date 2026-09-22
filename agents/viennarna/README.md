# ViennaRNA Agent for Microsoft Discovery

> RNA secondary-structure prediction and thermodynamics: minimum free energy folding, partition functions, and base-pair probabilities.

**Domain:** RNA Bioinformatics  
**Upstream project:** [https://www.tbi.univie.ac.at/RNA/](https://www.tbi.univie.ac.at/RNA/)  
**License:** Custom (free for academic/non-commercial)  
**Compute:** CPU-only (no GPU required)

## Capabilities

- Minimum free energy secondary structure
- Ensemble free energy and base-pair probabilities

## Tool Actions

| Action | Description |
|---|---|
| `fold_rna` | Predict MFE secondary structure for each RNA sequence in the input FASTA. |

## Container Dependencies

- **conda-forge:** viennarna, biopython

## Usage

This agent is invoked through Microsoft Discovery. Provide an input
directory with your data files and an output directory for results.
Each action writes `final_results.json` plus detailed artifacts.
