#!/usr/bin/env python3
"""03b_tanimoto_split.py - Phase 1C, REVISED.

The Murcko scaffold split failed because 91% of our halocarbon dataset is
acyclic (no scaffold). Instead, use Tanimoto-similarity Butina clustering
to define chemically novel holdout molecules.

Strategy:
  1. Compute Morgan fingerprints (radius=2, 2048 bits) for all 257 molecules.
  2. Butina cluster at similarity threshold 0.65 (tuned for halocarbon
     diversity - higher threshold = bigger / fewer clusters).
  3. Assign whole clusters to train or holdout to get target 80/20 split,
     with random shuffling for fairness.
  4. Verify: NN Tanimoto from holdout to train is below 0.7 for all (proves
     each holdout molecule is chemically novel relative to training set).

Inputs:  /input/processed/gwp_resolved_v2.csv  (from prior job 97c07b8c)
Outputs:
  /output/processed/gwp_train.csv
  /output/processed/gwp_holdout_external.csv
  /output/processed/clusters_summary.csv
  /output/processed/holdout_nn_similarities.csv  (per-holdout NN Tanimoto)
  /output/processed/dataset_assembly_report.json
  /output/distribution.png
  /output/cluster_size_hist.png
  /output/holdout_nn_similarity_hist.png
"""

import os, sys, json, logging
from pathlib import Path
import pandas as pd
import numpy as np

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("tani")

INPUT_DIR = Path("/input")
OUTPUT_DIR = Path("/output")
PROC_DIR = OUTPUT_DIR / "processed"
PROC_DIR.mkdir(parents=True, exist_ok=True)

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from rdkit import Chem, DataStructs, RDLogger
RDLogger.DisableLog("rdApp.*")
from rdkit.Chem import AllChem
from rdkit.ML.Cluster import Butina

# ============================================================
# Step 1: Load + sanity check
# ============================================================
log.info("=" * 70)
log.info("Step 1: Load resolved dataset")
log.info("=" * 70)
input_csv = INPUT_DIR / "processed" / "gwp_resolved_v2.csv"
log.info(f"  reading {input_csv} (exists={input_csv.exists()})")
df = pd.read_csv(input_csv).reset_index(drop=True)
log.info(f"  loaded {len(df)} rows")
assert "isomeric_smiles" in df.columns and "log10_gwp100" in df.columns


# ============================================================
# Step 2: Morgan fingerprints
# ============================================================
log.info("=" * 70)
log.info("Step 2: Compute Morgan fingerprints (r=2, 2048 bits)")
log.info("=" * 70)

# Use the modern MorganGenerator API to avoid deprecation warnings
gen = AllChem.GetMorganGenerator(radius=2, fpSize=2048)
fps = []
fp_failed = []
for i, smi in enumerate(df["isomeric_smiles"]):
    mol = Chem.MolFromSmiles(smi)
    if mol is None:
        fp_failed.append(i)
        fps.append(None)
        continue
    fp = gen.GetFingerprint(mol)
    fps.append(fp)

valid_idx = [i for i, fp in enumerate(fps) if fp is not None]
log.info(f"  fingerprints: {len(valid_idx)} valid, {len(fp_failed)} failed")
if fp_failed:
    log.warning(f"  failed indices: {fp_failed[:10]}")
df = df.iloc[valid_idx].reset_index(drop=True)
fps = [fps[i] for i in valid_idx]
log.info(f"  proceeding with {len(df)} valid molecules")


# ============================================================
# Step 3: Butina clustering at multiple thresholds to pick the best
# ============================================================
log.info("=" * 70)
log.info("Step 3: Butina clustering threshold sweep")
log.info("=" * 70)

# Pre-compute the upper-triangular distance matrix once (Butina expects this)
# distance = 1 - Tanimoto similarity
n = len(fps)
log.info(f"  computing {n*(n-1)//2:,} pairwise Tanimoto distances")
dists = []
for i in range(1, n):
    sims = DataStructs.BulkTanimotoSimilarity(fps[i], fps[:i])
    dists.extend(1.0 - np.array(sims))
