#!/usr/bin/env python3
"""Chemprop utilities library for Discovery platform workflows.

Provides simplified wrappers around Chemprop v2 for training, predicting, and
evaluating message-passing neural networks (D-MPNN) for molecular property
prediction.
"""

import os
import sys
import glob
import json
import logging
import shutil
import traceback
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd

# ============= CONSTANTS =============
INPUT_DIR = "/input"
OUTPUT_DIR = "/output"
WORK_DIR = "/workdir"
SCRATCH_DIR = "/tmp/chemprop_scratch"

# ============= SETUP FUNCTIONS =============

def quick_setup(input_dir="/input", output_dir="/output", work_dir="/workdir"):
    """Initialize logging, create directories, copy input files.

    ALL THREE parameters should be passed explicitly in every script.
    """
    global INPUT_DIR, OUTPUT_DIR, WORK_DIR
    INPUT_DIR, OUTPUT_DIR, WORK_DIR = input_dir, output_dir, work_dir

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )
    for d in [WORK_DIR, OUTPUT_DIR, SCRATCH_DIR]:
        os.makedirs(d, exist_ok=True)
    os.chdir(WORK_DIR)
    _copy_input_files()
    logging.info(f"Working directory: {WORK_DIR}")
    logging.info(f"Input files: {os.listdir(INPUT_DIR) if os.path.exists(INPUT_DIR) else '(none)'}")


def _copy_input_files():
    """Copy input files to working directory."""
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
    patterns = ["*.pt", "*.ckpt", "*.json", "*.csv", "*.png", "*.svg", "*.log", "*.out"]
    for pattern in patterns:
        for f in glob.glob(os.path.join(WORK_DIR, pattern)):
            shutil.copy(f, OUTPUT_DIR)
    logging.info("Outputs copied to /output")


def save_final_results(
    results: Dict,
    output_files: Optional[Dict] = None,
    file_descriptions: Optional[Dict] = None,
    status: str = "completed",
):
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
    """Handle numpy/torch types in JSON serialization."""
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


# ============= DATA FUNCTIONS =============

def load_csv_data(
    csv_path: str,
    smiles_column: str = "smiles",
    target_columns: Optional[List[str]] = None,
    max_rows: Optional[int] = None,
) -> pd.DataFrame:
    """Load and validate a CSV dataset with SMILES and target columns.

    Args:
        csv_path: Path to CSV file.
        smiles_column: Name of the SMILES column.
        target_columns: List of target column names. If None, auto-detects numeric columns.
        max_rows: Maximum number of rows to load. None means all.

    Returns:
        Validated pandas DataFrame.
    """
    df = pd.read_csv(csv_path, nrows=max_rows)
    logging.info(f"Loaded {len(df)} rows from {csv_path}")

    if smiles_column not in df.columns:
        raise ValueError(
            f"SMILES column '{smiles_column}' not found. "
            f"Available columns: {list(df.columns)}"
        )

    if target_columns is None:
        target_columns = [
            c for c in df.columns
            if c != smiles_column and pd.api.types.is_numeric_dtype(df[c])
        ]
        logging.info(f"Auto-detected target columns: {target_columns}")

    missing = [c for c in target_columns if c not in df.columns]
    if missing:
        raise ValueError(f"Target columns not found: {missing}")

    # Validate SMILES
    valid_mask = df[smiles_column].notna() & (df[smiles_column].str.strip() != "")
    n_invalid = (~valid_mask).sum()
    if n_invalid > 0:
        logging.warning(f"Dropping {n_invalid} rows with empty/null SMILES")
        df = df[valid_mask].reset_index(drop=True)

    # Drop rows with all-NaN targets
    target_nan_mask = df[target_columns].isna().all(axis=1)
    n_nan = target_nan_mask.sum()
    if n_nan > 0:
        logging.warning(f"Dropping {n_nan} rows with all-NaN targets")
        df = df[~target_nan_mask].reset_index(drop=True)

    logging.info(
        f"Dataset ready: {len(df)} molecules, "
        f"{len(target_columns)} target(s): {target_columns}"
    )
    return df


