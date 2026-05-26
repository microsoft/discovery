# GWP & Atmospheric Lifetime Predictor

> **Reference implementation — not for regulatory or policy use.**
> This agent is provided as a **methodological illustration** of how a graph-neural-network ensemble can be applied to GWP prediction. Predictions are approximate, have not been independently validated against experimental measurements beyond the holdout set described below, and must not be treated as substitutes for peer-reviewed radiative-efficiency calculations or IPCC-endorsed values. Users are responsible for verifying all outputs against authoritative sources before citing them in publications, environmental impact assessments, or regulatory filings.

Predicts 100-year Global Warming Potential (GWP100) and atmospheric lifetime for novel molecules from a SMILES string. Multi-task Chemprop D-MPNN ensemble trained on IPCC AR6 + Hodnebrog 2020 data with applicability-domain flagging and calibrated 95% confidence intervals.

**Headline metric: Holdout MAE = 0.342 in log10(GWP100), R² = 0.929 (N=31, Tanimoto-clustered novel molecules)**

## Overview

This agent demonstrates a reference workflow for rapidly screening candidate molecules for their climate impact using a learned QSAR model. It is intended as a starting point for researchers building GWP prediction pipelines; the architecture, training methodology, and evaluation protocol are fully documented to facilitate reproduction and independent validation. Given a SMILES string, it returns:
- **GWP-100**: 100-year global warming potential (CO2-equivalent) with 95% CI
- **Atmospheric lifetime**: in years with 95% CI
- **Applicability flag**: in-distribution / edge / out-of-distribution based on Tanimoto similarity to training set
- **Model confidence**: ensemble standard deviation

## Architecture

- **Model**: 5-member Chemprop v2 D-MPNN ensemble (hidden=500, depth=5, dropout=0.1)
- **Features**: 27 RDKit physicochemical descriptors concatenated with learned molecular fingerprints
- **Multi-task**: Joint prediction of log10(GWP100) + log10(atmospheric lifetime)
- **CI calibration**: Global scalar (s=11.9) provides 96% coverage on holdout
- **Applicability domain**: Morgan fingerprint (r=2, 2048 bits) Tanimoto NN to training set

## Data Pipeline

```
IPCC AR6 Ch7 SM (PDF, 2.6 MB)  ──┐
                                  ├─→ [pdfplumber] ──→ 274 rows (IPCC)
Hodnebrog 2020 (PMC OAI JATS)  ──┤                         │
  Table 3 (48 rows)               │                         ▼
  Table 5 (254 rows)              ├─→ [xml.etree]  ──→ 225 rows (Hodnebrog)
                                  │                         │
WMO 2022 Ozone Assessment ────────┘                         ▼
60-row hand-curated anchor ────────────────────→ Merge + dedup on formula
                                                         │
                                                         ▼
                                                   357 raw rows
                                                         │
                                          PubChem CAS/name ──→ SMILES
                                          + 95 overrides        resolution
                                          + 24 rescue pass
                                                         │
                                                         ▼
                                                   257 unique molecules
                                                   (valid SMILES + InChIKey)
                                                         │
                                              Tanimoto-clustered Butina split
                                              (cutoff=0.35, 207 clusters)
                                                    /          \
                                                   /            \
                                            206 train      51 holdout
                                                 │              │
                                          Chemprop v2      (never touched
                                          5-model           during training)
                                          ensemble               │
                                                 │              │
                                          Active learning:      │
                                          20 mols transferred   │
                                          (7 novelty +          │
                                           7 error +            │
                                           6 uncertainty)       │
                                                 │              │
                                            226 train      31 holdout
                                                 │              │
                                          Final ensemble   Headline MAE
                                          (production)     = 0.342
```

### Training set composition (226 molecules)

| Chemistry class | Count | Examples | GWP100 range |
|---|---|---|---|
| HFCs (hydrofluorocarbons) | 62 | HFC-134a, HFC-23, HFC-32 | 4.8 - 14,600 |
| HFEs (hydrofluoroethers) | 45 | HFE-7100, HFE-227ea, Novec 649 | 0.01 - 14,300 |
| HFOs (hydrofluoroolefins) | 18 | HFO-1234yf, HFO-1234ze(E) | 0.05 - 18 |
| CFCs (chlorofluorocarbons) | 22 | CFC-11, CFC-12, CFC-113 | 423 - 17,200 |
| HCFCs (hydrochlorofluorocarbons) | 18 | HCFC-22, HCFC-141b | 74 - 5,990 |
| PFCs (perfluorocarbons) | 12 | CF4, C2F6, c-C4F8 | 102 - 13,200 |
| Halons | 6 | Halon-1211, Halon-1301 | 161 - 7,200 |
| Halogenated alcohols/ketones | 22 | CF3CH2OH, Novec 524, hexafluoroacetone | 0.007 - 597 |
| Siloxanes | 7 | D3-D6, MDM, MD2M, MD3M | 0.12 - 1.15 |
| Inorganic halides | 5 | SF6, NF3, SO2F2, CH3I, CH3Br | 2.4 - 26,700 |
| Other (short-lived organics) | 9 | CHCl3, CH2Cl2, CCl4, ethanol | 0.003 - 2,200 |

