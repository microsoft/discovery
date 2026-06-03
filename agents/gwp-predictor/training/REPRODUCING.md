# Reproducing the gwp-predictor training pipeline

## Prerequisites

- Python 3.10+ (3.12 recommended)
- ~4 GB disk space (for PyTorch + model artifacts)
- Internet access (for data download in steps 1-4 and PubChem lookups in step 6)

## Setup

```bash
# Create and activate a virtual environment
python -m venv gwp_env
source gwp_env/bin/activate  # Linux/Mac
# or: gwp_env\Scripts\activate  # Windows

# Install dependencies
pip install -r requirements.txt
```

## Directory convention

Every script reads from an `input/` directory and writes to an `output/` directory.
Between steps, the previous step's output becomes the next step's input.

```bash
# Create the working root
mkdir -p gwp_workdir && cd gwp_workdir

# Helper function to chain steps (bash)
chain_step() {
    rm -rf input
    mv output input 2>/dev/null || mkdir -p input
    mkdir -p output
    export GWP_INPUT_DIR="$(pwd)/input"
    export GWP_OUTPUT_DIR="$(pwd)/output"
    export GWP_WORK_DIR="$(pwd)/workdir"
    mkdir -p workdir
}
```

Each script uses `/input/`, `/output/`, `/workdir/` as hardcoded paths (the Discovery
container convention). Before running locally, either:

- **Option A**: Create symlinks at the root level:
  ```bash
  sudo ln -sf $(pwd)/input /input
  sudo ln -sf $(pwd)/output /output
  sudo ln -sf $(pwd)/workdir /workdir
  ```

- **Option B**: Find-and-replace the paths in each script:
  ```bash
  sed -i 's|/input|./input|g; s|/output|./output|g; s|/workdir|./workdir|g' script.py
  ```

## Execution order

### Phase 1: Data acquisition (steps 1-5)

These steps download and parse the primary GWP data sources.

```bash
# Step 1: Download IPCC AR6 + Hodnebrog 2020 + WMO 2022 PDFs
chain_step
python scripts/01_data_ingest.py
# Output: interim/gwp_unified.csv (60-row anchor), raw/*.pdf

# Step 2: Extract tables from IPCC AR6 PDF
chain_step
python scripts/01b_parse_ipcc_pdfs.py
# Output: tables/ipcc_ar6_p*.csv (28 extracted tables)

# Step 3: Normalize IPCC tables to unified schema
chain_step
python scripts/01c_normalize_tables.py
# Output: processed/gwp_unified.csv (274 rows)
# Note: this script expects Step 2 tables at /input/tables/ AND
#       Step 1 processed data at a deps/ path. You may need to
#       copy Step 1 interim files into a /deps/ subfolder.

# Step 4: Parse Hodnebrog 2020 from PMC OAI JATS XML
chain_step
python scripts/01d_hodnebrog_jats_parse.py
# Output: jats/tables/rog20236-tbl-0005.csv (254 rows)

# Step 5: Merge IPCC + Hodnebrog + anchor into final raw dataset
# This script needs outputs from both Step 3 and Step 4.
# Copy Step 3 output to /input/ and Step 4 output to /deps/
chain_step
cp ../step3_output/processed/* input/processed/ 2>/dev/null
mkdir -p deps && cp -r ../step4_output/* deps/ 2>/dev/null
python scripts/01e_final_merge.py
# Output: processed/gwp_full.csv (357 rows)
```

### Phase 2: SMILES resolution (steps 6-7)

Requires internet access for PubChem REST API calls (~2 min).

```bash
# Step 6: Resolve CAS/name -> canonical SMILES via PubChem
chain_step
python scripts/02_smiles_resolution.py
# Output: processed/gwp_resolved.csv (233 mols), processed/gwp_unresolved.csv (56)

# Step 7: Hand-curated SMILES rescue for remaining 56
chain_step
python scripts/02b_smiles_rescue.py
# Output: processed/gwp_resolved_v2.csv (257 mols)
```

### Phase 3: Split + train (steps 8-9)

