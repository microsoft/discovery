"""
BindingDB Utilities Module

A utility module for accessing the BindingDB SQLite database,
providing comprehensive binding affinity data retrieval and analysis.

BindingDB specializes in:
- Detailed binding affinity measurements (Kd, Ki, IC50, EC50)
- Protein-ligand interaction data with 640 fields
- Kinetic parameters (kon, koff)
- Experimental conditions (pH, temperature)
- High-quality curated binding constants

This module provides SQLite database access with:
- Comprehensive binding data retrieval by UniProt ID
- Compound searches by name or SMILES
- Kinetic data analysis
- Database statistics

Available Functions:
- get_binding_data_by_uniprot_sqlite(): Retrieve comprehensive binding data
- search_by_compound_sqlite(): Search by compound name
- search_ligands_by_smiles_sqlite(): Find targets for specific SMILES
- get_kinetic_data_sqlite(): Get entries with kinetic parameters
- get_sqlite_database_stats(): Database statistics
"""

import json
import os
import sqlite3
from typing import List, Dict, Optional, Any


class BindingDBUtils:
    """
    Utility class for BindingDB SQLite database operations.
    
    BindingDB focuses on binding affinity data, providing detailed measurements
    with complete experimental context including kinetic parameters and conditions.
    
    Database provides 640 fields including:
    - Binding affinities (Kd, Ki, IC50, EC50)
    - Kinetic parameters (kon, koff)
    - Experimental conditions (pH, temperature)
    - Cross-references (PubChem, ChEBI, ChEMBL, DrugBank, KEGG, ZINC)
    - PDB structure IDs
    - Complete publication metadata
    """
    
    def __init__(self, sqlite_db_path: Optional[str] = None):
        """
        Initialize BindingDBUtils with SQLite database.
        
        Args:
            sqlite_db_path: Path to SQLite database file (default: /app/bindingdb.db or BINDINGDB_DATABASE env var)
        """
        import urllib.request
        # Get database location from env or default
        db_env = os.environ.get('BINDINGDB_DATABASE', '/app/bindingdb.db')
        # If it's a URL, download to /app/bindingdb.db if not present
        if db_env.startswith('http://') or db_env.startswith('https://'):
            local_path = '/app/bindingdb.db'
            if not os.path.exists(local_path):
                print(f"Downloading BindingDB database from {db_env}...")
                try:
                    urllib.request.urlretrieve(db_env, local_path)
                    print("✓ Download complete.")
                except Exception as e:
                    print(f"✗ Failed to download database: {e}")
            self.sqlite_db_path = local_path
        else:
            self.sqlite_db_path = db_env
        if sqlite_db_path is not None:
            self.sqlite_db_path = sqlite_db_path
        self.sqlite_conn = None
    
    @staticmethod
    def _safe_float(value: Any) -> Optional[float]:
        """
        Safely convert a value to float, returning None if conversion fails.
        
        Args:
            value: Value to convert
            
        Returns:
            Float value or None if conversion fails
        """
        if value is None or value == '':
            return None
        try:
            return float(value)
        except (ValueError, TypeError):
            return None
    
    @staticmethod
    def _safe_int(value: Any) -> Optional[int]:
        """
        Safely convert a value to int, returning None if conversion fails.
        
        Args:
            value: Value to convert
            
        Returns:
            Integer value or None if conversion fails
        """
        if value is None or value == '':
            return None
        try:
            return int(float(value))  # Convert through float to handle "3.0" -> 3
        except (ValueError, TypeError):
            return None
    
    @staticmethod
    def _parse_affinity(value: Any) -> tuple[Optional[float], Optional[str], Optional[str]]:
        """
        Parse affinity value, extracting numeric value and qualifier.
        
        Handles inequality symbols (>, <) commonly found in binding affinity data
        where measurements are beyond detection limits.
        
        Args:
            value: Affinity value (may contain '>' or '<' symbols)
            
        Returns:
            Tuple of (numeric_value, raw_string, qualifier)
            - numeric_value: Float for calculations (None if invalid)
            - raw_string: Original string value (None if empty)
            - qualifier: 'exact', 'greater_than', 'less_than', or None
            
        Examples:
            '<1' -> (1.0, '<1', 'less_than')
            '>10000' -> (10000.0, '>10000', 'greater_than')
            '5.2' -> (5.2, '5.2', 'exact')
        """
        if value is None or value == '':
            return None, None, None
        
        try:
            raw_str = str(value).strip()
            qualifier = 'exact'
            clean_val = raw_str
            
            # Check for inequality symbols
            if raw_str.startswith('>'):
                qualifier = 'greater_than'
                clean_val = raw_str[1:].strip()
            elif raw_str.startswith('<'):
                qualifier = 'less_than'
                clean_val = raw_str[1:].strip()
            
            # Convert to float
            numeric_val = float(clean_val) if clean_val else None
            return numeric_val, raw_str, qualifier
            
        except (ValueError, TypeError):
            return None, str(value) if value else None, None
    
    @staticmethod
    def _clean_sqlite_result(result: Dict[str, Any]) -> Dict[str, Any]:
        """
        Clean SQLite result by converting numeric fields to proper Python types.
        
        For affinity measurements (Kd, Ki, IC50, EC50):
        - Creates three fields for each measurement:
          * '[Measurement] (nM)': Numeric value for calculations
          * '[Measurement] (nM) Raw': Original string with qualifiers (>, <)
          * '[Measurement] (nM) Qualifier': 'exact', 'greater_than', or 'less_than'
        
        This preserves scientific meaning while enabling numeric operations.
        
        Examples:
            Ki='<1' becomes:
            - 'Ki (nM)': 1.0
            - 'Ki (nM) Raw': '<1'
            - 'Ki (nM) Qualifier': 'less_than'
        
        Args:
            result: Raw SQLite result dictionary
            
        Returns:
            Cleaned result with proper Python types and qualifier fields
        """
        # Define fields that should be parsed as affinities (handle > and <)
        affinity_fields = ['Kd (nM)', 'Ki (nM)', 'IC50 (nM)', 'EC50 (nM)']
        
        # Define fields that should be floats
        float_fields = ['kon (M-1-s-1)', 'koff (s-1)', 'pH', 'Temp (C)', 
                       'ΔG', 'ΔH', 'ΔS', '-TΔS']
        
        # Define fields that should be integers
        int_fields = ['Number of Protein Chains in Target (>1 implies a multichain complex)']
        
        cleaned = result.copy()
        
        # Parse affinity values (preserve qualifiers)
        for field in affinity_fields:
            if field in cleaned:
                numeric_val, raw_str, qualifier = BindingDBUtils._parse_affinity(cleaned[field])
                cleaned[field] = numeric_val  # Numeric for calculations
                cleaned[f'{field} Raw'] = raw_str  # Original with symbols
                cleaned[f'{field} Qualifier'] = qualifier  # exact/greater_than/less_than
        
        # Convert float fields
        for field in float_fields:
            if field in cleaned:
                cleaned[field] = BindingDBUtils._safe_float(cleaned[field])
        
        # Convert integer fields
        for field in int_fields:
            if field in cleaned:
                cleaned[field] = BindingDBUtils._safe_int(cleaned[field])
        
        return cleaned
    
    @staticmethod
    def safe_json_serialize(obj: Any) -> Any:
        """
        Convert Python objects to JSON-safe equivalents.
        
        Handles common issues with pandas DataFrames and numpy types:
        - NaN/inf values are converted to None
        - numpy types are converted to native Python types
        
        Args:
            obj: Object to convert
            
        Returns:
            JSON-safe version of the object
        """
        import math
        
        # Handle NaN and infinity
        if isinstance(obj, float):
            if math.isnan(obj) or math.isinf(obj):
                return None
            return obj
        
        # Handle lists
        if isinstance(obj, list):
            return [BindingDBUtils.safe_json_serialize(item) for item in obj]
        
        # Handle dictionaries
        if isinstance(obj, dict):
            return {key: BindingDBUtils.safe_json_serialize(value) for key, value in obj.items()}
        
        # Handle numpy types (if numpy is available)
        try:
            import numpy as np
            if isinstance(obj, (np.integer, np.floating)):
                if np.isnan(obj) or np.isinf(obj):
                    return None
                return obj.item()
            if isinstance(obj, np.ndarray):
                return BindingDBUtils.safe_json_serialize(obj.tolist())
        except ImportError:
            pass
        
        return obj
    
    def save_json(self, data: Any, filepath: str, indent: int = 2) -> None:
        """
        Save data to JSON file with safe serialization.
        
        Args:
            data: Data to save
            filepath: Path to save the JSON file
            indent: Indentation level for pretty printing
        """
        safe_data = self.safe_json_serialize(data)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(safe_data, f, indent=indent)
    
    # ========================================================================
    # SQLite Database Methods
    # ========================================================================
    
    def _connect_sqlite(self) -> Optional[sqlite3.Connection]:
        """
        Connect to SQLite database if path is configured.
        
        Returns:
            sqlite3 connection or None if database not available
        """
        if self.sqlite_conn is not None:
            return self.sqlite_conn
        
        if self.sqlite_db_path and os.path.exists(self.sqlite_db_path):
            self.sqlite_conn = sqlite3.connect(self.sqlite_db_path)
            return self.sqlite_conn
        
        print(f"✗ SQLite database not found at: {self.sqlite_db_path}")
        return None
    
    def get_binding_data_by_uniprot_sqlite(self, uniprot_id: str, limit: Optional[int] = 100) -> List[Dict[str, Any]]:
        """
        Retrieve comprehensive binding data from local SQLite database.
        
        Provides complete data with 640 fields including:
        - Experimental conditions (pH, temperature)
        - Kinetic parameters (kon, koff)
        - Complete cross-references (PubChem, ChEBI, ChEMBL, DrugBank, KEGG, ZINC)
        - PDB structure IDs
        - Full publication metadata (authors, institutions, dates)
        
        Args:
            uniprot_id: UniProt accession ID
            limit: Maximum number of results (None for all results)
            
        Returns:
            List of comprehensive binding data dictionaries
        """
        conn = self._connect_sqlite()
        if conn is None:
            print("✗ SQLite database not available")
            return []
        
        try:
            cursor = conn.cursor()
            
            # Build query with optional LIMIT clause
            if limit is None:
                query = """
                    SELECT * FROM bindings 
                    WHERE "UniProt (SwissProt) Primary ID of Target Chain 1" = ?
                """
                cursor.execute(query, (uniprot_id,))
            else:
                query = """
                    SELECT * FROM bindings 
                    WHERE "UniProt (SwissProt) Primary ID of Target Chain 1" = ? 
                    LIMIT ?
                """
                cursor.execute(query, (uniprot_id, limit))
            
            columns = [desc[0] for desc in cursor.description]
            rows = cursor.fetchall()
            
            if not rows:
                print(f"✓ Found 0 binding measurements for {uniprot_id} (SQLite)")
                return []
            
            results = []
            for row in rows:
                result = dict(zip(columns, row))
                # Clean and convert numeric fields
                result = self._clean_sqlite_result(result)
                results.append(result)
            
            print(f"✓ Found {len(results)} binding measurements for {uniprot_id} (SQLite)")
            return results
            
        except Exception as e:
            print(f"✗ SQLite query error: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    def search_by_compound_sqlite(self, compound_name: str, limit: Optional[int] = 100) -> List[Dict[str, Any]]:
        """
        Search for binding data by compound/ligand name in SQLite database.
        
        Args:
            compound_name: Compound or ligand name to search
            limit: Maximum number of results (None for all results)
            
        Returns:
            List of binding data dictionaries
        """
        conn = self._connect_sqlite()
        if conn is None:
            print("✗ SQLite database not available")
            return []
        
        try:
            cursor = conn.cursor()
            
            if limit is None:
                query = """
                    SELECT * FROM bindings 
                    WHERE "BindingDB Ligand Name" LIKE ?
                """
                cursor.execute(query, (f'%{compound_name}%',))
            else:
                query = """
                    SELECT * FROM bindings 
                    WHERE "BindingDB Ligand Name" LIKE ? 
                    LIMIT ?
                """
                cursor.execute(query, (f'%{compound_name}%', limit))
            
            columns = [desc[0] for desc in cursor.description]
            rows = cursor.fetchall()
            
            results = []
            for row in rows:
                result = dict(zip(columns, row))
                # Clean and convert numeric fields
                result = self._clean_sqlite_result(result)
                results.append(result)
            
            print(f"✓ Found {len(results)} entries for compound '{compound_name}' (SQLite)")
            return results
            
        except Exception as e:
            print(f"✗ SQLite search error: {e}")
            return []
    
    def get_kinetic_data_sqlite(self, uniprot_id: str, limit: Optional[int] = 100) -> List[Dict[str, Any]]:
        """
        Get binding data with kinetic parameters (kon, koff) from SQLite database.
        
        Filters for entries that have kon (association rate) or koff (dissociation rate) measurements.
        
        Args:
            uniprot_id: UniProt accession ID
            limit: Maximum number of results (None for all results)
            
        Returns:
            List of entries with kinetic data
        """
        conn = self._connect_sqlite()
        if conn is None:
            print("✗ SQLite database not available")
            return []
        
        try:
            cursor = conn.cursor()
            
            if limit is None:
                query = """
                    SELECT * FROM bindings 
                    WHERE "UniProt (SwissProt) Primary ID of Target Chain 1" = ? 
                      AND ("kon (M-1-s-1)" IS NOT NULL OR "koff (s-1)" IS NOT NULL)
                """
                cursor.execute(query, (uniprot_id,))
            else:
                query = """
                    SELECT * FROM bindings 
                    WHERE "UniProt (SwissProt) Primary ID of Target Chain 1" = ? 
                      AND ("kon (M-1-s-1)" IS NOT NULL OR "koff (s-1)" IS NOT NULL)
                    LIMIT ?
                """
                cursor.execute(query, (uniprot_id, limit))
            
            columns = [desc[0] for desc in cursor.description]
            rows = cursor.fetchall()
            
            results = []
            for row in rows:
                result = dict(zip(columns, row))
                # Clean and convert numeric fields
                result = self._clean_sqlite_result(result)
                results.append(result)
            
            print(f"✓ Found {len(results)} entries with kinetic data for {uniprot_id}")
            return results
            
        except Exception as e:
            print(f"✗ SQLite query error: {e}")
            return []
    
    def search_ligands_by_smiles_sqlite(self, smiles: str, limit: Optional[int] = 100) -> List[Dict[str, Any]]:
        """
        Search for protein targets that bind to a specific ligand SMILES in SQLite database.
        
        Performs exact SMILES matching to find all protein targets that have binding data
        for the specified compound. Much faster than similarity search and includes
        complete experimental data (640 fields).
        
        Note: This performs EXACT SMILES matching, not chemical similarity search.
        
        Args:
            smiles: SMILES string for the ligand
            limit: Maximum number of results (None for all results)
            
        Returns:
            List of binding data dictionaries, each containing target and affinity information
        """
        conn = self._connect_sqlite()
        if conn is None:
            print("✗ SQLite database not available")
            return []
        
        print(f"📊 Searching SQLite database for SMILES: {smiles[:50]}...")
        
        try:
            cursor = conn.cursor()
            
            if limit is None:
                query = """
                    SELECT * FROM bindings 
                    WHERE `Ligand SMILES` = ?
                """
                cursor.execute(query, (smiles,))
            else:
                query = """
                    SELECT * FROM bindings 
                    WHERE `Ligand SMILES` = ?
                    LIMIT ?
                """
                cursor.execute(query, (smiles, limit))
            
            columns = [desc[0] for desc in cursor.description]
            rows = cursor.fetchall()
            
            if not rows:
                print(f"✓ No targets found for SMILES (exact match)")
                return []
            
            # Convert to standardized format
            results = []
            for row in rows:
                result = dict(zip(columns, row))
                # Clean and convert numeric fields
                result = self._clean_sqlite_result(result)
                results.append(result)
            
            # Count unique targets
            unique_targets = len(set(r.get('UniProt (SwissProt) Primary ID of Target Chain 1') 
                                    for r in results 
                                    if r.get('UniProt (SwissProt) Primary ID of Target Chain 1')))
            
            print(f"✓ Found {len(results)} binding measurement(s) for compound across {unique_targets} target(s)")
            return results
            
        except Exception as e:
            print(f"✗ SQLite query error: {e}")
            return []
    
    def get_sqlite_database_stats(self) -> Dict[str, Any]:
        """
        Get statistics about the SQLite database.
        
        Returns:
            Dictionary with database statistics
        """
        conn = self._connect_sqlite()
        if conn is None:
            return {'error': 'SQLite database not available'}
        
        try:
            cursor = conn.cursor()
            
            # Total entries
            cursor.execute("SELECT COUNT(*) FROM bindings")
            total_entries = cursor.fetchone()[0]
            
            # Unique proteins (SwissProt)
            cursor.execute('SELECT COUNT(DISTINCT "UniProt (SwissProt) Primary ID of Target Chain 1") FROM bindings WHERE "UniProt (SwissProt) Primary ID of Target Chain 1" IS NOT NULL')
            unique_proteins = cursor.fetchone()[0]
            
            # Unique ligands
            cursor.execute('SELECT COUNT(DISTINCT "BindingDB Ligand Name") FROM bindings WHERE "BindingDB Ligand Name" IS NOT NULL')
            unique_ligands = cursor.fetchone()[0]
            
            # Entries with Kd
            cursor.execute('SELECT COUNT(*) FROM bindings WHERE "Kd (nM)" IS NOT NULL AND "Kd (nM)" != ""')
            kd_count = cursor.fetchone()[0]
            
            # Entries with Ki
            cursor.execute('SELECT COUNT(*) FROM bindings WHERE "Ki (nM)" IS NOT NULL AND "Ki (nM)" != ""')
            ki_count = cursor.fetchone()[0]
            
            # Entries with IC50
            cursor.execute('SELECT COUNT(*) FROM bindings WHERE "IC50 (nM)" IS NOT NULL AND "IC50 (nM)" != ""')
            ic50_count = cursor.fetchone()[0]
            
            # Entries with kinetic data
            cursor.execute("""
                SELECT COUNT(*) FROM bindings 
                WHERE "kon (M-1-s-1)" IS NOT NULL OR "koff (s-1)" IS NOT NULL
            """)
            kinetic_count = cursor.fetchone()[0]
            
            # Entries with PDB IDs
            cursor.execute("""
                SELECT COUNT(*) FROM bindings 
                WHERE "PDB ID(s) for Ligand-Target Complex" IS NOT NULL 
                AND "PDB ID(s) for Ligand-Target Complex" != ""
            """)
            pdb_count = cursor.fetchone()[0]
            
            return {
                'total_entries': total_entries,
                'unique_proteins': unique_proteins,
                'unique_ligands': unique_ligands,
                'entries_with_kd': kd_count,
                'entries_with_ki': ki_count,
                'entries_with_ic50': ic50_count,
                'entries_with_kinetics': kinetic_count,
                'entries_with_pdb_structures': pdb_count
            }
            
        except Exception as e:
            return {'error': str(e)}


# ============================================================================
# Standalone SQLite Functions (for convenience)
# ============================================================================

def get_binding_data_by_uniprot_sqlite(uniprot_id: str, limit: Optional[int] = 100, 
                                      db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Retrieve comprehensive binding data from local SQLite database.
    
    Convenience function that creates a BindingDBUtils instance and retrieves data.
    
    Args:
        uniprot_id: UniProt accession ID
        limit: Maximum number of results (None for all results, default: 100)
        db_path: Path to SQLite database (default: $BINDINGDB_DATABASE env var or /app/bindingdb.db)
        
    Returns:
        List of comprehensive binding data dictionaries
    """
    utils = BindingDBUtils(sqlite_db_path=db_path)
    return utils.get_binding_data_by_uniprot_sqlite(uniprot_id, limit)


def search_by_compound_sqlite(compound_name: str, limit: Optional[int] = 100,
                              db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Search for binding data by compound name.
    
    Convenience function that creates a BindingDBUtils instance and searches.
    
    Args:
        compound_name: Compound or ligand name to search
        limit: Maximum number of results (None for all results, default: 100)
        db_path: Path to SQLite database (default: $BINDINGDB_DATABASE env var or /app/bindingdb.db)
        
    Returns:
        List of binding data dictionaries
    """
    utils = BindingDBUtils(sqlite_db_path=db_path)
    return utils.search_by_compound_sqlite(compound_name, limit)


def search_ligands_by_smiles_sqlite(smiles: str, limit: Optional[int] = 100,
                                   db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Search for targets by exact SMILES match.
    
    Convenience function that creates a BindingDBUtils instance and searches.
    
    Args:
        smiles: SMILES string for the ligand
        limit: Maximum number of results (None for all results, default: 100)
        db_path: Path to SQLite database (default: $BINDINGDB_DATABASE env var or /app/bindingdb.db)
        
    Returns:
        List of binding data dictionaries
    """
    utils = BindingDBUtils(sqlite_db_path=db_path)
    return utils.search_ligands_by_smiles_sqlite(smiles, limit)


def get_kinetic_data_sqlite(uniprot_id: str, limit: Optional[int] = 100,
                           db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Get entries with kinetic parameters (kon, koff).
    
    Convenience function that creates a BindingDBUtils instance and retrieves kinetic data.
    
    Args:
        uniprot_id: UniProt accession ID
        limit: Maximum number of results (None for all results, default: 100)
        db_path: Path to SQLite database (default: $BINDINGDB_DATABASE env var or /app/bindingdb.db)
        
    Returns:
        List of entries with kinetic data
    """
    utils = BindingDBUtils(sqlite_db_path=db_path)
    return utils.get_kinetic_data_sqlite(uniprot_id, limit)


def get_sqlite_database_stats(db_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Get statistics about the SQLite database.
    
    Convenience function that creates a BindingDBUtils instance and retrieves stats.
    
    Args:
        db_path: Path to SQLite database (default: $BINDINGDB_DATABASE env var or /app/bindingdb.db)
        
    Returns:
        Dictionary with database statistics
    """
    utils = BindingDBUtils(sqlite_db_path=db_path)
    return utils.get_sqlite_database_stats()
