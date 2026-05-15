"""
PDBInsights Agent - single script entrypoint

Usage: set environment variables as needed and run this script. It will write
results to /output/final_results.json and other files into /output.
"""
import os
import sys
import argparse
import json
import time

from PDBInsights_utils import (
    search_pdb_by_query,
    download_pdb,
    clean_structure,
    fix_structure_with_pdbfixer,
    parse_pdb_header_metrics,
    compute_simple_geometry_metrics,
    generate_summary,
    rank_structures,
)


def main():
    parser = argparse.ArgumentParser(description='PDBInsights - search, download and assess PDB structures')
    parser.add_argument('target', help='Protein name or UniProt ID to search for')
    parser.add_argument('--out', required=True, help='Output directory')
    parser.add_argument('--max', type=int, default=20, help='Maximum number of PDBs to process')
    args = parser.parse_args()

    outdir = args.out
    os.makedirs(outdir, exist_ok=True)

    print(f"Searching PDB for target: {args.target}")
    pdb_ids = search_pdb_by_query(args.target, size=args.max)
    print(f"Found {len(pdb_ids)} entries")

    results = []
    for i, pdb_id in enumerate(pdb_ids, 1):
        print(f"[{i}/{len(pdb_ids)}] Processing {pdb_id}")
        downloaded = download_pdb(pdb_id, out_dir=outdir)
        if not downloaded:
            print(f"  ! Failed to download {pdb_id}")
            results.append({"pdb_id": pdb_id, "status": "download_failed"})
            continue

        cleaned = os.path.join(outdir, f"{pdb_id}_cleaned.pdb")
        try:
            clean_structure(downloaded, cleaned)
        except Exception as e:
            print(f"  ! Cleaning failed: {e}")
            results.append({"pdb_id": pdb_id, "status": "clean_failed"})
            continue

        fixed = os.path.join(outdir, f"{pdb_id}_fixed.pdb")
        fix_summary = {"missing_residues_fixed": 0, "missing_atoms_fixed": 0}
        try:
            fix_summary = fix_structure_with_pdbfixer(cleaned, fixed)
        except Exception as e:
            print(f"  ! PDBFixer step skipped or failed: {e}")
            # Fall back to cleaned file as fixed
            fixed = cleaned

        metrics = parse_pdb_header_metrics(downloaded)
        geom = compute_simple_geometry_metrics(fixed)

        entry = {
            "pdb_id": pdb_id,
            "status": "processed",
            "downloaded_path": downloaded,
            "cleaned_path": cleaned,
            "fixed_path": fixed,
            "missing_residues_fixed": fix_summary.get('missing_residues_fixed', 0),
            "missing_atoms_fixed": fix_summary.get('missing_atoms_fixed', 0),
            "resolution": metrics.get('resolution'),
            "r_free": metrics.get('r_free'),
            "r_work": metrics.get('r_work'),
            "chains": geom.get('chains'),
            "atom_count": geom.get('atom_count'),
        }
        results.append(entry)

        # Be polite to RCSB
        time.sleep(0.3)

    # Generate summary files
    final_json = os.path.join(outdir, 'final_results.json')
    final_csv = os.path.join(outdir, 'final_results.csv')
    generate_summary(results, out_json=final_json, out_csv=final_csv)

    best = rank_structures(results)
    report_lines = [f"PDBInsights report for target: {args.target}", "="*60, f"Total structures processed: {len(results)}"]
    if best:
        report_lines.append(f"Best representative structure: {best['pdb_id']}")
        report_lines.append(f"  Resolution: {best.get('resolution')}")
        report_lines.append(f"  R-free: {best.get('r_free')}")
        report_lines.append(f"  Chains: {best.get('chains')}, Atoms: {best.get('atom_count')}")
    else:
        report_lines.append("No suitable structures found")

    report_path = os.path.join(outdir, 'PDBInsights_report.txt')
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(report_lines))

    print(f"Report written to: {report_path}")
    print(f"Final JSON written to: {final_json}")


if __name__ == '__main__':
    main()
