#!/usr/bin/env python3
"""Download all MatterGen pretrained checkpoints from HuggingFace Hub."""
from huggingface_hub import hf_hub_download

MODELS = [
    "mattergen_base",
    "mp_20_base",
    "chemical_system",
    "space_group",
    "dft_band_gap",
    "dft_mag_density",
    "ml_bulk_modulus",
    "chemical_system_energy_above_hull",
    "dft_mag_density_hhi_score",
]

REPO = "microsoft/mattergen"

for m in MODELS:
    print(f"Downloading {m}...")
    hf_hub_download(repo_id=REPO, filename=f"checkpoints/{m}/checkpoints/last.ckpt")
    hf_hub_download(repo_id=REPO, filename=f"checkpoints/{m}/config.yaml")

print("All checkpoints downloaded.")
