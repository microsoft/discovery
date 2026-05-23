# esm-embed

Discovery agent for protein language model embeddings using Meta AI's ESM-2 (Evolutionary Scale Modeling, version 2).

## Overview

ESM-2 is a family of transformer protein language models trained on UniRef50. This agent loads pre-trained ESM-2 checkpoints from HuggingFace and computes per-residue and per-sequence embeddings, which are widely used as drop-in features for downstream tasks: structure prediction, contact / interaction prediction, variant effect prediction, function annotation, and protein clustering / retrieval.

## Supported models

| Model | Layers | Embed dim | Params | Recommended use |
|------|--------|-----------|--------|-----------------|
| `esm2_t6_8M_UR50D`   | 6  | 320  | 8M   | Quick prototyping, very large batches |
| `esm2_t12_35M_UR50D` | 12 | 480  | 35M  | Lightweight feature extraction |
| `esm2_t30_150M_UR50D`| 30 | 640  | 150M | Balanced cost / quality |
| `esm2_t33_650M_UR50D`| 33 | 1280 | 650M | **Default.** High quality embeddings |

Larger 3B / 15B checkpoints are intentionally NOT bundled (multi-tens-of-GB downloads, GPU memory hungry). Add them later if needed.

## Inputs

- FASTA file at `/input/sequences.fasta` (one record per sequence, standard 20 amino acids; non-standard residues are mapped to `X`)
- OR a JSON file at `/input/sequences.json` of the form `[{"id": "P12345", "sequence": "MKT..."}, ...]`

## Outputs

- `/output/embeddings.npz` — compressed numpy archive with:
  - `ids`: array of sequence identifiers
  - `mean_embeddings`: `(N, D)` float32 matrix of per-sequence (mean-pooled) embeddings
  - `lengths`: `(N,)` int32 sequence lengths after truncation
- `/output/per_residue/<id>.npy` — optional per-residue embedding tensors `(L, D)` (one file per sequence)
- `/output/contacts/<id>.npy` — optional `(L, L)` contact-probability maps
- `/output/manifest.json` — run metadata (model name, dim, count, device, timing, parameters)
- `/output/final_results.json` — Discovery-standard results record

## Compute

- GPU strongly recommended for the 650M model (~50x speedup over CPU)
- Falls back to CPU automatically when no CUDA device is present
- VRAM rule of thumb (650M, fp16): ~6 GB for sequences up to ~1024 residues at batch size 4

## Architecture

```
User prompt (FASTA / JSON of protein sequences)
        |
        v
+---------------------+
|   LLM Planner       |  (model: {{CHAT-MODEL}})
+----------+----------+
           | tool call: esm-embed
           v
+---------------------------------------------+
|  Tool Container (CPU / GPU)                 |
|  +---------------------------------------+  |
|  | torch + CUDA 12.1 (GPU autodetect)    |  |
|  | transformers (HuggingFace)            |  |
|  | esm_utils.py (this agent)             |  |
|  | numpy, biopython, scikit-learn        |  |
|  +---------------------------------------+  |
+----------+----------------------------------+
           |
           v
+---------------------+
|  ESM-2 model loaded |  weights pulled from HuggingFace on first run
|  (8M / 35M / 150M / |  and cached in the container.
|   650M parameters)  |
+----------+----------+
           |
           v
  embeddings.npz, per_residue/, contacts/, manifest.json
```

**Data flow:**

1. The user uploads a FASTA file (or JSON) of protein sequences to the input mount.
2. The agent loads the requested ESM-2 checkpoint via HuggingFace `transformers` (cached after first run).
3. For each sequence: tokenise -> forward pass -> mean-pool the per-residue embeddings into a per-sequence vector. Optionally also save per-residue tensors and contact-probability maps.
4. Outputs are written as a compressed `.npz` archive plus optional per-sequence files for downstream pipelines.

## Prerequisites

