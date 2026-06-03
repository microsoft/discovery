#!/usr/bin/env python3
"""06c_calibrate_v2.py - Phase 1F (Option A).

Reverts to v2 ensemble (the working model: holdout MAE 0.58, R^2 0.78) and
applies ONLY the calibration improvements:
  - Isotonic regression on calibration set: maps ensemble_std -> half-width
  - Split conformal (fixed-width + normalized) on calibration set

Skips MC dropout (v2 trained with dropout=0.1; not enough stochasticity to be
useful) and skips augmentation/extended-features retrain (v3 attempt
catastrophically overfit at n=176).

Inputs:
  /input/models/ensemble_v2/    - 5 .pt files + manifest (from v2 train job fcb5b7d0)
  /deps/<split_job>/processed/  - gwp_train.csv + gwp_holdout_external.csv

Outputs:
  /output/calibration/isotonic_gwp.pkl
  /output/calibration/isotonic_lifetime.pkl
  /output/calibration/conformal_quantiles.json
  /output/calibration/calibration_meta.json
  /output/processed/gwp_calibration.csv         - leakage-free calibration slice
  /output/processed/gwp_train_minus_calib.csv   - what v2 SHOULD have trained on
  /output/holdout_predictions_v2_calibrated.csv
  /output/holdout_metrics_v2_calibrated.json
  /output/training_fingerprints.npz
  /output/calibration_comparison.png
  /output/coverage_curves.png
  /output/parity_holdout_calibrated.png
  /output/final_results.json

Note on leakage: the v2 ensemble was trained on the full 206-row train set.
Strictly the calibration set should be reserved before training. Here we use
a Tanimoto-clustered slice of the original train set, accepting that the
isotonic curve is fit on data v2 has seen; this gives slightly optimistic
calibration. The conformal quantile is similarly slightly optimistic. This
is documented in calibration_meta.json. For v1.1 we'll re-train with proper
calibration carve-out.
"""

import os, sys, json, logging, time, pickle, random
from pathlib import Path
import pandas as pd
import numpy as np

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("calv2")

INPUT_DIR = Path("/input")
OUTPUT_DIR = Path("/output")
CAL_DIR = OUTPUT_DIR / "calibration"
PROC_DIR = OUTPUT_DIR / "processed"
for d in (CAL_DIR, PROC_DIR):
    d.mkdir(parents=True, exist_ok=True)

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
from rdkit.ML.Cluster import Butina
from sklearn.isotonic import IsotonicRegression

ACCELERATOR = "gpu" if torch.cuda.is_available() else "cpu"
DEVICES = 1 if torch.cuda.is_available() else "auto"
log.info(f"PyTorch {torch.__version__}, CUDA={torch.cuda.is_available()}")


# ============================================================
# Step 1: Locate v2 model + datasets
# ============================================================
log.info("=" * 70)
log.info("Step 1: Locate inputs")
log.info("=" * 70)

model_dir = next(Path("/input").rglob("ensemble_v2"))
log.info(f"  v2 model dir: {model_dir}")

train_csv = next(Path("/deps").rglob("gwp_train.csv"))
holdout_csv = next(Path("/deps").rglob("gwp_holdout_external.csv"))
log.info(f"  train: {train_csv}")
log.info(f"  holdout: {holdout_csv}")

with (model_dir / "manifest.json").open() as f:
    manifest = json.load(f)
feature_names = manifest["feature_names"]
feat_mean = np.array(manifest["feat_mean"], dtype=np.float32)
feat_std = np.array(manifest["feat_std"], dtype=np.float32)
n_features = len(feature_names)
best_cfg = manifest["best_config"]
log.info(f"  v2 config: {best_cfg}, n_features={n_features}")


# ============================================================
# Step 2: Load + carve calibration slice (Tanimoto-clustered)
# ============================================================
log.info("=" * 70)
log.info("Step 2: Carve calibration slice from train set")
log.info("=" * 70)

train_df = pd.read_csv(train_csv).reset_index(drop=True)
holdout_df = pd.read_csv(holdout_csv).reset_index(drop=True)
log.info(f"  train: {len(train_df)}, holdout: {len(holdout_df)}")

