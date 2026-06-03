#!/usr/bin/env python3
"""benchmark_gwp_vs_climatic.py - Head-to-head comparison.

Runs gwp-predictor (our agent) on 30 test molecules with known GWP100.
Saves predictions + ground truth for comparison with climatic-gwp.

The same script with minor modifications runs on climatic-gwp's container.
This version is for gwp-predictor.
"""
import os, sys, json, time
from pathlib import Path
import numpy as np

sys.path.insert(0, "/app")
OUTPUT_DIR = Path("/output")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# 30 test molecules with published GWP100 values from Hodnebrog 2020 / IPCC AR6.
# Selected to span full GWP range and multiple chemistry classes.
TEST_MOLECULES = [
    # (name, SMILES, published_GWP100, source)
    ("HFC-134a", "FC(F)(F)CF", 1530, "IPCC_AR6"),
    ("HFC-32", "FCF", 771, "IPCC_AR6"),
    ("HFC-23", "FC(F)F", 14600, "IPCC_AR6"),
    ("HFC-125", "FC(F)(F)C(F)F", 3740, "IPCC_AR6"),
    ("HFC-143a", "CC(F)(F)F", 5810, "IPCC_AR6"),
    ("HFC-152a", "CC(F)F", 164, "IPCC_AR6"),
    ("HFO-1234yf", "C=C(F)C(F)(F)F", 0.501, "Hodnebrog_2020"),
    ("CFC-11", "FC(Cl)(Cl)Cl", 6230, "IPCC_AR6"),
    ("CFC-12", "FC(F)(Cl)Cl", 10200, "IPCC_AR6"),
    ("HCFC-22", "FC(F)Cl", 1960, "IPCC_AR6"),
    ("Novec 649", "CCC(=O)C(F)(F)C(F)(F)C(F)(F)F", 1.0, "3M"),
    ("SF6", "FS(F)(F)(F)(F)F", 24300, "IPCC_AR6"),
    ("NF3", "FN(F)F", 17400, "IPCC_AR6"),
    ("Methane", "C", 29.8, "IPCC_AR6"),
    ("N2O", "[N-]=[N+]=O", 273, "IPCC_AR6"),
    ("HFC-227ea", "FC(F)(F)C(F)C(F)(F)F", 3600, "IPCC_AR6"),
    ("HFC-245fa", "FC(F)CC(F)(F)F", 962, "IPCC_AR6"),
    ("HFC-365mfc", "CC(F)(F)CC(F)(F)F", 914, "IPCC_AR6"),
    ("HCFC-141b", "CC(F)(Cl)Cl", 853, "IPCC_AR6"),
    ("Halon-1301", "FC(F)(F)Br", 7200, "IPCC_AR6"),
    ("CF4", "FC(F)(F)F", 7380, "IPCC_AR6"),
    ("C2F6", "FC(F)(F)C(F)(F)F", 12400, "IPCC_AR6"),
    ("HFE-7100", "COC(F)(F)C(F)(F)C(F)(F)C(F)(F)F", 460, "Hodnebrog_2020"),
    ("CCl4", "ClC(Cl)(Cl)Cl", 2200, "IPCC_AR6"),
    ("CH2Cl2", "ClCCl", 11.2, "IPCC_AR6"),
    ("CHCl3", "ClC(Cl)Cl", 20, "IPCC_AR6"),
    ("CH3Br", "CBr", 2.43, "IPCC_AR6"),
    ("SO2F2", "O=S(=O)(F)F", 4090, "Hodnebrog_2020"),
    ("HFO-1234ze(E)", "FC=CC(F)(F)F", 1.37, "Hodnebrog_2020"),
    ("Ethanol", "CCO", 0.003, "short_lived"),
]

# Determine which agent we're running on
try:
    from gwp_predictor_utils import predict_gwp_single, load_ensemble, load_training_fingerprints
    AGENT = "gwp-predictor"
    ensemble = load_ensemble("/app/models")
    try:
        training_fp = load_training_fingerprints("/app/models/training_fingerprints.npz")
    except Exception:
        training_fp = None
    print(f"Running on: {AGENT}")
except ImportError:
    try:
        from climatic_gwp_utils import predict_gwp
        AGENT = "climatic-gwp"
        print(f"Running on: {AGENT}")
    except ImportError:
        AGENT = "unknown"
        print("ERROR: Could not import either agent's utils")

results = []
t_total = time.time()

