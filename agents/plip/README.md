# PLIP (Protein-Ligand Interaction Profiler) Agent for Microsoft Discovery

> Detect and characterize non-covalent protein-ligand interactions (hydrogen bonds, hydrophobic contacts, pi-stacking, salt bridges) from complex structures.

**Domain:** Structural Biology  
**Upstream project:** [https://github.com/pharmai/plip](https://github.com/pharmai/plip)  
**License:** GPL-2.0  
**Compute:** CPU-only (no GPU required)

## Capabilities

- Detect hydrogen bonds, salt bridges, pi-stacking, hydrophobic contacts
- Per-ligand interaction reports

## Tool Actions

| Action | Description |
|---|---|
| `profile_interactions` | Profile non-covalent interactions in each protein-ligand complex PDB. |

## Container Dependencies

- **pip:** plip
- **apt:** openbabel

## Usage

This agent is invoked through Microsoft Discovery. Provide an input
directory with your data files and an output directory for results.
Each action writes `final_results.json` plus detailed artifacts.
