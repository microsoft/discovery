# ChemBERTa-2 Molecular Property Prediction Agent

## Overview

Predicting molecular properties—toxicity, solubility, binding affinity, metabolic stability—from chemical structure alone is a critical bottleneck in early-stage drug discovery. Traditional approaches rely on hand-crafted molecular descriptors or expensive quantum-mechanical calculations, limiting throughput and accessibility.

The ChemBERTa agent wraps the ChemBERTa-2 transformer model (77 million parameters, pre-trained on 77 million PubChem molecules) in a conversational interface. Researchers can extract molecular embeddings, fine-tune property classifiers or regressors, compute confidence scores, and perform molecular similarity analysis—all through natural-language prompts. The model is pre-cached at `/app/model_cache` inside the tool container for fast cold-start times.

### Key capabilities

| Capability | Description |
|---|---|
| **Embedding extraction** | Generate 768-dimensional molecular representations from SMILES strings. |
| **Classification fine-tuning** | Train binary or multi-class property classifiers on custom datasets. |
| **Regression fine-tuning** | Train continuous property predictors (e.g., logP, IC50). |
| **SMILES augmentation** | Apply non-canonical SMILES enumeration to increase training data diversity. |
| **Confidence scoring** | Estimate prediction reliability using the FART (Feature-space Adversarial Robustness Testing) paper method. |
| **Molecular similarity** | Compute cosine similarity between embedding vectors to find structural analogues. |
| **Clustering** | Group molecules by embedding similarity using k-means or DBSCAN. |
| **Visualization** | Generate t-SNE/UMAP plots, property distribution charts, and confidence heat-maps. |

## Architecture

`
User prompt
    │
    ▼
┌──────────────┐
│  LLM Planner │  (model: {{CHAT-MODEL}})
│  (reasoning) │
└──────┬───────┘
       │  tool call: chemberta
       ▼
┌───────────────────────────────┐
│  Tool Container (CPU / GPU)   │
│  ┌─────────────────────────┐  │
│  │ /app/model_cache        │  │  pre-cached ChemBERTa-2 weights
│  │ torch (CPU by default)  │  │  tensor operations
│  │ transformers            │  │  model loading & inference
│  │ rdkit                   │  │  SMILES parsing & augmentation
│  │ scikit-learn            │  │  classification, regression, clustering
│  │ numpy / pandas          │  │  data manipulation
│  │ matplotlib / seaborn    │  │  plotting & visualization
│  │ scipy                   │  │  distance metrics & statistics
│  │ tqdm                    │  │  progress tracking
│  └─────────────────────────┘  │
└───────────┬───────────────────┘
            │
            ▼
┌───────────────────────────────┐
│  ChemBERTa-2 Model (77M)     │
│  ┌──────────┐ ┌────────────┐ │
│  │ Embed    │ │ Fine-tune  │ │
│  │ (infer)  │ │ (train)    │ │
│  └──────────┘ └────────────┘ │
└───────────┬───────────────────┘
            │
            ▼
  Embeddings, predictions, confidence scores,
  similarity matrices, cluster assignments, plots
            │
            ▼
┌──────────────────────┐
│  LLM Planner         │
│  (interpret results) │
└──────────┬───────────┘
           │
           ▼
     User response
`

**Data flow:**

1. The user provides SMILES strings, a CSV dataset, or a natural-language description of the property prediction task.
2. The LLM planner converts the request into `chemberta` tool calls (embed, fine-tune, predict, cluster, etc.).
3. The tool container loads ChemBERTa-2 from `/app/model_cache`, performs the requested operation, and returns numerical results plus any generated plots.
4. The planner interprets the output, explains confidence levels, and suggests next steps (e.g., augment data, retrain, or filter low-confidence predictions).

## Prerequisites

| Requirement | Details |
|---|---|
| **Azure subscription** | An active Azure subscription with permissions to create resources. |
| **Azure AI Foundry project** | A deployed Azure AI Foundry project with agent capabilities enabled. |
| **Model deployment** | A chat-completion model deployed and referenced as `{{CHAT-MODEL}}`. |
| **Compute** | CPU compute is sufficient for embedding extraction and small-scale fine-tuning. GPU is optional but beneficial for large-scale fine-tuning (>10 000 molecules). |
| **Network access** | Not required at runtime; the ChemBERTa-2 model is pre-cached in the container image at `/app/model_cache`. |

## Configuration

Register the agent with the following parameters:

