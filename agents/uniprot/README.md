# UniProt Agent for Microsoft Discovery

> Query the UniProt knowledgebase for protein sequences, functional annotations, and cross-references via its public REST API.

**Domain:** Data Source  
**Upstream project:** [https://www.uniprot.org](https://www.uniprot.org)  
**License:** CC-BY-4.0 (data)  
**Compute:** CPU-only (no GPU required)

## Capabilities

- Retrieve protein entries by accession or query
- Fetch sequences and functional annotations

## Tool Actions

| Action | Description |
|---|---|
| `query_uniprot` | Search UniProtKB with a query string and save matching entries as JSON. |

## Container Dependencies

- **pip:** requests

## Usage

This agent is invoked through Microsoft Discovery. Provide an input
directory with your data files and an output directory for results.
Each action writes `final_results.json` plus detailed artifacts.
