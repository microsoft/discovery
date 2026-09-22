# Phonopy Agent for Microsoft Discovery

> Phonon and lattice-dynamics analysis from force constants produced by DFT codes: band structures, DOS, and thermal properties.

**Domain:** Materials Science  
**Upstream project:** [https://phonopy.github.io/phonopy/](https://phonopy.github.io/phonopy/)  
**License:** BSD-3-Clause  
**Compute:** CPU-only (no GPU required)

## Capabilities

- Generate displacement supercells
- Compute phonon DOS and thermal properties

## Tool Actions

| Action | Description |
|---|---|
| `compute_phonons` | Generate displacements and report supercell info from a crystal structure. |

## Container Dependencies

- **pip:** phonopy

## Usage

This agent is invoked through Microsoft Discovery. Provide an input
directory with your data files and an output directory for results.
Each action writes `final_results.json` plus detailed artifacts.