| Parameter | Value | Description |
|---|---|---|
| `name` | `chemberta` | Human-readable agent name. |
| `toolName` | `chemberta` | Tool identifier used in tool calls. |
| `toolId` | `{{chembertaToolId}}` | Unique tool ID assigned during provisioning. |
| `model` | `{{CHAT-MODEL}}` | The backing LLM deployment name. |
| `container.gpu` | `false` (optional `true`) | GPU is optional; enable for large fine-tuning jobs. |
| `container.packages` | `torch, transformers, rdkit, scikit-learn, numpy, pandas, matplotlib, seaborn, scipy, tqdm` | Python packages inside the container. |
| `container.modelCache` | `/app/model_cache` | Path to the pre-cached ChemBERTa-2 model weights. |

### Example agent definition (YAML snippet)

`yaml
name: chemberta
model: "{{CHAT-MODEL}}"
tools:
  - name: chemberta
    id: "{{chembertaToolId}}"
    container:
      gpu: false  # set to true for large-scale fine-tuning
      packages:
        - torch
        - transformers
        - rdkit
        - scikit-learn
        - numpy
        - pandas
        - matplotlib
        - seaborn
        - scipy
        - tqdm
      modelCache: /app/model_cache
`

## Usage

### Step 1 — Extract molecular embeddings

`	ext
Generate ChemBERTa-2 embeddings for these molecules:

CCO (ethanol)
CC(=O)Oc1ccccc1C(=O)O (aspirin)
CC12CCC3C(C1CCC2O)CCC4=CC(=O)CCC34C (testosterone)
`

**Expected output:** A table of 768-dimensional embedding vectors (truncated for display) with molecule names:

| Molecule | Dim 0 | Dim 1 | Dim 2 | … | Dim 767 |
|---|---|---|---|---|---|
| ethanol | 0.0231 | −0.1482 | 0.0874 | … | 0.0412 |
| aspirin | −0.0653 | 0.2210 | −0.0319 | … | −0.0891 |
| testosterone | 0.1104 | −0.0765 | 0.1452 | … | 0.0283 |

### Step 2 — Fine-tune a toxicity classifier

`	ext
Fine-tune a binary toxicity classifier using the dataset at /data/tox21_train.csv.
The SMILES column is "smiles" and the label column is "toxic" (0 or 1).
Use SMILES augmentation with 5 enumerations per molecule.
Report accuracy, ROC-AUC, and a confusion matrix on a 20% held-out split.
`

**Expected output:**

`
Training complete (3 epochs, 8 421 molecules, 5x augmentation → 42 105 samples).

Held-out evaluation (1 684 molecules):
  Accuracy : 0.876
  ROC-AUC  : 0.921
  Confusion matrix:
              Predicted 0  Predicted 1
  Actual 0       712          94
  Actual 1       114         764
`

### Step 3 — Predict with confidence scores

`	ext
Predict toxicity for these SMILES and include FART confidence scores:

c1ccc2c(c1)cc1ccc3cccc4ccc2c1c34
CC(C)NCC(O)c1ccc(O)c(O)c1
`

**Expected output:**

| SMILES | Prediction | Probability | FART Confidence |
|---|---|---|---|
| c1ccc2c(c1)cc1ccc3cccc4ccc2c1c34 | Toxic | 0.92 | 0.88 (high) |
| CC(C)NCC(O)c1ccc(O)c(O)c1 | Non-toxic | 0.15 | 0.95 (high) |

### Step 4 — Similarity search and clustering

`	ext
Find the 5 most similar molecules to aspirin (CC(=O)Oc1ccccc1C(=O)O)
in the dataset at /data/drugbank.csv. Then cluster all molecules into
8 groups and show a t-SNE plot colored by cluster.
`

**Expected output:** A ranked list of the 5 nearest neighbours by cosine similarity, followed by an inline t-SNE scatter plot with 8 colour-coded clusters and a summary of each cluster's dominant structural motifs.

## Support

If you encounter issues or have feature requests:

- **GitHub Issues:** Open an issue at [microsoft/discovery-samples](https://github.com/microsoft/discovery-samples/issues) with the label `agent/chemberta`.
- **Documentation:** Refer to the [Microsoft Discovery authoring guide](https://github.com/microsoft/discovery-samples/blob/main/docs/authoring-guide.md) for agent development best practices.
- **Community:** Join the discussion in the repository's Discussions tab for questions and tips.


## Tools

| Tool | Path | Description |
|---|---|---|
| `chemberta` | `tools/chemberta/` | ChemBERTa-2 molecular property prediction agent. Provides SMILES-based molecular embeddings, classification and regression fine-tuning, SMILES augm... |

## Known Limitations

No known limitations at this time. If you encounter issues, please report them via the support channel above.

## Contributing

This project welcomes contributions and suggestions. Please see the repository's top-level [CONTRIBUTING guidelines](https://github.com/microsoft/microsoft-discovery-samples/blob/main/CONTRIBUTING.md) for details on how to contribute.