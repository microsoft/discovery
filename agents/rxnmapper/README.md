# RXNMapper Agent for Microsoft Discovery

> Atom-atom mapping of chemical reactions using an attention-based transformer. Runs on CPU for reaction SMILES.

**Domain:** Cheminformatics  
**Upstream project:** [https://github.com/rxn4chemistry/rxnmapper](https://github.com/rxn4chemistry/rxnmapper)  
**License:** MIT  
**Compute:** CPU-only (no GPU required)

## Capabilities

- Atom-atom mapping for reaction SMILES
- Confidence scores per mapping

## Tool Actions

| Action | Description |
|---|---|
| `map_reactions` | Compute atom-atom mappings and confidence for reaction SMILES (one per line). |

## Container Dependencies

- **pip:** setuptools<81, rxnmapper, rdkit

## Usage

This agent is invoked through Microsoft Discovery. Provide an input
directory with your data files and an output directory for results.
Each action writes `final_results.json` plus detailed artifacts.
