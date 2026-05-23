# Boltz-2

Expert agent for biomolecular structure prediction and binding affinity
estimation using Boltz-2, the predictive foundation model from MIT's Jameel
Clinic. Predicts 3D structures of proteins, nucleic acids, small molecules,
and their complexes via co-folding, with a novel affinity head that estimates
binder probability and pIC50 for drug discovery applications.

## Overview

Boltz-2 solves the problem of predicting biomolecular 3D structures and
estimating binding affinity in a single unified model:

- **Who is it for?** Structural biologists, computational chemists, and drug
  discovery researchers who need fast, accurate structure predictions and
  binding affinity estimates.
- **What scenario?** Predicting protein folds, modeling protein-ligand
  complexes, ranking drug candidates by predicted binding strength, and
  evaluating multi-chain assemblies.
- **Successful outcome:** Predicted CIF structures with per-residue confidence
  scores (pLDDT > 70), interface metrics (iPTM > 0.6), and binding affinity
  predictions (pIC50) for ligand ranking.

## Architecture

```
User Query
    |
    v
Agent (LLM) -- interprets request, generates Python script
    |
    v
boltztwo_utils.py -- builds input YAML, invokes boltz CLI, parses output
    |
    v
boltz predict (GPU) -- runs Boltz-2 neural network inference
    |
    v
Output: CIF structures + confidence JSON + affinity JSON
    |
    v
Analysis & Visualization -- pLDDT plots, PAE heatmaps, affinity bar charts
```

- **Model:** Boltz-2 foundation model (PyTorch, CUDA-accelerated)
- **External dependencies:** None (model weights baked into container)
- **Data flow:** FASTA/SMILES in -> YAML manifest -> boltz predict -> CIF + JSON out

## Prerequisites

- Azure subscription with Discovery workspace
- GPU nodepool available (H100 or A100 recommended)
- Model deployment for the agent LLM (e.g., GPT-4o)

## Configuration

| Parameter | Description | Example |
|-----------|-------------|---------|
| `{{CHAT-MODEL}}` | Model deployment name | `gpt-4o-deployment` |

## Tools

| Tool | Description |
|------|-------------|
| `boltztwo` | Boltz-2 structure prediction container. Image: `mdqacr.azurecr.io/boltztwo:latest`. Requires GPU (min 1x). Supports protein folding, co-folding, and affinity prediction. |

**Compute requirements:**
- Minimum: 4 CPU, 32 GB RAM, 1 GPU
- Recommended: NC40ads_H100_v5 (1x H100)
- Large systems (>1000 residues): NC80adis_H100_v5 (2x H100)

**Input formats:** YAML manifest (version 2), FASTA (converted via helper)
**Output formats:** CIF (structures), JSON (confidence, affinity), PNG (plots)

## Usage

### Example 1: Predict a protein structure

```
"Predict the 3D structure of the protein with sequence MKTAYIAKQ..."
```

The agent will:
1. Build an input YAML with the protein sequence
2. Run `boltz predict` with default parameters
3. Parse confidence metrics and plot pLDDT
4. Return the predicted CIF structure

### Example 2: Protein-ligand binding affinity

```
"Predict the binding affinity of aspirin (SMILES: CC(=O)Oc1ccccc1C(=O)O) to COX-2 (sequence: MLA...)"
```

The agent will:
1. Build an input YAML with protein + SMILES ligand
2. Run `boltz predict --affinity` to enable the affinity head
3. Parse binder probability and pIC50
4. Return structure + affinity results

### Example 3: Batch screening

```
"Screen these 5 ligands against my target protein and rank by predicted pIC50"
```

The agent will:
1. Generate an input YAML for each protein-ligand pair
2. Use `batch_predict()` for sequential processing with checkpointing
3. Collect pIC50 values and create a ranking bar chart
4. Return ranked results with structures

## Support

- Issues: https://github.com/microsoft/discovery-catalog/issues
- Contact: discovery-catalog@microsoft.com

## Known Limitations

- GPU required for all predictions (no CPU fallback)
- Very large systems (>3000 residues) may require multi-GPU nodes
- Affinity predictions are approximate and should be validated experimentally
- Model weights are downloaded at build time (~5 GB); first build is slow
- Batch predictions are sequential (GPU cannot be trivially parallelized)

## Contributing

See the repository's CONTRIBUTING.md for guidelines on submitting changes
to Discovery agents.
