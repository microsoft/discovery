#!/usr/bin/env python3
"""Example: Search and list high-quality PDB structures for human EPOR (UniProt P19235)

This script demonstrates safe filtering using the helper functions in PDBInsights_utils
and avoids direct comparisons that can crash when metrics are missing.
"""
from PDBInsights_utils import search_and_analyze_by_uniprot, filter_results_by_metrics


def main():
    uniprot_id = "P19235"
    print(f"Searching and analyzing structures for UniProt {uniprot_id} (limit 50)...")
    summary = search_and_analyze_by_uniprot(uniprot_id, limit=50, outdir=None, download=False, clean=False)

    # Safely filter by resolution and R-free thresholds. Entries with missing metrics
    # are treated as not meeting the thresholds and thus are skipped.
    high_quality = filter_results_by_metrics(summary.get("results", []), resolution_lt=3.0, r_free_lt=0.25)

    print(f"Found {len(high_quality)} high-quality structures:")
    for r in high_quality:
        print(f"{r['pdb_id']}: Res={r.get('resolution')} Å, R-free={r.get('r_free')}, Context={r.get('context')}")


if __name__ == "__main__":
    main()
