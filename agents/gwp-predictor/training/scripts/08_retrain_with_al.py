#!/usr/bin/env python3
"""10_retrain_with_active_learning.py - Phase 1H aggregation.

The active-learning loop:
  1. Load gwp_train.csv (206 mols) and gwp_holdout_external.csv (51 mols)
  2. Load active_learning_selection.csv (20 selected holdout mols)
  3. Move the 20 selected mols from holdout to training (using their
     PUBLISHED GWP100 + lifetime values -- NOT Psi4-derived ones)
  4. Retrain v2 chemprop ensemble on augmented 226-mol training set
  5. Re-evaluate on remaining 31-mol holdout
  6. Compare MAE before vs after active learning

Inputs (from depends_on split job):
  /input/processed/gwp_train.csv
  /input/processed/gwp_holdout_external.csv

The 20 selected molecules are embedded inline (from the selection job output).

Outputs:
  /output/gwp_train_augmented.csv (226 rows)
  /output/gwp_holdout_remaining.csv (31 rows)
  /output/models/ensemble_al/model_{0..4}.pt
  /output/models/ensemble_al/manifest.json
  /output/holdout_metrics_al.json
  /output/parity_holdout_al.png
  /output/comparison.json (before vs after)
  /output/final_results.json
"""

import os, sys, json, logging, time, traceback
from pathlib import Path
import pandas as pd
import numpy as np

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("al")

INPUT_DIR = Path("/input")
OUTPUT_DIR = Path("/output")
MODELS_DIR = OUTPUT_DIR / "models" / "ensemble_al"
MODELS_DIR.mkdir(parents=True, exist_ok=True)

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

# The 20 selected molecule identifiers (from selection job)
SELECTED_IDENTIFIERS = [
    "Methyl iodide", "Nitrogen trifluoride", "Sulfuryl fluoride",
    "HFC-272ca", "(z)-hex-2-en-1-ol", "Sulfur hexafluoride",
    "HFC-365mfc", "Hexafluorobuta-1,3-diene", "Hexafluorocyclobutene",
    "1,1,2,2,3,3-hexafluorocyclopentane", "Octamethyltri-siloxane",
    "Octafluorocyclopentene", "2,2,3,3,4,4,5,5-Octafluorocyclopentanol",
    "Decamethyl-tetrasiloxane", "HFE-7300",
    "3,3,4,4,5,5,6,6,7,7,7-Undecafluoroheptan-1-ol",
    "Dodecamethyl-pentasiloxane",
    "3,3,4,4,5,5,6,6,7,7,8,8,9,9,9-Pentadecafluorononan-1-ol",
    "HFE-7500",
    "3,3,4,4,5,5,6,6,7,7,8,8,9,9,10,10,11,11,11-Nonadecafluoroundecan-1-ol",
]

# ============================================================
# Step 1: Load train + holdout, split by selected identifiers
# ============================================================
log.info("=" * 70)
log.info("Step 1: Load and split")
log.info("=" * 70)

train_df = pd.read_csv(INPUT_DIR / "processed" / "gwp_train.csv").reset_index(drop=True)
holdout_df = pd.read_csv(INPUT_DIR / "processed" / "gwp_holdout_external.csv").reset_index(drop=True)
log.info(f"  original train: {len(train_df)}, holdout: {len(holdout_df)}")

# Match selected identifiers to holdout rows
selected_mask = holdout_df["identifier"].isin(SELECTED_IDENTIFIERS)
n_matched = selected_mask.sum()
log.info(f"  matched {n_matched} of {len(SELECTED_IDENTIFIERS)} selected identifiers in holdout")

# Some identifiers might not match exactly due to whitespace/formatting
if n_matched < len(SELECTED_IDENTIFIERS):
    # Try fuzzy matching
    unmatched = [s for s in SELECTED_IDENTIFIERS if s not in holdout_df["identifier"].values]
    log.warning(f"  unmatched identifiers: {unmatched[:5]}")
    # Try substring matching
    for um in unmatched:
        for idx, row in holdout_df.iterrows():
            if um.lower()[:20] in str(row["identifier"]).lower():
                selected_mask.iloc[idx] = True
                log.info(f"    fuzzy matched: {um} -> {row['identifier']}")
                break

