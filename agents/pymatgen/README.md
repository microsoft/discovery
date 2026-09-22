# Pymatgen Agent for Microsoft Discovery

> Materials analysis library (the engine behind the Materials Project). Analyzes crystal structures, symmetry, densities, and generates I/O for common DFT codes.

**Domain:** Materials Science  
**Upstream project:** [https://pymatgen.org](https://pymatgen.org)  
**License:** MIT  
**Compute:** CPU-only (no GPU required)

## Capabilities

- Parse CIF and POSCAR crystal structures
- Determine space group and symmetry
- Compute density, volume, and composition

## Tool Actions

| Action | Description |
|---|---|
| `analyze_structure` | Analyze crystal structures: space group, density, lattice parameters, and composition. |

## Container Dependencies

- **pip:** pymatgen

## Usage

This agent is invoked through Microsoft Discovery. Provide an input
directory with your data files and an output directory for results.
Each action writes `final_results.json` plus detailed artifacts.
