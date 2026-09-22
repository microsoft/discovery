# Multiple Sequence Alignment (MAFFT/MUSCLE/Clustal Omega) Agent for Microsoft Discovery

> Multiple sequence alignment via MAFFT, MUSCLE, or Clustal Omega for protein and nucleotide sequences.

**Domain:** Sequence Alignment  
**Upstream project:** [https://mafft.cbrc.jp/alignment/software/](https://mafft.cbrc.jp/alignment/software/)  
**License:** Open source (per tool)  
**Compute:** CPU-only (no GPU required)

## Capabilities

- Align sequences with MAFFT, MUSCLE, or Clustal Omega
- Selectable aligner via parameter

## Tool Actions

| Action | Description |
|---|---|
| `align` | Build a multiple sequence alignment from a FASTA file. |

## Container Dependencies

- **conda-forge:** mafft, muscle, clustalo

## Usage

This agent is invoked through Microsoft Discovery. Provide an input
directory with your data files and an output directory for results.
Each action writes `final_results.json` plus detailed artifacts.
