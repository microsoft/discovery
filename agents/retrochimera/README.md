# Retrosynthesis Predictor (powered by RetroChimera)

A Discovery platform agent for retrosynthetic analysis using the RetroChimera
model (Maziarz et al., 2025). Predicts single-step retrosynthetic disconnections
and multi-step synthesis routes for target drug-like molecules.

## Overview

RetroChimera is a frontier retrosynthesis model that ensembles two novel
components with complementary inductive biases: a template-based model and a
de novo SMILES transformer. It outperforms existing models by a large margin and
is preferred by industrial organic chemists in blind tests.

This agent wraps RetroChimera for use on the Microsoft Discovery platform,
providing:

- **Single-step retrosynthesis**: predict precursor reagents for a target molecule
- **Batch prediction**: process multiple targets efficiently using native batching
- **Multi-step route search**: find complete synthesis routes using syntheseus tree search
- **Visualization**: probability bar charts and HTML reports with Discovery CSS

## Architecture

```
User SMILES input
       |
  [retrochimera_utils.py]
       |
  RetroChimeraModel (Pistachio checkpoint)
    - TemplateLocalizationModel (edit-based)
    - SmilesTransformerModel (de novo)
    - Ensemble scoring & ranking
       |
  Ranked reactions with probabilities
       |
  [Visualization / HTML report]
```

The Discovery tool allocates a GPU because RetroChimera's upstream search stack
is CUDA-oriented and CPU inference is very slow for interactive use. The
Pistachio checkpoint (~4.2 GB) and eMolecules building blocks (~5M compounds)
are stored in separate pre-built ACR images so that code-only changes don't
trigger re-downloads.

## Prerequisites

- Microsoft Discovery workspace with compute nodepools
- GPU nodepool strongly recommended; the tool requests `gpu: 1`
- Azure Container Registry with the pre-built data and deps images (see
  *Building the container image* below), or use the all-in-one Dockerfile
  for a standalone build
- The container ships with the eMolecules building blocks catalog (~5M
  compounds) for multi-step route search. Users can override with a
  project-specific inventory file (one SMILES per line).

## Configuration

| Parameter | Description | Example |
|---|---|---|
| `{{CHAT-MODEL}}` | Model deployment name | `gpt-4o-deployment` |

## Tools

| Tool | Description |
|---|---|
| `retrochimera` | Retrosynthesis prediction using RetroChimera with pre-loaded Pistachio checkpoint. Supports single-step, batch, and multi-step workflows. Container image based on condaforge/mambaforge with Python 3.9, PyTorch 2.2, PyG 2.5, RDKit 2023.09. |

Compute requirements: 4-96 CPU cores, 16-320 GB RAM, and 1 GPU. CPU-only
execution can be forced in scripts with `device="cpu"`, but it is intended for
debugging rather than normal interactive use.

Input: SMILES strings (inline or from /input/ files).
Output: JSON results with ranked reactions, probabilities, and scores.

## Usage

### Single-step retrosynthesis

Provide a SMILES string and the agent will predict the most likely
retrosynthetic disconnections:

```
Predict retrosynthetic precursors for caffeine (CN1C=NC2=C1C(=O)N(C(=O)N2C)C)
using the single-step workflow with 5 results.
```

### Batch retrosynthesis

Provide multiple SMILES for efficient batch processing:

```
Run single-step retrosynthesis for these drug molecules:
- Acetaminophen: CC(=O)NC1=CC=C(C=C1)O
- Ibuprofen: CC(C)CC1=CC=C(C=C1)C(C)C(=O)O
- Aspirin: CC(=O)OC1=CC=CC=C1C(=O)O
Return 5 results per molecule.
```

### Multi-step route search

Find complete synthesis routes from purchasable starting materials:

```
Find multi-step synthesis routes for
C=CC(=O)N1CCCCC(n2c(=O)c3ncccc3n(Cc3ccc(Oc4cccc(F)c4)cc3)c2=O)C1
using the multi-step workflow with 5 routes and a time limit of 120 seconds.
```

