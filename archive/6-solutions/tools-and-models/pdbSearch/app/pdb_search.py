#!/usr/bin/env python
"""
Command-line wrapper for the RCSBPDB pdb_search action.
"""
import argparse
import sys
import os
import glob
from search_utils import search_by_organism, search_by_resolution
from pdb_utils import download_structure

def read_pdb_ids_from_file(filepath):
    """
    Read PDB IDs from a text file (one per line or comma-separated).
    
    Returns:
        List of PDB IDs (empty list if file cannot be read)
    """
    pdb_ids = []
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read().strip()
            # Handle both line-separated and comma-separated formats
            if ',' in content:
                pdb_ids = [pdb_id.strip() for pdb_id in content.split(',')]
            else:
                pdb_ids = [line.strip() for line in content.split('\n') if line.strip()]
        return [pdb_id for pdb_id in pdb_ids if pdb_id]
    except FileNotFoundError:
        print(f"⚠️ File not found: {filepath}")
        return []
    except PermissionError:
        print(f"⚠️ Permission denied reading file: {filepath}")
        return []
    except UnicodeDecodeError as e:
        print(f"⚠️ Encoding error reading file {filepath}: {e}")
        print(f"   Try re-saving the file as UTF-8")
        return []
    except Exception as e:
        print(f"⚠️ Unexpected error reading file {filepath}: {e}")
        return []

def main():
    parser = argparse.ArgumentParser(
        description="Search RCSB PDB and download structures based on query or PDB ID list"
    )
    parser.add_argument(
        "--organism",
        help="Organism name (e.g., 'Homo sapiens')",
    )
    parser.add_argument(
        "--min_res", type=float,
        help="Minimum resolution in Angstroms"
    )
    parser.add_argument(
        "--max_res", type=float,
        help="Maximum resolution in Angstroms"
    )
    parser.add_argument(
        "--pdb_ids",
        help="Comma-separated list of PDB IDs (e.g., '1LYZ,2LYZ,3LYZ')"
    )
    parser.add_argument(
        "--input_dir", required=True,
        help="Directory to read input files from"
    )
    parser.add_argument(
        "--output_dir", required=True,
        help="Directory to save downloaded structures"
    )
    args = parser.parse_args()

    pdb_ids = []

    # Priority 1: Use explicit PDB IDs if provided
    if args.pdb_ids:
        pdb_ids = [pdb_id.strip() for pdb_id in args.pdb_ids.split(',')]
        print(f"Using provided PDB IDs: {pdb_ids}")
    
    # Priority 2: Search for PDB ID files in input directory
    elif os.path.exists(args.input_dir):
        id_files = glob.glob(os.path.join(args.input_dir, "*.txt")) + \
                   glob.glob(os.path.join(args.input_dir, "*.csv")) + \
                   glob.glob(os.path.join(args.input_dir, "*pdb*"))
        
        for id_file in id_files:
            try:
                file_pdb_ids = read_pdb_ids_from_file(id_file)
                pdb_ids.extend(file_pdb_ids)
                print(f"Read {len(file_pdb_ids)} PDB IDs from {id_file}")
            except Exception as e:
                print(f"Failed to read {id_file}: {e}")
    
    # Priority 3: Perform database search
    if not pdb_ids:
        if args.organism:
            pdb_ids = search_by_organism(args.organism)
            print(f"Found {len(pdb_ids)} structures for organism: {args.organism}")
        elif args.min_res is not None and args.max_res is not None:
            pdb_ids = search_by_resolution(args.min_res, args.max_res)
            print(f"Found {len(pdb_ids)} structures with resolution {args.min_res}-{args.max_res}Å")
        else:
            print("Error: No PDB IDs provided and no valid search criteria specified.", file=sys.stderr)
            print("Provide --pdb_ids, place files in input directory, or specify search criteria.", file=sys.stderr)
            sys.exit(1)

    if not pdb_ids:
        print("No PDB entries found for given criteria.")
        sys.exit(0)

    # Download structures
    os.makedirs(args.output_dir, exist_ok=True)
    successful_downloads = 0
    
    for pdb_id in pdb_ids:
        filepath = download_structure(pdb_id, args.output_dir)
        if filepath:
            print(f"✓ Downloaded {pdb_id} to {filepath}")
            successful_downloads += 1
        else:
            print(f"✗ Failed to download {pdb_id}")

    print(f"\nSummary: Successfully downloaded {successful_downloads}/{len(pdb_ids)} structures")

if __name__ == "__main__":
    main()
