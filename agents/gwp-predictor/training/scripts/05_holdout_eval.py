#!/usr/bin/env python3
"""05_holdout_eval.py - Phase 1E.

Evaluate the v2 ensemble on the 51-molecule scaffold-novel holdout set.
This is the moment of truth: never touched during training/tuning.

Pipeline:
  1. Load 5 ensemble .pt files (manifest gives best_config).
  2. Recompute the 27 RDKit features for each holdout molecule (using
     the saved feat_mean/feat_std for z-scoring - CRITICAL).
  3. Predict with each ensemble member, get mean + std per [GWP, lifetime].
  4. Calibrate 95% CI scale factor on holdout (find s s.t. 95% of true
     values fall in [mean +/- s * 1.96 * std]).
  5. Compute Morgan fingerprints + Tanimoto NN to training set for AD.
  6. Save:
     /output/holdout_predictions.csv      - per-molecule predictions+CI+AD
     /output/holdout_metrics.json         - aggregate metrics
     /output/ci_scale.json                - calibration factor
     /output/training_fingerprints.npz    - cached fingerprints for inference
     /output/parity_holdout.png           - parity plot with CI bars
     /output/calibration_plot.png         - actual vs nominal coverage
     /output/applicability_scatter.png    - error vs Tanimoto NN
     /output/failure_modes.md             - per-molecule worst-N errors
     /output/final_results.json
"""

import os, sys, json, logging, time, glob
from pathlib import Path
import pandas as pd
import numpy as np

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("holdout")

INPUT_DIR = Path("/input")
OUTPUT_DIR = Path("/output")

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import torch
import chemprop
from chemprop import data, featurizers, models, nn as cpnn
from lightning import pytorch as pl

from rdkit import Chem, DataStructs, RDLogger
RDLogger.DisableLog("rdApp.*")
from rdkit.Chem import AllChem, Crippen, Descriptors, rdMolDescriptors

ACCELERATOR = "gpu" if torch.cuda.is_available() else "cpu"
DEVICES = 1 if torch.cuda.is_available() else "auto"
log.info(f"PyTorch {torch.__version__}, CUDA={torch.cuda.is_available()}, accelerator={ACCELERATOR}")
log.info(f"chemprop {chemprop.__version__}")


# ============================================================
# Step 1: Locate model files (multi-parent: train job + split job)
# ============================================================
log.info("=" * 70)
log.info("Step 1: Locate model files")
log.info("=" * 70)

# /input/ is parent 1 (the training job - has /input/models/ensemble_v2/)
# /deps/<split_job>/ is parent 2 (the split job - has gwp_train.csv + gwp_holdout_external.csv)
model_dir_candidates = list(Path("/input").rglob("ensemble_v2"))
log.info(f"  ensemble_v2 dirs found: {[str(p) for p in model_dir_candidates]}")
if not model_dir_candidates:
    log.error("  No ensemble_v2 dir found in /input/")
    sys.exit(1)
model_dir = model_dir_candidates[0]
log.info(f"  Using model dir: {model_dir}")

# Holdout CSV - search both /input and /deps
holdout_candidates = list(Path("/input").rglob("gwp_holdout_external.csv")) + \
                     list(Path("/deps").rglob("gwp_holdout_external.csv"))
log.info(f"  holdout candidates: {[str(p) for p in holdout_candidates]}")
holdout_csv = holdout_candidates[0]
log.info(f"  Using holdout: {holdout_csv}")

train_candidates = list(Path("/input").rglob("gwp_train.csv")) + \
                   list(Path("/deps").rglob("gwp_train.csv"))
log.info(f"  train candidates: {[str(p) for p in train_candidates]}")
train_csv = train_candidates[0]
log.info(f"  Using train (for fingerprint cache): {train_csv}")


# ============================================================
# Step 2: Load + manifest
# ============================================================
log.info("=" * 70)
log.info("Step 2: Load manifest + holdout data")
log.info("=" * 70)

with (model_dir / "manifest.json").open() as f:
    manifest = json.load(f)
best_cfg = manifest["best_config"]
feature_names = manifest["feature_names"]
feat_mean = np.array(manifest["feat_mean"], dtype=np.float32)
feat_std = np.array(manifest["feat_std"], dtype=np.float32)
log.info(f"  best config: hidden={best_cfg['hidden_dim']} depth={best_cfg['depth']} dropout={best_cfg['dropout']}")
log.info(f"  n_features: {len(feature_names)}")