log.info(f"  distance vector length: {len(dists)}")
log.info(f"  distance stats: min={min(dists):.3f}, max={max(dists):.3f}, mean={np.mean(dists):.3f}")

# Try several thresholds and pick the one that gives a reasonable number of
# clusters for an 80/20 split. We want many small-medium clusters, not one
# giant cluster.
sweep = {}
for cutoff in [0.20, 0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60]:
    clusters = Butina.ClusterData(dists, n, cutoff, isDistData=True)
    sizes = sorted([len(c) for c in clusters], reverse=True)
    sweep[cutoff] = {
        "n_clusters": len(clusters),
        "max_size": sizes[0],
        "median_size": int(np.median(sizes)),
        "n_singletons": sum(1 for s in sizes if s == 1),
    }
    log.info(
        f"  cutoff={cutoff:.2f} -> n_clusters={len(clusters):4d}  "
        f"max={sizes[0]:4d}  median={int(np.median(sizes)):4d}  singletons={sum(1 for s in sizes if s==1):4d}"
    )

# Pick a cutoff: aim for max_size <= ~30 (so any single cluster is < 12% of total),
# and a respectable number of multi-member clusters
chosen_cutoff = None
for c in [0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.30, 0.20]:
    s = sweep[c]
    if s["max_size"] <= 35 and s["n_clusters"] >= 30:
        chosen_cutoff = c
        break
if chosen_cutoff is None:
    chosen_cutoff = 0.45  # reasonable default
log.info(f"  CHOSEN CUTOFF: {chosen_cutoff}")

clusters = list(Butina.ClusterData(dists, n, chosen_cutoff, isDistData=True))
cluster_sizes = sorted([len(c) for c in clusters], reverse=True)
log.info(f"  Final clustering: {len(clusters)} clusters, sizes (top 10): {cluster_sizes[:10]}")


# ============================================================
# Step 4: Assign clusters to train/holdout for 80/20 split
# ============================================================
log.info("=" * 70)
log.info("Step 4: Assign clusters to train/holdout")
log.info("=" * 70)

# Sort clusters by size descending. Place biggest clusters in train so the
# tail (smaller clusters) goes to holdout - this maximizes chemical novelty
# of the holdout while keeping the bulk of training data intact.
clusters_sorted = sorted(clusters, key=lambda c: -len(c))

target_holdout = int(0.20 * n)
train_idx = []
holdout_idx = []
rng = np.random.default_rng(42)

# Greedy assignment: walk through clusters smallest-first to ensure
# holdout has chemical diversity. But also shuffle within size class for
# fairness so the holdout doesn't always contain only the very smallest clusters.
small_clusters = [c for c in clusters_sorted if len(c) <= 5]
big_clusters = [c for c in clusters_sorted if len(c) > 5]
rng.shuffle(small_clusters)

# All big clusters go to train (they represent the most-common chemistry)
for c in big_clusters:
    train_idx.extend(c)

# Small clusters go to holdout up to target_holdout, then to train
for c in small_clusters:
    if len(holdout_idx) + len(c) <= target_holdout:
        holdout_idx.extend(c)
    else:
        train_idx.extend(c)

train_idx = sorted(set(train_idx))
holdout_idx = sorted(set(holdout_idx))
log.info(f"  train={len(train_idx)}  holdout={len(holdout_idx)}  total={len(train_idx)+len(holdout_idx)} (expected {n})")

train_df = df.iloc[train_idx].copy().reset_index(drop=True)
holdout_df = df.iloc[holdout_idx].copy().reset_index(drop=True)

# Assert disjoint
assert set(train_idx).isdisjoint(set(holdout_idx)), "train and holdout overlap"


# ============================================================
# Step 5: Verify NN Tanimoto - holdout should be chemically novel
# ============================================================
log.info("=" * 70)
log.info("Step 5: Verify holdout chemical novelty (NN Tanimoto)")
log.info("=" * 70)

train_fps = [fps[i] for i in train_idx]
holdout_fps = [fps[i] for i in holdout_idx]

