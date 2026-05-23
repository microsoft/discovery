# Nucleotide Transformer Agent — DNA Sequence Analysis

## Overview

This Discovery agent wraps InstaDeep's **Nucleotide Transformer v2 (500M multi-species)** foundation model for DNA sequence analysis. The model is pre-trained on 850 genomes (174 billion nucleotides) from diverse species.

**Key capabilities:**
- **Embedding extraction**: Generate 1024-dimensional representations from raw DNA sequences
- **Variant effect prediction**: Score nucleotide variants via masked language modeling
- **Sequence similarity**: Compute pairwise cosine similarity between sequences
- **Clustering**: Group sequences by embedding similarity (k-means or hierarchical)
- **Visualization**: Publication-quality scatter plots, heatmaps, and probability charts

## Prerequisites

- Microsoft Discovery platform access
- Azure Container Registry (ACR) configured
- GPU nodepool recommended for sequences > 1,000 nt (H100 or A100)
- CPU-only inference supported for smaller workloads

## Usage

### Basic Calculations

| Prompt | Input Files | Description |
|--------|-------------|-------------|
| Extract embeddings for all sequences in my FASTA file | sequences.fasta | Batch embedding extraction |
| Compare similarity between these DNA sequences | sequences.fasta | Pairwise similarity heatmap |
| Predict the effect of a G>A variant at position 150 | None (inline sequence) | Masked language model scoring |

### Advanced Analysis

| Prompt | Description |
|--------|-------------|
| Cluster these promoter sequences and visualize the groups | Embedding + k-means + PCA scatter |
| Find the most similar sequences to my query in the database | Nearest-neighbor search by cosine similarity |
| Score all single-nucleotide variants across a 500 nt region | Systematic variant effect scanning |

## File Structure

```
nucleotide-tf/
├── agent.yaml                              # Agent definition (instructions)
├── metadata.yaml                           # Tags, description, metadata
├── README.md                               # This file
└── tools/
    └── nucleotide-tf/
        ├── tool.yaml                       # Tool definition (infra specs)
        ├── Dockerfile                      # Container build definition
        ├── nucleotide_tf_utils.py          # Python utilities library
        └── test_nucleotide_tf_utils.py     # Unit tests (pytest)
```

## Agent Capabilities

| Capability | Function | Description |
|------------|----------|-------------|
| Embeddings | `extract_embeddings()` / `batch_extract_embeddings()` | 1024-dim vectors per sequence |
| Masked prediction | `predict_masked()` | Variant effect scoring via MLM |
| Similarity | `compute_similarity_matrix()` | Pairwise cosine similarity |
| Nearest neighbor | `find_similar_sequences()` | Top-k most similar sequences |
| Clustering | `cluster_sequences()` | K-means with silhouette scoring |
| Dimensionality reduction | `reduce_dimensions()` | PCA or t-SNE to 2D |
| Visualization | `plot_embedding_scatter()`, `plot_similarity_matrix()` | Publication-quality figures |

## Key Configuration Details

- **Model**: `InstaDeepAI/nucleotide-transformer-v2-500m-multi-species`
- **Embedding dimension**: 1024
- **Max input**: ~12,282 nucleotides per chunk (2048 tokens with 6-mer tokenizer)
- **Model cache**: Pre-downloaded at `/app/model_cache` (no internet needed at runtime)
- **Input formats**: FASTA (.fa, .fasta), plain text, JSON
- **Output directory**: `/output/`

## Architecture

This agent operates as a `kind: prompt` agent within Discovery Studio.

    User Input → Nucleotide Transformer (LLM) → Nucleotide Transformer Tool (Container) → Results

- **Model:** Configured via the `{{model}}` parameter at deploy time
- **Tool:** Nucleotide Transformer container for DNA sequence analysis using InstaDeep's v2 foundation model

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
| `nucleotideTf` | `tools/nucleotide-tf/` | DNA foundation model tool using InstaDeep's Nucleotide Transformer v2 (500M multi-species). |

## Known Limitations

No known limitations at this time. If you encounter issues, please report them via the support channel above.

## Contributing

This project welcomes contributions and suggestions. Please see the repository's top-level [CONTRIBUTING guidelines](https://github.com/microsoft/microsoft-discovery-samples/blob/main/CONTRIBUTING.md) for details on how to contribute.