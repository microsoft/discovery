# KEGG Agent for Microsoft Discovery

> Query the KEGG database for pathways, reactions, compounds, and genes via the public KEGG REST API.

**Domain:** Data Source  
**Upstream project:** [https://www.kegg.jp](https://www.kegg.jp)  
**License:** Free for academic use  
**Compute:** CPU-only (no GPU required)

## Capabilities

- Look up pathways, compounds, and reactions
- Retrieve entry details by KEGG identifier

## Tool Actions

| Action | Description |
|---|---|
| `query_kegg` | Retrieve or search KEGG entries by identifier or keyword. |

## Container Dependencies

- **pip:** requests

## Notes

KEGG's REST API is free for academic use; commercial use requires a license.

## Usage

This agent is invoked through Microsoft Discovery. Provide an input
directory with your data files and an output directory for results.
Each action writes `final_results.json` plus detailed artifacts.