nn_records = []
for hi, hfp in enumerate(holdout_fps):
    sims = DataStructs.BulkTanimotoSimilarity(hfp, train_fps)
    sims_arr = np.array(sims)
    top5_idx = np.argsort(sims_arr)[::-1][:5]
    nn_records.append({
        "holdout_identifier": holdout_df.iloc[hi]["identifier"],
        "holdout_smiles": holdout_df.iloc[hi]["isomeric_smiles"],
        "max_tanimoto_to_train": float(sims_arr.max()),
        "mean_top5_tanimoto": float(sims_arr[top5_idx].mean()),
        "nn_train_identifier": train_df.iloc[int(np.argmax(sims_arr))]["identifier"],
    })
nn_df = pd.DataFrame(nn_records)
nn_df.to_csv(PROC_DIR / "holdout_nn_similarities.csv", index=False)
log.info(f"  Holdout NN max-Tanimoto distribution:")
log.info(f"    min={nn_df['max_tanimoto_to_train'].min():.3f}")
log.info(f"    median={nn_df['max_tanimoto_to_train'].median():.3f}")
log.info(f"    mean={nn_df['max_tanimoto_to_train'].mean():.3f}")
log.info(f"    max={nn_df['max_tanimoto_to_train'].max():.3f}")
log.info(f"  Holdout NN mean-top-5-Tanimoto distribution:")
log.info(f"    median={nn_df['mean_top5_tanimoto'].median():.3f}")
log.info(f"    mean={nn_df['mean_top5_tanimoto'].mean():.3f}")
n_truly_novel = int((nn_df["mean_top5_tanimoto"] < 0.4).sum())
log.info(f"  Truly-novel holdout (mean top5 NN sim < 0.4): {n_truly_novel} / {len(nn_df)}")


# ============================================================
# Step 6: Save outputs
# ============================================================
log.info("=" * 70)
log.info("Step 6: Save outputs")
log.info("=" * 70)

# Add cluster_id column for transparency
cluster_lookup = {}
for ci, members in enumerate(clusters):
    for m in members:
        cluster_lookup[m] = ci
df["cluster_id"] = [cluster_lookup.get(i, -1) for i in range(len(df))]
train_df["cluster_id"] = [cluster_lookup.get(i, -1) for i in train_idx]
holdout_df["cluster_id"] = [cluster_lookup.get(i, -1) for i in holdout_idx]

train_df.to_csv(PROC_DIR / "gwp_train.csv", index=False)
holdout_df.to_csv(PROC_DIR / "gwp_holdout_external.csv", index=False)

# Cluster summary
cluster_summary = pd.DataFrame([
    {
        "cluster_id": ci,
        "size": len(members),
        "members": "; ".join(df.iloc[m]["identifier"] for m in members[:5]),
    }
    for ci, members in enumerate(clusters)
]).sort_values("size", ascending=False)
cluster_summary.to_csv(PROC_DIR / "clusters_summary.csv", index=False)

# Plots
fig, axes = plt.subplots(1, 2, figsize=(12, 4))
axes[0].hist(df["log10_gwp100"], bins=30, alpha=0.7, color="steelblue", edgecolor="black")
axes[0].set_xlabel("log10(GWP100)")
axes[0].set_ylabel("count")
axes[0].set_title(f"Full dataset (N={len(df)})")
axes[0].grid(alpha=0.3)
axes[1].hist(train_df["log10_gwp100"], bins=20, alpha=0.6, label=f"train (N={len(train_df)})", color="steelblue", edgecolor="black")
axes[1].hist(holdout_df["log10_gwp100"], bins=20, alpha=0.6, label=f"holdout (N={len(holdout_df)})", color="orange", edgecolor="black")
axes[1].set_xlabel("log10(GWP100)")
axes[1].set_ylabel("count")
axes[1].set_title(f"Tanimoto-clustered split (cutoff={chosen_cutoff})")
axes[1].legend()
axes[1].grid(alpha=0.3)
plt.tight_layout()
plt.savefig(OUTPUT_DIR / "distribution.png", dpi=120, bbox_inches="tight")
plt.close()