for name, smi, true_gwp, source in TEST_MOLECULES:
    t0 = time.time()
    try:
        if AGENT == "gwp-predictor":
            pred = predict_gwp_single(smi, ensemble=ensemble, training_fp=training_fp)
            pred_gwp = pred.get("gwp_100", None)
            ad_flag = pred.get("applicability", None)
            ci_lo = pred.get("gwp_100_low", None)
            ci_hi = pred.get("gwp_100_high", None)
            model_status = pred.get("model_status", "error")
        elif AGENT == "climatic-gwp":
            preds = predict_gwp([smi])
            if preds and preds[0].get("gwp_100") is not None:
                pred_gwp = preds[0]["gwp_100"]
                ad_flag = None
                ci_lo = None
                ci_hi = None
                model_status = "ok"
            else:
                pred_gwp = None
                ad_flag = None
                ci_lo = None
                ci_hi = None
                model_status = preds[0].get("error", "unknown") if preds else "empty"
        else:
            pred_gwp = None
            ad_flag = None
            ci_lo = None
            ci_hi = None
            model_status = "no_agent"
    except Exception as e:
        pred_gwp = None
        ad_flag = None
        ci_lo = None
        ci_hi = None
        model_status = f"error: {e}"

    elapsed = time.time() - t0

    # Compute error metrics
    if pred_gwp is not None and pred_gwp > 0 and true_gwp > 0:
        log_err = abs(np.log10(pred_gwp) - np.log10(true_gwp))
        factor_err = max(pred_gwp / true_gwp, true_gwp / pred_gwp)
        in_ci = ci_lo is not None and ci_lo <= true_gwp <= ci_hi
    else:
        log_err = None
        factor_err = None
        in_ci = None

    results.append({
        "name": name, "smiles": smi, "true_gwp100": true_gwp, "source": source,
        "agent": AGENT, "predicted_gwp100": pred_gwp, "model_status": model_status,
        "log10_abs_error": log_err, "factor_error": factor_err,
        "ad_flag": ad_flag, "ci_lo": ci_lo, "ci_hi": ci_hi, "true_in_ci": in_ci,
        "inference_ms": round(elapsed * 1000, 1),
    })
    status_str = f"pred={pred_gwp:.2f}" if pred_gwp else f"FAIL({model_status})"
    print(f"  {name:20s}  true={true_gwp:8.1f}  {status_str}  {elapsed*1000:.0f}ms")

total_time = time.time() - t_total

# Aggregate metrics
ok_results = [r for r in results if r["log10_abs_error"] is not None]
if ok_results:
    mae = float(np.mean([r["log10_abs_error"] for r in ok_results]))
    rmse = float(np.sqrt(np.mean([r["log10_abs_error"]**2 for r in ok_results])))
    true_log = np.array([np.log10(r["true_gwp100"]) for r in ok_results])
    pred_log = np.array([np.log10(r["predicted_gwp100"]) for r in ok_results])
    ss_res = np.sum((pred_log - true_log)**2)
    ss_tot = np.sum((true_log - true_log.mean())**2)
    r2 = float(1 - ss_res / ss_tot) if ss_tot > 0 else 0.0
    median_factor = float(np.median([r["factor_error"] for r in ok_results]))
    ci_coverage = None
    if any(r["true_in_ci"] is not None for r in ok_results):
        ci_results = [r for r in ok_results if r["true_in_ci"] is not None]
        ci_coverage = float(np.mean([r["true_in_ci"] for r in ci_results]))
else:
    mae = rmse = r2 = median_factor = ci_coverage = None

summary = {
    "agent": AGENT,
    "n_test": len(TEST_MOLECULES),
    "n_predicted": len(ok_results),
    "n_failed": len(TEST_MOLECULES) - len(ok_results),
    "mae_log10_gwp": mae,
    "rmse_log10_gwp": rmse,
    "r2_log10_gwp": r2,
    "median_factor_error": median_factor,
    "ci_coverage_95": ci_coverage,
    "total_inference_seconds": round(total_time, 2),
    "mean_inference_ms": round(total_time / len(TEST_MOLECULES) * 1000, 1),
}
print(f"\n=== {AGENT} SUMMARY ===")
for k, v in summary.items():
    print(f"  {k}: {v}")

with (OUTPUT_DIR / "benchmark_results.json").open("w") as f:
    json.dump({"summary": summary, "per_molecule": results}, f, indent=2, default=str)

with (OUTPUT_DIR / "final_results.json").open("w") as f:
    json.dump({"status": "completed", "summary": summary}, f, indent=2, default=str)