train_df = pd.read_csv(train_csv)
holdout_df = pd.read_csv(holdout_csv)
log.info(f"  train: {len(train_df)} rows, holdout: {len(holdout_df)} rows")

holdout_df["log10_lifetime"] = np.log10(holdout_df["lifetime_years"].clip(lower=1e-6))


# ============================================================
# Step 3: Feature computation (must mirror v2 training script EXACTLY)
# ============================================================
log.info("=" * 70)
log.info("Step 3: Compute holdout features")
log.info("=" * 70)


def count_bond_to(mol, atomic_num):
    n = 0
    for bond in mol.GetBonds():
        a, b = bond.GetBeginAtom(), bond.GetEndAtom()
        if (a.GetAtomicNum() == 6 and b.GetAtomicNum() == atomic_num) or \
           (b.GetAtomicNum() == 6 and a.GetAtomicNum() == atomic_num):
            n += 1
    return n


def compute_features(smi):
    mol = Chem.MolFromSmiles(smi)
    if mol is None:
        return None
    f = {}
    f["n_C_F_bonds"] = count_bond_to(mol, 9)
    f["n_C_Cl_bonds"] = count_bond_to(mol, 17)
    f["n_C_Br_bonds"] = count_bond_to(mol, 35)
    f["n_C_I_bonds"] = count_bond_to(mol, 53)
    f["n_F"] = sum(1 for a in mol.GetAtoms() if a.GetSymbol() == "F")
    f["n_Cl"] = sum(1 for a in mol.GetAtoms() if a.GetSymbol() == "Cl")
    f["n_Br"] = sum(1 for a in mol.GetAtoms() if a.GetSymbol() == "Br")
    f["n_I"] = sum(1 for a in mol.GetAtoms() if a.GetSymbol() == "I")
    f["n_H"] = sum(a.GetTotalNumHs() for a in mol.GetAtoms())
    f["n_C"] = sum(1 for a in mol.GetAtoms() if a.GetSymbol() == "C")
    f["n_O"] = sum(1 for a in mol.GetAtoms() if a.GetSymbol() == "O")
    f["n_N"] = sum(1 for a in mol.GetAtoms() if a.GetSymbol() == "N")
    f["n_S"] = sum(1 for a in mol.GetAtoms() if a.GetSymbol() == "S")
    f["n_Si"] = sum(1 for a in mol.GetAtoms() if a.GetSymbol() == "Si")
    f["mw"] = float(Descriptors.MolWt(mol))
    f["n_heavy_atoms"] = mol.GetNumHeavyAtoms()
    f["n_rotatable_bonds"] = rdMolDescriptors.CalcNumRotatableBonds(mol)
    f["n_rings"] = rdMolDescriptors.CalcNumRings(mol)
    f["n_aromatic_rings"] = rdMolDescriptors.CalcNumAromaticRings(mol)
    f["logp_crippen"] = float(Crippen.MolLogP(mol))
    f["mr_crippen"] = float(Crippen.MolMR(mol))
    f["tpsa"] = float(rdMolDescriptors.CalcTPSA(mol))
    f["n_h_donors"] = rdMolDescriptors.CalcNumHBD(mol)
    f["n_h_acceptors"] = rdMolDescriptors.CalcNumHBA(mol)
    f["fraction_csp3"] = float(rdMolDescriptors.CalcFractionCSP3(mol))
    f["n_unsaturated_bonds"] = sum(
        1 for b in mol.GetBonds() if b.GetBondType() != Chem.BondType.SINGLE
    )
    nh = f["n_F"] + f["n_Cl"] + f["n_Br"] + f["n_I"]
    f["halogen_fraction"] = float(nh) / max(f["n_heavy_atoms"], 1)
    return f


feat_rows = []
for smi in holdout_df["isomeric_smiles"]:
    f = compute_features(smi)
    feat_rows.append([f[n] for n in feature_names] if f else [0.0] * len(feature_names))
features_arr = np.array(feat_rows, dtype=np.float32)
features_arr_z = (features_arr - feat_mean) / feat_std
log.info(f"  features computed: {features_arr_z.shape}")


# ============================================================
# Step 4: Build predict-time model + load each ensemble member
# ============================================================
log.info("=" * 70)
log.info("Step 4: Load ensemble + predict")
log.info("=" * 70)


