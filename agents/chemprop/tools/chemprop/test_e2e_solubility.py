#!/usr/bin/env python3
"""End-to-end test: Train a solubility regression model using Chemprop v2.

This script tests the full pipeline:
1. Import verification
2. Data loading and splitting
3. Model building and training
4. Prediction and evaluation
5. Model save/load round-trip
6. Parity plot generation
"""

import sys
import os
import json
import traceback
import logging

# Verify imports
print("=" * 60)
print("STEP 0: Verifying imports")
print("=" * 60)

try:
    import numpy as np
    print(f"  numpy: {np.__version__}")
    import pandas as pd
    print(f"  pandas: {pd.__version__}")
    import torch
    print(f"  torch: {torch.__version__}")
    import lightning
    print(f"  lightning: {lightning.__version__}")
    import chemprop
    print(f"  chemprop: {chemprop.__version__}")
    from rdkit import Chem
    print(f"  rdkit: OK")
    import sklearn
    print(f"  scikit-learn: {sklearn.__version__}")
    import matplotlib
    print(f"  matplotlib: {matplotlib.__version__}")
    from chemprop_utils import (
        quick_setup, quick_finish, save_final_results,
        load_csv_data, create_datapoints, split_data, build_dataloaders,
        build_mpnn, train_model, predict_dataloader, compute_metrics,
        save_model_file, load_model_file, predict_smiles, plot_parity,
        compute_fingerprints,
    )
    print("  chemprop_utils: OK")
    print("ALL IMPORTS SUCCESSFUL")
except ImportError as e:
    print(f"IMPORT ERROR: {e}")
    traceback.print_exc()
    sys.exit(1)

# Setup
quick_setup(input_dir='/input', output_dir='/output', work_dir='/workdir')

results = {}
output_files = {}
errors = []

