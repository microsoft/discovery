#!/usr/bin/env python3
"""07_select_active_learning_mols.py - Phase 1H step 1.

Selects 20 holdout molecules for Psi4 frequency calcs using a hybrid
strategy:
  - 7 max-novelty (lowest mean-top-5 Tanimoto similarity to training set)
  - 7 max-error (largest |predicted - true| log10 GWP from current v2)
  - 6 max-uncertainty (largest ensemble std)

Buckets are made disjoint (no double-counting). Then assigns each to a
nodepool tier based on heavy-atom count (proxy for Psi4 calc time).

Inputs:
  /input/holdout_predictions_v2_calibrated.csv (from job b01ed71e)

Outputs:
  /output/active_learning_selection.csv
  /output/selection_report.json
  /output/final_results.json
"""

import os, json, logging
from pathlib import Path
import pandas as pd
import numpy as np
from rdkit import Chem, RDLogger
RDLogger.DisableLog("rdApp.*")

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("select")

INPUT_DIR = Path("/input")
OUTPUT_DIR = Path("/output")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Load holdout predictions
pred_csv = next(INPUT_DIR.rglob("holdout_predictions_v2_calibrated.csv"))
log.info(f"Loading {pred_csv}")
df = pd.read_csv(pred_csv).reset_index(drop=True)
log.info(f"  {len(df)} holdout rows")
log.info(f"  AD distribution: {df['ad_flag'].value_counts().to_dict()}")

# Add heavy-atom count for sizing
def heavy_count(smi):
    mol = Chem.MolFromSmiles(smi)
    return mol.GetNumHeavyAtoms() if mol else 0

df["n_heavy"] = df["smiles"].apply(heavy_count)
log.info(f"  heavy-atom range: {df['n_heavy'].min()} - {df['n_heavy'].max()}")


# ============================================================
# Strategy A: Maximum novelty (lowest mean-top-5 Tanimoto)
# ============================================================
N_NOVELTY = 7
novelty_picks = df.nsmallest(N_NOVELTY, "mean_top5_tanimoto").copy()
novelty_picks["selection_strategy"] = "novelty"
log.info(f"\nNovelty picks (top {N_NOVELTY} most-novel):")
for _, r in novelty_picks.iterrows():
    log.info(f"  {r['identifier'][:45]:45s}  NN_top5={r['mean_top5_tanimoto']:.2f}  AD={r['ad_flag']}")

# Remove from candidate pool
remaining = df[~df.index.isin(novelty_picks.index)].copy()


# ============================================================
# Strategy B: Maximum error (largest |pred - true| log10 GWP)
# ============================================================
N_ERROR = 7
error_picks = remaining.nlargest(N_ERROR, "abs_err_log10_gwp").copy()
error_picks["selection_strategy"] = "error"
log.info(f"\nError picks (top {N_ERROR} largest current errors, after novelty):")
for _, r in error_picks.iterrows():
    log.info(f"  {r['identifier'][:45]:45s}  |err|={r['abs_err_log10_gwp']:.2f}  true_GWP={r['true_gwp100']:.2g}  pred=10^{r['pred_log10_gwp']:.2f}")

remaining = remaining[~remaining.index.isin(error_picks.index)].copy()


# ============================================================
# Strategy C: Maximum uncertainty (largest ensemble std)
# ============================================================
N_UNCERTAINTY = 6
uncertainty_picks = remaining.nlargest(N_UNCERTAINTY, "ens_std_log10_gwp").copy()
uncertainty_picks["selection_strategy"] = "uncertainty"
log.info(f"\nUncertainty picks (top {N_UNCERTAINTY} highest ensemble std, after novelty+error):")
for _, r in uncertainty_picks.iterrows():
    log.info(f"  {r['identifier'][:45]:45s}  std={r['ens_std_log10_gwp']:.2f}  AD={r['ad_flag']}")


# ============================================================
# Combine
# ============================================================
selected = pd.concat([novelty_picks, error_picks, uncertainty_picks], ignore_index=False)
selected = selected.sort_values("n_heavy")
log.info(f"\nTotal selected: {len(selected)} mols")
log.info(f"  by strategy: {selected['selection_strategy'].value_counts().to_dict()}")
log.info(f"  by AD flag: {selected['ad_flag'].value_counts().to_dict()}")
log.info(f"  heavy-atom range: {selected['n_heavy'].min()} - {selected['n_heavy'].max()}")


# ============================================================
# Assign to nodepool tier based on heavy-atom count
#   small (<= 10 heavy) -> d48sv6small  (8 cores per Psi4 process)
#   medium (11-15)      -> d48sv6small  (16 cores)
#   large (16-20)       -> d128sv6med   (16 cores)
#   xlarge (>20)        -> d128sv6med or h100 (32 cores + GPU)
# ============================================================
def assign_nodepool(n_heavy):
    if n_heavy <= 10:
        return ("d48sv6small", 8)
    elif n_heavy <= 15:
        return ("d48sv6small", 16)
    elif n_heavy <= 22:
        return ("d128sv6med", 16)
    else:
        return ("h100", 32)

selected[["nodepool", "psi4_threads"]] = selected.apply(
    lambda r: pd.Series(assign_nodepool(r["n_heavy"])), axis=1
)
log.info(f"\nNodepool assignment:")
for np_name in selected["nodepool"].unique():
    sub = selected[selected["nodepool"] == np_name]
    log.info(f"  {np_name:20s}  n={len(sub)}  heavy_range={sub['n_heavy'].min()}-{sub['n_heavy'].max()}")


# ============================================================
# Save outputs
# ============================================================
# Subset of columns we actually need downstream
out_cols = [
    "identifier", "smiles", "true_gwp100", "true_log10_gwp",
    "true_lifetime_years", "true_log10_lifetime",
    "pred_log10_gwp", "abs_err_log10_gwp", "ens_std_log10_gwp",
    "max_tanimoto_to_train", "mean_top5_tanimoto", "ad_flag",
    "n_heavy", "selection_strategy", "nodepool", "psi4_threads",
]
selected[out_cols].to_csv(OUTPUT_DIR / "active_learning_selection.csv", index=False)

report = {
    "n_selected": int(len(selected)),
    "by_strategy": selected["selection_strategy"].value_counts().to_dict(),
    "by_ad_flag": selected["ad_flag"].value_counts().to_dict(),
    "by_nodepool": selected["nodepool"].value_counts().to_dict(),
    "n_heavy_stats": {
        "min": int(selected["n_heavy"].min()),
        "max": int(selected["n_heavy"].max()),
        "mean": float(selected["n_heavy"].mean()),
        "median": float(selected["n_heavy"].median()),
    },
    "tanimoto_stats": {
        "min": float(selected["mean_top5_tanimoto"].min()),
        "max": float(selected["mean_top5_tanimoto"].max()),
        "median": float(selected["mean_top5_tanimoto"].median()),
    },
    "abs_err_stats": {
        "min": float(selected["abs_err_log10_gwp"].min()),
        "max": float(selected["abs_err_log10_gwp"].max()),
        "median": float(selected["abs_err_log10_gwp"].median()),
    },
}
with (OUTPUT_DIR / "selection_report.json").open("w") as f:
    json.dump(report, f, indent=2, default=str)

with (OUTPUT_DIR / "final_results.json").open("w") as f:
    json.dump({"status": "completed", "summary": report}, f, indent=2, default=str)

log.info("\nDONE")
for k, v in report.items():
    log.info(f"  {k}: {v}")