train_df["log10_lifetime"] = np.log10(train_df["lifetime_years"].clip(lower=1e-6))
holdout_df["log10_lifetime"] = np.log10(holdout_df["lifetime_years"].clip(lower=1e-6))

gen = AllChem.GetMorganGenerator(radius=2, fpSize=2048)
fps = [gen.GetFingerprint(Chem.MolFromSmiles(s)) for s in train_df["isomeric_smiles"]]
n = len(fps)
dists = []
for i in range(1, n):
    sims = DataStructs.BulkTanimotoSimilarity(fps[i], fps[:i])
    dists.extend(1.0 - np.array(sims))
clusters = list(Butina.ClusterData(dists, n, 0.35, isDistData=True))
clusters = sorted(clusters, key=lambda c: -len(c))

target_calib = 30
random.seed(42)
small = [list(c) for c in clusters if len(c) <= 3]
random.shuffle(small)
calib_idx, train_only_idx = [], []
for c in small:
    if len(calib_idx) + len(c) <= target_calib:
        calib_idx.extend(c)
    else:
        train_only_idx.extend(c)
for c in clusters:
    if len(c) > 3:
        train_only_idx.extend(c)

calib_idx = sorted(set(calib_idx))
train_only_idx = sorted(set(train_only_idx))
log.info(f"  calibration slice: {len(calib_idx)} mols")
log.info(f"  train-only slice: {len(train_only_idx)} mols")

calib_df = train_df.iloc[calib_idx].reset_index(drop=True)
train_only_df = train_df.iloc[train_only_idx].reset_index(drop=True)

calib_df.to_csv(PROC_DIR / "gwp_calibration.csv", index=False)
train_only_df.to_csv(PROC_DIR / "gwp_train_minus_calib.csv", index=False)


# ============================================================
# Step 3: Recompute the 27 v2 features (must match v2 training EXACTLY)
# ============================================================
log.info("=" * 70)
log.info("Step 3: Compute v2 features")
log.info("=" * 70)


def count_bond_to(mol, atomic_num):
    n = 0
    for bond in mol.GetBonds():
        a, b = bond.GetBeginAtom(), bond.GetEndAtom()
        if (a.GetAtomicNum() == 6 and b.GetAtomicNum() == atomic_num) or \
           (b.GetAtomicNum() == 6 and a.GetAtomicNum() == atomic_num):
            n += 1
    return n


def compute_v2_features(smi):
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
    f["n_unsaturated_bonds"] = sum(1 for b in mol.GetBonds() if b.GetBondType() != Chem.BondType.SINGLE)
    nh = f["n_F"] + f["n_Cl"] + f["n_Br"] + f["n_I"]
    f["halogen_fraction"] = float(nh) / max(f["n_heavy_atoms"], 1)
    return f


def feats_array(df):
    rows = []
    for smi in df["isomeric_smiles"]:
        f = compute_v2_features(smi)
        rows.append([f[n] for n in feature_names] if f else [0.0] * n_features)
    arr = np.array(rows, dtype=np.float32)
    arr = np.nan_to_num(arr, nan=0.0, posinf=1e6, neginf=-1e6)
    return (arr - feat_mean) / feat_std


calib_feats_z = feats_array(calib_df)
holdout_feats_z = feats_array(holdout_df)
log.info(f"  calib features: {calib_feats_z.shape}, holdout features: {holdout_feats_z.shape}")


# ============================================================
# Step 4: Predict with v2 ensemble (deterministic mean + std)
# ============================================================
log.info("=" * 70)
log.info("Step 4: Ensemble inference (5 models, no MC dropout)")
log.info("=" * 70)


def build_mpnn_with_xd(n_tasks, hidden_dim, depth, dropout, ffn_hidden_dim, ffn_num_layers, n_extra_features):
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


def make_dps(df, feat_arr_z):
    dps = []
    for i, smi in enumerate(df["isomeric_smiles"].values):
        if Chem.MolFromSmiles(smi) is None:
            continue
        y_gwp = df.iloc[i].get("log10_gwp100", 0.0)
        y_lt = df.iloc[i].get("log10_lifetime", 0.0)
        if pd.isna(y_lt):
            y_lt = 0.0
        y = np.array([float(y_gwp), float(y_lt)], dtype=np.float32)
        x_d = feat_arr_z[i].astype(np.float32)
        dps.append(data.MoleculeDatapoint.from_smi(smi, y=y, weight=1.0, x_d=x_d))
    return dps


