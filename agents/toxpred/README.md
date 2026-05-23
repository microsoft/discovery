# ToxPred — Toxicity Prediction Agent

## Overview

Early identification of compound toxicity is critical in drug discovery — late-stage toxicity failures account for a significant fraction of clinical trial attrition. Computational toxicity prediction enables rapid triage of candidate molecules before costly in vitro and in vivo testing, but building reliable models requires harmonizing heterogeneous data sources and applying appropriate machine-learning workflows.

The ToxPred agent provides an end-to-end toxicity modeling pipeline for drug-like compounds. It harmonizes chemical identifiers through a DSSTox/CompTox spine, aggregates ToxCast in vitro bioactivity evidence, ingests endpoint labels (AMES mutagenicity, hERG cardiotoxicity, DILI hepatotoxicity, and others), and trains multitask classifiers using Chemprop message-passing neural networks or random-forest baselines. Researchers can also run batch predictions on new compound libraries.

The intended user is a computational toxicologist, medicinal chemist, or safety scientist who needs rapid, reproducible toxicity assessment from molecular structures. A successful outcome is a harmonized toxicity panel with trained predictive models, per-endpoint metrics, and batch predictions for candidate compounds.

### Key capabilities

| Capability | Description |
|---|---|
| **DSSTox spine construction** | Canonicalize and validate SMILES with RDKit; build a DSSTox-centered harmonized identifier backbone. |
| **ToxCast aggregation** | Summarize ToxCast assay activity counts, active fractions, and potency metrics by chemical. |
| **Endpoint ingestion** | Ingest AMES, hERG, DILI, and custom toxicity endpoint tables from TDC-compatible CSV exports. |
| **Data harmonization** | Merge DSSTox identifiers, ToxCast summaries, and multiple endpoint labels into a unified panel. |
| **Multitask Chemprop training** | Train multitask message-passing neural network classifiers for production toxicity workflows. |
| **Random-forest baseline** | Train quick smoke-test models for small datasets or rapid feasibility checks. |
| **Batch prediction** | Score new compound libraries against trained Chemprop models with per-endpoint predictions. |

## Architecture

```
User Prompt
    │
    ▼
┌──────────────────┐
│  LLM Planner     │  (model: {{CHAT-MODEL}}, temperature 0)
│  (reasoning)     │
└──────┬───────────┘
       │  tool call: toxpred
       ▼
┌───────────────────────────────────────┐
│  Tool Container (CPU)                 │
│  ┌─────────────────────────────────┐  │
│  │ toxpred_utils library           │  │  build_dsstox_spine, summarize_toxcast,
│  │                                 │  │  normalize_endpoint_table, merge_toxicity_panel,
│  │                                 │  │  run_chemprop_train, run_chemprop_predict
│  │ chemprop                        │  │  multitask message-passing neural networks
│  │ rdkit                           │  │  SMILES validation and Morgan fingerprints
│  │ scikit-learn                    │  │  random-forest baseline and metrics
│  │ numpy / pandas                  │  │  data manipulation
│  │ matplotlib / seaborn            │  │  visualization
│  └─────────────────────────────────┘  │
└───────────┬───────────────────────────┘
            │
            ▼
  Harmonized panel (CSV), trained models,
  evaluation metrics, batch predictions
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

1. The user provides toxicity data files (DSSTox spine, ToxCast activity, endpoint CSVs) or describes the prediction task.
2. The LLM planner generates a Python script using `toxpred_utils` functions.
3. The tool container harmonizes data sources, trains models, and generates evaluation metrics.
4. Results are saved to `/output/` as CSV tables, model artifacts, and a `final_results.json` summary.
5. The planner interprets per-endpoint metrics and provides recommendations for model deployment or further data collection.

**External dependencies:** None at runtime. All libraries are pre-installed in the container. No GPU required — CPU-only compute.

## Prerequisites

| Requirement | Details |
|---|---|
| **Azure subscription** | An active Azure subscription with permissions to create resources. |
| **Azure AI Foundry project** | A deployed Azure AI Foundry project with agent capabilities enabled. |
| **Model deployment** | A chat-completion model deployed and referenced as `{{CHAT-MODEL}}`. |
| **Compute** | CPU compute is sufficient. Recommended SKU: `Standard_D4s_v6` or `Standard_D8s_v6`. No GPU required. |
| **Network access** | Not required at runtime; all libraries and models are pre-installed in the container image. |

## Configuration

Register the agent with the following parameters:

| Parameter | Value | Description |
|---|---|---|
| `name` | `toxpred` | Agent identifier. |
| `displayName` | `ToxPred` | Human-readable agent name shown in Discovery Studio. |
| `toolName` | `toxpred` | Tool identifier used in tool calls. |
| `toolId` | `{{toxpredToolId}}` | Unique tool ID assigned during provisioning. |
| `model` | `{{CHAT-MODEL}}` | The backing LLM deployment name. |
| `container.gpu` | `false` | CPU-only; no GPU required. |
| `container.packages` | `toxpred_utils, chemprop, rdkit, numpy, pandas, scikit-learn, matplotlib, seaborn` | Python packages inside the container. |

### Example input files

The agent ships with synthetic demonstration datasets in `example-input-files/`:

| File | Description |
|---|---|
| `dsstox_spine.csv` | DSSTox substance identifiers, preferred names, and canonical SMILES. |
| `toxcast_activity.csv` | ToxCast assay hit-call and potency summaries by substance. |
| `ames.csv` | AMES mutagenicity endpoint labels with train/test splits. |
| `herg.csv` | hERG cardiotoxicity endpoint labels with train/test splits. |
| `dili.csv` | Drug-induced liver injury endpoint labels with train/test splits. |
| `compounds_to_score.csv` | New compounds for batch prediction scoring. |

### Example agent definition (YAML snippet)

```yaml
kind: prompt
name: toxpred
displayName: ToxPred
model:
  id: '{{CHAT-MODEL}}'
  options:
    temperature: 0
    topP: 0