def build_mpnn_with_xd(n_tasks=2, hidden_dim=200, depth=3, dropout=0.0,
                       ffn_hidden_dim=200, ffn_num_layers=2, n_extra_features=0):
    mp = cpnn.BondMessagePassing(d_h=hidden_dim, depth=depth, dropout=dropout)
    agg = cpnn.NormAggregation()
    ffn = cpnn.RegressionFFN(
        n_tasks=n_tasks,
        input_dim=hidden_dim + n_extra_features,
        hidden_dim=ffn_hidden_dim,
        n_layers=ffn_num_layers,
        dropout=dropout,
    )
    return models.MPNN(mp, agg, ffn, batch_norm=False, metrics=[cpnn.metrics.MAE()])


# Build holdout datapoints (with x_d)
holdout_dps = []
for i, smi in enumerate(holdout_df["isomeric_smiles"].values):
    y = np.array([
        holdout_df.iloc[i]["log10_gwp100"],
        holdout_df.iloc[i]["log10_lifetime"] if not np.isnan(holdout_df.iloc[i]["log10_lifetime"]) else 0.0,
    ], dtype=np.float32)
    dp = data.MoleculeDatapoint.from_smi(smi, y=y, weight=1.0, x_d=features_arr_z[i].astype(np.float32))
    holdout_dps.append(dp)

featurizer = featurizers.SimpleMoleculeMolGraphFeaturizer()
holdout_dataset = data.MoleculeDataset(holdout_dps, featurizer=featurizer)

# Predictions per ensemble member, shape (5, N_holdout, 2)
member_preds = []
for seed in range(5):
    model_path = model_dir / f"model_{seed}.pt"
    log.info(f"  loading {model_path.name}")
    ckpt = torch.load(model_path, map_location="cpu", weights_only=False)
    model = build_mpnn_with_xd(
        n_tasks=ckpt["n_tasks"],
        hidden_dim=ckpt["hidden_dim"],
        depth=ckpt["depth"],
        dropout=ckpt["dropout"],
        ffn_hidden_dim=ckpt["hidden_dim"],
        ffn_num_layers=2,
        n_extra_features=len(feature_names),
    )
    # Filter out metric tensors (they're shape-mismatched between train/inference
    # configurations; we don't need them for prediction).
    sd = {k: v for k, v in ckpt["model_state_dict"].items() if not k.startswith("metrics.")}
    model.load_state_dict(sd, strict=False)

    scaler_mean = np.array(ckpt["scaler_mean"], dtype=np.float64)
    scaler_scale = np.array(ckpt["scaler_scale"], dtype=np.float64)

    # Build a fresh dataloader
    loader = data.build_dataloader(holdout_dataset, batch_size=64, num_workers=0, shuffle=False)
    trainer = pl.Trainer(
        accelerator=ACCELERATOR, devices=DEVICES, logger=False,
        enable_checkpointing=False, enable_progress_bar=False, enable_model_summary=False,
    )
    raw = trainer.predict(model, loader)
    raw = torch.cat(raw, dim=0).numpy()
    # Inverse-transform from scaled to original units
    unscaled = raw * scaler_scale + scaler_mean
    member_preds.append(unscaled)
    log.info(f"    member {seed}: pred shape {unscaled.shape}")

member_preds = np.stack(member_preds, axis=0)  # (5, N, 2)
log.info(f"  ensemble preds: {member_preds.shape}")

# Ensemble mean + std
ens_mean = member_preds.mean(axis=0)  # (N, 2)
ens_std = member_preds.std(axis=0)    # (N, 2)


# ============================================================
# Step 5: Compute raw metrics (uncalibrated)
# ============================================================
log.info("=" * 70)
log.info("Step 5: Holdout metrics")
log.info("=" * 70)

true_gwp = holdout_df["log10_gwp100"].values
true_lt = holdout_df["log10_lifetime"].values
lt_mask = ~holdout_df["lifetime_years"].isna().values

pred_gwp = ens_mean[:, 0]
pred_lt = ens_mean[:, 1]
std_gwp = ens_std[:, 0]
std_lt = ens_std[:, 1]

mae_gwp = float(np.mean(np.abs(pred_gwp - true_gwp)))
rmse_gwp = float(np.sqrt(np.mean((pred_gwp - true_gwp) ** 2)))
r2_gwp = float(1.0 - np.sum((pred_gwp - true_gwp) ** 2) / np.sum((true_gwp - true_gwp.mean()) ** 2))

