# NVIDIA RFD4-Proteina Agent

Expert agent for joint protein structure and sequence design using the
[NVIDIA RFD4-Proteina NIM](https://build.nvidia.com/ipd/rfd4-proteina).
Powered by the [NVIDIA BioNeMo Agent Toolkit](https://github.com/NVIDIA-BioNeMo/bionemo-agent-toolkit).

## What this agent does

RFD4-Proteina generates protein 3D structures and amino acid sequences in a single
model pass. A scientist describes what they want in natural language — the agent
prepares the request, calls the NIM, and returns ranked design candidates.

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
Discovery Agent (this agent.yaml)
        │
        │  writes request.json
        ▼
Tool Container (Dockerfile + design.py)
        │
        │  POST /biology/ipd/rfd4-proteina/generative
        ▼
NVIDIA RFD4-Proteina NIM
  (hosted: health.api.nvidia.com  OR  local: self-hosted NIM on AKS/VM)
        │
        │  returns mmCIF structures + sequences
        ▼
/output/run_001/
  ├── design_0000.cif   ← generated protein structures
  ├── sequences.fasta   ← amino acid sequences
  ├── summary.json      ← metrics, validation, provenance
  └── transport.json    ← HTTP status, request SHA-256
```

## Requirements

- Azure subscription with a Discovery workspace
- A GPU nodepool is **not required** for this tool — GPU compute runs on the NIM
- `NVIDIA_API_KEY` secret configured in Discovery (for hosted mode)
- Input structures must be in **mmCIF format** (`.cif` or `.mmcif`)

## Setup

1. Configure `NVIDIA_API_KEY` in your Discovery workspace secrets
2. Import this agent using the `add-example-agents` skill
3. Place your target protein mmCIF file in the conversation or `/input`

## Example request

> "Design 10 protein binders for my PD-1 target structure. Use the annotated mmCIF
> I uploaded. Report all designs with their sequences."

## Input/Output

**Input:** mmCIF structure file of the target protein (from `/input` or uploaded in chat)

**Output** (written to `/output`):
- `design_NNNN.cif` — generated protein structures in mmCIF
- `sequences.fasta` — amino acid sequences for each design
- `summary.json` — design count, validation status, model provenance, metrics
- `transport.json` — request provenance and HTTP status

## Validated scope

- Protein binder design via `generation` task
- Motif scaffolding
- Inverse folding
- Hosted NVIDIA API (health.api.nvidia.com)

**Experimental (requires explicit user confirmation):**
- Reward-guided beam search
- Small-molecule binder design
- Enzyme active-site design with novel geometries

## Relationship to existing Discovery agents

This agent complements the existing `rfdiffusion` agent:

| Capability | rfdiffusion | nvidia-rfd4-proteina |
|---|---|---|
| Protein backbone generation | Yes | Yes (joint backbone + sequence) |
| Sequence design | No (needs ProteinMPNN separately) | Yes (in one model pass) |
| Model generation | 3rd generation (2022) | 4th generation (2026) |
| Compute | Runs locally in container | Calls NVIDIA NIM (hosted or self-hosted) |
| Input format | PDB | mmCIF |

## License

Wrapper code (agent.yaml, Dockerfile, design.py): Apache-2.0

Third-party components retain their own licenses — see THIRD_PARTY_NOTICES.md.

## Support

- BioNeMo Agent Toolkit: https://github.com/NVIDIA-BioNeMo/bionemo-agent-toolkit
- NVIDIA RFD4-Proteina NIM: https://build.nvidia.com/ipd/rfd4-proteina
- Discovery community: https://techcommunity.microsoft.com/category/azure/discussions/microsoft-discovery-discussions