def create_datapoints(
    smiles_list: List[str],
    targets: Optional[np.ndarray] = None,
    weights: Optional[np.ndarray] = None,
):
    """Create Chemprop MoleculeDatapoint list from SMILES and targets.

    Args:
        smiles_list: List of SMILES strings.
        targets: Optional numpy array of targets, shape (n_molecules, n_targets).
        weights: Optional per-sample weights, shape (n_molecules,).

    Returns:
        List of MoleculeDatapoint objects.
    """
    from chemprop.data import MoleculeDatapoint

    datapoints = []
    for i, smi in enumerate(smiles_list):
        y = targets[i] if targets is not None else None
        w = float(weights[i]) if weights is not None else 1.0
        try:
            dp = MoleculeDatapoint.from_smi(smi, y, weight=w)
            datapoints.append(dp)
        except Exception as e:
            logging.warning(f"Failed to create datapoint for SMILES '{smi}': {e}")
    logging.info(f"Created {len(datapoints)}/{len(smiles_list)} datapoints")
    return datapoints


def split_data(
    datapoints,
    split_type: str = "random",
    sizes: Tuple[float, float, float] = (0.8, 0.1, 0.1),
    seed: int = 0,
    num_replicates: int = 1,
):
    """Split datapoints into train/val/test sets.

    Args:
        datapoints: List of MoleculeDatapoint.
        split_type: One of 'random', 'scaffold_balanced', 'kmeans', 'kennard_stone'.
        sizes: Tuple of (train, val, test) fractions.
        seed: Random seed.
        num_replicates: Number of replicate splits.

    Returns:
        Tuple of (train_data, val_data, test_data) lists.
    """
    from chemprop.data import make_split_indices, split_data_by_indices

    mols = [dp.mol for dp in datapoints]
    train_indices, val_indices, test_indices = make_split_indices(
        mols, split=split_type, sizes=sizes, seed=seed, num_replicates=num_replicates
    )
    train_data, val_data, test_data = split_data_by_indices(
        datapoints, train_indices, val_indices, test_indices
    )

    logging.info(
        f"Split ({split_type}): train={len(train_data[0])}, "
        f"val={len(val_data[0])}, test={len(test_data[0])}"
    )
    return train_data[0], val_data[0], test_data[0]


def build_dataloaders(
    train_data,
    val_data,
    test_data=None,
    batch_size: int = 64,
    num_workers: int = 0,
):
    """Build Chemprop dataloaders from split data.

    Args:
        train_data: Training datapoints.
        val_data: Validation datapoints.
        test_data: Optional test datapoints.
        batch_size: Batch size.
        num_workers: Number of data loading workers.

    Returns:
        Tuple of (train_loader, val_loader, test_loader).
    """
    from chemprop.data import MoleculeDataset, build_dataloader

    train_dset = MoleculeDataset(train_data)
    val_dset = MoleculeDataset(val_data)

    train_loader = build_dataloader(train_dset, batch_size=batch_size, shuffle=True, num_workers=num_workers)
    val_loader = build_dataloader(val_dset, batch_size=batch_size, shuffle=False, num_workers=num_workers)

    test_loader = None
    if test_data:
        test_dset = MoleculeDataset(test_data)
        test_loader = build_dataloader(test_dset, batch_size=batch_size, shuffle=False, num_workers=num_workers)

    return train_loader, val_loader, test_loader


# ============= MODEL BUILDING =============

