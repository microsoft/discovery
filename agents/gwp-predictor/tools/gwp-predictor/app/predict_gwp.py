#!/usr/bin/env python3
"""predict_gwp.py - CLI entrypoint for the GWP predictor agent.

Usage:
  python3 predict_gwp.py --smiles "CCC(=O)C(F)(F)C(F)(F)F"
  python3 predict_gwp.py --input-csv /input/molecules.csv --column smiles

Outputs:
  /output/final_results.json        - per-molecule predictions + summary
  /output/gwp_predictions.csv       - tabular predictions (batch mode)
"""

import argparse
import json
import logging
import os
import sys
import traceback
from pathlib import Path

import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
from gwp_predictor_utils import (
    quick_setup, quick_finish, save_final_results,
    validate_smiles, predict_gwp_single, predict_gwp_batch,
    load_ensemble, load_training_fingerprints,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
log = logging.getLogger("predict_gwp")


def main():
    parser = argparse.ArgumentParser(description="Predict GWP100 and atmospheric lifetime from SMILES")
    parser.add_argument("--smiles", type=str, help="Single SMILES string to predict")
    parser.add_argument("--input-csv", type=str, help="Path to CSV file with SMILES column")
    parser.add_argument("--column", type=str, default="smiles", help="Column name for SMILES (default: smiles)")
    parser.add_argument("--model-dir", type=str, default="/app/models", help="Model directory")
    parser.add_argument("--output-dir", type=str, default="/output", help="Output directory")
    args = parser.parse_args()

    quick_setup(input_dir="/input", output_dir=args.output_dir, work_dir="/workdir")

    results = {}
    output_files = {}

    try:
        log.info("******* STEP 1: LOAD MODEL *******")
        ensemble = load_ensemble(args.model_dir)
        try:
            training_fp = load_training_fingerprints(
                os.path.join(args.model_dir, "training_fingerprints.npz")
            )
        except FileNotFoundError:
            log.warning("Training fingerprints not found; AD will be unavailable")
            training_fp = None

        if args.smiles:
            # Single SMILES mode
            log.info(f"******* STEP 2: PREDICT SINGLE SMILES *******")
            log.info(f"  SMILES: {args.smiles}")
            pred = predict_gwp_single(args.smiles, ensemble=ensemble, training_fp=training_fp)
            results["prediction"] = pred
            results["mode"] = "single"

            # Print formatted output
            if pred["model_status"] == "ok":
                log.info(f"  GWP-100:    {pred['gwp_100']:.2f}  [{pred['gwp_100_low']:.2f}, {pred['gwp_100_high']:.2f}]")
                log.info(f"  Lifetime:   {pred['atmospheric_lifetime_years']:.4f} yr  [{pred['atmospheric_lifetime_years_low']:.4f}, {pred['atmospheric_lifetime_years_high']:.4f}]")
                log.info(f"  AD:         {pred['applicability']} (NN sim = {pred['tanimoto_nn_mean']:.3f})")
            else:
                log.warning(f"  model_status: {pred['model_status']}")

            # Write the JSON sentinel (contract with orchestrator)
            sentinel = f"\nGWP_PREDICTION:\n{json.dumps(pred, indent=2, default=str)}\n"
            log.info(sentinel)

        elif args.input_csv:
            # Batch CSV mode
            log.info(f"******* STEP 2: PREDICT BATCH CSV *******")
            csv_path = args.input_csv
            if not os.path.exists(csv_path):
                csv_path = os.path.join("/input", os.path.basename(args.input_csv))
            log.info(f"  CSV: {csv_path}")
            df = pd.read_csv(csv_path)
            if args.column not in df.columns:
                raise ValueError(f"Column '{args.column}' not found. Available: {list(df.columns)}")

            smiles_list = df[args.column].tolist()
            log.info(f"  {len(smiles_list)} molecules to predict")

            preds = predict_gwp_batch(smiles_list, ensemble=ensemble, training_fp=training_fp)

            # Build output CSV
            pred_df = pd.DataFrame(preds)
            out_csv = os.path.join(args.output_dir, "gwp_predictions.csv")
            pred_df.to_csv(out_csv, index=False)
            output_files["predictions"] = "gwp_predictions.csv"

            # Summary stats
            ok_preds = [p for p in preds if p.get("model_status") == "ok"]
            results["mode"] = "batch"
            results["n_input"] = len(smiles_list)
            results["n_predicted"] = len(ok_preds)
            results["n_failed"] = len(smiles_list) - len(ok_preds)
            if ok_preds:
                gwps = [p["gwp_100"] for p in ok_preds]
                results["gwp100_min"] = min(gwps)
                results["gwp100_max"] = max(gwps)
                results["gwp100_median"] = float(sorted(gwps)[len(gwps) // 2])
                results["n_low_gwp"] = sum(1 for g in gwps if g < 10)
                results["n_high_gwp"] = sum(1 for g in gwps if g > 1000)
                ad_counts = {}
                for p in ok_preds:
                    flag = p.get("applicability", "unknown")
                    ad_counts[flag] = ad_counts.get(flag, 0) + 1
                results["applicability_counts"] = ad_counts

            log.info(f"  {results['n_predicted']}/{results['n_input']} predicted successfully")

        else:
            log.error("Either --smiles or --input-csv is required")
            results["error"] = "No input provided"

    except Exception as e:
        log.error(f"Error: {e}")
        traceback.print_exc()
        results["error"] = str(e)

    save_final_results(results, output_files)
    quick_finish()


if __name__ == "__main__":
    main()
