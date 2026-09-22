# Matminer Agent for Microsoft Discovery

> Data mining for materials science: featurize compositions and crystal structures into descriptors for machine learning.

**Domain:** Materials Science  
**Upstream project:** [https://hackingmaterials.lbl.gov/matminer/](https://hackingmaterials.lbl.gov/matminer/)  
**License:** Modified BSD  
**Compute:** CPU-only (no GPU required)

## Capabilities

- Composition-based featurization (element properties)
- Structure-based descriptors

## Tool Actions

| Action | Description |
|---|---|
| `featurize` | Featurize chemical compositions (one formula per line) with element-property statistics. |

## Container Dependencies

- **pip:** matminer, pymatgen

## Usage

This agent is invoked through Microsoft Discovery. Provide an input
directory with your data files and an output directory for results.
Each action writes `final_results.json` plus detailed artifacts.