def build_mpnn(
    task_type: str = "regression",
    message_passing: str = "bond",
    aggregation: str = "norm",
    hidden_dim: int = 300,
    depth: int = 3,
    ffn_hidden_dim: int = 300,
    ffn_num_layers: int = 2,
    dropout: float = 0.0,
    n_tasks: int = 1,
    n_classes: int = 3,
    batch_norm: bool = False,
    metrics_list: Optional[List[str]] = None,
    warmup_epochs: int = 2,
    init_lr: float = 1e-4,
    max_lr: float = 1e-3,
    final_lr: float = 1e-4,
):
    """Build a Chemprop MPNN model.

    Args:
        task_type: 'regression', 'binary_classification', or 'multiclass'.
        message_passing: 'bond' or 'atom'.
        aggregation: 'norm', 'mean', or 'sum'.
        hidden_dim: Hidden dimension for message passing.
        depth: Number of message passing steps.
        ffn_hidden_dim: Hidden dimension for FFN.
        ffn_num_layers: Number of FFN layers.
        dropout: Dropout rate.
        n_tasks: Number of prediction targets.
        n_classes: Number of classes (for multiclass only).
        batch_norm: Whether to use batch normalization.
        metrics_list: Optional list of metric names (e.g., ['rmse', 'mae', 'r2']).
        warmup_epochs: Number of warmup epochs for learning rate scheduler.
        init_lr: Initial learning rate.
        max_lr: Maximum learning rate.
        final_lr: Final learning rate.

    Returns:
        MPNN model.
    """
    from chemprop.models.model import MPNN
    from chemprop import nn as chemprop_nn

    # Message passing
    if message_passing == "bond":
        mp = chemprop_nn.BondMessagePassing(d_h=hidden_dim, depth=depth, dropout=dropout)
    elif message_passing == "atom":
        mp = chemprop_nn.AtomMessagePassing(d_h=hidden_dim, depth=depth, dropout=dropout)
    else:
        raise ValueError(f"Unknown message_passing: {message_passing}. Use 'bond' or 'atom'.")

    # Aggregation
    agg_map = {
        "norm": chemprop_nn.NormAggregation,
        "mean": chemprop_nn.MeanAggregation,
        "sum": chemprop_nn.SumAggregation,
    }
    if aggregation not in agg_map:
        raise ValueError(f"Unknown aggregation: {aggregation}. Use {list(agg_map.keys())}")
    agg = agg_map[aggregation]()

    # FFN / Predictor
    if task_type == "regression":
        ffn = chemprop_nn.RegressionFFN(
            input_dim=hidden_dim,
            hidden_dim=ffn_hidden_dim,
            n_layers=ffn_num_layers,
            dropout=dropout,
            n_tasks=n_tasks,
        )
    elif task_type == "binary_classification":
        ffn = chemprop_nn.BinaryClassificationFFN(
            input_dim=hidden_dim,
            hidden_dim=ffn_hidden_dim,
            n_layers=ffn_num_layers,
            dropout=dropout,
            n_tasks=n_tasks,
        )
    elif task_type == "multiclass":
        ffn = chemprop_nn.MulticlassClassificationFFN(
            input_dim=hidden_dim,
            hidden_dim=ffn_hidden_dim,
            n_layers=ffn_num_layers,
            dropout=dropout,
            n_tasks=n_tasks,
            n_classes=n_classes,
        )
    else:
        raise ValueError(
            f"Unknown task_type: {task_type}. "
            "Use 'regression', 'binary_classification', or 'multiclass'."
        )

    # Metrics
    metrics = None
    if metrics_list:
        metrics = _build_metrics(metrics_list)

    model = MPNN(
        mp, agg, ffn,
        batch_norm=batch_norm,
        metrics=metrics,
        warmup_epochs=warmup_epochs,
        init_lr=init_lr,
        max_lr=max_lr,
        final_lr=final_lr,
    )

    n_params = sum(p.numel() for p in model.parameters() if p.requires_grad)
    logging.info(f"Built MPNN ({task_type}): {n_params:,} trainable parameters")
    return model


def _build_metrics(metric_names: List[str]):
    """Build Chemprop metric objects from names."""
    from chemprop.nn import metrics as m

    metric_map = {
        "rmse": m.RMSE,
        "mse": m.MSE,
        "mae": m.MAE,
        "r2": m.R2Score,
        "auroc": m.BinaryAUROC,
        "auprc": m.BinaryAUPRC,
        "accuracy": m.BinaryAccuracy,
        "f1": m.BinaryF1Score,
        "mcc": m.BinaryMCCScore,
    }
    result = []
    for name in metric_names:
        name_lower = name.lower()
        if name_lower not in metric_map:
            logging.warning(f"Unknown metric '{name}', skipping. Available: {list(metric_map.keys())}")
            continue
        result.append(metric_map[name_lower]())
    return result if result else None


# ============= TRAINING =============

def train_model(
    model,
    train_loader,
    val_loader,
    max_epochs: int = 50,
    patience: int = 10,
    accelerator: str = "auto",
    output_dir: Optional[str] = None,
):
    """Train a Chemprop MPNN model using PyTorch Lightning.

    Args:
        model: MPNN model to train.
        train_loader: Training dataloader.
        val_loader: Validation dataloader.
        max_epochs: Maximum number of training epochs.
        patience: Early stopping patience (epochs).
        accelerator: 'auto', 'cpu', 'gpu'.
        output_dir: Directory to save model checkpoints.

    Returns:
        Tuple of (trained model, trainer).
    """
    import lightning as pl
    from lightning.pytorch.callbacks import EarlyStopping, ModelCheckpoint

    if output_dir is None:
        output_dir = os.path.join(WORK_DIR, "model_output")
    os.makedirs(output_dir, exist_ok=True)

    callbacks = []

    # Early stopping
    callbacks.append(
        EarlyStopping(monitor="val_loss", patience=patience, mode="min", verbose=True)
    )

    # Checkpointing
    callbacks.append(
        ModelCheckpoint(
            dirpath=output_dir,
            filename="best-{epoch}-{val_loss:.4f}",
            monitor="val_loss",
            mode="min",
            save_top_k=1,
            save_last=True,
        )
    )

    trainer = pl.Trainer(
        max_epochs=max_epochs,
        accelerator=accelerator,
        callbacks=callbacks,
        enable_progress_bar=True,
        logger=False,
        default_root_dir=output_dir,
    )

    logging.info(f"Starting training for up to {max_epochs} epochs (patience={patience})")
    trainer.fit(model, train_loader, val_loader)
    logging.info("Training complete")

    return model, trainer


