# RFDiffusion Agent — Protein Backbone Design

## Overview

RFDiffusion is a denoising diffusion probabilistic model for protein backbone generation, developed by the Baker Lab (University of Washington). This Discovery agent wraps RFDiffusion for automated protein backbone design workflows.

**Key capabilities:**
- **Unconditional generation**: Generate random protein backbones of specified length
- **Binder design**: Design proteins that bind a given target structure
- **Motif scaffolding**: Build scaffolds around functional motifs (epitopes, active sites)
- **Symmetric oligomers**: Design symmetric protein assemblies (C3, C6, etc.)
- **Fold conditioning**: Generate backbones with specific topologies

**Model weights included:**
- `Base_ckpt.pt` — Unconditional generation & motif scaffolding
- `Complex_base_ckpt.pt` — Binder design (protein-protein interactions)

## Prerequisites

- Microsoft Discovery platform access
- Azure Container Registry (ACR) configured
- GPU nodepool available (H100 or A100 recommended)

## Build Docker Image

```bash
catalog_publish_image(image_name="rfdiffusion:latest", build_context="<bundle_path>")
```

## Usage

### Basic Calculations

| Prompt | Input Files | Description |
|--------|-------------|-------------|
| Generate 10 random protein backbones of 100 residues | None | Unconditional monomer generation |
| Generate 5 backbones between 80-150 residues | None | Variable-length generation |
| Design 10 binders against insulin | 4INS.pdb | PPI binder design with Complex model |
| Scaffold the RSV epitope from 5IZ7 | 5IZ7.pdb | Motif scaffolding |

### Advanced Analysis

| Prompt | Description |
|--------|-------------|
| Design a C3-symmetric trimer with 80-residue protomers | Symmetric oligomer design |
| Generate 50 diverse backbones and cluster by compactness | Large-scale generation + analysis |
| Design binders with hotspot residues A30, A33, A34 | Targeted binder design |

## File Structure

```
bundles/rfdiffusion/
├── Dockerfile                          # Container build definition
├── rfdiffusion_utils.py               # Python utilities library
├── test_rfdiffusion_utils.py          # Unit tests (pytest)
├── rfdiffusion-tool-definition.yaml   # Tool definition (infra specs)
├── rfdiffusion-agent-definition.yaml  # Agent definition (instructions)
└── README.md                          # This file
```

## Agent Capabilities

| Capability | Function | Model |
|------------|----------|-------|
| Unconditional backbone | `generate_unconditional()` | Base |
| Binder design | `design_binder()` | Complex |
| Motif scaffolding | `scaffold_motif()` | Base |
| Symmetric oligomers | `design_symmetric_oligomer()` | Base |
| Custom inference | `run_rfdiffusion()` | Any |
| Backbone analysis | `compute_backbone_metrics()` | N/A |
| Design comparison | `plot_design_comparison()` | N/A |

## Key Configuration Details

- **GPU**: Required for all inference. H100 recommended for speed.
- **Diffusion steps**: Default 50 (T=50). Increase for higher quality.
- **Model weights**: Stored at `/opt/RFdiffusion/models/` in the container
- **Output format**: PDB files + TRB files (trajectory metadata)
- **Typical runtime**: ~5-30 seconds per design on H100

## Architecture

This agent operates as a `kind: prompt` agent within Discovery Studio.

    User Input → RFDiffusion (LLM) → RFDiffusion Tool (Container) → Results

- **Model:** Configured via the `{{model}}` parameter at deploy time
- **Tool:** RFDiffusion container for protein backbone design using denoising diffusion

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
| `rfDiffusion` | `tools/rfdiffusion/` | Protein backbone design via RFDiffusion denoising diffusion probabilistic model |

## Known Limitations

No known limitations at this time. If you encounter issues, please report them via the support channel above.

## Contributing

This project welcomes contributions and suggestions. Please see the repository's top-level [CONTRIBUTING guidelines](https://github.com/microsoft/microsoft-discovery-samples/blob/main/CONTRIBUTING.md) for details on how to contribute.