## Building the container image

The build is split into three images for fast iteration. Data images are
built once and cached in ACR; the main image pulls from them.

| Image | Dockerfile | Rebuilds when | Build time |
|-------|------------|---------------|------------|
| `retrochimera` (default) | `Dockerfile` | Any change (standalone, no ACR deps) | ~25 min |
| `retrochimera-deps` | `Dockerfile.deps` | Package version bumps | ~12 min |
| `retrochimera-checkpoint` | `Dockerfile.checkpoint` | New model checkpoint | ~10 min |
| `retrochimera-bb` | `Dockerfile.bb` | eMolecules URL rotates (monthly) | ~20 min |
| `retrochimera` (fast) | `Dockerfile.fast` | Code changes only (requires pre-built images) | **~8 min** |

### Using the build scripts

```powershell
# Standalone build (default Dockerfile, no pre-built images required)
.\build-acr.ps1 -Target allinone -AcrName <your-acr>

# Build all pre-built images + fast main image (first time setup)
.\build-acr.ps1 -Target all -AcrName <your-acr>

# Fast rebuild after a code change (requires pre-built images in ACR)
.\build-acr.ps1 -Target main -AcrName <your-acr>

# Update building blocks when eMolecules rotates their URL
.\build-acr.ps1 -Target bb -AcrName <your-acr> -BbTag 2026-05 `
    -BbUrl "https://downloads.emolecules.com/orderbb/2026-05-01/parent.smi.gz"
```

```bash
# Bash equivalent
./build-acr.sh allinone <your-acr>
./build-acr.sh all <your-acr>
./build-acr.sh main <your-acr>
./build-acr.sh bb <your-acr> --bb-tag 2026-05 \
    --bb-url "https://downloads.emolecules.com/orderbb/2026-05-01/parent.smi.gz"
```

## Support

File issues at: https://github.com/microsoft/discovery-catalog/issues
Contact: discovery-catalog@microsoft.com

## Known Limitations

- Reactions ranked lower than 5-10 are increasingly likely to be hallucinations
- All predictions must be verified by chemistry experts before real-world use
- Multi-step route search uses Syntheseus tree search against a bundled
  eMolecules building blocks inventory (~5M compounds). To restrict to a
  specific vendor, pass a custom `inventory_smiles_file` (one SMILES per line).
- The Pistachio checkpoint is trained on proprietary reaction data; USPTO
  checkpoints are available but weaker
- Python 3.9 is required (retrochimera's dependencies are pinned to this version)

## License

This Discovery wrapper (agent definition, tool definition, Dockerfile,
utilities library) is licensed under the MIT License. See [`LICENSE`](LICENSE).

## Third-Party Components

The container image embeds the following open-source components:

| Component | Version | License | Source |
|---|---|---|---|
| RetroChimera | latest (PyPI) | MIT | https://github.com/microsoft/retrochimera |
| Pistachio checkpoint | v1 | See upstream release terms | https://figshare.com/ndownloader/files/59468882 |
| syntheseus | >=0.7.2 | MIT | https://github.com/microsoft/syntheseus |
| PyTorch | 2.2.2 | BSD-3-Clause | https://github.com/pytorch/pytorch |
| PyG (torch_geometric) | 2.5.2 | MIT | https://github.com/pyg-team/pytorch_geometric |
| RDKit | 2023.09.6 | BSD-3-Clause | https://github.com/rdkit/rdkit |
| rdchiral_cpp | latest | MIT | https://github.com/connorcoley/rdchiral |

Full attribution and license text for every bundled third-party component is
in [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md). The container preserves
upstream LICENSE files at `/app/retrochimera-license/LICENSE`.

## Contributing

See [CONTRIBUTING](https://github.com/microsoft/discovery-catalog/blob/main/CLA.md).
