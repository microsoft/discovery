# AiZynthFinder Agent for Microsoft Discovery

Retrosynthetic route planning agent using [AiZynthFinder](https://github.com/MolecularAI/aizynthfinder) (v4.x) with neural-network-guided Monte Carlo Tree Search.

## Overview

This agent breaks down target drug-like molecules into commercially available starting materials using:
- **USPTO expansion policy** -- 50k+ reaction templates from US Patent literature
- **RingBreaker** -- specialised ring-forming reaction templates
- **USPTO filter policy** -- neural network feasibility filter
- **ZINC stock** -- 230k+ purchasable compounds for precursor checking

## Prerequisites

- Microsoft Discovery platform access
- Azure Container Registry (ACR) configured
- Docker (for local builds) or ACR cloud build capability

## Build Docker Image

```bash
# Local build
docker build --platform linux/amd64 -t aizynthfinder:latest .

# Or ACR cloud build (no local Docker needed)
# Use catalog_publish_image via Discovery workbench
```

## Usage

### Basic Analysis

| Prompt | Description |
|--------|-------------|
| "Find synthesis routes for aspirin (CC(=O)Oc1ccccc1C(=O)O)" | Single molecule retrosynthesis |
| "What are the immediate precursors for ibuprofen?" | Single-step expansion |
| "Analyse retrosynthetic routes for these SMILES: CCO, c1ccccc1, CC(=O)O" | Small batch analysis |

### Advanced Analysis

| Prompt | Description |
|--------|-------------|
| "Run thorough retrosynthesis for osimertinib with 500 iterations and max 8 steps" | Deep search with custom parameters |
| "Screen these 20 drug candidates for synthetic accessibility" | Batch with summary statistics |
| "Find routes for this molecule using only the RingBreaker policy" | Policy-specific analysis |
| "Load SMILES from /input/targets.txt and run batch retrosynthesis" | File-based batch input |

## File Structure

```
bundles/aizynthfinder/
  Dockerfile                           # Multi-stage Docker build
  aizynthfinder-tool-definition.yaml   # Tool infrastructure spec
  aizynthfinder-agent-definition.yaml  # Agent instructions + LLM config
  aizynthfinder_utils.py               # Python utilities library
  test_aizynthfinder_utils.py          # Unit tests (pytest)
  README.md                            # This file
```

## Agent Capabilities

| Capability | Function | Notes |
|------------|----------|-------|
| Full retrosynthesis | `run_retrosynthesis()` | MCTS tree search, ~2 min/molecule |
| Single-step expansion | `run_single_step_expansion()` | Fast, no tree search |
| Batch processing | `run_retrosynthesis_batch()` | Sequential with checkpointing |
| Parallel processing | `run_retrosynthesis_parallel()` | Multi-process batch |
| Route visualisation | `plot_route_image()` | PNG route diagrams |
| Batch summary | `plot_search_summary()` | Four-panel statistics |
| Custom stock | `create_config(stock_files=...)` | User-provided purchasable compounds |
| SMILES validation | `validate_smiles()` | Pre-flight check via RDKit |

## Key Configuration

| Parameter | Default | Range | Effect |
|-----------|---------|-------|--------|
| iteration_limit | 100 | 10-2000 | MCTS iterations; more = better routes but slower |
| time_limit | 120s | 10-1200 | Wall-clock timeout per molecule |
| max_transforms | 6 | 2-12 | Max synthesis steps (tree depth) |
| C | 1.4 | 0.5-5.0 | Exploration vs exploitation trade-off |
| return_first | False | True/False | Stop at first solution |

## Compute Requirements

| Resource | Minimum | Recommended |
|----------|---------|-------------|
| CPU | 4 cores | 8-16 cores |
| RAM | 16 GB | 32 GB |
| GPU | Not needed | Not needed |
| Nodepool | Standard_D8s_v6 | Standard_D16s_v6 |

Image size: ~2.5-3 GB (includes pre-baked neural network models and ZINC stock).

## Architecture

This agent operates as a `kind: prompt` agent within Discovery Studio.

    User Input → AiZynthFinder (LLM) → AiZynthFinder Tool (Container) → Results

- **Model:** Configured via the `{{model}}` parameter at deploy time
- **Tool:** AiZynthFinder containerized tool for retrosynthetic route planning

## Configuration

| Parameter | Description | Example |
|---|---|---|
| `{{model}}` | Azure AI Foundry model deployment name | `gpt-4o` |


## Support

For issues or questions, open a GitHub issue:
<https://github.com/microsoft/discovery-catalog/issues>

Microsoft Discovery team contact: discovery-catalog@microsoft.com


## Tools

| Tool | Path | Description |
|---|---|---|
| `aizynthFinder` | `tools/aizynthfinder/` | Retrosynthetic route planning using AiZynthFinder with neural-network-guided |

## Known Limitations

No known limitations at this time. If you encounter issues, please report them via the support channel above.

## Contributing

This project welcomes contributions and suggestions. Please see the repository's top-level [CONTRIBUTING guidelines](https://github.com/microsoft/microsoft-discovery-samples/blob/main/CONTRIBUTING.md) for details on how to contribute.