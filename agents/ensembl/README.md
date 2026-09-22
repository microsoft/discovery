# Ensembl REST Agent for Microsoft Discovery

> Query Ensembl for genes, transcripts, variants, and cross-references across many species via the Ensembl REST API.

**Domain:** Data Source  
**Upstream project:** [https://rest.ensembl.org](https://rest.ensembl.org)  
**License:** Apache-2.0 (software), open data  
**Compute:** CPU-only (no GPU required)

## Capabilities

- Look up genes and transcripts by symbol or ID
- Retrieve cross-references and sequences

## Tool Actions

| Action | Description |
|---|---|
| `query_ensembl` | Look up a gene by symbol/ID for a given species via the Ensembl REST API. |

## Container Dependencies

- **pip:** requests

## Usage

This agent is invoked through Microsoft Discovery. Provide an input
directory with your data files and an output directory for results.
Each action writes `final_results.json` plus detailed artifacts.