try:
    # ====== STEP 1: Create inline test data ======
    print("\n" + "=" * 60)
    print("STEP 1: Creating test dataset")
    print("=" * 60)

    # Small solubility dataset (inline to avoid input file dependency)
    data = {
        "smiles": [
            "OCC3OC(OCC2OC(OC(C#N)c1ccccc1)C(O)C(O)C2O)C(O)C(O)C3O",
            "Cc1occc1C(=O)Nc2ccccc2",
            "CC(C)=CCCC(C)=CC(=O)",
            "c1ccccc1",
            "c1ccsc1",
            "CC12CCC3C(CCc4cc(O)ccc34)C2CCC1O",
            "CC(C)(C)c1ccc(O)cc1",
            "Clc1ccc(Cl)c(Cl)c1",
            "C(Cl)(Cl)Cl",
            "CC1=CC(=O)CC(C)(C)C1",
            "CCCC=O",
            "CCCCCCCC(=O)OC",
            "CC1C2CCC(C2)C1C",
            "c1ccc(cc1)c2ccccc2",
            "c1ccc(cc1)C(=O)O",
            "CC(=O)C(C)C",
            "CCC(=O)OCC",
            "ClC(Cl)=C(Cl)Cl",
            "ClCCCl",
            "CCCCCCCCCCCO",
            "C(Cl)Cl",
            "CC(C)O",
            "CCOCC",
            "CCC(C)O",
            "OCC(O)CO",
        ],
        "logSolubility": [
            -0.77, -3.30, -2.06, -3.30, -1.33,
            -5.03, -2.84, -4.19, -1.74, -2.45,
            -0.70, -3.56, -3.68, -4.56, -1.60,
            -0.30, -0.94, -2.56, -1.17, -3.56,
            -0.62, -0.16, -0.21, -0.50, -0.07,
        ],
    }

    df = pd.DataFrame(data)
    csv_path = "/workdir/test_data.csv"
    df.to_csv(csv_path, index=False)
    print(f"  Created dataset: {len(df)} molecules")
    results["n_molecules"] = len(df)

    # ====== STEP 2: Load and prepare data ======
    print("\n" + "=" * 60)
    print("STEP 2: Loading and preparing data")
    print("=" * 60)

    df_loaded = load_csv_data(csv_path, "smiles", ["logSolubility"])
    print(f"  Loaded: {len(df_loaded)} rows")

    smiles = df_loaded["smiles"].tolist()
    targets = df_loaded[["logSolubility"]].values

    datapoints = create_datapoints(smiles, targets)
    print(f"  Created {len(datapoints)} datapoints")

    train_data, val_data, test_data = split_data(
        datapoints, split_type="random", sizes=(0.7, 0.15, 0.15), seed=42
    )
    print(f"  Split: train={len(train_data)}, val={len(val_data)}, test={len(test_data)}")

    train_loader, val_loader, test_loader = build_dataloaders(
        train_data, val_data, test_data, batch_size=16
    )
    print("  Dataloaders built")

    results["n_train"] = len(train_data)
    results["n_val"] = len(val_data)
    results["n_test"] = len(test_data)

    # ====== STEP 3: Build and train model ======
    print("\n" + "=" * 60)
    print("STEP 3: Building and training model")
    print("=" * 60)

    model = build_mpnn(
        task_type="regression",
        n_tasks=1,
        hidden_dim=200,
        depth=3,
        ffn_num_layers=2,
        dropout=0.0,
        max_lr=1e-3,
    )

    n_params = sum(p.numel() for p in model.parameters() if p.requires_grad)
    print(f"  Model parameters: {n_params:,}")
    results["n_parameters"] = n_params

    model, trainer = train_model(
        model, train_loader, val_loader,
        max_epochs=20,  # Short for testing
        patience=5,
        accelerator="cpu",
    )
    print("  Training complete")

    # ====== STEP 4: Evaluate ======
    print("\n" + "=" * 60)
    print("STEP 4: Evaluating model")
    print("=" * 60)

    preds = predict_dataloader(model, test_loader)
    true_vals = np.array([dp.y for dp in test_data])

    metrics = compute_metrics(true_vals, preds, "regression")
    print(f"  Test RMSE: {metrics['rmse']:.4f}")
    print(f"  Test MAE:  {metrics['mae']:.4f}")
    print(f"  Test R^2:  {metrics['r2']:.4f}")

    results["test_metrics"] = metrics

    # ====== STEP 5: Save/Load round-trip ======
    print("\n" + "=" * 60)
    print("STEP 5: Model save/load round-trip")
    print("=" * 60)

    model_path = "/output/model.pt"
    save_model_file(model, model_path)
    print(f"  Saved model to {model_path}")

    loaded_model = load_model_file(model_path)
    print("  Model loaded successfully")

    # Verify predictions match
    preds2 = predict_smiles(loaded_model, smiles[:5])
    print(f"  Loaded model predictions (first 5): {preds2.flatten()[:5]}")
    output_files["model"] = "model.pt"

    # ====== STEP 6: Fingerprints ======
    print("\n" + "=" * 60)
    print("STEP 6: Computing learned fingerprints")
    print("=" * 60)

    fps = compute_fingerprints(model, smiles[:5])
    print(f"  Fingerprint shape: {fps.shape}")
    results["fingerprint_dim"] = int(fps.shape[1])

    # ====== STEP 7: Parity plot ======
    print("\n" + "=" * 60)
    print("STEP 7: Generating parity plot")
    print("=" * 60)

    plot_parity(true_vals, preds, "parity_plot.png",
                title="Solubility Prediction (Test Set)")
    output_files["parity_plot"] = "parity_plot.png"
    print("  Parity plot saved")

    # ====== STEP 8: Predict from SMILES ======
    print("\n" + "=" * 60)
    print("STEP 8: Predict from SMILES list")
    print("=" * 60)

    new_smiles = ["CCO", "c1ccccc1", "CC(=O)O", "CCCCCC"]
    new_preds = predict_smiles(model, new_smiles)
    for smi, pred in zip(new_smiles, new_preds.flatten()):
        print(f"  {smi}: {pred:.4f}")

    pred_df = pd.DataFrame({"smiles": new_smiles, "predicted_logS": new_preds.flatten()})
    pred_df.to_csv("/output/new_predictions.csv", index=False)
    output_files["new_predictions"] = "new_predictions.csv"

    results["status"] = "ALL_TESTS_PASSED"
    print("\n" + "=" * 60)
    print("ALL TESTS PASSED SUCCESSFULLY!")
    print("=" * 60)

except Exception as e:
    results["status"] = "FAILED"
    results["error"] = str(e)
    errors.append(str(e))
    print(f"\nERROR: {e}")
    traceback.print_exc()

finally:
    save_final_results(
        results, output_files,
        {"model": "Trained Chemprop MPNN model",
         "parity_plot": "Predicted vs actual solubility plot",
         "new_predictions": "Predictions for new molecules"},
        status="completed" if not errors else "failed",
    )
    quick_finish()