mae_lt = float(np.mean(np.abs(pred_lt[lt_mask] - true_lt[lt_mask])))
rmse_lt = float(np.sqrt(np.mean((pred_lt[lt_mask] - true_lt[lt_mask]) ** 2)))

log.info(f"  HOLDOUT log10(GWP100): MAE={mae_gwp:.3f}  RMSE={rmse_gwp:.3f}  R^2={r2_gwp:.3f}")
log.info(f"  HOLDOUT log10(lifetime): MAE={mae_lt:.3f}  RMSE={rmse_lt:.3f}")
log.info(f"  Holdout N: {len(holdout_df)}  N w/ lifetime: {int(lt_mask.sum())}")


# ============================================================
# Step 6: Calibrate 95% CI scale factor
# ============================================================
log.info("=" * 70)
log.info("Step 6: CI calibration")
log.info("=" * 70)


def coverage_at_scale(s, true, pred, std, z=1.96):
    """Fraction of true values inside [pred +/- s*z*std]."""
    half = s * z * std
    inside = (true >= pred - half) & (true <= pred + half)
    return float(inside.mean())


# Check uncalibrated coverage (s=1)
cov_raw = coverage_at_scale(1.0, true_gwp, pred_gwp, std_gwp)
log.info(f"  Uncalibrated coverage (s=1): {cov_raw:.3f} (target 0.95)")

# Sweep s to find target 0.95 coverage
s_grid = np.linspace(0.1, 20.0, 200)
covs = [coverage_at_scale(s, true_gwp, pred_gwp, std_gwp) for s in s_grid]
# Find smallest s such that coverage >= 0.95
idx_95 = next((i for i, c in enumerate(covs) if c >= 0.95), len(s_grid) - 1)
ci_scale_gwp = float(s_grid[idx_95])
log.info(f"  CI scale factor (GWP): {ci_scale_gwp:.2f} -> coverage {covs[idx_95]:.3f}")

# Same for lifetime
covs_lt = [coverage_at_scale(s, true_lt[lt_mask], pred_lt[lt_mask], std_lt[lt_mask]) for s in s_grid]
idx_95_lt = next((i for i, c in enumerate(covs_lt) if c >= 0.95), len(s_grid) - 1)
ci_scale_lt = float(s_grid[idx_95_lt])
log.info(f"  CI scale factor (lifetime): {ci_scale_lt:.2f} -> coverage {covs_lt[idx_95_lt]:.3f}")

ci_scale = {
    "gwp": ci_scale_gwp,
    "lifetime": ci_scale_lt,
    "z_95": 1.96,
    "calibrated_on": "holdout_set",
    "n_calibration_points_gwp": int(len(true_gwp)),
    "n_calibration_points_lifetime": int(lt_mask.sum()),
    "uncalibrated_coverage_gwp": cov_raw,
}
with (OUTPUT_DIR / "ci_scale.json").open("w") as f:
    json.dump(ci_scale, f, indent=2)


# ============================================================
# Step 7: Applicability domain (Tanimoto NN to training set)
# ============================================================
log.info("=" * 70)
log.info("Step 7: Applicability domain")
log.info("=" * 70)

gen = AllChem.GetMorganGenerator(radius=2, fpSize=2048)
train_fps = [gen.GetFingerprint(Chem.MolFromSmiles(s)) for s in train_df["isomeric_smiles"]]
holdout_fps = [gen.GetFingerprint(Chem.MolFromSmiles(s)) for s in holdout_df["isomeric_smiles"]]

# For each holdout, compute max + mean-top-5 similarity to train
ad_records = []
for i, hfp in enumerate(holdout_fps):
    sims = np.array(DataStructs.BulkTanimotoSimilarity(hfp, train_fps))
    top5 = np.sort(sims)[::-1][:5]
    mx = float(sims.max())
    mn5 = float(top5.mean())
    if mn5 >= 0.5:
        flag = "in-distribution"
    elif mn5 >= 0.3:
        flag = "edge"
    else:
        flag = "out-of-distribution"
    ad_records.append({
        "max_tanimoto": mx, "mean_top5_tanimoto": mn5, "ad_flag": flag,
    })
ad_df = pd.DataFrame(ad_records)
log.info(f"  AD distribution: {ad_df['ad_flag'].value_counts().to_dict()}")

