# Foldseek Agent for Microsoft Discovery

> Ultra-fast protein structure search and structural alignment, scaling structural comparison to millions of entries on CPU.

**Domain:** Structural Search  
**Upstream project:** [https://github.com/steineggerlab/foldseek](https://github.com/steineggerlab/foldseek)  
**License:** GPL-3.0  
**Compute:** CPU-only (no GPU required)

## Capabilities

- Structure-to-structure search (easy-search)
- All-vs-all structural comparison

## Tool Actions

| Action | Description |
|---|---|
| `structure_search` | Run Foldseek easy-search of query structures against a target set of structures. |

## Container Dependencies

- **conda-forge:** foldseek

## Usage

This agent is invoked through Microsoft Discovery. Provide an input
directory with your data files and an output directory for results.
Each action writes `final_results.json` plus detailed artifacts.
