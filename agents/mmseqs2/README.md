# MMseqs2 Agent for Microsoft Discovery

> Ultra-fast and sensitive sequence search and clustering for huge protein and nucleotide datasets, running efficiently on CPU.

**Domain:** Sequence Search  
**Upstream project:** [https://github.com/soedinglab/MMseqs2](https://github.com/soedinglab/MMseqs2)  
**License:** GPL-3.0  
**Compute:** CPU-only (no GPU required)

## Capabilities

- Fast many-against-many sequence search
- Sequence clustering (easy-cluster)

## Tool Actions

| Action | Description |
|---|---|
| `search` | Search query sequences against a target FASTA with MMseqs2 easy-search. |
| `cluster` | Cluster sequences in a FASTA file with MMseqs2 easy-cluster. |

## Container Dependencies

- **conda-forge:** mmseqs2

## Usage

This agent is invoked through Microsoft Discovery. Provide an input
directory with your data files and an output directory for results.
Each action writes `final_results.json` plus detailed artifacts.