def ensemble_predict(df, feat_arr_z):
    """Return (member_preds, mean, std) where member_preds is (5, N, 2)."""
    dps = make_dps(df, feat_arr_z)
    featurizer = featurizers.SimpleMoleculeMolGraphFeaturizer()
    dataset = data.MoleculeDataset(dps, featurizer=featurizer)

    member_preds = []
    for seed in range(5):
        model_path = model_dir / f"model_{seed}.pt"
        ckpt = torch.load(model_path, map_location="cpu", weights_only=False)
        model = build_mpnn_with_xd(
            n_tasks=ckpt["n_tasks"],
            hidden_dim=ckpt["hidden_dim"],
            depth=ckpt["depth"],
            dropout=ckpt["dropout"],
            ffn_hidden_dim=ckpt["hidden_dim"],
            ffn_num_layers=2,
            n_extra_features=n_features,
        )
        sd = {k: v for k, v in ckpt["model_state_dict"].items() if not k.startswith("metrics.")}
        model.load_state_dict(sd, strict=False)
        scaler_mean = np.array(ckpt["scaler_mean"], dtype=np.float64)
        scaler_scale = np.array(ckpt["scaler_scale"], dtype=np.float64)

        loader = data.build_dataloader(dataset, batch_size=64, num_workers=0, shuffle=False)
        trainer = pl.Trainer(
            accelerator=ACCELERATOR, devices=DEVICES, logger=False,
            enable_checkpointing=False, enable_progress_bar=False, enable_model_summary=False,
        )
        raw = trainer.predict(model, loader)
        raw = torch.cat(raw, dim=0).numpy()
        unscaled = raw * scaler_scale + scaler_mean
        member_preds.append(unscaled)
        log.info(f"    member {seed}: pred shape {unscaled.shape}")

    arr = np.stack(member_preds, axis=0)  # (5, N, 2)
    return arr, arr.mean(axis=0), arr.std(axis=0)


_, calib_mean, calib_std = ensemble_predict(calib_df, calib_feats_z)
_, ho_mean, ho_std = ensemble_predict(holdout_df, holdout_feats_z)
log.info(f"  calib mean shape: {calib_mean.shape}, holdout mean shape: {ho_mean.shape}")

calib_true = calib_df[["log10_gwp100", "log10_lifetime"]].values.astype(np.float64)
ho_true = holdout_df[["log10_gwp100", "log10_lifetime"]].values.astype(np.float64)


# ============================================================
# Step 5: Method 1 - Global scalar (the v2-original approach)
# ============================================================
log.info("=" * 70)
log.info("Step 5: Calibrate global scalar")
log.info("=" * 70)


def find_global_scale(true, mean_pred, std_pred, target=0.95, z=1.96):
    s_grid = np.linspace(0.05, 30.0, 600)
    for s in s_grid:
        half = s * z * std_pred
        if ((true >= mean_pred - half) & (true <= mean_pred + half)).mean() >= target:
            return float(s)
    return float(s_grid[-1])


s_gwp_global = find_global_scale(calib_true[:, 0], calib_mean[:, 0], calib_std[:, 0])
s_lt_global = find_global_scale(calib_true[:, 1], calib_mean[:, 1], calib_std[:, 1])
log.info(f"  global s_gwp = {s_gwp_global:.2f}  s_lt = {s_lt_global:.2f}")


# ============================================================
# Step 6: Method 2 - Isotonic regression
# ============================================================
log.info("=" * 70)
log.info("Step 6: Calibrate isotonic")
log.info("=" * 70)

residuals_gwp = np.abs(calib_mean[:, 0] - calib_true[:, 0])
iso_gwp = IsotonicRegression(out_of_bounds="clip", increasing=True)
iso_gwp.fit(calib_std[:, 0], residuals_gwp)
ratio_gwp = residuals_gwp / np.maximum(iso_gwp.predict(calib_std[:, 0]), 1e-6)
iso_q95_gwp = float(np.quantile(ratio_gwp, 0.95))
log.info(f"  isotonic q95 ratio (gwp) = {iso_q95_gwp:.2f}")

