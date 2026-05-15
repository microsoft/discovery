#!/usr/bin/env python3
"""
BindingDB TSV to SQLite Converter

This script downloads the BindingDB TSV file and converts it to an optimized
SQLite database for fast querying. Intended for use during Docker image builds.

Usage:
    python tsv_to_sqlite.py [--output bindingdb.db]

Expected input: BindingDB TSV file (downloaded automatically or provided)
Output: Optimized SQLite database with indexes
"""

import argparse
import os
import sys
import time
import sqlite3
import pandas as pd
import requests
from typing import Optional
from pathlib import Path


class BindingDBConverter:
    """Convert BindingDB TSV file to optimized SQLite database."""
    
    # Default download URL for BindingDB TSV (October 2025 snapshot)
    DEFAULT_TSV_URL = "https://www.bindingdb.org/rwd/bind/downloads/BindingDB_All_202510_tsv.zip"
    
    def __init__(self, output_db: str = "bindingdb.db", tsv_url: Optional[str] = None):
        """
        Initialize converter.
        
        Args:
            output_db: Path to output SQLite database
            tsv_url: Custom download URL (defaults to October 2025 snapshot)
        """
        self.output_db = output_db
        self.tsv_url = tsv_url or self.DEFAULT_TSV_URL
        self.tsv_file = None
        self.zip_file = None
        # Optional sampling options (set from CLI)
        self.sample_rate: Optional[float] = None
        self.sample_seed: Optional[int] = None
        
    def download_tsv(self, force: bool = False) -> str:
        """
        Download BindingDB TSV file.
        
        Args:
            force: Force download even if file exists
            
        Returns:
            Path to downloaded ZIP file
        """
        # Look for any existing BindingDB zip file (flexible naming)
        existing_zips = [f for f in os.listdir('.') if f.startswith('BindingDB_All') and f.endswith('.zip')]
        
        if existing_zips and not force:
            zip_path = existing_zips[0]
            print(f"✓ ZIP file already exists: {zip_path}")
            print("  Use --force-download to re-download")
            self.zip_file = zip_path
            return zip_path
        
        # Download with a generic name
        zip_path = "BindingDB_All.zip"
        
        print("📥 Downloading BindingDB TSV file...")
        print(f"   URL: {self.tsv_url}")
        print("   This may take 10-20 minutes depending on connection...")
        
        start_time = time.time()
        
        try:
            response = requests.get(self.tsv_url, stream=True, timeout=3600)
            response.raise_for_status()
            
            # Download with progress indication
            total_size = 0
            chunk_count = 0
            
            with open(zip_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        total_size += len(chunk)
                        chunk_count += 1
                        
                        # Print progress every 10 MB
                        if chunk_count % 1280 == 0:  # 1280 * 8KB = ~10MB
                            print(f"   Downloaded: {total_size / (1024**2):.1f} MB")
            
            elapsed = time.time() - start_time
            print(f"✓ Download complete: {total_size / (1024**2):.1f} MB in {elapsed:.1f}s")
            print(f"   Average speed: {(total_size / (1024**2)) / elapsed:.1f} MB/s")
            
            self.zip_file = zip_path
            return zip_path
            
        except requests.RequestException as e:
            print(f"❌ Build failed: network error (falling back)")
            # If download fails and we have an existing file, use it
            if existing_zips:
                print(f"⚠️  Using existing zip file: {existing_zips[0]}")
                self.zip_file = existing_zips[0]
                return existing_zips[0]
            print(f"✗ Download failed: {e}")
            sys.exit(1)
    
    def extract_tsv(self) -> str:
        """
        Extract TSV file from ZIP archive.
        
        Returns:
            Path to extracted TSV file
        """
        import zipfile
        
        if not self.zip_file:
            raise ValueError("No ZIP file available. Call download_tsv() first.")
        
        print("\n📦 Extracting TSV from ZIP archive...")
        
        try:
            with zipfile.ZipFile(self.zip_file, 'r') as zip_ref:
                # List contents
                file_list = zip_ref.namelist()
                tsv_files = [f for f in file_list if f.endswith('.tsv')]
                
                if not tsv_files:
                    print(f"✗ No TSV files found in archive. Contents: {file_list}")
                    sys.exit(1)
                
                tsv_file = tsv_files[0]
                print(f"   Extracting: {tsv_file}")
                
                zip_ref.extract(tsv_file)
                
                file_size = os.path.getsize(tsv_file)
                print(f"✓ Extracted: {tsv_file} ({file_size / (1024**3):.2f} GB)")
                
                self.tsv_file = tsv_file
                return tsv_file
                
        except Exception as e:
            print(f"✗ Extraction failed: {e}")
            sys.exit(1)
    
    def convert_to_sqlite(self, chunksize: int = 100000, page_size: int = 1024) -> None:
        """
        Convert TSV to SQLite database with indexes.
        (a) numeric casting + trimming empties
        (b) slimmer targeted indexes (partial/composite)
        """
        if not self.tsv_file:
            raise ValueError("No TSV file available. Call extract_tsv() first.")
        
        print(f"\n🔄 Converting TSV to SQLite database...")
        print(f"   Input: {self.tsv_file}")
        print(f"   Output: {self.output_db}")
        print(f"   Chunk size: {chunksize:,} rows")
        print(f"   Page size: {page_size:,} bytes")
        print("   This may take 15-30 minutes...")
        
        start_time = time.time()

        # Validate sampling parameters on start of conversion
        sample_rate = getattr(self, 'sample_rate', None)
        sample_seed = getattr(self, 'sample_seed', None)
        if sample_rate is not None:
            if not (0.0 < sample_rate <= 1.0):
                raise ValueError('--sample-rate must be between 0 (exclusive) and 1 (inclusive)')
            print(f"   Sampling enabled: {sample_rate * 100:.1f}% of rows (seed={sample_seed})")
        
        # Remove existing database
        if os.path.exists(self.output_db):
            os.remove(self.output_db)
        
        conn = sqlite3.connect(self.output_db)
        
        # Keep original behavior: set page size BEFORE any table creation, then VACUUM
        conn.execute(f'PRAGMA page_size = {page_size}')
        conn.execute('VACUUM')  # Apply the page size
        
        try:
            # (a) prepare column lists once (does not change behavior for missing columns)
            num_cols = [
                "Kd (nM)", "Ki (nM)", "IC50 (nM)", "EC50 (nM)",
                "kon (M-1-s-1)", "koff (s-1)"
            ]
            text_cols = [
                "Ligand SMILES", "BindingDB Ligand Name", "Target Name",
                "UniProt (SwissProt) Primary ID of Target Chain 1", "Article DOI"
            ]

            # Read and insert in chunks
            chunk_num = 0
            total_rows = 0
            
            print("\n   Reading TSV in chunks...")
            for chunk in pd.read_csv(
                self.tsv_file,
                sep='\t',
                chunksize=chunksize,
                low_memory=False,
                encoding='utf-8',
                on_bad_lines='skip'
            ):
                chunk_num += 1
                rows_in_chunk = len(chunk)
                total_rows += rows_in_chunk
                
                print(f"   Chunk {chunk_num}: {rows_in_chunk:,} rows (total: {total_rows:,})")
                
                # (a) Normalize empties → NULL (None) to avoid storing empty strings
                #     Keep NaN handling intact; this maps "" to None only.
                # Optionally sample the chunk for quicker testing
                if sample_rate is not None and 0.0 < sample_rate < 1.0:
                    # Use pandas sample for random selection; preserve index reset
                    chunk = chunk.sample(frac=sample_rate, random_state=sample_seed)
                    chunk = chunk.reset_index(drop=True)

                chunk = chunk.replace({pd.NA: None, "": None})

                # (a) Cast known numeric columns to REAL (non-parsable → NaN → stored as NULL)
                for col in num_cols:
                    if col in chunk.columns:
                        chunk[col] = pd.to_numeric(chunk[col], errors="coerce")

                # (a) Light text hygiene to reduce whitespace bloat; preserves None
                for col in text_cols:
                    if col in chunk.columns:
                        # Use string dtype for vectorized .str ops; None stays None
                        chunk[col] = chunk[col].astype("string").str.strip()

                # Write to SQLite
                chunk.to_sql('bindings', conn, if_exists='append', index=False)
            
            elapsed = time.time() - start_time
            print(f"\n✓ Imported {total_rows:,} rows in {elapsed:.1f}s")
            print(f"   Rate: {total_rows / elapsed:.0f} rows/sec")
            
            # (b) Create targeted indexes instead of many single-column ones
            print("\n🔍 Creating indexes...")
            indexes = [
                # Target-centric potency lookups (skip NULLs to shrink index size)
                (None, '''CREATE INDEX IF NOT EXISTS idx_u_kd 
                        ON bindings("UniProt (SwissProt) Primary ID of Target Chain 1","Kd (nM)") 
                        WHERE "Kd (nM)" IS NOT NULL'''),
                (None, '''CREATE INDEX IF NOT EXISTS idx_u_ki 
                        ON bindings("UniProt (SwissProt) Primary ID of Target Chain 1","Ki (nM)") 
                        WHERE "Ki (nM)" IS NOT NULL'''),
                (None, '''CREATE INDEX IF NOT EXISTS idx_u_ic50 
                        ON bindings("UniProt (SwissProt) Primary ID of Target Chain 1","IC50 (nM)") 
                        WHERE "IC50 (nM)" IS NOT NULL'''),

                # Ligand-centric potency lookup
                (None, '''CREATE INDEX IF NOT EXISTS idx_smiles_kd 
                        ON bindings("Ligand SMILES","Kd (nM)") 
                        WHERE "Kd (nM)" IS NOT NULL'''),

                # Literature presence only (avoid indexing NULLs)
                (None, '''CREATE INDEX IF NOT EXISTS idx_pmid_nonnull 
                        ON bindings("PMID") WHERE "PMID" IS NOT NULL''')
            ]
            
            for _, sql in indexes:
                try:
                    conn.execute(sql)
                except Exception as e:
                    print(f"   ⚠️  Index creation warning: {e}")
            
            print("\n🗜️  Optimizing database (VACUUM)...")
            conn.execute('VACUUM')
            
            # Get final database size and stats
            conn.execute('ANALYZE')
            
            db_size = os.path.getsize(self.output_db)
            
            # Get row count
            cursor = conn.execute('SELECT COUNT(*) FROM bindings')
            row_count = cursor.fetchone()[0]
            
            # Get table info
            cursor = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='index'")
            index_count = cursor.fetchone()[0]
            
            total_elapsed = time.time() - start_time
            
            print("\n" + "=" * 60)
            print("✅ CONVERSION COMPLETE")
            print("=" * 60)
            print(f"Database: {self.output_db}")
            print(f"Size: {db_size / (1024**3):.2f} GB")
            print(f"Rows: {row_count:,}")
            print(f"Indexes: {index_count}")
            print(f"Total time: {total_elapsed / 60:.1f} minutes")
            print("=" * 60)
            
        except Exception as e:
            print(f"\n✗ Conversion failed: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)
        finally:
            conn.close()

    def test_queries(self) -> None:
        """
        Test the SQLite database with sample queries.
        """
        print("\n🧪 Testing database with sample queries...")

        conn = sqlite3.connect(self.output_db)

        test_queries = [
            ("Row count", 'SELECT COUNT(*) FROM bindings'),
            ("UniProt targets", 'SELECT COUNT(DISTINCT "UniProt (SwissProt) Primary ID of Target Chain") FROM bindings'),
            ("Entries with Kd", 'SELECT COUNT(*) FROM bindings WHERE "Kd (nM)" IS NOT NULL'),
            ("Entries with Ki", 'SELECT COUNT(*) FROM bindings WHERE "Ki (nM)" IS NOT NULL'),
            ("Sample P00734 query", 'SELECT COUNT(*) FROM bindings WHERE "UniProt (SwissProt) Primary ID of Target Chain" = \'P00734\' LIMIT 10'),
        ]

        for test_name, query in test_queries:
            start = time.time()
            cursor = conn.execute(query)
            result = cursor.fetchone()[0]
            elapsed = (time.time() - start) * 1000  # Convert to ms

            print(f"   {test_name}: {result:,} ({elapsed:.1f} ms)")

        # Test indexed query performance
        print("\n   Testing indexed query performance...")
        query = '''
            SELECT "BindingDB MonomerID", "Ligand SMILES", "Kd (nM)", "Ki (nM)"
            FROM bindings 
            WHERE "UniProt (SwissProt) Primary ID of Target Chain" = 'P00734'
            AND "Kd (nM)" < 100
            LIMIT 10
        '''

        start = time.time()
        df = pd.read_sql_query(query, conn)
        elapsed = (time.time() - start) * 1000

        print(f"   Filtered query: {len(df)} rows returned ({elapsed:.1f} ms)")

        if len(df) > 0:
            print("\n   Sample results:")
            print(df.head())

        conn.close()

        print("\n✅ Database tests passed!")

    def cleanup(self, keep_tsv: bool = False, keep_zip: bool = False) -> None:
        """
        Clean up temporary files.

        Args:
            keep_tsv: Keep extracted TSV file
            keep_zip: Keep ZIP archive
        """
        print("\n🧹 Cleaning up temporary files...")

        if self.tsv_file and os.path.exists(self.tsv_file) and not keep_tsv:
            os.remove(self.tsv_file)
            print(f"   Removed: {self.tsv_file}")

        if self.zip_file and os.path.exists(self.zip_file) and not keep_zip:
            os.remove(self.zip_file)
            print(f"   Removed: {self.zip_file}")

        print("✓ Cleanup complete")


def main():
    """Main conversion workflow."""
    parser = argparse.ArgumentParser(
        description="Convert BindingDB TSV to optimized SQLite database"
    )
    parser.add_argument(
        '--output', '-o',
        default='bindingdb.db',
        help='Output SQLite database path (default: bindingdb.db)'
    )
    parser.add_argument(
        '--url', '-u',
        default=None,
        help='BindingDB TSV download URL (default: October 2025 snapshot). '
             'For monthly updates, use: https://www.bindingdb.org/rwd/bind/downloads/BindingDB_All_YYYYMM_tsv.zip'
    )
    parser.add_argument(
        '--input', '-i',
        default=None,
        help='Path to a pre-downloaded BindingDB ZIP file; if provided the script will skip downloading.'
    )
    parser.add_argument(
        '--chunksize', '-c',
        type=int,
        default=100000,
        help='Number of rows to process at once (default: 100000)'
    )
    parser.add_argument(
        '--page-size', '-p',
        type=int,
        default=1024,
        choices=[1024, 2048, 4096, 8192, 16384, 32768],
        help='SQLite page size in bytes (default: 1024 for ~30%% space savings)'
    )
    parser.add_argument(
        '--sample-rate',
        type=float,
        default=None,
        help='Optional sampling fraction between 0 and 1 (e.g. 0.2 for 20%% of rows). '
             'When set, import a random sample of rows for faster testing.'
    )
    parser.add_argument(
        '--sample-seed',
        type=int,
        default=None,
        help='Optional random seed for reproducible sampling when --sample-rate is set.'
    )
    parser.add_argument(
        '--delete-tsv',
        action='store_true',
        help='Delete extracted TSV file after conversion (default: keep)'
    )
    parser.add_argument(
        '--delete-zip',
        action='store_true',
        help='Delete ZIP archive after conversion (default: keep)'
    )
    parser.add_argument(
        '--force-download',
        action='store_true',
        help='Force re-download even if ZIP exists'
    )
    parser.add_argument(
        '--skip-test',
        action='store_true',
        help='Skip database testing after conversion'
    )
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("BindingDB TSV to SQLite Converter")
    print("=" * 60)
    
    converter = BindingDBConverter(
        output_db=args.output,
        tsv_url=args.url,
        )
    # Attach optional sampling parameters for use during conversion
    converter.sample_rate = args.sample_rate
    converter.sample_seed = args.sample_seed

    # If an input zip is provided, prefer it and skip the download step
    if args.input:
        if not os.path.exists(args.input):
            print(f"ERROR: Provided input file does not exist: {args.input}")
            sys.exit(1)
        converter.zip_file = args.input
    
    try:
        # Step 1: Download (skipped if converter.zip_file already set via --input)
        if not converter.zip_file:
            converter.download_tsv(force=args.force_download)
        
        # Step 2: Extract
        converter.extract_tsv()
        
        # Step 3: Convert
        converter.convert_to_sqlite(chunksize=args.chunksize, page_size=args.page_size)
        
        # Step 4: Test
        if not args.skip_test:
            converter.test_queries()
        
        # Step 5: Cleanup
        converter.cleanup(keep_tsv=not args.delete_tsv, keep_zip=not args.delete_zip)
        
        print("\n" + "=" * 60)
        print("🎉 SUCCESS!")
        print("=" * 60)
        print(f"SQLite database ready: {args.output}")
        print("You can now use this database in your BindingDB agent.")
        print("=" * 60)
        
    except KeyboardInterrupt:
        print("\n\n⚠️  Conversion interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n✗ Conversion failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
