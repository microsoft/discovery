# nmrglue Agent for Microsoft Discovery

> Read, process, and analyze NMR data from Bruker, Varian/Agilent, and NMRPipe formats. Extract spectra and basic processing metadata.

**Domain:** Analytical Chemistry  
**Upstream project:** [https://www.nmrglue.com](https://www.nmrglue.com)  
**License:** BSD-3-Clause  
**Compute:** CPU-only (no GPU required)

## Capabilities

- Read Bruker and NMRPipe datasets
- Report spectral dimensions and metadata

## Tool Actions

| Action | Description |
|---|---|
| `process_nmr` | Read NMRPipe (.ft/.fid) or Bruker datasets and report dimensions and basic stats. |

## Container Dependencies

- **pip:** nmrglue, numpy

## Usage

This agent is invoked through Microsoft Discovery. Provide an input
directory with your data files and an output directory for results.
Each action writes `final_results.json` plus detailed artifacts.