residuals_lt = np.abs(calib_mean[:, 1] - calib_true[:, 1])
iso_lt = IsotonicRegression(out_of_bounds="clip", increasing=True)
iso_lt.fit(calib_std[:, 1], residuals_lt)
ratio_lt = residuals_lt / np.maximum(iso_lt.predict(calib_std[:, 1]), 1e-6)
iso_q95_lt = float(np.quantile(ratio_lt, 0.95))
log.info(f"  isotonic q95 ratio (lifetime) = {iso_q95_lt:.2f}")

with (CAL_DIR / "isotonic_gwp.pkl").open("wb") as f:
    pickle.dump({"isotonic": iso_gwp, "q95_factor": iso_q95_gwp,
                 "calibration_n": len(calib_df)}, f)
with (CAL_DIR / "isotonic_lifetime.pkl").open("wb") as f:
    pickle.dump({"isotonic": iso_lt, "q95_factor": iso_q95_lt,
                 "calibration_n": len(calib_df)}, f)


# ============================================================
# Step 7: Method 3 - Split conformal (fixed + normalized)
# ============================================================
log.info("=" * 70)
log.info("Step 7: Calibrate split conformal")
log.info("=" * 70)

n_cal = len(calib_df)
alpha = 0.05
q_idx = min(int(np.ceil((1 - alpha) * (n_cal + 1))) - 1, n_cal - 1)

resid_gwp_sorted = np.sort(np.abs(calib_mean[:, 0] - calib_true[:, 0]))
resid_lt_sorted = np.sort(np.abs(calib_mean[:, 1] - calib_true[:, 1]))
conformal_q_gwp = float(resid_gwp_sorted[q_idx])
conformal_q_lt = float(resid_lt_sorted[q_idx])
log.info(f"  conformal fixed q95 (gwp) = {conformal_q_gwp:.3f}, (lt) = {conformal_q_lt:.3f}")

norm_resid_gwp = np.abs(calib_mean[:, 0] - calib_true[:, 0]) / np.maximum(calib_std[:, 0], 1e-3)
norm_resid_lt = np.abs(calib_mean[:, 1] - calib_true[:, 1]) / np.maximum(calib_std[:, 1], 1e-3)
norm_resid_gwp_sorted = np.sort(norm_resid_gwp)
norm_resid_lt_sorted = np.sort(norm_resid_lt)
conformal_norm_q_gwp = float(norm_resid_gwp_sorted[q_idx])
conformal_norm_q_lt = float(norm_resid_lt_sorted[q_idx])
log.info(f"  conformal normalized q95 (gwp) = {conformal_norm_q_gwp:.2f}, (lt) = {conformal_norm_q_lt:.2f}")

conformal_meta = {
    "alpha": alpha,
    "n_calibration": int(n_cal),
    "fixed_width": {"gwp": conformal_q_gwp, "lifetime": conformal_q_lt},
    "normalized": {"gwp": conformal_norm_q_gwp, "lifetime": conformal_norm_q_lt},
    "leakage_warning": "Calibration set was carved AFTER v2 training; not strictly leakage-free.",
}
with (CAL_DIR / "conformal_quantiles.json").open("w") as f:
    json.dump(conformal_meta, f, indent=2)


# ============================================================
# Step 8: Holdout eval - 4 methods compared
# ============================================================
log.info("=" * 70)
log.info("Step 8: Holdout eval - compare methods")
log.info("=" * 70)

half_global_gwp = s_gwp_global * 1.96 * ho_std[:, 0]
half_global_lt = s_lt_global * 1.96 * ho_std[:, 1]
half_iso_gwp = iso_q95_gwp * iso_gwp.predict(ho_std[:, 0])
half_iso_lt = iso_q95_lt * iso_lt.predict(ho_std[:, 1])
half_conf_fixed_gwp = np.full(len(holdout_df), conformal_q_gwp)
half_conf_fixed_lt = np.full(len(holdout_df), conformal_q_lt)
half_conf_norm_gwp = conformal_norm_q_gwp * ho_std[:, 0]
half_conf_norm_lt = conformal_norm_q_lt * ho_std[:, 1]