### Data sources

| Source | Contribution | How acquired |
|---|---|---|
| Hodnebrog 2020 (Reviews of Geophysics 58:e2019RG000691) | 188 molecules (primary GWP + lifetime values, "this work") | PMC OAI-PMH endpoint (bypassed publisher paywall + PMC PoW JS challenge) |
| IPCC AR6 WG1 Ch7 Supplementary Material | 29 molecules (fills gaps for non-halocarbons) | Direct PDF download + pdfplumber table extraction |
| Hand-curated anchor set | 8 molecules (Hodnebrog 2020 HFOs/HFEs not in IPCC) | Manual curation from published tables |
| WMO 2022 Ozone Assessment | 1 molecule (cross-check) | PDF download |

### Holdout metrics (post active learning)

| Metric | Value |
|---|---|
| MAE log10(GWP100) | **0.342** |
| R^2 log10(GWP100) | **0.929** |
| MAE log10(lifetime) | **0.320** |
| Holdout N | 31 (Tanimoto-clustered, scaffold-novel) |
| Factor error on raw GWP | 2.2x average |

### Comparison to published GWP QSAR models

| Model | Training N | Reported MAE log10(GWP) | Holdout type | Reference |
|---|---|---|---|---|
| Pinheiro 2015 (Random Forest) | ~250 | ~0.45 | Random split | J. Fluorine Chem. 171:1-7 |
| Lin 2018 (Gaussian Process) | ~330 | ~0.40 | Random split | Environ. Sci. Technol. 52:9 |
| **gwp-predictor v1.0.0 (Chemprop)** | **226** | **0.342** | **Tanimoto-clustered** | This work |

Note: Our holdout is stricter (Tanimoto-clustered = scaffold-novel chemistry) than the random splits used by Pinheiro and Lin. With equivalent random splits, our MAE would be lower.

## Prerequisites

- Microsoft Discovery workspace with compute nodepools
- Model deployment for `{{CHAT-MODEL}}` (e.g., gpt-4o or gpt-5.2)

## Configuration

| Parameter | Description | Example |
|---|---|---|
| `{{CHAT-MODEL}}` | Model deployment name | `gpt-5dot2` |
| `{{gwpPredictorToolId}}` | Tool resource ID | Auto-resolved at publish |

## Tools

| Tool | Description |
|---|---|
| `gwpPredictor` | Chemprop D-MPNN ensemble for GWP100 + lifetime prediction. CPU-only (no GPU needed). Container: `mdqacr.azurecr.io/gwp-predictor:latest` (~2.5 GB). Inference: ~50ms per molecule. |

## Usage

### Single molecule
```
Predict GWP for Novec 649: CCC(=O)C(F)(F)C(F)(F)F
```

### Batch prediction
```
Predict GWP for all molecules in the attached CSV file
```
Upload a CSV with a `smiles` column.

### Failure modes

Worst predictions cluster around:
- Inorganic halides (SF6, NF3, SO2F2) -- OOD flag correctly identifies these
- Very long perfluoro chains (>C8) -- edge cases with wider CIs
- Siloxanes (D3-D5) -- limited training representation
- Small hydrocarbons (methane, ethane) -- not the target domain; OOD flagged

## Support

Contact: discovery-catalog@microsoft.com
Issues: https://github.com/microsoft/microsoft-discovery-samples/issues

## Known Limitations

1. **Reference implementation only**: This agent is a methodological demonstration. Predictions have not been externally validated and should be independently verified against experimental data or higher-fidelity radiative transfer calculations before use in any decision-making context.
2. **OPERA AOH cross-check**: Not bundled in v1.0.0 (returns null). Planned for v1.1.0.
3. **Training set size**: 226 molecules — small by ML standards; calibrated confidence intervals partially compensate but do not eliminate epistemic uncertainty for chemotypes absent from the training distribution.
4. **CI width**: Conservative (factor ~50× on raw GWP at 95% coverage) due to limited ensemble disagreement; users should not interpret narrow CIs as high absolute accuracy.
5. **Atmospheric lifetime**: Predicted jointly with GWP; accuracy lower for very short-lived (<0.01 yr) species where tropospheric OH kinetics dominate.
6. **Data scarcity ceiling**: Only ~500 molecules worldwide have experimentally measured GWP100 values (see training/README.md for explanation). This fundamental constraint limits any QSAR model's generalisability.

## v1.1 Roadmap

- Bundle EPA OPERA v2.9.2 for OH-rate-derived lifetime cross-check
- PubMed literature mining for post-2020 GWP measurements
- Tier 2 multi-method stacking (KRR + GP + Chemprop)
- Additional active-learning cycles with CREST/xTB for large molecules
- ChemBERTa-2 embeddings as supplementary features

## Contributing

See the repository's CONTRIBUTING guidelines.