def test_model(model, trainer, test_loader):
    """Test a trained model on a test dataloader.

    Args:
        model: Trained MPNN model.
        trainer: Lightning Trainer used for training.
        test_loader: Test dataloader.

    Returns:
        Test results dictionary.
    """
    results = trainer.test(model, test_loader)
    logging.info(f"Test results: {results}")
    return results


def cross_validate(
    csv_path: str,
    smiles_column: str = "smiles",
    target_columns: Optional[List[str]] = None,
    task_type: str = "regression",
    num_folds: int = 5,
    split_type: str = "random",
    max_epochs: int = 50,
    batch_size: int = 64,
    hidden_dim: int = 300,
    depth: int = 3,
    seed: int = 0,
    **model_kwargs,
) -> Dict:
    """Perform k-fold cross-validation.

    Args:
        csv_path: Path to CSV file.
        smiles_column: SMILES column name.
        target_columns: Target column names.
        task_type: 'regression' or 'binary_classification'.
        num_folds: Number of cross-validation folds.
        split_type: Split type for each fold.
        max_epochs: Max epochs per fold.
        batch_size: Batch size.
        hidden_dim: MPNN hidden dimension.
        depth: MPNN message passing depth.
        seed: Random seed.
        **model_kwargs: Additional arguments for build_mpnn.

    Returns:
        Dictionary with per-fold and aggregate results.
    """
    from chemprop.data import MoleculeDatapoint, MoleculeDataset, build_dataloader
    from chemprop.data import make_split_indices, split_data_by_indices

    df = load_csv_data(csv_path, smiles_column, target_columns)
    if target_columns is None:
        target_columns = [
            c for c in df.columns
            if c != smiles_column and pd.api.types.is_numeric_dtype(df[c])
        ]

    smiles = df[smiles_column].tolist()
    targets = df[target_columns].values
    n_tasks = len(target_columns)

    datapoints = create_datapoints(smiles, targets)
    mols = [dp.mol for dp in datapoints]

    # Generate fold splits
    train_indices, val_indices, test_indices = make_split_indices(
        mols,
        split=split_type,
        sizes=(0.8, 0.1, 0.1),
        seed=seed,
        num_replicates=num_folds,
    )

    fold_results = []
    all_test_preds = []
    all_test_true = []

    for fold_idx in range(num_folds):
        logging.info(f"====== Fold {fold_idx + 1}/{num_folds} ======")

        train_dps, val_dps, test_dps = split_data_by_indices(
            datapoints,
            [train_indices[fold_idx]],
            [val_indices[fold_idx]],
            [test_indices[fold_idx]],
        )
        train_dps, val_dps, test_dps = train_dps[0], val_dps[0], test_dps[0]

        train_loader = build_dataloader(MoleculeDataset(train_dps), batch_size=batch_size, shuffle=True)
        val_loader = build_dataloader(MoleculeDataset(val_dps), batch_size=batch_size, shuffle=False)
        test_loader = build_dataloader(MoleculeDataset(test_dps), batch_size=batch_size, shuffle=False)

        model = build_mpnn(
            task_type=task_type,
            n_tasks=n_tasks,
            hidden_dim=hidden_dim,
            depth=depth,
            **model_kwargs,
        )

        fold_dir = os.path.join(WORK_DIR, f"fold_{fold_idx}")
        model, trainer = train_model(model, train_loader, val_loader,
                                     max_epochs=max_epochs, output_dir=fold_dir)

        # Evaluate on test set
        test_results = trainer.test(model, test_loader)

        # Get predictions
        preds = predict_dataloader(model, test_loader)
        true_vals = np.array([dp.y for dp in test_dps])

        fold_metrics = compute_metrics(true_vals, preds, task_type)
        fold_metrics["fold"] = fold_idx + 1
        fold_results.append(fold_metrics)

        all_test_preds.extend(preds.tolist())
        all_test_true.extend(true_vals.tolist())

        logging.info(f"Fold {fold_idx + 1} metrics: {fold_metrics}")

        # Save checkpoint
        _save_checkpoint(fold_results, "cv_progress.json")

    # Aggregate results
    aggregate = _aggregate_cv_results(fold_results)
    cv_results = {
        "num_folds": num_folds,
        "task_type": task_type,
        "target_columns": target_columns,
        "fold_results": fold_results,
        "aggregate": aggregate,
    }

    logging.info(f"Cross-validation complete. Aggregate: {aggregate}")
    return cv_results