```bash
# Step 8: Tanimoto-clustered train/holdout split (80/20)
chain_step
python scripts/03_tanimoto_split.py
# Output: processed/gwp_train.csv (206), processed/gwp_holdout_external.csv (51)

# Step 9: Train 5-model Chemprop D-MPNN ensemble with hyperopt
chain_step
python scripts/04_train_ensemble_v2.py
# Output: models/ensemble_v2/model_{0..4}.pt, sweep/hyperopt_results.csv
# Note: requires PyTorch + chemprop. ~10 min on modern CPU.
```

### Phase 4: Evaluate + calibrate (steps 10-11)

```bash
# Step 10: Holdout evaluation (needs both Step 8 split AND Step 9 models)
# Copy Step 8 output to /deps/ and Step 9 output to /input/
chain_step
mkdir -p deps && cp -r ../step8_output/* deps/
cp -r ../step9_output/* input/
python scripts/05_holdout_eval.py
# Output: holdout_predictions.csv, holdout_metrics.json, parity plot

# Step 11: CI calibration (same inputs as Step 10)
chain_step
cp -r ../step9_output/* input/
mkdir -p deps && cp -r ../step8_output/* deps/
python scripts/06_calibrate_v2.py
# Output: calibration/isotonic_gwp.pkl, calibration_meta.json
```

### Phase 5: Active learning (steps 12-13)

```bash
# Step 12: Select 20 high-value molecules from holdout
chain_step
cp -r ../step11_output/* input/
python scripts/07_select_active_learning.py
# Output: active_learning_selection.csv (20 mols with strategy labels)

# Step 13: Transfer 20 mols to training set, retrain ensemble
chain_step
cp -r ../step8_output/* input/
python scripts/08_retrain_with_al.py
# Output: models/ensemble_al/model_{0..4}.pt (PRODUCTION MODELS)
#         gwp_train_augmented.csv (226 mols), gwp_holdout_remaining.csv (31 mols)
#         Final MAE = 0.342 log10(GWP), R^2 = 0.929
```

### Phase 6: Benchmark (step 14)

```bash
# Step 14: Benchmark on 30 test molecules (self-contained)
chain_step
python scripts/09_benchmark.py
# Output: benchmark_results.json (per-molecule predictions + metrics)
# Note: requires the production model at /app/models/. Either copy the
#       Step 13 models there, or modify MODEL_DIR in the script.
```

## Shortcut: skip data ingest, retrain from provided CSVs

If you only want to retrain the model (skip steps 1-8 and 12):

```bash
mkdir -p input/processed
cp data/processed/gwp_train_augmented.csv input/processed/gwp_train.csv
cp data/processed/gwp_holdout_remaining.csv input/processed/gwp_holdout_external.csv
mkdir -p output
python scripts/08_retrain_with_al.py
```

The provided `data/processed/gwp_train_augmented.csv` contains all 226 molecules with:
SMILES, CAS, GWP100, lifetime, log10 values, source provenance, and cluster IDs.

## Expected final metrics

| Metric | Value |
|--------|-------|
| Training set | 226 molecules |
| Holdout set | 31 molecules (Tanimoto-clustered, scaffold-novel) |
| MAE log10(GWP100) | 0.342 |
| R^2 log10(GWP100) | 0.929 |
| Median factor error | 2.2x on raw GWP |

## Troubleshooting

**"Module not found: chemprop"**: Install via `pip install chemprop==2.2.2 lightning rdkit`.

**PubChem returns 0 hits**: The API changed property names in 2025. The scripts use the
current names (`SMILES`, `ConnectivitySMILES`). If this changes again, update the
`pubchem_props_by_cid()` function in `02_smiles_resolution.py`.

**"/input/ not found"**: Scripts use absolute container paths. Either create symlinks
(see Setup above) or sed-replace to relative paths.

**Multi-parent chaining (steps 5, 10, 11)**: Some scripts need outputs from two prior
steps simultaneously. Copy both into the expected mount points (`/input/` for the primary
parent, `/deps/<id>/` for the secondary). When running locally, just copy both directories'
contents into the appropriate paths as shown in the step-by-step above.