transfer_df = holdout_df[selected_mask].copy()
remaining_holdout_df = holdout_df[~selected_mask].copy()
log.info(f"  transferring {len(transfer_df)} mols from holdout to training")
log.info(f"  remaining holdout: {len(remaining_holdout_df)}")

# Augmented training set
train_aug_df = pd.concat([train_df, transfer_df], ignore_index=True)
log.info(f"  augmented training set: {len(train_aug_df)} mols")

# Ensure log10 columns exist
if "log10_gwp100" not in train_aug_df.columns:
    train_aug_df["log10_gwp100"] = np.log10(train_aug_df["gwp100"].clip(lower=1e-6))
train_aug_df["log10_lifetime"] = np.log10(train_aug_df["lifetime_years"].clip(lower=1e-6))
if "log10_gwp100" not in remaining_holdout_df.columns:
    remaining_holdout_df["log10_gwp100"] = np.log10(remaining_holdout_df["gwp100"].clip(lower=1e-6))
remaining_holdout_df["log10_lifetime"] = np.log10(remaining_holdout_df["lifetime_years"].clip(lower=1e-6))

# Save
train_aug_df.to_csv(OUTPUT_DIR / "gwp_train_augmented.csv", index=False)
remaining_holdout_df.to_csv(OUTPUT_DIR / "gwp_holdout_remaining.csv", index=False)


# ============================================================
# Step 2: Compute v2 features (27 features, same as v2 training)
# ============================================================
log.info("=" * 70)
log.info("Step 2: Compute features")
log.info("=" * 70)

FEATURE_NAMES = [
    "n_C_F_bonds", "n_C_Cl_bonds", "n_C_Br_bonds", "n_C_I_bonds",
    "n_F", "n_Cl", "n_Br", "n_I", "n_H", "n_C", "n_O", "n_N", "n_S", "n_Si",
    "mw", "n_heavy_atoms", "n_rotatable_bonds", "n_rings", "n_aromatic_rings",
    "logp_crippen", "mr_crippen", "tpsa", "n_h_donors", "n_h_acceptors",
    "fraction_csp3", "n_unsaturated_bonds", "halogen_fraction",
]


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
    f["n_unsaturated_bonds"] = sum(1 for b in mol.GetBonds() if b.GetBondType() != Chem.BondType.SINGLE)
    nh = f["n_F"] + f["n_Cl"] + f["n_Br"] + f["n_I"]
    f["halogen_fraction"] = float(nh) / max(f["n_heavy_atoms"], 1)
    return f


def feats_array(df):
    rows = []
    for smi in df["isomeric_smiles"]:
        f = compute_features(smi)
        rows.append([f[n] for n in FEATURE_NAMES] if f else [0.0] * len(FEATURE_NAMES))
    arr = np.array(rows, dtype=np.float32)
    return np.nan_to_num(arr, nan=0.0, posinf=1e6, neginf=-1e6)


train_feats = feats_array(train_aug_df)
feat_mean = train_feats.mean(axis=0)
feat_std = train_feats.std(axis=0) + 1e-8
train_feats_z = (train_feats - feat_mean) / feat_std

holdout_feats = feats_array(remaining_holdout_df)
holdout_feats_z = (holdout_feats - feat_mean) / feat_std
log.info(f"  train features: {train_feats_z.shape}, holdout features: {holdout_feats_z.shape}")


# ============================================================
# Step 3: Build datapoints + train 5-model ensemble
# ============================================================
log.info("=" * 70)
log.info("Step 3: Train 5-model ensemble on augmented set")
log.info("=" * 70)


def make_dps(df, feat_arr_z):
    dps = []
    for i, smi in enumerate(df["isomeric_smiles"].values):
        if Chem.MolFromSmiles(smi) is None:
            continue
        y = np.array([
            float(df.iloc[i]["log10_gwp100"]),
            float(df.iloc[i]["log10_lifetime"]) if not np.isnan(df.iloc[i]["log10_lifetime"]) else 0.0,
        ], dtype=np.float32)
        x_d = feat_arr_z[i].astype(np.float32)
        dps.append(data.MoleculeDatapoint.from_smi(smi, y=y, weight=1.0, x_d=x_d))
    return dps


