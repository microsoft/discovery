# Chemprop Agent for Microsoft Discovery

## Overview

Chemprop is a message-passing neural network (D-MPNN) framework for molecular property prediction. This agent wraps [Chemprop v2](https://chemprop.readthedocs.io/) for the Microsoft Discovery platform, enabling:

- **Regression**: Predict continuous properties (solubility, logP, pKa, IC50, binding affinity)
- **Binary classification**: Predict binary labels (active/inactive, toxic/non-toxic)
- **Multiclass classification**: Predict categorical labels
- **Multi-task learning**: Predict multiple properties simultaneously
- **Cross-validation**: K-fold CV with scaffold/random splitting
- **Learned fingerprints**: Extract D-MPNN molecular representations
- **Hyperparameter optimization**: Automated search for best model configuration

## Prerequisites

- Microsoft Discovery platform access
- Azure Container Registry (ACR) configured
- Docker (for local builds) or `catalog_publish_image` (cloud builds)

## Build Docker Image

   ```
   catalog_publish_image(image_name="chemprop:latest", dockerfile_path="<path>/Dockerfile", build_context="<path>")
   ```

## Usage

### Basic Training
| Prompt | Input File(s) | Description |
|--------|---------------|-------------|
| Train a solubility prediction model on my CSV data | solubility.csv (smiles + logSolubility) | Regression model training with evaluation |
| Predict toxicity for a list of drug candidates | compounds.csv (smiles + toxicity label) | Binary classification training |
| Train a multi-task model for ADMET properties | admet.csv (smiles + multiple targets) | Multi-task regression |

### Advanced Analysis
| Prompt | Description |
|--------|-------------|
| Perform 5-fold cross-validation on my solubility dataset using scaffold splitting | Scaffold-balanced CV for realistic performance estimate |
| Generate learned molecular fingerprints using a trained model | Extract D-MPNN representations for downstream tasks |
| Optimize hyperparameters for my binding affinity model | Automated hyperparameter search |
| Predict solubility for new molecules using a saved model | Inference with pre-trained model |

## File Structure

```
chemprop/
Γö£ΓöÇΓöÇ Dockerfile                    # Container build definition
Γö£ΓöÇΓöÇ chemprop-tool-definition.yaml # Discovery tool specification
Γö£ΓöÇΓöÇ chemprop-agent-definition.yaml # Discovery agent specification
Γö£ΓöÇΓöÇ chemprop_utils.py             # Python utilities library
Γö£ΓöÇΓöÇ test_chemprop_utils.py        # Unit tests
Γö£ΓöÇΓöÇ README.md                     # This file
ΓööΓöÇΓöÇ example-input-files/
    ΓööΓöÇΓöÇ solubility_sample.csv     # Example training data
```

## Agent Capabilities

| Capability | Method | Notes |
|-----------|--------|-------|
| Train MPNN | `train_pipeline()` or `train_model()` | Full pipeline or step-by-step |
| Cross-validate | `cross_validate()` | K-fold with multiple split types |
| Predict | `predict_smiles()` / `predict_csv()` | From SMILES list or CSV |
| Save/Load models | `save_model_file()` / `load_model_file()` | .pt format |
| Fingerprints | `compute_fingerprints()` | Learned D-MPNN representations |
| Hyperopt | `hyperopt()` | Automated hyperparameter search |
| Evaluate | `compute_metrics()` | RMSE, MAE, R┬▓, AUROC, AUPRC, etc. |
| Visualize | `plot_parity()` / `plot_cv_results()` | Publication-quality plots |

## Key Configuration Details

- **Base image**: Azure Linux 3.0 with Python 3.12
- **PyTorch**: CPU-only by default (GPU auto-detected if available)
- **Default hidden_dim**: 300 (D-MPNN message passing dimension)
- **Default depth**: 3 (message passing iterations)
- **Early stopping**: patience=10 on validation loss
- **Thread control**: Single-threaded by default (OMP_NUM_THREADS=1)

## References

1. Yang et al. "Analyzing Learned Molecular Representations for Property Prediction" *JCIM* (2019)
2. Heid et al. "Chemprop: A Machine Learning Package for Chemical Property Prediction" *JCIM* (2023)
3. Chemprop v2: [https://chemprop.readthedocs.io/](https://chemprop.readthedocs.io/)

## Architecture

This agent operates as a `kind: prompt` agent within Discovery Studio.

    User Input → Chemprop (LLM) → Chemprop Tool (Container) → Results

- **Model:** Configured via the `{{model}}` parameter at deploy time
- **Tool:** Chemprop container for molecular property prediction using D-MPNN

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
| `chemProp` | `tools/chemprop/` | Chemprop v2 Message-passing neural networks (D-MPNN) for molecular property prediction. Supports regression, binary classification, and multiclass ... |

## Known Limitations

No known limitations at this time. If you encounter issues, please report them via the support channel above.

## Contributing

This project welcomes contributions and suggestions. Please see the repository's top-level [CONTRIBUTING guidelines](https://github.com/microsoft/microsoft-discovery-samples/blob/main/CONTRIBUTING.md) for details on how to contribute.