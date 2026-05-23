# TamGen — Target-Aware Molecular Generation Agent

## Overview

Structure-based drug design requires generating novel molecules that complement specific protein binding pockets. Traditional virtual screening is limited to existing compound libraries, while de novo design methods often produce chemically invalid or synthetically infeasible candidates.

The TamGen agent wraps the TamGen transformer model (Wu et al., *Nature Communications* 15:9360, 2024) — a chemical language model that generates novel drug-like molecules conditioned on protein binding pocket structures. Researchers can extract pocket geometries from PDB structures, generate molecules with tunable diversity, apply scaffold constraints, filter by drug-likeness properties, and analyze chemical diversity — all through natural-language prompts. Model checkpoints are pre-cached at `/app/TamGen/checkpoints/` inside the tool container.

The intended user is a computational chemist, medicinal chemist, or drug discovery researcher who needs rapid generation of target-specific molecular candidates. A successful outcome is a diverse set of valid, drug-like molecules with computed properties (MW, LogP, QED, TPSA, Lipinski compliance) ready for downstream docking or ADMET evaluation.

### Key capabilities

| Capability | Description |
|---|---|
| **Pocket extraction** | Automatic binding site detection from PDB co-crystallized ligands or explicit center coordinates. |
| **Conditional generation** | Generate molecules conditioned on protein pocket geometry using a VAE-transformer architecture. |
| **Scaffold-constrained design** | Generate molecules containing a specified molecular scaffold within the binding pocket context. |
| **Property computation** | Compute molecular weight, LogP, QED, TPSA, HBD/HBA counts, and Lipinski rule-of-five compliance. |
| **Drug-likeness filtering** | Filter generated molecules by property ranges, Lipinski compliance, or custom criteria. |
| **Diversity analysis** | Compute Tanimoto diversity metrics using Morgan fingerprints across generated sets. |
| **Batch screening** | Generate and evaluate molecules for multiple targets in a single workflow. |

## Architecture

```
User Prompt
    │
    ▼
┌──────────────────┐
│  LLM Planner     │  (model: {{CHAT-MODEL}}, temperature 0)
│  (reasoning)     │
└──────┬───────────┘
       │  tool call: tamgen
       ▼
┌──────────────────────────────────────────┐
│  Tool Container (GPU: CUDA 12.1)         │
│  ┌────────────────────────────────────┐  │
│  │ tamgen_utils library               │  │  quick_setup, prepare_pocket_*,
│  │                                    │  │  generate_molecules, filter_molecules,
│  │                                    │  │  compute_diversity, summarize_generation
│  │ TamGen model (fairseq)            │  │  transformer + VAE molecule generation
│  │ torch 2.3.0 + CUDA 12.1           │  │  GPU-accelerated deep learning
│  │ torch_geometric                    │  │  graph neural network operations
│  │ rdkit                              │  │  cheminformatics and property computation
│  │ BioPython                          │  │  protein structure parsing (PDB)
│  │ numpy / pandas / scipy             │  │  data manipulation and computation
│  │ matplotlib / seaborn               │  │  visualization
│  └────────────────────────────────────┘  │
│  ┌────────────────────────────────────┐  │
│  │ /app/TamGen/checkpoints/           │  │  pre-cached model weights
│  │   crossdock_pdb_A10 (default)      │  │  CrossDocked2020 + PDB augmentation
│  │   crossdocked_model                │  │  CrossDocked2020 base
│  │ /app/TamGen/gpt_model/             │  │  GPT molecule decoder
│  └────────────────────────────────────┘  │
└───────────┬──────────────────────────────┘
            │
            ▼
  Generated molecules (SMILES + properties),
  diversity metrics, filtered candidates, plots
            │
            ▼
┌──────────────────────┐
│  LLM Planner         │
│  (interpret results) │
└──────────┬───────────┘
           │
           ▼
     User response
```

**Data flow:**

1. The user specifies a protein target (PDB ID or uploaded structure) and generation parameters.
2. The LLM planner generates a Python script using `tamgen_utils` functions.
3. The tool container extracts the binding pocket, runs TamGen inference on GPU, computes molecular properties, and filters results.
4. Generated molecules are saved to `/output/` as CSV files with SMILES and computed properties.
5. The planner summarizes generation statistics, diversity metrics, and drug-likeness profiles.

**External dependencies:** PDB/RCSB servers for protein structure download (when using PDB IDs). **GPU required** — TamGen inference requires CUDA-capable hardware.

## Prerequisites

| Requirement | Details |
|---|---|
| **Azure subscription** | An active Azure subscription with permissions to create resources. |
| **Azure AI Foundry project** | A deployed Azure AI Foundry project with agent capabilities enabled. |
| **Model deployment** | A chat-completion model deployed and referenced as `{{CHAT-MODEL}}`. |
| **GPU compute** | **Required.** CUDA 12.1-compatible GPU node. Recommended SKU: `Standard_NC40ads_H100_v5`. |
| **Network access** | Required for PDB structure download from RCSB servers. Not required if protein structures are pre-uploaded to `/input/`. |

## Configuration