def build_mpnn(n_tasks=2, hidden_dim=500, depth=5, dropout=0.1, n_extra=27):
    mp = cpnn.BondMessagePassing(d_h=hidden_dim, depth=depth, dropout=dropout)
    agg = cpnn.NormAggregation()
    ffn = cpnn.RegressionFFN(
        n_tasks=n_tasks, input_dim=hidden_dim + n_extra,
        hidden_dim=hidden_dim, n_layers=2, dropout=dropout,
    )
    return models.MPNN(mp, agg, ffn, batch_norm=False, metrics=[cpnn.metrics.MAE()])


train_dps = make_dps(train_aug_df, train_feats_z)
log.info(f"  {len(train_dps)} training datapoints")

ensemble_meta = []
for seed in range(5):
    log.info(f"\n--- Ensemble member {seed+1}/5 (seed={seed}) ---")
    t0 = time.time()
    pl.seed_everything(seed, workers=True)
    featurizer = featurizers.SimpleMoleculeMolGraphFeaturizer()
    dataset = data.MoleculeDataset(train_dps, featurizer=featurizer)
    scaler = dataset.normalize_targets()
    loader = data.build_dataloader(dataset, batch_size=64, num_workers=0, shuffle=True)
    model = build_mpnn(n_extra=len(FEATURE_NAMES))
    trainer = pl.Trainer(
        accelerator=ACCELERATOR, devices=DEVICES, max_epochs=60,
        logger=False, enable_checkpointing=False,
        enable_progress_bar=False, enable_model_summary=False,
    )
    trainer.fit(model, loader)
    elapsed = time.time() - t0
    model_path = MODELS_DIR / f"model_{seed}.pt"
    torch.save({
        "model_state_dict": model.state_dict(),
        "scaler_mean": scaler.mean_.tolist(),
        "scaler_scale": scaler.scale_.tolist(),
        "feat_mean": feat_mean.tolist(),
        "feat_std": feat_std.tolist(),
        "feature_names": FEATURE_NAMES,
        "n_tasks": 2,
        "hidden_dim": 500, "depth": 5, "dropout": 0.1,
    }, model_path)
    log.info(f"  saved {model_path.name} in {elapsed:.1f}s")
    ensemble_meta.append({"seed": seed, "train_seconds": elapsed})


# ============================================================
# Step 4: Predict on remaining holdout (31 mols)
# ============================================================
log.info("=" * 70)
log.info("Step 4: Evaluate on remaining holdout")
log.info("=" * 70)

holdout_dps = make_dps(remaining_holdout_df, holdout_feats_z)
featurizer = featurizers.SimpleMoleculeMolGraphFeaturizer()
holdout_dataset = data.MoleculeDataset(holdout_dps, featurizer=featurizer)

member_preds = []
for seed in range(5):
    model_path = MODELS_DIR / f"model_{seed}.pt"
    ckpt = torch.load(model_path, map_location="cpu", weights_only=False)
    model = build_mpnn(n_extra=len(FEATURE_NAMES))
    sd = {k: v for k, v in ckpt["model_state_dict"].items() if not k.startswith("metrics.")}
    model.load_state_dict(sd, strict=False)
    scaler_mean = np.array(ckpt["scaler_mean"], dtype=np.float64)
    scaler_scale = np.array(ckpt["scaler_scale"], dtype=np.float64)
    loader = data.build_dataloader(holdout_dataset, batch_size=64, num_workers=0, shuffle=False)
    trainer = pl.Trainer(
        accelerator=ACCELERATOR, devices=DEVICES, logger=False,
        enable_checkpointing=False, enable_progress_bar=False, enable_model_summary=False,
    )
    raw = trainer.predict(model, loader)
    raw = torch.cat(raw, dim=0).numpy()
    unscaled = raw * scaler_scale + scaler_mean
    member_preds.append(unscaled)

member_preds = np.stack(member_preds, axis=0)
ho_mean = member_preds.mean(axis=0)
ho_std = member_preds.std(axis=0)
ho_true = remaining_holdout_df[["log10_gwp100", "log10_lifetime"]].values.astype(np.float64)

