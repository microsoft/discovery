# Materials Project Agent for Microsoft Discovery

> Query the Materials Project database for computed properties of inorganic materials via the mp-api client.

**Domain:** Data Source  
**Upstream project:** [https://materialsproject.org](https://materialsproject.org)  
**License:** Open data (API key required)  
**Compute:** CPU-only (no GPU required)

## Capabilities

- Query materials by formula or chemical system
- Retrieve formation energy, band gap, and stability

## Tool Actions

| Action | Description |
|---|---|
| `query_materials` | Query Materials Project by chemical formula and return key computed properties. |

## Container Dependencies

- **pip:** mp-api

## Notes

Requires a free Materials Project API key, supplied via the MP_API_KEY environment variable or the api_key parameter.

## Usage

This agent is invoked through Microsoft Discovery. Provide an input
directory with your data files and an output directory for results.
Each action writes `final_results.json` plus detailed artifacts.
