# matchms Agent for Microsoft Discovery

> Import, process, and compute similarity between tandem mass spectra for metabolomics and small-molecule identification.

**Domain:** Analytical Chemistry  
**Upstream project:** [https://github.com/matchms/matchms](https://github.com/matchms/matchms)  
**License:** Apache-2.0  
**Compute:** CPU-only (no GPU required)

## Capabilities

- Load MGF/MSP mass spectra
- Cosine and modified-cosine spectral similarity

## Tool Actions

| Action | Description |
|---|---|
| `compare_spectra` | Compute pairwise cosine similarity across mass spectra in MGF/MSP files. |

## Container Dependencies

- **pip:** matchms

## Usage

This agent is invoked through Microsoft Discovery. Provide an input
directory with your data files and an output directory for results.
Each action writes `final_results.json` plus detailed artifacts.
