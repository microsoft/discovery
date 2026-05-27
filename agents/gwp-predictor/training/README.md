# gwp-predictor / training

Complete training artifacts for reproducing the gwp-predictor v1.0.0 model.

**See [REPRODUCING.md](REPRODUCING.md) for step-by-step instructions.**

## Quick start (retrain only)

```bash
pip install -r requirements.txt
mkdir -p input/processed output
cp data/processed/gwp_train_augmented.csv input/processed/gwp_train.csv
cp data/processed/gwp_holdout_remaining.csv input/processed/gwp_holdout_external.csv
python scripts/08_retrain_with_al.py
```

## Folder structure

```
training/
  REPRODUCING.md                            Step-by-step local reproduction guide
  requirements.txt                          Python dependencies (pip install -r)
  GWP_Predictor_Training_Pipeline.ipynb     Reproducible Jupyter notebook (100 cells)

  data/processed/
    gwp_train_augmented.csv                 Final training set (226 mols)
    gwp_holdout_remaining.csv               Final holdout set (31 mols)

  scripts/                                  14 pipeline scripts (see REPRODUCING.md)
    01_data_ingest.py                       Download IPCC AR6 + Hodnebrog 2020 + WMO 2022
    01b_parse_ipcc_pdfs.py                  Extract tables from IPCC PDF
    01c_normalize_tables.py                 Normalize to unified schema
    01d_hodnebrog_jats_parse.py             Parse Hodnebrog JATS XML from PMC OAI
    01e_final_merge.py                      Merge all sources (357 rows)
    02_smiles_resolution.py                 CAS/name -> SMILES via PubChem
    02b_smiles_rescue.py                    Hand-curated rescue for 56 failures
    03_tanimoto_split.py                    Butina clustering + 80/20 split
    04_train_ensemble_v2.py                 Chemprop hyperopt + 5-model ensemble
    05_holdout_eval.py                      Holdout evaluation + CI + AD
    06_calibrate_v2.py                      CI calibration (isotonic + conformal)
    07_select_active_learning.py            Select 20 mols for active learning
    08_retrain_with_al.py                   Retrain on 226-mol augmented set
    09_benchmark.py                         Head-to-head vs climatic-gwp

  active_learning/                          Active learning cycle 1 artifacts
  results/                                  Holdout metrics, calibration, plots
  benchmark/                                Benchmark results (ours vs climatic-gwp)
```

## Key metrics

| Stage | N train | N holdout | MAE log10(GWP) | R^2 |
|-------|---------|-----------|----------------|-----|
| After initial split | 206 | 51 | 0.576 | 0.779 |
| After active learning | 226 | 31 | **0.342** | **0.929** |

## Data sources

Raw data is downloaded by `01_data_ingest.py` at runtime (requires internet):
- IPCC AR6 WG1 Ch7 SM: https://www.ipcc.ch/report/ar6/wg1/
- Hodnebrog 2020: PMC OAI endpoint (PMC7518032)
- WMO 2022: https://csl.noaa.gov/assessments/ozone/2022/