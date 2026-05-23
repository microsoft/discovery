# MatterGen Crystal Generator

A generative AI agent for inorganic crystal structure design using MatterGen,
a diffusion-based model published by Microsoft Research in Nature 2025. Generates
novel, thermodynamically plausible crystal structures that can be conditioned on
target properties including chemical composition, space group symmetry, electronic
band gap, magnetic density, and bulk modulus.

## Overview

MatterGen addresses the challenge of inverse materials design: given a set of
desired material properties, generate candidate crystal structures that are likely
to be stable and synthesizable. The model uses a denoising diffusion process that
jointly generates atom positions, lattice parameters, and atomic species.

- **Intended users**: Materials scientists, solid-state chemists, computational
  physicists conducting high-throughput materials screening.
- **Successful outcome**: A set of novel crystal structures (CIF files) with target
  properties, accompanied by composition diversity analysis and lattice statistics.

## Architecture

The agent wraps the [MatterGen](https://github.com/microsoft/mattergen) diffusion
model (Zeni et al., Nature 2025, DOI:10.1038/s41586-025-08628-5).

- **Model**: GemNet-based denoising diffusion model with predictor-corrector sampling
- **Conditioning**: Classifier-free guidance for property-conditioned generation
- **Checkpoints**: 9 pretrained models hosted on HuggingFace Hub (`microsoft/mattergen`)
- **Output**: pymatgen Structure objects, saved as CIF and extended XYZ files

## Prerequisites

- Azure subscription with Discovery workspace
- GPU nodepool (H100 or A100 recommended)
- Model deployment for agent LLM (e.g., GPT-4o)

## Configuration

| Parameter | Description | Example |
|---|---|---|
| `{{CHAT-MODEL}}` | Model deployment name for agent LLM | `gpt-4o-deployment` |

## Tools

| Tool | Description |
|---|---|
| `mattergen` | GPU-accelerated crystal structure generation via MatterGen diffusion model. Container: `mdqacr.azurecr.io/mattergen:latest`. Requires CUDA GPU. |

Compute requirements: min 4 CPU, 32 GB RAM, 1 GPU. Recommended: Standard_NC40ads_H100_v5.

Supported input: Python scripts using `mattergen_utils` library.
Supported output: CIF files, extxyz files, CSV summaries, PNG plots, JSON results.

## Usage

### Unconditional generation
```
Generate 32 novel crystal structures using the base model
```

### Property-conditioned generation
```
Generate crystal structures with a band gap around 1.5 eV for photovoltaic applications
```

### Composition-constrained generation
```
Generate silicon dioxide (SiO2) crystal structures
```

### Multi-property conditioning
```
Generate magnetic materials (0.15 muB/atom) from abundant elements using the
dft_mag_density_hhi_score model
```

## Support

File issues at https://github.com/microsoft/discovery-catalog/issues

## Known Limitations

- GPU required for inference (no CPU fallback)
- Maximum ~20 atoms per generated unit cell (training data constraint)
- Conditioning properties are limited to the 7 fine-tuned model variants
- Generated structures should be validated with DFT (e.g., CP2K, Quantum Espresso)
  before experimental synthesis
- No explicit control over crystal system beyond space group conditioning

## License

This agent is governed by the repository's top-level
[`LICENSE`](../../../LICENSE).

## Third-Party Components

| Component | Version | License | Source |
|---|---|---|---|
| MatterGen | 1.0.3 | MIT | https://github.com/microsoft/mattergen |
| MatterGen model weights | 1.0.3 | MIT | https://huggingface.co/microsoft/mattergen |
| PyTorch | 2.2.1 | BSD-3-Clause | https://github.com/pytorch/pytorch |
| PyTorch Geometric | 2.5+ | MIT | https://github.com/pyg-team/pytorch_geometric |
| pymatgen | 2024.6+ | MIT | https://github.com/materialsproject/pymatgen |
| ASE | 3.25 | LGPL-2.1 | https://wiki.fysik.dtu.dk/ase/ |

> Full attribution for every bundled third-party component is in
> `THIRD_PARTY_NOTICES.md`. The container preserves upstream `LICENSE` and
> `NOTICE` files at `/app/mattergen-src/licenses/`.

## Contributing

See the repository's CONTRIBUTING.md guidelines.
