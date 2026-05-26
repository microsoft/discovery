#!/usr/bin/env python3
"""GWP Predictor utilities library for Discovery platform workflows.

Predicts 100-year Global Warming Potential (GWP100) and atmospheric lifetime
for molecules from SMILES using a Chemprop D-MPNN ensemble with calibrated
95% confidence intervals and applicability-domain flagging.

Trained on IPCC AR6 + Hodnebrog 2020 data (226 molecules after active learning).
Holdout MAE on log10(GWP100) = 0.342, R^2 = 0.929 (N=31, Tanimoto-clustered).
"""

import os
import sys
import glob
import json
import logging
import shutil
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

# ============= CONSTANTS =============
INPUT_DIR = "/input"
OUTPUT_DIR = "/output"
WORK_DIR = "/workdir"
MODEL_DIR = "/app/models"
SCRATCH_DIR = "/tmp/gwp_scratch"

# Applicability domain thresholds (Tanimoto NN to training set)
AD_IN_DISTRIBUTION_MIN = 0.5
AD_EDGE_MIN = 0.3

# CI calibration (global scalar from v2 calibration; conservative)
CI_SCALE_GWP = 11.9
CI_SCALE_LIFETIME = 5.6
CI_Z_95 = 1.96

# Feature names (must match training exactly)
FEATURE_NAMES = [
    "n_C_F_bonds", "n_C_Cl_bonds", "n_C_Br_bonds", "n_C_I_bonds",
    "n_F", "n_Cl", "n_Br", "n_I", "n_H", "n_C", "n_O", "n_N", "n_S", "n_Si",
    "mw", "n_heavy_atoms", "n_rotatable_bonds", "n_rings", "n_aromatic_rings",
    "logp_crippen", "mr_crippen", "tpsa", "n_h_donors", "n_h_acceptors",
    "fraction_csp3", "n_unsaturated_bonds", "halogen_fraction",
]


# ============= SETUP FUNCTIONS =============
def quick_setup(input_dir="/input", output_dir="/output", work_dir="/workdir"):
    """Initialize logging, create directories, copy input files."""
    global INPUT_DIR, OUTPUT_DIR, WORK_DIR
    INPUT_DIR, OUTPUT_DIR, WORK_DIR = input_dir, output_dir, work_dir
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    for d in [WORK_DIR, OUTPUT_DIR, SCRATCH_DIR]:
        os.makedirs(d, exist_ok=True)
    os.chdir(WORK_DIR)
    _copy_input_files()
    logging.info(f"Working directory: {WORK_DIR}")
    logging.info(f"Input files: {os.listdir(INPUT_DIR) if os.path.exists(INPUT_DIR) else '(none)'}")


def _copy_input_files():
    if os.path.realpath(INPUT_DIR) == os.path.realpath(WORK_DIR):
        return
    if os.path.exists(INPUT_DIR):
        for f in glob.glob(os.path.join(INPUT_DIR, "*")):
            if os.path.isfile(f):
                shutil.copy(f, WORK_DIR)


def quick_finish():
    """Copy key output files to output directory."""
    if os.path.realpath(WORK_DIR) == os.path.realpath(OUTPUT_DIR):
        return
    patterns = ["*.json", "*.csv", "*.png", "*.svg", "*.log"]
    for pattern in patterns:
        for f in glob.glob(os.path.join(WORK_DIR, pattern)):
            shutil.copy(f, OUTPUT_DIR)
    logging.info("Outputs copied to /output")


def save_final_results(results: Dict, output_files: Optional[Dict] = None,
                       file_descriptions: Optional[Dict] = None, status: str = "completed"):
    """Save final results to JSON file (MANDATORY for every script)."""
    final_data = {"status": status, "summary": results}
    if output_files:
        final_data["output_files"] = output_files
    if file_descriptions:
        final_data["file_descriptions"] = file_descriptions
    out_path = os.path.join(OUTPUT_DIR, "final_results.json")
    with open(out_path, "w") as f:
        json.dump(final_data, f, indent=2, default=_json_serializer)
    logging.info(f"Saved final_results.json to {out_path}")