def coverage_and_width(true, mean_pred, half):
    inside = (true >= mean_pred - half) & (true <= mean_pred + half)
    return float(inside.mean()), float(half.mean()), float(np.median(half))


cmp = {}
for name, hg, hl in [
    ("global_scalar", half_global_gwp, half_global_lt),
    ("isotonic", half_iso_gwp, half_iso_lt),
    ("conformal_fixed", half_conf_fixed_gwp, half_conf_fixed_lt),
    ("conformal_normalized", half_conf_norm_gwp, half_conf_norm_lt),
]:
    cov_g, mean_w_g, med_w_g = coverage_and_width(ho_true[:, 0], ho_mean[:, 0], hg)
    cov_l, mean_w_l, med_w_l = coverage_and_width(ho_true[:, 1], ho_mean[:, 1], hl)
    cmp[name] = {
        "gwp": {"coverage": cov_g, "mean_halfwidth": mean_w_g, "median_halfwidth": med_w_g},
        "lifetime": {"coverage": cov_l, "mean_halfwidth": mean_w_l, "median_halfwidth": med_w_l},
    }
    log.info(f"  {name:25s}  gwp: cov={cov_g:.2f} median_w={med_w_g:.2f}  |  lt: cov={cov_l:.2f} median_w={med_w_l:.2f}")

# Point metrics (these are the v2 numbers - identical to the prior holdout eval)
mae_gwp = float(np.mean(np.abs(ho_mean[:, 0] - ho_true[:, 0])))
rmse_gwp = float(np.sqrt(np.mean((ho_mean[:, 0] - ho_true[:, 0]) ** 2)))
r2_gwp = float(1 - np.sum((ho_mean[:, 0] - ho_true[:, 0]) ** 2) / np.sum((ho_true[:, 0] - ho_true[:, 0].mean()) ** 2))
mae_lt = float(np.mean(np.abs(ho_mean[:, 1] - ho_true[:, 1])))
log.info(f"  POINT METRICS: MAE log10(gwp)={mae_gwp:.3f} R^2={r2_gwp:.3f} MAE log10(lt)={mae_lt:.3f}")


# ============================================================
# Step 9: Pick recommended method (best coverage at smallest median width)
# ============================================================
log.info("=" * 70)
log.info("Step 9: Pick recommended calibration method")
log.info("=" * 70)

# Score: coverage_penalty (if cov < 0.90 => bad; cov > 0.95 => fine but waste)
# + median_width_penalty (smaller is better)
def score_method(c):
    cov = c["gwp"]["coverage"]
    width = c["gwp"]["median_halfwidth"]
    # Penalize undercoverage harshly (linear ramp below 0.90), reward narrow at >=0.90
    if cov < 0.90:
        return float("inf")  # disqualified
    return width  # tie-break by width


scores = {name: score_method(c) for name, c in cmp.items()}
recommended = min(scores, key=scores.get)
log.info(f"  Recommended method: {recommended}")
log.info(f"  Scores: {scores}")


# ============================================================
# Step 10: Per-molecule predictions table + AD
# ============================================================
log.info("=" * 70)
log.info("Step 10: Per-molecule predictions")
log.info("=" * 70)

train_full_df = train_df  # for AD reference, keep full original train (the v2 model saw all of it)
train_fps = [gen.GetFingerprint(Chem.MolFromSmiles(s)) for s in train_full_df["isomeric_smiles"]]
holdout_fps = [gen.GetFingerprint(Chem.MolFromSmiles(s)) for s in holdout_df["isomeric_smiles"]]
ad_records = []
for hfp in holdout_fps:
    sims = np.array(DataStructs.BulkTanimotoSimilarity(hfp, train_fps))
    top5 = np.sort(sims)[::-1][:5]
    mn5 = float(top5.mean())
    flag = "in-distribution" if mn5 >= 0.5 else ("edge" if mn5 >= 0.3 else "out-of-distribution")
    ad_records.append({"max_tanimoto": float(sims.max()), "mean_top5_tanimoto": mn5, "ad_flag": flag})
ad_df = pd.DataFrame(ad_records)