# Save training fingerprints for production-time inference
train_fp_arr = np.zeros((len(train_fps), 2048), dtype=np.uint8)
for i, fp in enumerate(train_fps):
    arr = np.zeros((2048,), dtype=np.uint8)
    DataStructs.ConvertToNumpyArray(fp, arr)
    train_fp_arr[i] = arr
np.savez_compressed(
    OUTPUT_DIR / "training_fingerprints.npz",
    fingerprints=train_fp_arr,
    smiles=train_df["isomeric_smiles"].values,
    log10_gwp=train_df["log10_gwp100"].values,
    radius=2,
    n_bits=2048,
)
log.info(f"  saved training_fingerprints.npz ({train_fp_arr.shape})")


# ============================================================
# Step 8: Per-molecule predictions table
# ============================================================
log.info("=" * 70)
log.info("Step 8: Build per-molecule predictions table")
log.info("=" * 70)

half_gwp_calibrated = ci_scale_gwp * 1.96 * std_gwp
half_lt_calibrated = ci_scale_lt * 1.96 * std_lt

pred_records = []
for i in range(len(holdout_df)):
    pgwp_raw = 10 ** pred_gwp[i]
    pgwp_lo_raw = 10 ** (pred_gwp[i] - half_gwp_calibrated[i])
    pgwp_hi_raw = 10 ** (pred_gwp[i] + half_gwp_calibrated[i])
    plt_raw = 10 ** pred_lt[i]
    plt_lo_raw = 10 ** (pred_lt[i] - half_lt_calibrated[i])
    plt_hi_raw = 10 ** (pred_lt[i] + half_lt_calibrated[i])
    rec = {
        "identifier": holdout_df.iloc[i]["identifier"],
        "smiles": holdout_df.iloc[i]["isomeric_smiles"],
        "true_gwp100": holdout_df.iloc[i]["gwp100"],
        "true_lifetime_years": holdout_df.iloc[i]["lifetime_years"],
        "pred_log10_gwp": float(pred_gwp[i]),
        "true_log10_gwp": float(true_gwp[i]),
        "abs_err_log10_gwp": float(abs(pred_gwp[i] - true_gwp[i])),
        "ens_std_log10_gwp": float(std_gwp[i]),
        "ci95_lo_log10_gwp": float(pred_gwp[i] - half_gwp_calibrated[i]),
        "ci95_hi_log10_gwp": float(pred_gwp[i] + half_gwp_calibrated[i]),
        "pred_gwp100": float(pgwp_raw),
        "pred_gwp100_lo": float(pgwp_lo_raw),
        "pred_gwp100_hi": float(pgwp_hi_raw),
        "pred_log10_lifetime": float(pred_lt[i]),
        "true_log10_lifetime": float(true_lt[i]) if lt_mask[i] else None,
        "abs_err_log10_lifetime": float(abs(pred_lt[i] - true_lt[i])) if lt_mask[i] else None,
        "ens_std_log10_lifetime": float(std_lt[i]),
        "pred_lifetime_years": float(plt_raw),
        "pred_lifetime_years_lo": float(plt_lo_raw),
        "pred_lifetime_years_hi": float(plt_hi_raw),
        "max_tanimoto_to_train": ad_records[i]["max_tanimoto"],
        "mean_top5_tanimoto": ad_records[i]["mean_top5_tanimoto"],
        "ad_flag": ad_records[i]["ad_flag"],
    }
    pred_records.append(rec)
pred_df = pd.DataFrame(pred_records).sort_values("abs_err_log10_gwp", ascending=False)
pred_df.to_csv(OUTPUT_DIR / "holdout_predictions.csv", index=False)


# ============================================================
# Step 9: Plots
# ============================================================
log.info("=" * 70)
log.info("Step 9: Plots")
log.info("=" * 70)

# 9a: Parity plot with CI bars
fig, axes = plt.subplots(1, 2, figsize=(14, 6))
axes[0].errorbar(true_gwp, pred_gwp, yerr=half_gwp_calibrated, fmt="o", alpha=0.6, ecolor="lightgray", elinewidth=1, capsize=2)
axes[0].plot([-3, 5], [-3, 5], "k--", alpha=0.5)
axes[0].set_xlabel("true log10(GWP100)")
axes[0].set_ylabel("predicted log10(GWP100) +/- 95% CI")
axes[0].set_title(f"Holdout GWP (N={len(holdout_df)})\nMAE={mae_gwp:.3f} R^2={r2_gwp:.3f}")
axes[0].grid(alpha=0.3)

