# Third-Party Components

This agent's container image embeds the following third-party open-source components.
Each component is governed by its own license. The Discovery wrapper code itself is
licensed under MIT and is governed by the repository's top-level
[`LICENSE`](../../../LICENSE).

## Primary upstream tools

| Component | Version | License | Source | Notes |
|---|---|---|---|---|
| Chemprop | 2.2.2 | MIT | https://github.com/chemprophub/chemprop | D-MPNN molecular property prediction framework. Core inference engine. |
| PyTorch | >=2.2.0 (CPU) | BSD-3-Clause | https://github.com/pytorch/pytorch | Tensor computation; model loading and inference. CPU-only wheels bundled (no CUDA). |
| Lightning | >=2.4.0 | Apache-2.0 | https://github.com/Lightning-AI/pytorch-lightning | Training loop abstraction; used by chemprop for model inference. |
| RDKit | >=2024.3.0 | BSD-3-Clause | https://github.com/rdkit/rdkit | SMILES validation, molecular fingerprints, physicochemical descriptors. |
| scikit-learn | >=1.4 | BSD-3-Clause | https://github.com/scikit-learn/scikit-learn | Isotonic regression for CI calibration. |
| astartes | >=1.3.0 | MIT | https://github.com/JacksonBurns/astartes | Molecular dataset splitting (Tanimoto-clustered Butina). |

## Bundled trained models

The container includes a 5-model Chemprop D-MPNN ensemble at `/app/models/`:

| File | Size | Description |
|---|---|---|
| `model_{0..4}.pt` | 4.2 MB each | Trained D-MPNN weights (hidden=500, depth=5, dropout=0.1) |
| `manifest.json` | 2.3 KB | Model configuration, feature scaler parameters, training metadata |
| `training_fingerprints.npz` | 8.8 KB | Morgan fingerprints (r=2, 2048 bits) of 226 training molecules for applicability domain |

### Training data provenance

The models were trained on 226 molecules with published experimental GWP100 and
atmospheric lifetime values from peer-reviewed sources:

| Source | License | Molecules | Reference |
|---|---|---|---|
| Hodnebrog et al. 2020, Reviews of Geophysics | CC BY 4.0 | 188 | doi:10.1029/2019RG000691 (PMC7518032) |
| IPCC AR6 WG1 Chapter 7 Supplementary Material | IPCC re-use terms (attribution required) | 29 | Table 7.SM.7, https://www.ipcc.ch/report/ar6/wg1/ |
| WMO 2022 Scientific Assessment of Ozone Depletion | Public domain (WMO/UNEP) | 1 | Annex A1, https://csl.noaa.gov/assessments/ozone/2022/ |
| Hand-curated (3M, Honeywell, Solvay datasheets) | Public product datasheets | 8 | Various manufacturer safety data sheets |

The training data was acquired via:
- PMC OAI-PMH endpoint for Hodnebrog 2020 (CC BY 4.0 open-access article)
- Direct PDF download for IPCC AR6 (publicly released supplementary material)
- PubChem REST API for CAS-to-SMILES resolution (public domain, NIH/NCBI)

### Holdout evaluation metrics

| Metric | Value |
|---|---|
| Holdout MAE log10(GWP100) | 0.342 |
| Holdout R^2 log10(GWP100) | 0.929 |
| Holdout N | 31 (Tanimoto-clustered, scaffold-novel) |

Full training pipeline and reproducibility instructions: see `training/REPRODUCING.md`.

## Key Python dependencies (all permissive)

| Component | License | Source |
|---|---|---|
| numpy | BSD-3-Clause | https://github.com/numpy/numpy |
| pandas | BSD-3-Clause | https://github.com/pandas-dev/pandas |
| scipy | BSD-3-Clause | https://github.com/scipy/scipy |
| matplotlib | PSF (BSD-compatible) | https://github.com/matplotlib/matplotlib |
| seaborn | BSD-3-Clause | https://github.com/mwaskom/seaborn |
| requests | Apache-2.0 | https://github.com/psf/requests |

## Container base image

| Component | License | Source |
|---|---|---|
| Azure Linux 3.0 (Python 3.12) | MIT | mcr.microsoft.com/azurelinux/base/python:3.12 |

## Notes

- No proprietary or restricted-license components are bundled.
- All training data sources are publicly available and appropriately licensed.
- The Hodnebrog 2020 article is CC BY 4.0; any redistribution of derived data
  must include attribution to the original authors.
- IPCC material is subject to IPCC re-use terms: attribution required, no
  endorsement implied.