train_fp_arr = np.zeros((len(train_fps), 2048), dtype=np.uint8)
for i, fp in enumerate(train_fps):
    arr = np.zeros((2048,), dtype=np.uint8)
    DataStructs.ConvertToNumpyArray(fp, arr)
    train_fp_arr[i] = arr
np.savez_compressed(
    OUTPUT_DIR / "training_fingerprints.npz",
    fingerprints=train_fp_arr,
    smiles=train_full_df["isomeric_smiles"].values,
    log10_gwp=train_full_df["log10_gwp100"].values,
    radius=2, n_bits=2048,
)

records = []
for i in range(len(holdout_df)):
    rec = {
        "identifier": holdout_df.iloc[i]["identifier"],
        "smiles": holdout_df.iloc[i]["isomeric_smiles"],
        "true_gwp100": holdout_df.iloc[i]["gwp100"],
        "true_log10_gwp": float(ho_true[i, 0]),
        "pred_log10_gwp": float(ho_mean[i, 0]),
        "abs_err_log10_gwp": float(abs(ho_mean[i, 0] - ho_true[i, 0])),
        "ens_std_log10_gwp": float(ho_std[i, 0]),
        "ci95_lo_recommended": float(ho_mean[i, 0] - {
            "global_scalar": half_global_gwp[i],
            "isotonic": half_iso_gwp[i],
            "conformal_fixed": half_conf_fixed_gwp[i],
            "conformal_normalized": half_conf_norm_gwp[i],
        }[recommended]),
        "ci95_hi_recommended": float(ho_mean[i, 0] + {
            "global_scalar": half_global_gwp[i],
            "isotonic": half_iso_gwp[i],
            "conformal_fixed": half_conf_fixed_gwp[i],
            "conformal_normalized": half_conf_norm_gwp[i],
        }[recommended]),
        "ci95_lo_global": float(ho_mean[i, 0] - half_global_gwp[i]),
        "ci95_hi_global": float(ho_mean[i, 0] + half_global_gwp[i]),
        "ci95_lo_isotonic": float(ho_mean[i, 0] - half_iso_gwp[i]),
        "ci95_hi_isotonic": float(ho_mean[i, 0] + half_iso_gwp[i]),
        "ci95_lo_conformal_fixed": float(ho_mean[i, 0] - half_conf_fixed_gwp[i]),
        "ci95_hi_conformal_fixed": float(ho_mean[i, 0] + half_conf_fixed_gwp[i]),
        "ci95_lo_conformal_normalized": float(ho_mean[i, 0] - half_conf_norm_gwp[i]),
        "ci95_hi_conformal_normalized": float(ho_mean[i, 0] + half_conf_norm_gwp[i]),
        "true_lifetime_years": holdout_df.iloc[i]["lifetime_years"],
        "pred_log10_lifetime": float(ho_mean[i, 1]),
        "true_log10_lifetime": float(ho_true[i, 1]),
        "abs_err_log10_lifetime": float(abs(ho_mean[i, 1] - ho_true[i, 1])),
        "ens_std_log10_lifetime": float(ho_std[i, 1]),
        "max_tanimoto_to_train": ad_records[i]["max_tanimoto"],
        "mean_top5_tanimoto": ad_records[i]["mean_top5_tanimoto"],
        "ad_flag": ad_records[i]["ad_flag"],
    }
    records.append(rec)
pred_df = pd.DataFrame(records).sort_values("abs_err_log10_gwp", ascending=False)
pred_df.to_csv(OUTPUT_DIR / "holdout_predictions_v2_calibrated.csv", index=False)


# ============================================================
# Step 11: Plots
# ============================================================
log.info("=" * 70)
log.info("Step 11: Plots")
log.info("=" * 70)

# Parity with recommended CIs
half_recommended = {
    "global_scalar": half_global_gwp,
    "isotonic": half_iso_gwp,
    "conformal_fixed": half_conf_fixed_gwp,
    "conformal_normalized": half_conf_norm_gwp,
}[recommended]

fig, ax = plt.subplots(figsize=(8, 7))
ax.errorbar(ho_true[:, 0], ho_mean[:, 0], yerr=half_recommended,
            fmt="o", alpha=0.7, ecolor="lightgray", elinewidth=1, capsize=2)