| Requirement | Details |
|---|---|
| **Azure subscription** | An active Azure subscription with permissions to create resources. |
| **Azure AI Foundry project** | A deployed Azure AI Foundry project with agent capabilities enabled. |
| **Model deployment** | A chat-completion model deployed and referenced as `{{CHAT-MODEL}}`. |
| **Compute** | CPU works; GPU strongly recommended for the 650M model. |
| **Network access** | Required on first run to pull the ESM-2 checkpoint from HuggingFace; cached for subsequent runs. |

## Configuration

Register the agent with the following parameters:

| Parameter | Value | Description |
|---|---|---|
| `name` | `esm-embed` | Agent identifier. |
| `toolName` | `esm-embed` | Tool identifier used in tool calls. |
| `toolId` | `{{esmEmbedToolId}}` | Unique tool ID assigned during provisioning. |
| `model` | `{{CHAT-MODEL}}` | Backing LLM deployment name. |
| `container.gpu` | `true` (recommended) | GPU strongly recommended for the 650M model; CPU works for smaller variants. |

Per-call agent inputs (extracted by the planner from the user prompt or supplied directly):

| Input | Type | Default | Description |
|---|---|---|---|
| `model_name` | string | `esm2_t33_650M_UR50D` | Which ESM-2 checkpoint to load. |
| `return_contacts` | boolean | `false` | Whether to also compute and save per-sequence contact maps. |
| `return_per_residue` | boolean | `false` | Whether to also save per-residue embedding tensors. |
| `batch_size` | integer | auto | Sequences per forward pass; tuned to fit the chosen model and available VRAM. |
| `max_length` | integer | 1022 | Truncate sequences to this many residues (excluding special tokens). |

## Tools

| Tool | Path | Description |
|---|---|---|
| `esm-embed` | `tools/esm-embed/` | ESM-2 protein language-model inference. Single action: compute per-residue and per-sequence embeddings (and optional contact maps) for a batch of protein sequences. |

## Usage

Sample prompts that exercise the agent:

| Prompt | Behaviour |
|---|---|
| "Embed the proteins in `/input/sequences.fasta` using the 650M model" | Default high-quality embeddings, mean-pooled per sequence. |
| "Compute per-residue ESM-2 embeddings for these sequences" | Saves per-residue tensors under `/output/per_residue/`. |
| "Predict contact maps for the sequences in this FASTA file" | Saves contact-probability maps under `/output/contacts/`. |
| "Use the 35M model so this fits on CPU" | Loads the smaller `esm2_t12_35M_UR50D` checkpoint. |

Outputs are described in the [Outputs](#outputs) section above. The agent also writes a Discovery-standard `final_results.json` summarising what ran.

## Support

For issues or questions, open a GitHub issue:
<https://github.com/microsoft/discovery-catalog/issues>

## License

This Discovery wrapper (agent definition, tool definition, Dockerfile, utilities
library) is licensed under **MIT**. The repository's top-level
[`LICENSE`](../../../LICENSE) governs all agents in this catalog. See
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) for the licenses of bundled
upstream open-source components.


## Third-Party Components

This agent's container image embeds third-party open-source components, each governed
by its own license. See [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) for the
full per-component breakdown including licenses, source URLs, and any attribution or
redistribution obligations.

## Known Limitations

- ESM-2 has a hard maximum context of 1024 tokens. Sequences longer than ~1022 residues are truncated; long-protein workflows should split into windows or use a different model.
- The 3B and 15B ESM-2 checkpoints are intentionally NOT bundled. They are multi-tens-of-GB downloads and require substantial GPU memory; add them only when needed.
- Contact-prediction outputs are probability maps, not validated 3D structures. For structures use a folding agent (e.g. AlphaFold or BoltzGen).
- The agent does not fine-tune ESM-2; it is inference-only. For fine-tuning workflows, build on top of the bundled `transformers` install or use a dedicated training agent.

## Contributing

This project welcomes contributions and suggestions. Please see the repository's top-level [CONTRIBUTING guidelines](https://github.com/microsoft/microsoft-discovery-samples/blob/main/CONTRIBUTING.md) for details on how to contribute.
