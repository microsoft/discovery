# SIRIUS Agent for Microsoft Discovery

> Metabolite structure elucidation from tandem mass spectra: molecular formula identification and structure ranking (CSI:FingerID).

**Domain:** Analytical Chemistry  
**Upstream project:** [https://bio.informatik.uni-jena.de/software/sirius/](https://bio.informatik.uni-jena.de/software/sirius/)  
**License:** Free for academic use (login required for some features)  
**Compute:** CPU-only (no GPU required)

## Capabilities

- Molecular formula identification from MS/MS
- Fragmentation tree computation

## Tool Actions

| Action | Description |
|---|---|
| `elucidate_structure` | Run SIRIUS formula identification on MS/MS input files (.ms/.mgf). |

## Container Dependencies

- **conda-forge:** sirius-csifingerid

## Notes

SIRIUS web features (CSI:FingerID, structure DB search) require a free account login at runtime. Formula identification runs offline.

## Usage

This agent is invoked through Microsoft Discovery. Provide an input
directory with your data files and an output directory for results.
Each action writes `final_results.json` plus detailed artifacts.