def _json_serializer(obj):
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    try:
        import torch
        if isinstance(obj, torch.Tensor):
            return obj.detach().cpu().numpy().tolist()
    except ImportError:
        pass
    return str(obj)


# ============= SMILES VALIDATION =============
def validate_smiles(smiles: str) -> bool:
    """Check if a SMILES string is valid and parseable by RDKit."""
    if not smiles or not smiles.strip():
        return False
    from rdkit import Chem
    mol = Chem.MolFromSmiles(smiles)
    return mol is not None and mol.GetNumAtoms() > 0


# ============= FEATURE COMPUTATION =============
def _count_bond_to(mol, atomic_num: int) -> int:
    n = 0
    for bond in mol.GetBonds():
        a, b = bond.GetBeginAtom(), bond.GetEndAtom()
        if (a.GetAtomicNum() == 6 and b.GetAtomicNum() == atomic_num) or \
           (b.GetAtomicNum() == 6 and a.GetAtomicNum() == atomic_num):
            n += 1
    return n


def compute_features(smiles: str) -> Optional[Dict[str, float]]:
    """Compute the 27 physicochemical features for one SMILES.

    Returns dict with FEATURE_NAMES keys, or None if SMILES is invalid.
    """
    from rdkit import Chem
    from rdkit.Chem import Crippen, Descriptors, rdMolDescriptors
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return None
    f = {}
    f["n_C_F_bonds"] = _count_bond_to(mol, 9)
    f["n_C_Cl_bonds"] = _count_bond_to(mol, 17)
    f["n_C_Br_bonds"] = _count_bond_to(mol, 35)
    f["n_C_I_bonds"] = _count_bond_to(mol, 53)
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


# ============= MODEL LIFECYCLE =============
_ENSEMBLE_CACHE = None


def load_ensemble(model_dir: str = "/app/models") -> dict:
    """Load the 5-model Chemprop ensemble + scaler + feature stats.

    Returns dict with keys: models, scaler_means, scaler_scales,
    feat_mean, feat_std, n_tasks, config.
    """
    global _ENSEMBLE_CACHE
    if _ENSEMBLE_CACHE is not None:
        return _ENSEMBLE_CACHE

    import torch
    from chemprop import nn as cpnn, models, data as cpdata

    manifest_path = os.path.join(model_dir, "manifest.json")
    with open(manifest_path) as f:
        manifest = json.load(f)

    feat_mean = np.array(manifest["feat_mean"], dtype=np.float32)
    feat_std = np.array(manifest["feat_std"], dtype=np.float32)
    config = manifest.get("config", manifest.get("best_config", {}))
    hidden_dim = config.get("hidden_dim", 500)
    depth = config.get("depth", 5)
    dropout = config.get("dropout", 0.1)
    n_features = len(manifest.get("feature_names", FEATURE_NAMES))

    loaded_models = []
    scaler_means = []
    scaler_scales = []

    for seed in range(5):
        pt_path = os.path.join(model_dir, f"model_{seed}.pt")
        if not os.path.exists(pt_path):
            logging.warning(f"Model file not found: {pt_path}")
            continue
        ckpt = torch.load(pt_path, map_location="cpu", weights_only=False)

        mp = cpnn.BondMessagePassing(d_h=hidden_dim, depth=depth, dropout=dropout)
        agg = cpnn.NormAggregation()
        ffn = cpnn.RegressionFFN(
            n_tasks=2, input_dim=hidden_dim + n_features,
            hidden_dim=hidden_dim, n_layers=2, dropout=dropout,
        )
        model = models.MPNN(mp, agg, ffn, batch_norm=False, metrics=[cpnn.metrics.MAE()])
        sd = {k: v for k, v in ckpt["model_state_dict"].items() if not k.startswith("metrics.")}
        model.load_state_dict(sd, strict=False)
        model.eval()
        loaded_models.append(model)
        scaler_means.append(np.array(ckpt["scaler_mean"], dtype=np.float64))
        scaler_scales.append(np.array(ckpt["scaler_scale"], dtype=np.float64))

    _ENSEMBLE_CACHE = {
        "models": loaded_models,
        "scaler_means": scaler_means,
        "scaler_scales": scaler_scales,
        "feat_mean": feat_mean,
        "feat_std": feat_std,
        "n_tasks": 2,
        "config": config,
        "n_models": len(loaded_models),
    }
    logging.info(f"Loaded {len(loaded_models)} ensemble models from {model_dir}")
    return _ENSEMBLE_CACHE


