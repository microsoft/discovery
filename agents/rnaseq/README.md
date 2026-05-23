# RNA-seq — Differential Expression Analysis Agent

A Microsoft Discovery agent for end-to-end bulk RNA-seq bioinformatics analysis. Supports GEO data ingestion, QC/normalization, differential expression with DESeq2-style statistical testing, volcano and MA plots, WGCNA-style co-expression module detection, gene ontology enrichment, pathway analysis, and machine-learning feature ranking.

## Overview

Bulk RNA-seq experiments generate count matrices that require a multi-step analysis pipeline — from normalization and quality control through differential expression testing to biological interpretation. Building and executing this pipeline demands expertise in statistics, bioinformatics, and data visualization.

This agent provides a conversational interface to a complete RNA-seq analysis toolkit. It enables:

- **Data ingestion** — download and parse GEO datasets or load local count matrices and phenotype files
- **QC and normalization** — filter low-count genes, apply DESeq2 median-of-ratios or voom (log-CPM with weights) normalization, and run PCA for sample-level quality assessment
- **Differential expression** — perform limma-voom (empirical Bayes moderated t-test) or Welch's t-test with Benjamini–Hochberg FDR correction; generate volcano plots
- **Co-expression analysis** — build WGCNA-style weighted co-expression networks with topological overlap, dynamic tree cutting, and module eigengene computation
- **Machine-learning ranking** — run elastic net logistic regression for sparse feature selection and XGBoost for nonlinear feature importance; produce combined feature-importance plots
- **Structured output** — assemble a JSON handoff artifact with all results, CSV tables, and PNG visualizations for downstream pipeline consumption

The intended user is a bioinformatician, computational biologist, or translational researcher who needs rapid, reproducible RNA-seq analysis. A successful outcome is a set of differentially expressed genes with statistical metrics, co-expression modules, ML-ranked biomarker candidates, and publication-ready visualizations.

## Architecture

`
User Prompt
    → RNA-seq Agent (LLM: {{CHAT-MODEL}}, temperature 0)
        → rnaseq tool container (Python 3)
            → rnaseq_utils library
                → GEOparse (GEO data download)
                → NumPy / SciPy / pandas (computation)
                → statsmodels (multiple testing correction, LOWESS)
                → scikit-learn (PCA, elastic net)
                → XGBoost (gradient-boosted ranking)
                → matplotlib / seaborn (visualization)
        → Structured output (JSON handoff + CSV + PNG)
`

**Model**: `{{CHAT-MODEL}}` — used for pipeline planning, script generation, and result interpretation. Temperature is set to 0 for deterministic outputs.

**Tool container**: A Docker image running Python 3 with the `rnaseq_utils` helper library and a full scientific Python stack. The agent generates a single Python script that the container executes.

**Data flow**:

1. The user describes an RNA-seq analysis task (e.g., "Analyse GSE54456 psoriasis data with DE and WGCNA")
2. The LLM generates a comprehensive Python script using `rnaseq_utils` functions
3. The script runs inside the tool container — downloads data, normalizes, tests, clusters, and ranks features
4. Results are saved via `save_final_results()` and exported to `/output/` (CSV, JSON, PNG)
5. The LLM summarises findings and returns them with visualizations

**External dependencies**: GEO/NCBI servers for dataset download (when using `download_geo_dataset`). No GPU needed — CPU-only compute.

## Prerequisites

- Microsoft Discovery workspace with Azure Container Registry (ACR) access
- Azure AI Foundry project with a model deployment for `{{CHAT-MODEL}}`
- CPU compute node pool (e.g., `Standard_D4s_v6` or equivalent) — no GPU required
- Network access from the container to NCBI/GEO servers (if downloading GEO datasets)

## Configuration

### Agent parameters

| Parameter | Description | Example |
|---|---|---|
| `{{CHAT-MODEL}}` | Azure AI Foundry model deployment name | `gpt-4o-deployment` |
| `{{rnaseqToolId}}` | Tool ID for the RNA-seq tool definition | `rnaseq-tool-v1` |

### Tool container resources

| Resource | Minimum | Maximum |
|---|---|---|
| CPU | 2 cores | 16 cores |
| RAM | 8 Gi | 64 Gi |
| GPU | 0 | 0 |

### Container packages

| Package | Version | Description |
|---|---|---|
| `rnaseq_utils` | — | Custom helper library for RNA-seq analysis |
| `numpy` | 2.2.4 | Numerical computation |
| `pandas` | 2.2.3 | Data manipulation and I/O |
| `scipy` | 1.15.2 | Statistical functions and clustering |
| `scikit-learn` | 1.6.1 | PCA, elastic net, preprocessing |
| `statsmodels` | 0.14.6 | Multiple testing correction, LOWESS |
| `xgboost` | 3.0.1 | Gradient-boosted classification and ranking |
| `matplotlib` | 3.10.1 | Plotting (Agg backend) |
| `seaborn` | 0.13.2 | Statistical visualizations |
| `GEOparse` | 2.0.4 | GEO dataset download and parsing |
| `networkx` | 3.4.2 | Network analysis for co-expression modules |

## Usage

### 1. Build the Docker image

```bash
catalog_publish_image(image_name="rnaseq:latest", dockerfile_path="Dockerfile", build_context=".")
```

### 2. Publish the agent and tool

```bash
catalog_publish_agent(
  agent_yaml_path="rnaseq-agent-definition.yaml",
  tool_yaml_path="rnaseq-tool-definition.yaml"
)
```

### 3. Deploy via Discovery Studio

Navigate to the RNA-seq agent card in Discovery Studio and click **Deploy**. Fill in the configuration parameters listed above.

### 4. Example prompts

**Basic: Download and QC a GEO dataset:**

`
Download GSE54456 psoriasis RNA-seq data and run QC with PCA visualization.
`

**Full pipeline:**

`
Run the complete RNA-seq pipeline on GSE54456 including differential expression,
WGCNA co-expression modules, elastic net, and XGBoost feature ranking.
Export all results as CSV and generate volcano and feature-importance plots.
`

**Custom data:**

`
Analyze RNA-seq counts from /input/counts.csv with sample labels from
/input/phenotype.csv. Run DE analysis with limma-voom (FDR < 0.05, |log2FC| > 1)
and produce a volcano plot.
`

### 5. Example output

`json
{
  "status": "completed",
  "n_degs": 1247,
  "n_modules": 8,
  "elastic_net_cv_accuracy": 0.94,
  "xgboost_cv_accuracy": 0.97,
  "output_files": {
    "de_results": "/output/de_results.csv",
    "volcano_plot": "/output/volcano.png",
    "pca_plot": "/output/pca_plot.png",
    "feature_importance": "/output/feature_importance.png",
    "handoff_artifact": "/output/handoff_artifact.json"
  }
}
`

## Support

For issues or questions, open a GitHub issue:
https://github.com/microsoft/discovery-catalog/issues


## Tools

| Tool | Path | Description |
|---|---|---|
| `rnaseq` | `tools/rnaseq/` | Python code environment for bulk RNA-seq bioinformatics: GEO data ingestion, QC/normalization (DESeq2-style), differential expression (limma-voom),... |

## Known Limitations

No known limitations at this time. If you encounter issues, please report them via the support channel above.

## Contributing

This project welcomes contributions and suggestions. Please see the repository's top-level [CONTRIBUTING guidelines](https://github.com/microsoft/microsoft-discovery-samples/blob/main/CONTRIBUTING.md) for details on how to contribute.