mae_gwp = float(np.mean(np.abs(ho_mean[:, 0] - ho_true[:, 0])))
rmse_gwp = float(np.sqrt(np.mean((ho_mean[:, 0] - ho_true[:, 0]) ** 2)))
r2_gwp = float(1 - np.sum((ho_mean[:, 0] - ho_true[:, 0]) ** 2) / np.sum((ho_true[:, 0] - ho_true[:, 0].mean()) ** 2))
mae_lt = float(np.mean(np.abs(ho_mean[:, 1] - ho_true[:, 1])))

log.info(f"  HOLDOUT MAE log10(GWP) = {mae_gwp:.3f}  (was 0.576 before AL)")
log.info(f"  HOLDOUT R^2 log10(GWP) = {r2_gwp:.3f}  (was 0.779 before AL)")
log.info(f"  HOLDOUT MAE log10(lt)  = {mae_lt:.3f}  (was 0.465 before AL)")
log.info(f"  improvement: {100*(0.576 - mae_gwp)/0.576:+.1f}%")


# ============================================================
# Step 5: Parity plot
# ============================================================
fig, ax = plt.subplots(figsize=(8, 7))
ax.scatter(ho_true[:, 0], ho_mean[:, 0], alpha=0.7, s=40)
ax.plot([-3, 5], [-3, 5], "k--", alpha=0.5)
ax.set_xlabel("true log10(GWP100)")
ax.set_ylabel("predicted log10(GWP100)")
ax.set_title(f"After active learning (N_train={len(train_aug_df)}, N_holdout={len(remaining_holdout_df)})\nMAE={mae_gwp:.3f} R^2={r2_gwp:.3f}")
ax.grid(alpha=0.3)
plt.tight_layout()
plt.savefig(OUTPUT_DIR / "parity_holdout_al.png", dpi=120, bbox_inches="tight")
plt.close()


# ============================================================
# Step 6: Save manifest + comparison
# ============================================================
manifest = {
    "version": "al_cycle1",
    "n_train_original": 206,
    "n_transferred_from_holdout": int(len(transfer_df)),
    "n_train_augmented": int(len(train_aug_df)),
    "n_holdout_remaining": int(len(remaining_holdout_df)),
    "config": {"hidden_dim": 500, "depth": 5, "dropout": 0.1},
    "feature_names": FEATURE_NAMES,
    "feat_mean": feat_mean.tolist(),
    "feat_std": feat_std.tolist(),
    "members": ensemble_meta,
}
with (MODELS_DIR / "manifest.json").open("w") as f:
    json.dump(manifest, f, indent=2, default=str)

comparison = {
    "before_al": {
        "n_train": 206, "n_holdout": 51,
        "mae_log10_gwp": 0.576, "r2_log10_gwp": 0.779, "mae_log10_lifetime": 0.465,
    },
    "after_al": {
        "n_train": int(len(train_aug_df)),
        "n_holdout": int(len(remaining_holdout_df)),
        "mae_log10_gwp": mae_gwp, "r2_log10_gwp": r2_gwp, "mae_log10_lifetime": mae_lt,
    },
    "improvement": {
        "mae_gwp_delta": 0.576 - mae_gwp,
        "mae_gwp_pct": float(100 * (0.576 - mae_gwp) / 0.576),
        "r2_gwp_delta": r2_gwp - 0.779,
    },
}
with (OUTPUT_DIR / "comparison.json").open("w") as f:
    json.dump(comparison, f, indent=2)

final = {
    "status": "completed",
    "summary": {
        **comparison["after_al"],
        "improvement_pct": comparison["improvement"]["mae_gwp_pct"],
        "before_mae": 0.576,
        "after_mae": mae_gwp,
    },
}
with (OUTPUT_DIR / "final_results.json").open("w") as f:
    json.dump(final, f, indent=2)

log.info("=" * 70)
log.info("DONE - Active learning cycle 1 complete")
log.info(f"  before: MAE={0.576:.3f} R^2={0.779:.3f} (N_train=206, N_holdout=51)")
log.info(f"  after:  MAE={mae_gwp:.3f} R^2={r2_gwp:.3f} (N_train={len(train_aug_df)}, N_holdout={len(remaining_holdout_df)})")
log.info(f"  delta:  {comparison['improvement']['mae_gwp_pct']:+.1f}%")