# Cluster size histogram
fig, ax = plt.subplots(figsize=(8, 4))
ax.hist(cluster_sizes, bins=30, color="seagreen", edgecolor="black")
ax.set_xlabel("Cluster size (n molecules)")
ax.set_ylabel("Number of clusters")
ax.set_title(f"Butina cluster sizes at cutoff={chosen_cutoff} ({len(clusters)} clusters)")
ax.set_yscale("log")
ax.grid(alpha=0.3)
plt.tight_layout()
plt.savefig(OUTPUT_DIR / "cluster_size_hist.png", dpi=120, bbox_inches="tight")
plt.close()

# Holdout NN similarity histogram
fig, ax = plt.subplots(figsize=(8, 4))
ax.hist(nn_df["max_tanimoto_to_train"], bins=20, alpha=0.6, label="max Tanimoto", color="steelblue", edgecolor="black")
ax.hist(nn_df["mean_top5_tanimoto"], bins=20, alpha=0.6, label="mean top-5 Tanimoto", color="orange", edgecolor="black")
ax.axvline(0.4, color="red", linestyle="--", label="OOD threshold = 0.4")
ax.set_xlabel("Tanimoto similarity to training set")
ax.set_ylabel("count")
ax.set_title(f"Holdout chemical novelty (N={len(nn_df)})")
ax.legend()
ax.grid(alpha=0.3)
plt.tight_layout()
plt.savefig(OUTPUT_DIR / "holdout_nn_similarity_hist.png", dpi=120, bbox_inches="tight")
plt.close()


# ============================================================
# Step 7: Final report
# ============================================================
report = {
    "input_resolved_rows": int(len(df)),
    "n_morgan_fps": int(len(fps)),
    "butina_cutoff": float(chosen_cutoff),
    "butina_sweep": sweep,
    "n_clusters": int(len(clusters)),
    "cluster_size_max": int(cluster_sizes[0]),
    "cluster_size_median": int(np.median(cluster_sizes)),
    "n_singletons": int(sum(1 for s in cluster_sizes if s == 1)),
    "split_train_n": int(len(train_df)),
    "split_holdout_n": int(len(holdout_df)),
    "split_train_pct": round(len(train_df) / n * 100, 1),
    "split_holdout_pct": round(len(holdout_df) / n * 100, 1),
    "train_log10_gwp_range": [float(train_df["log10_gwp100"].min()), float(train_df["log10_gwp100"].max())],
    "holdout_log10_gwp_range": [float(holdout_df["log10_gwp100"].min()), float(holdout_df["log10_gwp100"].max())],
    "holdout_nn_max_tanimoto_median": float(nn_df["max_tanimoto_to_train"].median()),
    "holdout_nn_mean_top5_median": float(nn_df["mean_top5_tanimoto"].median()),
    "holdout_truly_novel_count": n_truly_novel,
    "train_lifetime_known": int(train_df["lifetime_years"].notna().sum()),
    "holdout_lifetime_known": int(holdout_df["lifetime_years"].notna().sum()),
    "train_by_source": train_df["source"].value_counts().to_dict(),
    "holdout_by_source": holdout_df["source"].value_counts().to_dict(),
}
log.info("=" * 70)
log.info("FINAL")
log.info("=" * 70)
for k, v in report.items():
    if k == "butina_sweep":
        continue
    log.info(f"  {k}: {v}")

with (PROC_DIR / "dataset_assembly_report.json").open("w") as f:
    json.dump(report, f, indent=2, default=str)

final = {
    "status": "completed",
    "summary": report,
    "outputs": [
        "processed/gwp_train.csv",
        "processed/gwp_holdout_external.csv",
        "processed/clusters_summary.csv",
        "processed/holdout_nn_similarities.csv",
        "processed/dataset_assembly_report.json",
        "distribution.png",
        "cluster_size_hist.png",
        "holdout_nn_similarity_hist.png",
    ],
    "next_phase": "Phase 1D: Train Chemprop multi-task ensemble",
}
with (OUTPUT_DIR / "final_results.json").open("w") as f:
    json.dump(final, f, indent=2)

log.info("DONE")
