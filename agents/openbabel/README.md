# Open Babel Agent for Microsoft Discovery

> Universal chemical toolbox for interconverting 100+ chemical file formats, generating 3D coordinates, and computing molecular descriptors and fingerprints.

**Domain:** Cheminformatics  
**Upstream project:** [https://openbabel.org](https://openbabel.org)  
**License:** GPL-2.0  
**Compute:** CPU-only (no GPU required)

## Capabilities

- Convert between SMILES, SDF, MOL2, PDB, XYZ, InChI and 100+ formats
- Generate 3D coordinates and add hydrogens
- Compute molecular descriptors (MW, logP, TPSA, etc.)

## Tool Actions

| Action | Description |
|---|---|
| `convert_formats` | Convert chemistry files from one format to another, optionally generating 3D coordinates. |
| `generate_descriptors` | Compute molecular descriptors (MW, logP, TPSA, HBD, HBA) for each input molecule. |

## Container Dependencies

- **conda-forge:** openbabel

## Usage

This agent is invoked through Microsoft Discovery. Provide an input
directory with your data files and an output directory for results.
Each action writes `final_results.json` plus detailed artifacts.