discoveryExtensions:
  tools:
    - toolId: '{{toxpredToolId}}'
      confirmation: Disabled
```

## Usage

### Step 1 — Build and publish the container image

```bash
catalog_publish_image(
    image_name="toxpred:latest",
    dockerfile_path="Dockerfile",
    build_context="."
)
```

### Step 2 — Publish the tool and agent definitions

```bash
catalog_publish_tool(tool_yaml_path="toxpred-tool-definition.yaml")
catalog_publish_agent(
    agent_yaml_path="toxpred-agent-definition.yaml",
    tool_name="toxpred"
)
```

### Step 3 — Deploy via Discovery Studio

Navigate to the ToxPred agent card in Discovery Studio and click **Deploy**. Fill in the configuration parameters listed above.

### Step 4 — Example prompts

**Full harmonization and multitask training:**

```text
Harmonize DSSTox, ToxCast, and AMES/hERG/DILI tables in /input and train a
multitask Chemprop model. Report per-endpoint ROC-AUC and export the harmonized
panel.
```

**ToxCast activity summarization:**

```text
Summarize ToxCast activity for the DSSTox spine in /input/dsstox_spine.csv and
export a harmonized panel with active fractions and potency summaries.
```

**Quick smoke-test baseline:**

```text
Train a quick random-forest smoke-test model on the harmonized toxicity panel
and report per-endpoint accuracy, ROC-AUC, and F1 scores.
```

**Batch prediction on new compounds:**

```text
Score /input/compounds_to_score.csv with the Chemprop model stored in
/input/model_dir. Report per-endpoint predicted probabilities and flag
high-risk compounds.
```

### Step 5 — Example output

```json
{
  "status": "completed",
  "train_result": {
    "endpoints": ["ames", "herg", "dili"],
    "metrics": {
      "ames": {"roc_auc": 0.87, "accuracy": 0.82},
      "herg": {"roc_auc": 0.84, "accuracy": 0.79},
      "dili": {"roc_auc": 0.81, "accuracy": 0.76}
    }
  },
  "output_files": {
    "harmonized_panel": "/output/harmonized_panel.csv",
    "chemprop_model": "/output/chemprop_model/",
    "final_results": "/output/final_results.json"
  }
}
```

> **Note:** The bundled example input files are synthetic demonstrations for validation only. For scientific use, replace them with authoritative CompTox, ToxCast, and endpoint exports. Missing endpoint labels are treated as unknowns, not negatives. Scaffold-aware evaluation is recommended for real lead-optimization datasets.

## Support

If you encounter issues or have feature requests:

- **GitHub Issues:** Open an issue at [microsoft/microsoft-discovery-samples](https://github.com/microsoft/discovery-catalog/issues) with the label `agent/toxpred`.
- **Contact:** [discovery-catalog@microsoft.com](mailto:discovery-catalog@microsoft.com)
- **Documentation:** Refer to the [Microsoft Discovery authoring guide](https://github.com/microsoft/microsoft-discovery-samples/blob/main/docs/authoring-guide.md) for agent development best practices.
- **Community:** Join the discussion in the repository's Discussions tab for questions and tips.


## Tools

| Tool | Path | Description |
|---|---|---|
| `toxpred` | `tools/toxpred/` | Toxicity prediction tool for drug-like compounds using DSSTox harmonization, ToxCast aggregation, endpoint tables, and Chemprop-ready workflows |

## Known Limitations

No known limitations at this time. If you encounter issues, please report them via the support channel above.

## Contributing

This project welcomes contributions and suggestions. Please see the repository's top-level [CONTRIBUTING guidelines](https://github.com/microsoft/microsoft-discovery-samples/blob/main/CONTRIBUTING.md) for details on how to contribute.