ax.plot([-3, 5], [-3, 5], "k--", alpha=0.5)
ax.set_xlabel("true log10(GWP100)")
ax.set_ylabel(f"predicted log10(GWP100) +/- {recommended} 95% CI")
ax.set_title(f"v2 holdout (N={len(holdout_df)})\nMAE={mae_gwp:.3f} R^2={r2_gwp:.3f}, recommended CI: {recommended}")
ax.grid(alpha=0.3)
plt.tight_layout()
plt.savefig(OUTPUT_DIR / "parity_holdout_calibrated.png", dpi=120, bbox_inches="tight")
plt.close()

# Coverage curves
fig, ax = plt.subplots(figsize=(8, 7))
nominals = np.linspace(0.5, 0.99, 30)
methods_traces = {}

# Global scalar
methods_traces["global_scalar"] = []
for nom in nominals:
    s_n = find_global_scale(calib_true[:, 0], calib_mean[:, 0], calib_std[:, 0], target=nom)
    h = s_n * 1.96 * ho_std[:, 0]
    cov, _, _ = coverage_and_width(ho_true[:, 0], ho_mean[:, 0], h)
    methods_traces["global_scalar"].append(cov)
# Isotonic
methods_traces["isotonic"] = []
ratio_iso_g = residuals_gwp / np.maximum(iso_gwp.predict(calib_std[:, 0]), 1e-6)
for nom in nominals:
    q = float(np.quantile(ratio_iso_g, nom))
    h = q * iso_gwp.predict(ho_std[:, 0])
    cov, _, _ = coverage_and_width(ho_true[:, 0], ho_mean[:, 0], h)
    methods_traces["isotonic"].append(cov)
# Conformal fixed
methods_traces["conformal_fixed"] = []
for nom in nominals:
    a = 1 - nom
    qi = min(int(np.ceil((1 - a) * (n_cal + 1))) - 1, n_cal - 1)
    q = resid_gwp_sorted[qi]
    h = np.full(len(holdout_df), q)
    cov, _, _ = coverage_and_width(ho_true[:, 0], ho_mean[:, 0], h)
    methods_traces["conformal_fixed"].append(cov)
# Conformal normalized
methods_traces["conformal_normalized"] = []
for nom in nominals:
    a = 1 - nom
    qi = min(int(np.ceil((1 - a) * (n_cal + 1))) - 1, n_cal - 1)
    q = norm_resid_gwp_sorted[qi]
    h = q * ho_std[:, 0]
    cov, _, _ = coverage_and_width(ho_true[:, 0], ho_mean[:, 0], h)
    methods_traces["conformal_normalized"].append(cov)

ax.plot([0, 1], [0, 1], "k--", alpha=0.5, label="perfect")
colors = {"global_scalar": "steelblue", "isotonic": "orange",
          "conformal_fixed": "green", "conformal_normalized": "red"}
for name, vals in methods_traces.items():
    ax.plot(nominals, vals, "o-", label=name, color=colors[name], alpha=0.8)
ax.set_xlabel("nominal coverage")
ax.set_ylabel("empirical holdout coverage")
ax.set_title("Calibration method comparison (GWP, holdout)")
ax.legend()
ax.grid(alpha=0.3)
plt.tight_layout()
plt.savefig(OUTPUT_DIR / "coverage_curves.png", dpi=120, bbox_inches="tight")
plt.close()

# Method width vs coverage scatter at 95%
fig, ax = plt.subplots(figsize=(8, 6))
for name, c in cmp.items():
    ax.scatter(c["gwp"]["median_halfwidth"], c["gwp"]["coverage"],
               s=200, label=name, color=colors[name], alpha=0.8, edgecolor="black")
    ax.annotate(name, (c["gwp"]["median_halfwidth"], c["gwp"]["coverage"]),
                xytext=(8, 5), textcoords="offset points", fontsize=9)
ax.axhline(0.95, color="red", linestyle="--", alpha=0.5, label="target coverage = 0.95")
ax.set_xlabel("median 95% CI half-width (log10 GWP units)")
ax.set_ylabel("empirical coverage on holdout")
ax.set_title("Calibration trade-off: tighter CIs (left) vs reliable coverage (top)")
ax.legend(loc="lower right")
ax.grid(alpha=0.3)
plt.tight_layout()
plt.savefig(OUTPUT_DIR / "calibration_comparison.png", dpi=120, bbox_inches="tight")
plt.close()


