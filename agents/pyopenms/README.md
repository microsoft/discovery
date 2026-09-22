# pyOpenMS Agent for Microsoft Discovery

> Mass-spectrometry data processing for proteomics and metabolomics: read mzML, inspect spectra, and extract peak/feature information.

**Domain:** Analytical Chemistry  
**Upstream project:** [https://pyopenms.readthedocs.io](https://pyopenms.readthedocs.io)  
**License:** BSD-3-Clause  
**Compute:** CPU-only (no GPU required)

## Capabilities

- Read and summarize mzML spectra
- Report MS levels, precursor and peak counts

## Tool Actions

| Action | Description |
|---|---|
| `process_spectra` | Read mzML files and summarize spectra (counts, MS levels, base peak). |

## Container Dependencies

- **pip:** pyopenms

## Usage

This agent is invoked through Microsoft Discovery. Provide an input
directory with your data files and an output directory for results.
Each action writes `final_results.json` plus detailed artifacts.