def _save_checkpoint(data, filename):
    """Save checkpoint data."""
    path = os.path.join(OUTPUT_DIR, filename)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=_json_serializer)


def _aggregate_cv_results(fold_results: List[Dict]) -> Dict:
    """Aggregate cross-validation results across folds."""
    keys = [k for k in fold_results[0] if k != "fold" and isinstance(fold_results[0][k], (int, float))]
    agg = {}
    for k in keys:
        vals = [fr[k] for fr in fold_results if k in fr and fr[k] is not None]
        if vals:
            agg[k] = {
                "mean": float(np.mean(vals)),
                "std": float(np.std(vals)),
                "min": float(np.min(vals)),
                "max": float(np.max(vals)),
            }
    return agg


# ============= PREDICTION =============

def predict_dataloader(model, dataloader) -> np.ndarray:
    """Run predictions on a dataloader.

    Args:
        model: Trained MPNN model.
        dataloader: Chemprop dataloader.

    Returns:
        Numpy array of predictions.
    """
    import torch
    import lightning as pl

    trainer = pl.Trainer(
        accelerator="auto",
        logger=False,
        enable_progress_bar=False,
    )
    with torch.no_grad():
        preds_batches = trainer.predict(model, dataloader)

    preds = np.concatenate([p.numpy() for p in preds_batches], axis=0)
    return preds


def predict_smiles(
    model,
    smiles_list: List[str],
    batch_size: int = 64,
) -> np.ndarray:
    """Predict properties for a list of SMILES strings.

    Args:
        model: Trained MPNN model.
        smiles_list: List of SMILES strings.
        batch_size: Batch size for prediction.

    Returns:
        Numpy array of predictions, shape (n_molecules, n_tasks).
    """
    from chemprop.data import MoleculeDatapoint, MoleculeDataset, build_dataloader

    datapoints = [MoleculeDatapoint.from_smi(smi) for smi in smiles_list]
    dataset = MoleculeDataset(datapoints)
    loader = build_dataloader(dataset, batch_size=batch_size, shuffle=False)
    return predict_dataloader(model, loader)


def predict_csv(
    model,
    csv_path: str,
    smiles_column: str = "smiles",
    output_path: Optional[str] = None,
    batch_size: int = 64,
) -> pd.DataFrame:
    """Predict properties from a CSV file and save results.

    Args:
        model: Trained MPNN model.
        csv_path: Path to input CSV.
        smiles_column: SMILES column name.
        output_path: Path to save predictions CSV.
        batch_size: Batch size.

    Returns:
        DataFrame with SMILES and predictions.
    """
    df = pd.read_csv(csv_path)
    smiles_list = df[smiles_column].tolist()
    preds = predict_smiles(model, smiles_list, batch_size=batch_size)

    result_df = pd.DataFrame({smiles_column: smiles_list})
    for i in range(preds.shape[1]):
        result_df[f"pred_{i}"] = preds[:, i]

    if output_path is None:
        output_path = os.path.join(OUTPUT_DIR, "predictions.csv")
    result_df.to_csv(output_path, index=False)
    logging.info(f"Predictions saved to {output_path}")
    return result_df


# ============= MODEL I/O =============

def save_model_file(model, path: Optional[str] = None):
    """Save a Chemprop MPNN model to a .pt file.

    Args:
        model: MPNN model.
        path: Output path. Defaults to /output/model.pt.
    """
    from chemprop.models.utils import save_model

    if path is None:
        path = os.path.join(OUTPUT_DIR, "model.pt")
    save_model(path, model)
    logging.info(f"Model saved to {path}")


def load_model_file(path: str):
    """Load a Chemprop MPNN model from a .pt or .ckpt file.

    Args:
        path: Path to model file.

    Returns:
        MPNN model.
    """
    from chemprop.models.model import MPNN

    model = MPNN.load_from_file(path)
    logging.info(f"Model loaded from {path}")
    return model


# ============= EVALUATION =============

