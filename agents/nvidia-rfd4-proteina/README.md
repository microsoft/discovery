# NVIDIA RFD4-Proteina Agent

## Overview

RFD4-Proteina is NVIDIA's fourth-generation protein design model, developed in collaboration
with the Institute for Protein Design at the University of Washington. It generates protein 3D
structures and amino acid sequences **in a single model pass** — a significant advance over
prior-generation pipelines that required separate backbone design and sequence design steps.

The [NVIDIA BioNeMo Agent Toolkit](https://github.com/NVIDIA-BioNeMo/bionemo-agent-toolkit)
wraps this model in a conversational interface so that scientists can design protein binders,
scaffolds, and enzymes by describing their goal in plain language. The agent translates
natural-language requests into NIM API calls via the included tool container and returns
ranked design candidates.

**Supported design tasks:**

| Task | Description |
|---|---|
| Protein binder design | Design a protein that grips a target at specified hotspot residues |
| Motif scaffolding | Build a stable scaffold around a functional motif |
| Enzyme design | Scaffold an active site into a new protein fold |
| Small-molecule binder | Design proteins that bind small molecule ligands |
| Antibody CDR design | Design CDR loops for antibody binding |
| Partial diffusion | Refine or diversify existing structures |
| Inverse folding | Find sequences that fold into a given backbone |

## Architecture

```
Discovery Agent (agent.yaml)
        │
        │  writes request.json
        ▼
Tool Container (Dockerfile + design.py)
  python:3.11-slim, CPU-only, no model weights
        │
        │  POST /biology/ipd/rfd4-proteina/generative
        ▼
NVIDIA RFD4-Proteina NIM
  GPU compute — NVIDIA hosted API or Azure AI Foundry
        │
        │  returns mmCIF structures + sequences
        ▼
/output/run_001/
  ├── design_0000.cif   ← generated protein structures
  ├── sequences.fasta   ← amino acid sequences
  ├── summary.json      ← metrics, validation, provenance
  └── transport.json    ← HTTP status, request SHA-256
```

## Prerequisites

| Requirement | Details |
|---|---|
| **Microsoft Discovery workspace** | Desktop app or Azure-deployed Discovery workspace |
| **NVIDIA API key** | From [build.nvidia.com/ipd/rfd4-proteina](https://build.nvidia.com/ipd/rfd4-proteina) — free credits available |
| **Docker** | For local container build (not required when pulling from ACR) |
| **Input format** | Target protein structure must be in **mmCIF format** (`.cif` or `.mmcif`) |
| **GPU compute** | Not required in the tool container — GPU runs on the NIM side |

## Configuration

Register the agent with the following parameters:

| Parameter | Value | Description |
|---|---|---|
| `name` | `nvidia-rfd4-proteina` | Agent identifier |
| `toolName` | `nvidiaRfd4Proteina` | Tool identifier used in tool calls |
| `toolId` | `{{nvidiaRfd4ProteinaToolId}}` | Unique tool ID assigned during provisioning |
| `model` | `{{CHAT-MODEL}}` | The backing LLM deployment name |
| `NVIDIA_API_KEY` | Workspace secret | API key for the NVIDIA hosted NIM endpoint |

**Steps:**

1. In Discovery, run `/add-example-agents`
2. Point to the community catalog: `https://github.com/microsoft/discovery`
3. Select `nvidia-rfd4-proteina`
4. Set your `NVIDIA_API_KEY` in workspace secrets
5. Build the tool container:
   ```bash
   cd agents/nvidia-rfd4-proteina/tools/nvidia-rfd4-proteina
   docker build -t nvidia-rfd4-proteina:1.0.0 .
   ```

## Usage

Start designing by describing your target in plain language:

> "Design 10 protein binders for my PD-1 target structure. Use the mmCIF file I uploaded."

> "Scaffold the active site from residues 45-62 of my enzyme into a new stable fold."

> "Find sequences that will fold into the backbone structure in target.cif."

**Input:** mmCIF structure file of the target protein (from `/input` or uploaded in chat)

**Output** (written to `/output`):
- `design_NNNN.cif` — generated protein structures in mmCIF
- `sequences.fasta` — amino acid sequences for each design
- `summary.json` — design count, validation status, model provenance, metrics
- `transport.json` — request provenance and HTTP status

**Validated scope:**
- Protein binder design via `generation` task
- Motif scaffolding
- Inverse folding
- Hosted NVIDIA API (health.api.nvidia.com)

**Experimental (requires explicit user confirmation):**
- Reward-guided beam search
- Small-molecule binder design
- Enzyme active-site design with novel geometries

## Tools

| Tool | Path | Description |
|---|---|---|
| `nvidiaRfd4Proteina` | `tools/nvidia-rfd4-proteina/` | CPU-only NIM client container. Calls the NVIDIA RFD4-Proteina hosted API or a self-hosted NIM. No model weights inside — GPU compute runs on the NIM. |

## Known Limitations

- **mmCIF format only** — PDB files are not accepted. Renaming a `.pdb` file to `.cif` does not convert it.
- **RFdiffusion API fields not supported** — `contigs`, `input_pdb`, and `hotspot_res` are from the older RFdiffusion API and are not valid for RFD4-Proteina.
- **Experimental tasks** — small-molecule binder design and enzyme design with novel active sites are unvalidated and should be confirmed with the user before running.
- **Exit code 3** — HTTP 202 (accepted/pending) is not a failure. Preserve the request ID and do not re-POST the job.

## Relationship to rfdiffusion

This agent complements the existing `rfdiffusion` agent:

| Capability | rfdiffusion | nvidia-rfd4-proteina |
|---|---|---|
| Protein backbone generation | Yes | Yes (joint backbone + sequence) |
| Sequence design | No (needs ProteinMPNN separately) | Yes (in one model pass) |
| Model generation | 3rd generation (2022) | 4th generation (2026) |
| Compute | Runs locally in container | Calls NVIDIA NIM (hosted or self-hosted) |
| Input format | PDB | mmCIF |

## Contributing

This project welcomes contributions and suggestions. Please see the repository's top-level
[CONTRIBUTING guidelines](https://github.com/microsoft/discovery/blob/main/CONTRIBUTING.md)
for details on how to contribute.

## Support

- BioNeMo Agent Toolkit: https://github.com/NVIDIA-BioNeMo/bionemo-agent-toolkit
- NVIDIA RFD4-Proteina NIM: https://build.nvidia.com/ipd/rfd4-proteina
- Discovery community: https://techcommunity.microsoft.com/category/azure/discussions/microsoft-discovery-discussions

## License

Wrapper code (agent.yaml, Dockerfile, design.py): Apache-2.0

Third-party components retain their own licenses — see THIRD_PARTY_NOTICES.md.
