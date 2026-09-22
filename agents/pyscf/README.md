# PySCF Agent for Microsoft Discovery

> Python-based ab initio quantum chemistry. Runs Hartree-Fock and DFT single-point energies and geometry properties for small molecules on CPU.

**Domain:** Quantum Chemistry  
**Upstream project:** [https://pyscf.org](https://pyscf.org)  
**License:** Apache-2.0  
**Compute:** CPU-only (no GPU required)

## Capabilities

- Restricted Hartree-Fock (RHF) single-point energies
- DFT energies with selectable exchange-correlation functional
- Reads XYZ geometries

## Tool Actions

| Action | Description |
|---|---|
| `run_scf` | Run an RHF single-point energy calculation on an XYZ geometry. |
| `run_dft` | Run a DFT single-point energy calculation on an XYZ geometry. |

## Container Dependencies

- **conda-forge:** pyscf

## Usage

This agent is invoked through Microsoft Discovery. Provide an input
directory with your data files and an output directory for results.
Each action writes `final_results.json` plus detailed artifacts.