def compute_metrics(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    task_type: str = "regression",
) -> Dict[str, float]:
    """Compute evaluation metrics.

    Args:
        y_true: True values, shape (n, n_tasks) or (n,).
        y_pred: Predicted values, same shape.
        task_type: 'regression' or 'binary_classification'.

    Returns:
        Dictionary of metric names to values.
    """
    from sklearn.metrics import (
        mean_squared_error,
        mean_absolute_error,
        r2_score,
        roc_auc_score,
        average_precision_score,
        accuracy_score,
    )

    y_true = np.asarray(y_true).flatten()
    y_pred = np.asarray(y_pred).flatten()

    # Remove NaN pairs
    mask = ~(np.isnan(y_true) | np.isnan(y_pred))
    y_true, y_pred = y_true[mask], y_pred[mask]

    if len(y_true) == 0:
        logging.warning("No valid samples for metric computation")
        return {}

    metrics = {}
    if task_type == "regression":
        metrics["rmse"] = float(np.sqrt(mean_squared_error(y_true, y_pred)))
        metrics["mae"] = float(mean_absolute_error(y_true, y_pred))
        metrics["r2"] = float(r2_score(y_true, y_pred))
        metrics["mse"] = float(mean_squared_error(y_true, y_pred))
    elif task_type == "binary_classification":
        try:
            metrics["auroc"] = float(roc_auc_score(y_true, y_pred))
        except ValueError:
            metrics["auroc"] = None
        try:
            metrics["auprc"] = float(average_precision_score(y_true, y_pred))
        except ValueError:
            metrics["auprc"] = None
        y_pred_binary = (np.asarray(y_pred) >= 0.5).astype(int)
        metrics["accuracy"] = float(accuracy_score(y_true, y_pred_binary))

    return metrics


# ============= FINGERPRINTS =============

def compute_fingerprints(
    model,
    smiles_list: List[str],
    batch_size: int = 64,
) -> np.ndarray:
    """Compute learned MPNN fingerprints for molecules.

    Args:
        model: Trained MPNN model.
        smiles_list: List of SMILES strings.
        batch_size: Batch size.

    Returns:
        Numpy array of fingerprints, shape (n_molecules, hidden_dim).
    """
    import torch
    from chemprop.data import MoleculeDatapoint, MoleculeDataset, build_dataloader

    model.eval()
    datapoints = [MoleculeDatapoint.from_smi(smi) for smi in smiles_list]
    dataset = MoleculeDataset(datapoints)
    loader = build_dataloader(dataset, batch_size=batch_size, shuffle=False)

    fps = []
    with torch.no_grad():
        for batch in loader:
            bmg, V_d, X_d, *_ = batch
            fp = model.fingerprint(bmg, V_d, X_d)
            fps.append(fp.cpu().numpy())

    return np.concatenate(fps, axis=0)


# ============= VISUALIZATION =============

def plot_parity(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    output_file: str = "parity_plot.png",
    title: str = "Predicted vs. Actual",
    xlabel: str = "Actual",
    ylabel: str = "Predicted",
):
    """Create a parity plot (predicted vs actual).

    Args:
        y_true: True values.
        y_pred: Predicted values.
        output_file: Path to save plot.
        title: Plot title.
        xlabel: X-axis label.
        ylabel: Y-axis label.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    y_true = np.asarray(y_true).flatten()
    y_pred = np.asarray(y_pred).flatten()

    fig, ax = plt.subplots(1, 1, figsize=(6, 6))
    ax.scatter(y_true, y_pred, alpha=0.5, s=20, edgecolors="none")

    # Diagonal line
    lo = min(y_true.min(), y_pred.min())
    hi = max(y_true.max(), y_pred.max())
    margin = (hi - lo) * 0.05
    ax.plot([lo - margin, hi + margin], [lo - margin, hi + margin], "r--", lw=1.5)

    # Metrics annotation
    metrics = compute_metrics(y_true, y_pred, "regression")
    text = f"RMSE: {metrics['rmse']:.3f}\nMAE: {metrics['mae']:.3f}\nR┬▓: {metrics['r2']:.3f}"
    ax.text(0.05, 0.95, text, transform=ax.transAxes, va="top",
            fontsize=10, bbox=dict(boxstyle="round", facecolor="wheat", alpha=0.5))

    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.set_aspect("equal", adjustable="box")

    out = os.path.join(OUTPUT_DIR, output_file) if not os.path.isabs(output_file) else output_file
    plt.tight_layout()
    plt.savefig(out, dpi=150, bbox_inches="tight")
    plt.close()
    logging.info(f"Parity plot saved to {out}")


def plot_training_loss(
    log_path: str,
    output_file: str = "training_loss.png",
):
    """Plot training loss from Lightning CSV logger.

    Args:
        log_path: Path to metrics.csv from Lightning logger.
        output_file: Path to save plot.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    df = pd.read_csv(log_path)

    fig, ax = plt.subplots(1, 1, figsize=(8, 5))

    if "train_loss" in df.columns:
        train = df[df["train_loss"].notna()]
        ax.plot(train["epoch"], train["train_loss"], label="Train Loss", alpha=0.8)
    if "val_loss" in df.columns:
        val = df[df["val_loss"].notna()]
        ax.plot(val["epoch"], val["val_loss"], label="Val Loss", alpha=0.8)

    ax.set_xlabel("Epoch")
    ax.set_ylabel("Loss")
    ax.set_title("Training Progress")
    ax.legend()

    out = os.path.join(OUTPUT_DIR, output_file) if not os.path.isabs(output_file) else output_file
    plt.tight_layout()
    plt.savefig(out, dpi=150, bbox_inches="tight")
    plt.close()
    logging.info(f"Training loss plot saved to {out}")