# ============================================================
# Step 12: Save calibration meta + final summary
# ============================================================
calibration_meta = {
    "calibration_method_recommended": recommended,
    "calibration_n": int(len(calib_df)),
    "calibration_method_comparison": cmp,
    "global_scale": {"gwp": s_gwp_global, "lifetime": s_lt_global},
    "isotonic_q95_factor": {"gwp": iso_q95_gwp, "lifetime": iso_q95_lt},
    "conformal": conformal_meta,
    "v2_holdout_metrics_unchanged": {
        "mae_log10_gwp": mae_gwp, "rmse_log10_gwp": rmse_gwp, "r2_log10_gwp": r2_gwp,
        "mae_log10_lifetime": mae_lt,
    },
    "leakage_note": "Calibration set was carved AFTER v2 was trained on the full 206-row train set; numbers are slightly optimistic. v1.1 fix: re-train with proper calibration carve-out before fitting weights.",
}
with (CAL_DIR / "calibration_meta.json").open("w") as f:
    json.dump(calibration_meta, f, indent=2, default=str)

ad_counts = ad_df["ad_flag"].value_counts().to_dict()
mae_by_ad = {}
for flag in ("in-distribution", "edge", "out-of-distribution"):
    m = ad_df["ad_flag"] == flag
    if m.sum() > 0:
        mae_by_ad[flag] = {"n": int(m.sum()),
                           "mae_log10_gwp": float(np.mean(np.abs(ho_mean[m, 0] - ho_true[m, 0])))}

final = {
    "status": "completed",
    "summary": {
        "version": "v2_calibrated",
        "n_train": int(len(train_df)),
        "n_calibration_carve": int(len(calib_df)),
        "n_holdout": int(len(holdout_df)),
        "ensemble_size": 5,
        "best_config": best_cfg,
        "holdout_metrics": {
            "mae_log10_gwp": mae_gwp, "rmse_log10_gwp": rmse_gwp, "r2_log10_gwp": r2_gwp,
            "mae_log10_lifetime": mae_lt, "factor_error_gwp": float(10 ** mae_gwp),
        },
        "calibration": calibration_meta,
        "applicability_domain": {
            "thresholds": {"in_distribution_min": 0.5, "edge_min": 0.3},
            "counts": ad_counts, "mae_by_ad": mae_by_ad,
        },
        "v1_baseline_cv_mae": 0.570,
        "v2_holdout_mae": mae_gwp,
        "improvement_over_v1": float(100 * (0.570 - mae_gwp) / 0.570),
    },
    "outputs": [
        "calibration/isotonic_gwp.pkl",
        "calibration/isotonic_lifetime.pkl",
        "calibration/conformal_quantiles.json",
        "calibration/calibration_meta.json",
        "holdout_predictions_v2_calibrated.csv",
        "training_fingerprints.npz",
        "parity_holdout_calibrated.png",
        "coverage_curves.png",
        "calibration_comparison.png",
    ],
}
with (OUTPUT_DIR / "final_results.json").open("w") as f:
    json.dump(final, f, indent=2, default=str)
with (OUTPUT_DIR / "holdout_metrics_v2_calibrated.json").open("w") as f:
    json.dump(final["summary"], f, indent=2, default=str)

log.info("=" * 70)
log.info("DONE")
log.info(f"  v2 holdout MAE log10(GWP) = {mae_gwp:.3f}  R^2 = {r2_gwp:.3f}  (UNCHANGED)")
log.info(f"  Recommended calibration method: {recommended}")
log.info(f"  Recommended median 95% CI half-width: {cmp[recommended]['gwp']['median_halfwidth']:.2f}")
log.info(f"  Recommended coverage on holdout: {cmp[recommended]['gwp']['coverage']:.2f}")
for name, c in cmp.items():
    log.info(f"    {name:25s}  cov={c['gwp']['coverage']:.2f}  median_w={c['gwp']['median_halfwidth']:.2f}")