def load_training_fingerprints(path: str = "/app/models/training_fingerprints.npz") -> np.ndarray:
    """Load cached Morgan fingerprints of training set for AD computation."""
    data = np.load(path)
    return data["fingerprints"]


# ============= APPLICABILITY DOMAIN =============
def compute_applicability(smiles: str, training_fp: Optional[np.ndarray] = None) -> Dict:
    """Compute applicability domain for a single SMILES.

    Returns dict with max_tanimoto, mean_top5_tanimoto, ad_flag.
    """
    from rdkit import Chem, DataStructs
    from rdkit.Chem import AllChem

    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return {"max_tanimoto": 0.0, "mean_top5_tanimoto": 0.0, "ad_flag": "invalid_smiles"}

    gen = AllChem.GetMorganGenerator(radius=2, fpSize=2048)
    query_fp = gen.GetFingerprint(mol)

    if training_fp is None:
        try:
            training_fp = load_training_fingerprints()
        except FileNotFoundError:
            return {"max_tanimoto": 0.0, "mean_top5_tanimoto": 0.0,
                    "ad_flag": "no_training_fingerprints"}

    # Convert training fingerprints from uint8 array to RDKit BitVects
    train_bvs = []
    for i in range(training_fp.shape[0]):
        bv = DataStructs.ExplicitBitVect(2048)
        on_bits = np.where(training_fp[i] > 0)[0]
        for bit in on_bits:
            bv.SetBit(int(bit))
        train_bvs.append(bv)

    sims = np.array(DataStructs.BulkTanimotoSimilarity(query_fp, train_bvs))
    top5 = np.sort(sims)[::-1][:5]
    mx = float(sims.max())
    mn5 = float(top5.mean())

    if mn5 >= AD_IN_DISTRIBUTION_MIN:
        flag = "in-distribution"
    elif mn5 >= AD_EDGE_MIN:
        flag = "edge"
    else:
        flag = "out-of-distribution"

    return {"max_tanimoto": mx, "mean_top5_tanimoto": mn5, "ad_flag": flag}