Register the agent with the following parameters:

| Parameter | Value | Description |
|---|---|---|
| `name` | `tamgen` | Agent identifier. |
| `displayName` | `TamGen` | Human-readable agent name shown in Discovery Studio. |
| `toolName` | `tamgen` | Tool identifier used in tool calls. |
| `toolId` | `{{tamgenToolId}}` | Unique tool ID assigned during provisioning. |
| `model` | `{{CHAT-MODEL}}` | The backing LLM deployment name. |
| `container.gpu` | `true` | **GPU required** for TamGen inference (CUDA 12.1). |
| `container.packages` | `tamgen_utils, torch, torch_geometric, rdkit, BioPython, numpy, pandas, scipy, matplotlib, seaborn` | Python packages inside the container. |

### Generation parameters

| Parameter | Range | Default | Description |
|---|---|---|---|
| `beam_size` | 5–50 | 20 | Number of candidates per generation step. Higher values yield more candidates. |
| `beta` | 0.1–2.0 | 1.0 | VAE diversity control. Higher values produce more novel/diverse molecules. |
| `num_molecules` | 1–500 | 50 | Target count of unique valid molecules. |
| `max_seeds` | 10–200 | 101 | Random seeds to iterate. More seeds increase diversity but slow generation. |
| `threshold` | 5–15 Å | 10.0 | Pocket radius around binding site center. Use 15 Å for larger binding sites. |
| `use_conditional` | true/false | true | Enable VAE conditional generation (recommended). |

### Example agent definition (YAML snippet)

```yaml
kind: prompt
name: tamgen
displayName: TamGen
model:
  id: '{{CHAT-MODEL}}'
  options:
    temperature: 0
    topP: 0
discoveryExtensions:
  tools:
    - toolId: '{{tamgenToolId}}'
      confirmation: Disabled
```

## Usage

### Step 1 — Build and publish the container image

```bash
catalog_publish_image(
    image_name="tamgen:latest",
    dockerfile_path="Dockerfile",
    build_context="."
)
```

### Step 2 — Publish the tool and agent definitions

```bash
catalog_publish_tool(tool_yaml_path="tamgen-tool-definition.yaml")
catalog_publish_agent(
    agent_yaml_path="tamgen-agent-definition.yaml",
    tool_name="tamgen"
)
```

### Step 3 — Deploy via Discovery Studio

Navigate to the TamGen agent card in Discovery Studio and click **Deploy**. Fill in the configuration parameters listed above. Ensure a GPU node pool is available.

### Step 4 — Example prompts

**Generate molecules for a known target:**

```text
Generate 50 drug-like molecules for the imatinib binding pocket of ABL kinase
(PDB: 1IEP). Filter results to Lipinski-compliant compounds and report diversity
metrics.
```

**Scaffold-constrained generation:**

```text
Generate molecules containing the pyrimidine scaffold (c1ccnc(N)n1) for the
EGFR binding pocket (PDB: 1M17) at coordinates (22.0, 0.5, -28.0) with a
15 Å pocket radius. Target 100 unique molecules with high diversity (beta=1.5).
```

**Multi-target comparison:**

```text
Generate 30 molecules each for CDK2 (PDB: 1FIN) and CDK4 (PDB: 2W96). Compare
the property distributions (MW, LogP, QED) between the two target sets and
report which target yields more drug-like candidates.
```

### Step 5 — Example output

```json
{
  "status": "completed",
  "summary": {
    "total_generated": 50,
    "unique_valid": 47,
    "validity_rate": 0.94,
    "drug_like_count": 38,
    "mean_qed": 0.62,
    "mean_mw": 387.4,
    "mean_logp": 2.8
  },
  "diversity": {
    "mean_tanimoto_distance": 0.71,
    "min_tanimoto_distance": 0.34,
    "unique_scaffolds": 29
  },
  "output_files": {
    "generated_molecules": "/output/generated_molecules.csv",
    "property_distributions": "/output/property_distributions.png"
  }
}
```

## Support

If you encounter issues or have feature requests:

- **GitHub Issues:** Open an issue at [microsoft/microsoft-discovery-samples](https://github.com/microsoft/discovery-catalog/issues) with the label `agent/tamgen`.
- **Contact:** [discovery-catalog@microsoft.com](mailto:discovery-catalog@microsoft.com)
- **Documentation:** Refer to the [Microsoft Discovery authoring guide](https://github.com/microsoft/microsoft-discovery-samples/blob/main/docs/authoring-guide.md) for agent development best practices.
- **Community:** Join the discussion in the repository's Discussions tab for questions and tips.


## Tools

| Tool | Path | Description |
|---|---|---|
| `tamgen` | `tools/tamgen/` | TamGen (Target-aware Molecule Generation) tool for structure-based drug design |

## Known Limitations

No known limitations at this time. If you encounter issues, please report them via the support channel above.

## Contributing

This project welcomes contributions and suggestions. Please see the repository's top-level [CONTRIBUTING guidelines](https://github.com/microsoft/microsoft-discovery-samples/blob/main/CONTRIBUTING.md) for details on how to contribute.