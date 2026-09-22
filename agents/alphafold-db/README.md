# AlphaFold DB Agent for Microsoft Discovery

> Retrieve precomputed protein structure predictions and confidence scores from the AlphaFold Protein Structure Database (no inference).

**Domain:** Data Source  
**Upstream project:** [https://alphafold.ebi.ac.uk](https://alphafold.ebi.ac.uk)  
**License:** CC-BY-4.0 (data)  
**Compute:** CPU-only (no GPU required)

## Capabilities

- Fetch predicted structures (PDB/mmCIF) by UniProt accession
- Retrieve per-residue pLDDT confidence

## Tool Actions

| Action | Description |
|---|---|
| `fetch_structure` | Fetch AlphaFold predicted structures by UniProt accession (one per line or via parameter). |

## Container Dependencies

- **pip:** requests

## Usage

This agent is invoked through Microsoft Discovery. Provide an input
directory with your data files and an output directory for results.
Each action writes `final_results.json` plus detailed artifacts.