def plot_cv_results(
    cv_results: Dict,
    output_file: str = "cv_results.png",
):
    """Plot cross-validation results.

    Args:
        cv_results: Results from cross_validate().
        output_file: Path to save plot.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fold_results = cv_results["fold_results"]
    metric_keys = [k for k in fold_results[0] if k != "fold" and isinstance(fold_results[0][k], (int, float))]

    n_metrics = len(metric_keys)
    fig, axes = plt.subplots(1, n_metrics, figsize=(5 * n_metrics, 4))
    if n_metrics == 1:
        axes = [axes]

    for ax, key in zip(axes, metric_keys):
        vals = [fr[key] for fr in fold_results if fr[key] is not None]
        folds = list(range(1, len(vals) + 1))
        ax.bar(folds, vals, alpha=0.7, color="steelblue")
        ax.axhline(np.mean(vals), color="red", linestyle="--", label=f"Mean: {np.mean(vals):.3f}")
        ax.set_xlabel("Fold")
        ax.set_ylabel(key.upper())
        ax.set_title(key.upper())
        ax.legend()

    out = os.path.join(OUTPUT_DIR, output_file) if not os.path.isabs(output_file) else output_file
    plt.tight_layout()
    plt.savefig(out, dpi=150, bbox_inches="tight")
    plt.close()
    logging.info(f"CV results plot saved to {out}")


# ============= HYPERPARAMETER OPTIMIZATION =============

def hyperopt(
    csv_path: str,
    smiles_column: str = "smiles",
    target_columns: Optional[List[str]] = None,
    task_type: str = "regression",
    n_trials: int = 20,
    max_epochs: int = 30,
    batch_size: int = 64,
    seed: int = 0,
) -> Dict:
    """Perform Chemprop hyperparameter optimization using CLI.

    Uses Chemprop's built-in hyperparameter search.

    Args:
        csv_path: Path to CSV data.
        smiles_column: SMILES column name.
        target_columns: Target column names.
        task_type: Task type.
        n_trials: Number of optimization trials.
        max_epochs: Max epochs per trial.
        batch_size: Batch size.
        seed: Random seed.

    Returns:
        Dictionary with best hyperparameters and performance.
    """
    import subprocess

    output_dir = os.path.join(WORK_DIR, "hpopt_output")
    os.makedirs(output_dir, exist_ok=True)

    cmd = [
        "chemprop", "hpopt",
        "--data-path", csv_path,
        "--task-type", task_type,
        "--output-dir", output_dir,
        "--epochs", str(max_epochs),
        "--batch-size", str(batch_size),
        "--num-iters", str(n_trials),
        "--seed", str(seed),
    ]

    if smiles_column != "smiles":
        cmd.extend(["--smiles-columns", smiles_column])

    if target_columns:
        cmd.extend(["--target-columns"] + target_columns)

    logging.info(f"Running hyperopt: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        logging.error(f"Hyperopt failed: {result.stderr}")
        raise RuntimeError(f"Hyperopt failed: {result.stderr}")

    logging.info(f"Hyperopt output: {result.stdout[-500:]}")

    # Parse results
    hpopt_results = {"output_dir": output_dir, "stdout": result.stdout}

    # Try to load best config
    config_path = os.path.join(output_dir, "best_config.toml")
    if os.path.exists(config_path):
        hpopt_results["best_config_path"] = config_path

    return hpopt_results


# ============= CLEANUP =============

def chemprop_cleanup(deep: bool = False):
    """Clean up Chemprop state between calculations.

    Args:
        deep: If True, also clear scratch files and GPU cache.
    """
    import gc
    gc.collect()

    if deep:
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass

        # Clear scratch files
        try:
            for entry in os.scandir(SCRATCH_DIR):
                if entry.is_file():
                    os.remove(entry.path)
        except FileNotFoundError:
            pass

        logging.info("Deep cleanup completed")


# ============= HELPER: FULL TRAINING PIPELINE =============

def train_pipeline(
    csv_path: str,
    smiles_column: str = "smiles",
    target_columns: Optional[List[str]] = None,
    task_type: str = "regression",
    split_type: str = "random",
    split_sizes: Tuple[float, float, float] = (0.8, 0.1, 0.1),
    max_epochs: int = 50,
    batch_size: int = 64,
    hidden_dim: int = 300,
    depth: int = 3,
    dropout: float = 0.0,
    patience: int = 10,
    seed: int = 0,
    save_model: bool = True,
    create_plots: bool = True,
    **model_kwargs,
) -> Dict:
    """Complete training pipeline: load data, train model, evaluate, save results.

    This is a convenience function that runs the full workflow.

    Args:
        csv_path: Path to CSV data file.
        smiles_column: SMILES column name.
        target_columns: Target column names.
        task_type: 'regression' or 'binary_classification'.
        split_type: Data split method.
        split_sizes: (train, val, test) fractions.
        max_epochs: Maximum training epochs.
        batch_size: Batch size.
        hidden_dim: MPNN hidden dimension.
        depth: Message passing depth.
        dropout: Dropout rate.
        patience: Early stopping patience.
        seed: Random seed.
        save_model: Whether to save the trained model.
        create_plots: Whether to create evaluation plots.
        **model_kwargs: Additional arguments for build_mpnn.

    Returns:
        Dictionary with model, metrics, and file paths.
    """
    # Load data
    df = load_csv_data(csv_path, smiles_column, target_columns)
    if target_columns is None:
        target_columns = [
            c for c in df.columns
            if c != smiles_column and pd.api.types.is_numeric_dtype(df[c])
        ]

    smiles = df[smiles_column].tolist()
    targets = df[target_columns].values
    n_tasks = len(target_columns)

    # Create datapoints and split
    datapoints = create_datapoints(smiles, targets)
    train_data, val_data, test_data = split_data(
        datapoints, split_type=split_type, sizes=split_sizes, seed=seed
    )

    # Build dataloaders
    train_loader, val_loader, test_loader = build_dataloaders(
        train_data, val_data, test_data, batch_size=batch_size
    )

    # Build and train model
    model = build_mpnn(
        task_type=task_type,
        n_tasks=n_tasks,
        hidden_dim=hidden_dim,
        depth=depth,
        dropout=dropout,
        **model_kwargs,
    )

    model, trainer = train_model(
        model, train_loader, val_loader,
        max_epochs=max_epochs, patience=patience,
    )

    # Evaluate
    preds = predict_dataloader(model, test_loader)
    true_vals = np.array([dp.y for dp in test_data])
    test_metrics = compute_metrics(true_vals, preds, task_type)

    logging.info(f"Test metrics: {test_metrics}")

    results = {
        "task_type": task_type,
        "target_columns": target_columns,
        "n_molecules": len(df),
        "n_train": len(train_data),
        "n_val": len(val_data),
        "n_test": len(test_data),
        "test_metrics": test_metrics,
    }

    output_files = {}

    # Save model
    if save_model:
        model_path = os.path.join(OUTPUT_DIR, "model.pt")
        save_model_file(model, model_path)
        output_files["model"] = model_path

    # Create plots
    if create_plots and task_type == "regression":
        plot_parity(true_vals, preds, "parity_plot.png")
        output_files["parity_plot"] = os.path.join(OUTPUT_DIR, "parity_plot.png")

    # Save predictions
    pred_df = pd.DataFrame({
        smiles_column: [dp.name for dp in test_data],
        "true": true_vals.flatten(),
        "predicted": preds.flatten(),
    })
    pred_path = os.path.join(OUTPUT_DIR, "test_predictions.csv")
    pred_df.to_csv(pred_path, index=False)
    output_files["predictions"] = pred_path

    return {
        "model": model,
        "trainer": trainer,
        "results": results,
        "output_files": output_files,
    }
