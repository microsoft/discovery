#!/usr/bin/env python3
"""
Add missing indexes to existing BindingDB SQLite database.

This script adds the correct indexes to improve query performance,
especially for UniProt ID and ligand name searches.
"""

import sqlite3
import sys
import time
from pathlib import Path


def add_indexes(db_path: str):
    """Add performance indexes to the BindingDB SQLite database."""
    
    if not Path(db_path).exists():
        print(f"❌ Database not found: {db_path}")
        sys.exit(1)
    
    print("=" * 70)
    print("BindingDB SQLite Index Creator")
    print("=" * 70)
    print(f"Database: {db_path}")
    print()
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Define indexes to create
    indexes = [
        ('idx_uniprot_chain1', '"UniProt (SwissProt) Primary ID of Target Chain 1"', 'UniProt lookups'),
        ('idx_ligand_name', '"BindingDB Ligand Name"', 'Compound searches'),
        ('idx_bindingdb_id', '"BindingDB MonomerID"', 'Entry ID lookups'),
        ('idx_ligand_smiles', '"Ligand SMILES"', 'SMILES searches'),
        ('idx_kd', '"Kd (nM)"', 'Kd filtering'),
        ('idx_ki', '"Ki (nM)"', 'Ki filtering'),
        ('idx_ic50', '"IC50 (nM)"', 'IC50 filtering'),
        ('idx_ec50', '"EC50 (nM)"', 'EC50 filtering'),
        ('idx_target_name', '"Target Name"', 'Target name searches'),
        ('idx_pmid', '"PMID"', 'PubMed lookups'),
    ]
    
    print("Creating indexes...")
    print()
    
    created = 0
    skipped = 0
    failed = 0
    
    for idx_name, column_name, description in indexes:
        try:
            # Check if index already exists
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name=?",
                (idx_name,)
            )
            
            if cursor.fetchone():
                print(f"⏭️  {idx_name:25} - Already exists ({description})")
                skipped += 1
                continue
            
            # Create the index
            print(f"🔨 {idx_name:25} - Creating... ", end='', flush=True)
            start_time = time.time()
            
            cursor.execute(f'CREATE INDEX {idx_name} ON bindings({column_name})')
            
            elapsed = time.time() - start_time
            print(f"✓ Done ({elapsed:.1f}s)")
            created += 1
            
        except Exception as e:
            print(f"❌ Error: {e}")
            failed += 1
    
    # Analyze database for query optimization
    print()
    print("📊 Analyzing database for query optimization...")
    cursor.execute('ANALYZE')
    
    # Get database stats
    cursor.execute("SELECT COUNT(*) FROM bindings")
    total_rows = cursor.fetchone()[0]
    
    db_size = Path(db_path).stat().st_size / (1024**3)  # GB
    
    conn.commit()
    conn.close()
    
    print()
    print("=" * 70)
    print("✅ Index Creation Complete")
    print("=" * 70)
    print(f"Database: {db_path}")
    print(f"Size: {db_size:.2f} GB")
    print(f"Total rows: {total_rows:,}")
    print()
    print(f"Indexes created: {created}")
    print(f"Already existed: {skipped}")
    print(f"Failed: {failed}")
    print()
    
    if created > 0:
        print("🚀 Query performance should be significantly improved!")
        print()
        print("Expected query times:")
        print("  - UniProt lookup: 3-10ms")
        print("  - Ligand name search: 50-200ms")
        print("  - Kd/Ki/IC50 filtering: 100-300ms")
    else:
        print("ℹ️  All indexes already exist. No changes made.")
    print()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Add performance indexes to BindingDB SQLite database"
    )
    parser.add_argument(
        'database',
        nargs='?',
        default='bindingdb.db',
        help='Path to SQLite database (default: bindingdb.db)'
    )
    
    args = parser.parse_args()
    add_indexes(args.database)
