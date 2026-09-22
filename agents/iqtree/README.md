# IQ-TREE Agent for Microsoft Discovery

> Maximum-likelihood phylogenetic inference with automatic substitution model selection (ModelFinder) and ultrafast bootstrap support.

**Domain:** Phylogenetics  
**Upstream project:** [http://www.iqtree.org](http://www.iqtree.org)  
**License:** GPL-2.0  
**Compute:** CPU-only (no GPU required)

## Capabilities

- ML tree inference with ModelFinder
- Ultrafast bootstrap support values

## Tool Actions

| Action | Description |
|---|---|
| `build_tree` | Infer a maximum-likelihood phylogenetic tree from a multiple sequence alignment. |

## Container Dependencies

- **conda-forge:** iqtree

## Usage

This agent is invoked through Microsoft Discovery. Provide an input
directory with your data files and an output directory for results.
Each action writes `final_results.json` plus detailed artifacts.
