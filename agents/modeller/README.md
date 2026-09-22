# MODELLER Agent for Microsoft Discovery

> Comparative (homology) modeling of protein 3D structure from a sequence alignment to one or more template structures.

**Domain:** Structural Biology  
**Upstream project:** [https://salilab.org/modeller/](https://salilab.org/modeller/)  
**License:** Academic (license key required)  
**Compute:** CPU-only (no GPU required)

## Capabilities

- Build comparative protein models from alignments
- Score models with the DOPE potential

## Tool Actions

| Action | Description |
|---|---|
| `build_model` | Build a comparative model given an alignment (.ali/.pir) and template structures. |

## Container Dependencies

- **conda-forge:** modeller

## Notes

MODELLER requires a free academic license key set via the KEY_MODELLER environment variable / MODELLER config. Provide it at container runtime; without it MODELLER will refuse to run.

## Usage

This agent is invoked through Microsoft Discovery. Provide an input
directory with your data files and an output directory for results.
Each action writes `final_results.json` plus detailed artifacts.