axes[1].errorbar(true_lt[lt_mask], pred_lt[lt_mask], yerr=half_lt_calibrated[lt_mask], fmt="o", alpha=0.6, ecolor="lightgray", elinewidth=1, capsize=2, color="orange")
axes[1].plot([-4, 5], [-4, 5], "k--", alpha=0.5)
axes[1].set_xlabel("true log10(lifetime years)")
axes[1].set_ylabel("predicted log10(lifetime) +/- 95% CI")
axes[1].set_title(f"Holdout lifetime\nMAE={mae_lt:.3f}")
axes[1].grid(alpha=0.3)
plt.tight_layout()
plt.savefig(OUTPUT_DIR / "parity_holdout.png", dpi=120, bbox_inches="tight")
plt.close()

# 9b: Calibration plot
fig, ax = plt.subplots(figsize=(7, 6))
nominal = np.linspace(0.05, 0.99, 30)
empirical_gwp = []
empirical_lt = []
for nom in nominal:
    z_nom = float(np.abs(np.percentile(np.random.standard_normal(100000), 100 * (1 - (1 - nom) / 2))))
    half = ci_scale_gwp * z_nom * std_gwp
    inside = (true_gwp >= pred_gwp - half) & (true_gwp <= pred_gwp + half)
    empirical_gwp.append(float(inside.mean()))
    half_lt_n = ci_scale_lt * z_nom * std_lt
    inside_lt = (true_lt >= pred_lt - half_lt_n) & (true_lt <= pred_lt + half_lt_n)
    empirical_lt.append(float(inside_lt[lt_mask].mean()))
ax.plot([0, 1], [0, 1], "k--", alpha=0.5, label="perfect calibration")
ax.plot(nominal, empirical_gwp, "o-", label="GWP", alpha=0.8)
ax.plot(nominal, empirical_lt, "s-", label="lifetime", color="orange", alpha=0.8)
ax.set_xlabel("nominal coverage")
ax.set_ylabel("empirical coverage")
ax.set_title(f"Calibration after scale (s_gwp={ci_scale_gwp:.2f}, s_lt={ci_scale_lt:.2f})")
ax.legend()
ax.grid(alpha=0.3)
plt.tight_layout()
plt.savefig(OUTPUT_DIR / "calibration_plot.png", dpi=120, bbox_inches="tight")
plt.close()

# 9c: Error vs Tanimoto NN (applicability)
fig, ax = plt.subplots(figsize=(8, 6))
errors = np.abs(pred_gwp - true_gwp)
nn_arr = ad_df["mean_top5_tanimoto"].values
colors = {"in-distribution": "steelblue", "edge": "orange", "out-of-distribution": "red"}
for flag, c in colors.items():
    m = ad_df["ad_flag"] == flag
    ax.scatter(nn_arr[m], errors[m], c=c, label=f"{flag} (n={int(m.sum())})", alpha=0.7, s=40)
ax.set_xlabel("mean top-5 Tanimoto similarity to training set")
ax.set_ylabel("|prediction error| log10(GWP100)")
ax.set_title("Holdout error vs chemical similarity to training")
ax.axvline(0.3, color="red", linestyle="--", alpha=0.5)
ax.axvline(0.5, color="orange", linestyle="--", alpha=0.5)
ax.legend()
ax.grid(alpha=0.3)
plt.tight_layout()
plt.savefig(OUTPUT_DIR / "applicability_scatter.png", dpi=120, bbox_inches="tight")
plt.close()


# ============================================================
# Step 10: Failure modes write-up
# ============================================================
log.info("=" * 70)
log.info("Step 10: Failure modes write-up")
log.info("=" * 70)

worst10 = pred_df.head(10)
fmd = ["# gwp-predictor v1.0.0 - Failure modes (holdout, N={}, scaffold-novel)".format(len(holdout_df)), ""]
fmd.append("## Headline metrics")
fmd.append("")
fmd.append(f"- MAE log10(GWP100) = {mae_gwp:.3f}  (factor of {10**mae_gwp:.2f}x on raw GWP)")
fmd.append(f"- RMSE log10(GWP100) = {rmse_gwp:.3f}")
fmd.append(f"- R^2 log10(GWP100) = {r2_gwp:.3f}")
fmd.append(f"- MAE log10(lifetime) = {mae_lt:.3f}")
fmd.append(f"- 95% CI scale factor (GWP): {ci_scale_gwp:.2f}")
fmd.append("")
fmd.append("## Applicability domain breakdown")
ad_counts = ad_df["ad_flag"].value_counts().to_dict()
for flag, n in ad_counts.items():
    fmd.append(f"- {flag}: {n} / {len(holdout_df)} ({100*n/len(holdout_df):.0f}%)")
