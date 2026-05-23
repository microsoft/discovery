#!/usr/bin/env python3
from __future__ import annotations

"""Download and canonicalize eMolecules building blocks for Syntheseus.
Used during Docker build (after conda env activation so RDKit is available).
Downloads the eMolecules free building-blocks file, canonicalizes every SMILES
with RDKit, deduplicates, and writes one canonical SMILES per line.

Usage:
    python prepare_building_blocks.py [--url URL] [--output /app/data/building_blocks.smi]

If the download fails (network, URL expired, etc.) the script exits 0 and leaves
the existing small bundled fallback in place so the image build does not break.
"""

import argparse
import gzip
import logging
import os
import sys
import time
import urllib.request

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# eMolecules publishes purchasable building blocks at /orderbb/.  The "parent"
# variant has salts stripped, which maximises Syntheseus match rate (the model
# often predicts the salt-free form).  eMolecules rotates the date slug every
# few months and removes old versions — check https://downloads.emolecules.com/orderbb/
# if the default 404s.  Override with --url or BUILDING_BLOCKS_URL env var.
DEFAULT_URL = (
    "https://downloads.emolecules.com/orderbb/2026-04-01/parent.smi.gz"
)

MAX_RETRIES = 3
RETRY_DELAY_S = 10


def download(url: str, dest: str) -> bool:
    """Download *url* to *dest* with retries.  Returns True on success."""
    opener = urllib.request.build_opener()
    opener.addheaders = [
        ("User-Agent", "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36")
    ]
    urllib.request.install_opener(opener)

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logging.info("Download attempt %d/%d: %s", attempt, MAX_RETRIES, url)
            urllib.request.urlretrieve(url, dest)
            size_mb = os.path.getsize(dest) / 1024 / 1024
            logging.info("Downloaded %.1f MB -> %s", size_mb, dest)
            if size_mb < 1:
                logging.warning("File suspiciously small (%.1f MB), retrying...", size_mb)
                os.remove(dest)
                time.sleep(RETRY_DELAY_S)
                continue
            return True
        except Exception as exc:
            logging.warning("Attempt %d failed: %s", attempt, exc)
            if os.path.exists(dest):
                os.remove(dest)
            time.sleep(RETRY_DELAY_S)
    return False


def _is_gzipped(path: str) -> bool:
    """Detect gzip by magic bytes (download path may not end in .gz)."""
    try:
        with open(path, "rb") as f:
            return f.read(2) == b"\x1f\x8b"
    except OSError:
        return False


def _canonicalize_chunk(smiles_list: list[str]) -> list[str | None]:
    """Canonicalize a batch of SMILES in a worker process.

    Returns a list of canonical SMILES (None for invalid entries).
    Imported per-worker so each subprocess loads RDKit once.
    """
    from rdkit import Chem, RDLogger

    RDLogger.DisableLog("rdApp.*")
    results = []
    for smi in smiles_list:
        mol = Chem.MolFromSmiles(smi)
        if mol is None:
            results.append(None)
        else:
            results.append(Chem.MolToSmiles(mol))
    return results


def canonicalize_and_dedup(input_path: str, output_path: str) -> int:
    """Read SMILES from *input_path*, canonicalize with RDKit, deduplicate,
    and write one canonical SMILES per line to *output_path*.

    Uses multiprocessing to parallelize RDKit canonicalization across all
    available CPU cores.  The file is read sequentially (gzip streams are
    not seekable), then chunks are dispatched to workers.

    Returns the number of unique canonical SMILES written.
    """
    import multiprocessing as mp

    # --- Phase 1: read raw SMILES from file (fast, sequential) ---
    open_fn = gzip.open if _is_gzipped(input_path) else open
    raw_smiles: list[str] = []

    logging.info("  reading raw SMILES from %s ...", input_path)
    with open_fn(input_path, "rt", errors="replace") as fin:
        for line in fin:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # eMolecules format: space-separated fields.
            #   orderbb/parent.smi: "isosmiles parent_id"  (2 fields)
            #   free/version.smi:   "isosmiles version_id parent_id"  (3 fields)
            # First token is always the SMILES string.
            parts = line.split()
            if not parts:
                continue
            token = parts[0]
            if token == "isosmiles":
                continue
            raw_smiles.append(token)

    total = len(raw_smiles)
    logging.info("  read %d raw SMILES, starting canonicalization ...", total)

    # --- Phase 2: canonicalize in parallel ---
    n_workers = min(mp.cpu_count() or 1, 8)
    chunk_size = max(2000, total // (n_workers * 4))

    # Split into chunks for Pool.map (one call per chunk, not per SMILES)
    chunks = [raw_smiles[i : i + chunk_size] for i in range(0, total, chunk_size)]
    logging.info("  using %d workers, %d chunks of ~%d SMILES", n_workers, len(chunks), chunk_size)

    with mp.Pool(n_workers) as pool:
        chunk_results = pool.map(_canonicalize_chunk, chunks)

    # --- Phase 3: dedup and write (sequential, fast) ---
    seen: set[str] = set()
    written = 0
    skipped = 0

    with open(output_path, "w") as fout:
        for chunk in chunk_results:
            for canon in chunk:
                if canon is None:
                    skipped += 1
                    continue
                if canon not in seen:
                    seen.add(canon)
                    fout.write(canon + "\n")
                    written += 1

    logging.info(
        "Canonicalization complete: %d unique SMILES written, %d invalid skipped",
        written,
        skipped,
    )
    return written


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--url",
        default=os.environ.get("BUILDING_BLOCKS_URL", DEFAULT_URL),
        help="URL to the eMolecules building-blocks .smi.gz file",
    )
    parser.add_argument(
        "--output",
        default="/app/data/building_blocks.smi",
        help="Output path for the canonicalized SMILES file",
    )
    args = parser.parse_args()

    os.makedirs(os.path.dirname(args.output), exist_ok=True)

    # If a small bundled fallback already exists, we will overwrite it on
    # success but keep it on failure.
    tmp_download = args.output + ".download"

    if not download(args.url, tmp_download):
        logging.error(
            "Could not download building blocks from %s. "
            "The small bundled fallback will remain at %s.",
            args.url,
            args.output,
        )
        return  # exit 0 — don't break the image build

    logging.info("Canonicalizing SMILES with RDKit...")
    tmp_canonical = args.output + ".tmp"
    count = canonicalize_and_dedup(tmp_download, tmp_canonical)

    if count < 100:
        logging.error(
            "Only %d valid SMILES found — something is wrong with the download. "
            "Keeping the existing fallback.",
            count,
        )
        os.remove(tmp_download)
        os.remove(tmp_canonical)
        return

    # Atomic swap: replace the bundled fallback with the full catalog
    os.replace(tmp_canonical, args.output)
    os.remove(tmp_download)
    logging.info("Building blocks ready: %d compounds at %s", count, args.output)


if __name__ == "__main__":
    main()