# ============= SINGLE PREDICTION =============
def predict_gwp_single(smiles: str, ensemble: Optional[dict] = None,
                       training_fp: Optional[np.ndarray] = None) -> Dict:
    """Predict GWP100 + lifetime for a single SMILES.

    Returns the JSON output contract dict:
      smiles, smiles_valid, model_status, gwp_100, gwp_100_low, gwp_100_high,
      atmospheric_lifetime_years, atmospheric_lifetime_years_low/high,
      applicability, tanimoto_nn_mean, lifetime_disagreement, model_id,
      training_set, holdout_mae_log10_gwp.
    """
    import torch
    from chemprop import data as cpdata, featurizers

    result = {
        "smiles": smiles,
        "smiles_valid": False,
        "model_status": "error",
    }

    # Validate SMILES
    if not validate_smiles(smiles):
        result["model_status"] = "invalid_smiles"
        return result
    result["smiles_valid"] = True

    # Load ensemble if not provided
    if ensemble is None:
        ensemble = load_ensemble()

    # Compute features
    feats = compute_features(smiles)
    if feats is None:
        result["model_status"] = "feature_computation_failed"
        return result
    feat_arr = np.array([feats[n] for n in FEATURE_NAMES], dtype=np.float32)
    feat_arr = np.nan_to_num(feat_arr, nan=0.0, posinf=1e6, neginf=-1e6)
    feat_z = (feat_arr - ensemble["feat_mean"]) / (ensemble["feat_std"] + 1e-8)

    # Build datapoint
    dp = cpdata.MoleculeDatapoint.from_smi(smiles, y=np.zeros(2, dtype=np.float32),
                                            weight=1.0, x_d=feat_z.astype(np.float32))
    featurizer = featurizers.SimpleMoleculeMolGraphFeaturizer()
    dataset = cpdata.MoleculeDataset([dp], featurizer=featurizer)
    loader = cpdata.build_dataloader(dataset, batch_size=1, num_workers=0, shuffle=False)

    # Predict with each ensemble member
    from lightning import pytorch as pl
    member_preds = []
    for i, model in enumerate(ensemble["models"]):
        trainer = pl.Trainer(
            accelerator="cpu", devices="auto", logger=False,
            enable_checkpointing=False, enable_progress_bar=False,
            enable_model_summary=False,
        )
        raw = trainer.predict(model, loader)
        raw = torch.cat(raw, dim=0).numpy()
        unscaled = raw * ensemble["scaler_scales"][i] + ensemble["scaler_means"][i]
        member_preds.append(unscaled[0])

    preds = np.stack(member_preds, axis=0)  # (5, 2)
    pred_mean = preds.mean(axis=0)
    pred_std = preds.std(axis=0)

    # log10 -> raw conversion
    log10_gwp = float(pred_mean[0])
    log10_lt = float(pred_mean[1])
    std_gwp = float(pred_std[0])
    std_lt = float(pred_std[1])

    half_gwp = CI_SCALE_GWP * CI_Z_95 * std_gwp
    half_lt = CI_SCALE_LIFETIME * CI_Z_95 * std_lt

    gwp_100 = 10 ** log10_gwp
    gwp_100_low = 10 ** (log10_gwp - half_gwp)
    gwp_100_high = 10 ** (log10_gwp + half_gwp)

    lt_years = 10 ** log10_lt
    lt_low = 10 ** (log10_lt - half_lt)
    lt_high = 10 ** (log10_lt + half_lt)

    # Applicability domain
    ad = compute_applicability(smiles, training_fp)

    result.update({
        "model_status": "ok",
        "gwp_100": round(gwp_100, 2),
        "gwp_100_low": round(gwp_100_low, 4),
        "gwp_100_high": round(gwp_100_high, 2),
        "atmospheric_lifetime_years": round(lt_years, 4),
        "atmospheric_lifetime_years_low": round(lt_low, 6),
        "atmospheric_lifetime_years_high": round(lt_high, 4),
        "applicability": ad["ad_flag"],
        "tanimoto_nn_mean": round(ad["mean_top5_tanimoto"], 3),
        "lifetime_disagreement": False,
        "opera_lifetime_years": None,
        "model_id": "chemprop-gwp-ensemble-al-v1",
        "training_set": "ipcc-ar6 + hodnebrog-2020 (n=226 train, 31 holdout)",
        "holdout_mae_log10_gwp": 0.342,
    })
    return result


# ============= BATCH PREDICTION =============
def predict_gwp_batch(smiles_list: List[str], ensemble: Optional[dict] = None,
                      training_fp: Optional[np.ndarray] = None) -> List[Dict]:
    """Predict GWP100 + lifetime for a list of SMILES.

    Returns list of dicts (same schema as predict_gwp_single).
    """
    if ensemble is None:
        ensemble = load_ensemble()
    if training_fp is None:
        try:
            training_fp = load_training_fingerprints()
        except FileNotFoundError:
            training_fp = None

    results = []
    for i, smi in enumerate(smiles_list):
        try:
            r = predict_gwp_single(smi, ensemble=ensemble, training_fp=training_fp)
        except Exception as e:
            r = {"smiles": smi, "smiles_valid": False, "model_status": f"error: {e}"}
        results.append(r)
        if (i + 1) % 10 == 0:
            logging.info(f"  predicted {i + 1}/{len(smiles_list)}")

    return results


# ============= CLEANUP =============
def gwp_cleanup(deep: bool = False):
    """Clean up caches and scratch files."""
    global _ENSEMBLE_CACHE
    try:
        if deep:
            _ENSEMBLE_CACHE = None
            import gc
            gc.collect()
            if os.path.exists(SCRATCH_DIR):
                for f in os.scandir(SCRATCH_DIR):
                    if f.is_file():
                        os.remove(f.path)
            logging.info("Deep cleanup completed")
    except Exception as e:
        logging.warning(f"Cleanup warning: {e}")
