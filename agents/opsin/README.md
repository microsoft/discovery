# OPSIN Agent for Microsoft Discovery

> Open Parser for Systematic IUPAC Nomenclature: convert chemical names into structures (SMILES/InChI/CML).

**Domain:** Cheminformatics  
**Upstream project:** [https://github.com/dan2097/opsin](https://github.com/dan2097/opsin)  
**License:** MIT  
**Compute:** CPU-only (no GPU required)

## Capabilities

- Convert IUPAC names to SMILES and InChI
- Batch name-to-structure conversion

## Tool Actions

| Action | Description |
|---|---|
| `name_to_structure` | Convert chemical names (one per line in a text file) to SMILES. |

## Container Dependencies

- **conda-forge:** openjdk
- **pip:** py2opsin

## Usage

This agent is invoked through Microsoft Discovery. Provide an input
directory with your data files and an output directory for results.
Each action writes `final_results.json` plus detailed artifacts.