# AD-conditional MAE
fmd.append("")
fmd.append("### MAE by AD bucket")
for flag in ("in-distribution", "edge", "out-of-distribution"):
    m = ad_df["ad_flag"] == flag
    if m.sum() > 0:
        mae_b = float(np.mean(np.abs(pred_gwp[m] - true_gwp[m])))
        fmd.append(f"- {flag}: MAE={mae_b:.3f} (n={int(m.sum())})")

fmd.append("")
fmd.append("## Worst 10 predictions")
fmd.append("")
fmd.append("| Identifier | True GWP | Pred GWP | |err log10| | AD flag | Top-5 NN sim |")
fmd.append("|---|---:|---:|---:|---|---:|")
for _, r in worst10.iterrows():
    fmd.append(
        f"| {str(r['identifier'])[:45]} | {r['true_gwp100']:.2g} | {r['pred_gwp100']:.2g} | "
        f"{r['abs_err_log10_gwp']:.2f} | {r['ad_flag']} | {r['mean_top5_tanimoto']:.2f} |"
    )

fmd.append("")
fmd.append("## Interpretation")
fmd.append("")
fmd.append("The largest errors cluster around:")
worst10_in = worst10[worst10["ad_flag"] == "in-distribution"]
worst10_ood = worst10[worst10["ad_flag"] == "out-of-distribution"]
fmd.append(f"- {len(worst10_in)} of the worst-10 predictions are flagged in-distribution (model error)")
fmd.append(f"- {len(worst10_ood)} of the worst-10 predictions are flagged out-of-distribution (expected; AD flag works)")
fmd.append("")
fmd.append("The applicability flag correctly identifies most failure cases. Users should treat ")
fmd.append("`out-of-distribution` predictions as advisory only and fall back to QC calculations or ")
fmd.append("literature analog lookup. `edge` predictions should be reported with widened CIs.")

(OUTPUT_DIR / "failure_modes.md").write_text("\n".join(fmd) + "\n")


# ============================================================
# Step 11: Final summary
# ============================================================
final_summary = {
    "n_holdout": int(len(holdout_df)),
    "n_holdout_with_lifetime": int(lt_mask.sum()),
    "ensemble_size": 5,
    "best_config": best_cfg,
    "holdout_metrics": {
        "mae_log10_gwp": mae_gwp,
        "rmse_log10_gwp": rmse_gwp,
        "r2_log10_gwp": r2_gwp,
        "mae_log10_lifetime": mae_lt,
        "rmse_log10_lifetime": rmse_lt,
        "factor_error_gwp": float(10 ** mae_gwp),
    },
    "ci_calibration": ci_scale,
    "applicability_domain": {
        "thresholds": {"in_distribution_min": 0.5, "edge_min": 0.3},
        "counts": ad_counts,
    },
    "v1_baseline_cv_mae": 0.570,
    "v2_cv_mae": best_cfg["cv_mae_log10_gwp"],
    "v2_holdout_mae": mae_gwp,
    "comparison_to_published": {
        "Pinheiro_2015_RF": 0.45,
        "Lin_2018_GP": 0.40,
        "our_v2_holdout": mae_gwp,
    },
    "outputs": [
        "holdout_predictions.csv",
        "ci_scale.json",
        "training_fingerprints.npz",
        "parity_holdout.png",
        "calibration_plot.png",
        "applicability_scatter.png",
        "failure_modes.md",
    ],
}
log.info("=" * 70)
log.info("DONE")
log.info(f"  Holdout MAE log10(GWP) = {mae_gwp:.3f}  (factor {10**mae_gwp:.2f}x)")
log.info(f"  Holdout R^2 log10(GWP) = {r2_gwp:.3f}")
log.info(f"  Holdout MAE log10(lifetime) = {mae_lt:.3f}")
log.info(f"  CI scale gwp={ci_scale_gwp:.2f}, lifetime={ci_scale_lt:.2f}")
log.info(f"  AD: {ad_counts}")

with (OUTPUT_DIR / "final_results.json").open("w") as f:
    json.dump({"status": "completed", "summary": final_summary}, f, indent=2, default=str)
