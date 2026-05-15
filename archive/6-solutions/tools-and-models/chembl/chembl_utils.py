"""
ChEMBL Utilities Module

A comprehensive utility module for accessing the ChEMBL database,
providing enhanced functionality for compound, target, and bioactivity data retrieval.

This module provides high-level functions for:
- Compound searches and property retrieval
- Target information and structure queries
- Bioactivity data extraction
- Cross-referencing with PDB structures
- Ligand and binding site analysis
"""

import json
import os
import re
import time
import requests
from typing import List, Dict, Optional, Any
from concurrent.futures import ThreadPoolExecutor, as_completed


class ChEMBLUtils:
    """
    Utility class for ChEMBL database operations with enhanced functionality.
    """
    
    def __init__(self, base_url: str = "https://www.ebi.ac.uk/chembl/api/data", max_workers: int = 10):
        """
        Initialize ChEMBLUtils with API configuration.
        
        Args:
            base_url: Base URL for ChEMBL API (default: official ChEMBL API)
            max_workers: Maximum number of parallel workers for concurrent requests (default: 10)
        """
        self.base_url = base_url.rstrip('/')
        self.session = requests.Session()
        self.session.headers.update({
            'Accept': 'application/json',
            'User-Agent': 'ChEMBL-Utils/1.0'
        })
        self.default_page_size = 200
        self.max_workers = max_workers

    def _build_url(self, endpoint: str) -> str:
        """Construct a fully-qualified URL for the given endpoint."""
        # Handle absolute URLs
        if endpoint.startswith("http://") or endpoint.startswith("https://"):
            return endpoint
        
        # Handle relative paths from API pagination (e.g., "/chembl/api/data/activity.json?...")
        if endpoint.startswith("/chembl/api/data/"):
            # Extract just the scheme and host from base_url
            from urllib.parse import urlparse
            parsed = urlparse(self.base_url)
            return f"{parsed.scheme}://{parsed.netloc}{endpoint}"
        
        # Handle regular endpoints
        endpoint = endpoint.lstrip('/')
        if endpoint.endswith('.json'):
            return f"{self.base_url}/{endpoint}"
        return f"{self.base_url}/{endpoint}.json"
    
    def _make_request(self, endpoint: str, params: Optional[Dict] = None) -> Dict[str, Any]:
        """
        Make a request to the ChEMBL API with error handling.
        
        Args:
            endpoint: API endpoint (e.g., 'molecule', 'target')
            params: Query parameters
            
        Returns:
            JSON response as dictionary
        """
        url = self._build_url(endpoint)
        
        try:
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"Error making request to {url}: {str(e)}")
            return {"error": str(e), "molecules": [], "targets": [], "activities": []}

    def _fetch_paginated(self, endpoint: str, params: Optional[Dict[str, Any]], result_key: str,
                          limit: Optional[int] = None):
        """
        Fetch paginated results for endpoints that return page_meta metadata.
        
        Returns:
            Tuple of (results_list, total_count) where total_count is the total available results
        """
        collected: List[Dict[str, Any]] = []
        next_endpoint: Optional[str] = None
        base_params = dict(params or {})
        total_count: Optional[int] = None

        while True:
            if limit is not None and len(collected) >= limit:
                break

            if next_endpoint:
                request_params = None
                current_endpoint = next_endpoint
            else:
                request_params = base_params.copy()
                current_endpoint = endpoint

            if request_params is not None:
                remaining = None if limit is None else max(limit - len(collected), 0)
                if remaining == 0:
                    break
                page_size = self.default_page_size if remaining is None else min(self.default_page_size, remaining)
                # Respect explicit limit set by caller if provided
                if 'limit' not in request_params:
                    request_params['limit'] = page_size
                else:
                    request_params['limit'] = min(request_params['limit'], page_size) if remaining is not None else request_params['limit']
            else:
                request_params = None

            response = self._make_request(current_endpoint, request_params)
            if 'error' in response and not response.get(result_key):
                break

            # Capture total_count from first response
            if total_count is None:
                page_meta = response.get('page_meta', {})
                total_count = page_meta.get('total_count')

            batch = response.get(result_key, [])
            collected.extend(batch)

            if limit is not None and len(collected) >= limit:
                collected = collected[:limit]
                break

            next_endpoint = response.get('page_meta', {}).get('next')
            if not next_endpoint:
                break

        return collected, total_count

    @staticmethod
    def _looks_like_chembl_id(value: str) -> bool:
        """Determine whether the input looks like a ChEMBL identifier."""
        return bool(re.fullmatch(r"CHEMBL\d+", value.strip().upper()))

    @staticmethod
    def _looks_like_smiles(value: str) -> bool:
        """Simple heuristic to decide whether a string resembles a SMILES."""
        if not value or ' ' in value.strip():
            return False
        smiles_chars = set("[]=#@()+-/\\")
        return any(char in smiles_chars for char in value)
    
    @staticmethod
    def _safe_float(value: Any) -> Optional[float]:
        """
        Safely convert a value to float, returning None if conversion fails.
        
        Args:
            value: Value to convert (string, number, or None)
            
        Returns:
            Float value or None if conversion fails
        """
        if value is None:
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
            value: Value to convert (string, number, or None)
            
        Returns:
            Integer value or None if conversion fails
        """
        if value is None:
            return None
        try:
            return int(float(value))  # Convert through float to handle "3.0" -> 3
        except (ValueError, TypeError):
            return None
    
    @staticmethod
    def safe_json_serialize(obj: Any, max_depth: int = 100) -> Any:
        """
        Convert Python objects to JSON-safe equivalents with depth limiting.
        
        This handles common issues with pandas DataFrames and numpy types:
        - NaN/inf values are converted to None
        - numpy types are converted to native Python types
        - Limits recursion depth to prevent stack overflow on large nested structures
        
        Args:
            obj: Object to convert
            max_depth: Maximum recursion depth (default: 100)
            
        Returns:
            JSON-safe version of the object
            
        Example:
            df_dict = df.to_dict(orient='records')
            safe_dict = ChEMBLUtils.safe_json_serialize(df_dict)
            json.dump(safe_dict, f, indent=2)
        """
        import math
        
        def _serialize(obj: Any, depth: int = 0) -> Any:
            # Check depth limit to prevent stack overflow
            if depth > max_depth:
                return str(obj)  # Convert to string if too deep
            
            # Handle None
            if obj is None:
                return None
            
            # Handle NaN and infinity for floats
            if isinstance(obj, float):
                if math.isnan(obj) or math.isinf(obj):
                    return None
                return obj
            
            # Handle numpy types (if numpy is available)
            try:
                import numpy as np
                if isinstance(obj, (np.integer, np.floating)):
                    if np.isnan(obj) or np.isinf(obj):
                        return None
                    return obj.item()  # Convert to native Python type
                if isinstance(obj, np.ndarray):
                    return _serialize(obj.tolist(), depth + 1)
            except ImportError:
                pass
            
            # Handle lists (process items incrementally to save memory)
            if isinstance(obj, list):
                return [_serialize(item, depth + 1) for item in obj]
            
            # Handle dictionaries
            if isinstance(obj, dict):
                return {key: _serialize(value, depth + 1) for key, value in obj.items()}
            
            # Return as-is for all other types (str, int, bool, etc.)
            return obj
        
        return _serialize(obj)
    
    def save_json(self, data: Any, filepath: str, indent: int = 2, chunk_size: Optional[int] = None) -> None:
        """
        Save data to JSON file with safe serialization and optional chunking for large datasets.
        
        Automatically handles NaN values and numpy types from pandas DataFrames.
        For very large datasets, use chunk_size to split data into multiple files.
        
        Args:
            data: Data to save (dict, list, or any JSON-serializable object)
            filepath: Path to save the JSON file
            indent: Indentation level for pretty printing
            chunk_size: If provided and data is a list, split into chunks of this size
                       and save as separate files (filename_1.json, filename_2.json, etc.)
            
        Example:
            # Normal usage
            utils.save_json(results, '/output/results.json')
            
            # Large dataset - split into chunks of 1000 items each
            utils.save_json(large_bioactivities, '/output/bioactivities.json', chunk_size=1000)
            # Creates: bioactivities_1.json, bioactivities_2.json, etc.
        """
        # Handle chunking for large lists
        if chunk_size and isinstance(data, list) and len(data) > chunk_size:
            print(f"Chunking {len(data)} items into files of {chunk_size} items each...")
            
            # Split filename and extension
            base_path = filepath.rsplit('.', 1)[0]
            extension = filepath.rsplit('.', 1)[1] if '.' in filepath else 'json'
            
            # Save each chunk
            num_chunks = (len(data) + chunk_size - 1) // chunk_size  # Ceiling division
            for i in range(num_chunks):
                start_idx = i * chunk_size
                end_idx = min((i + 1) * chunk_size, len(data))
                chunk = data[start_idx:end_idx]
                
                chunk_filepath = f"{base_path}_{i+1}.{extension}"
                safe_chunk = self.safe_json_serialize(chunk)
                
                with open(chunk_filepath, 'w', encoding='utf-8') as f:
                    json.dump(safe_chunk, f, indent=indent)
                
                print(f"  Saved chunk {i+1}/{num_chunks} ({len(chunk)} items) to {os.path.basename(chunk_filepath)}")
            
            print(f"✓ Saved {len(data)} total items across {num_chunks} files")
            return
        
        # Normal save for non-chunked data
        try:
            safe_data = self.safe_json_serialize(data)
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(safe_data, f, indent=indent)
        except (MemoryError, RecursionError) as e:
            # Fallback: try saving with minimal formatting
            print(f"Warning: Memory/recursion issue saving JSON, retrying with compact format...")
            try:
                safe_data = self.safe_json_serialize(data)
                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump(safe_data, f, indent=None, separators=(',', ':'))
                print(f"✓ Saved successfully with compact format")
            except Exception as e2:
                print(f"Error: Failed to save JSON even with compact format: {str(e2)}")
                print(f"Suggestion: Use chunk_size parameter to split large datasets")
                raise
    
    def enrich_bioactivities_with_compound_info(
        self, 
        bioactivities: List[Dict[str, Any]], 
        max_compounds: Optional[int] = None,
        rate_limit_delay: float = 0.1,
        parallel: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Enrich bioactivity data with compound information incrementally.
        
        This is a memory-efficient alternative to fetching all compounds, creating DataFrames,
        and performing pandas merges. Each bioactivity is enriched on-the-fly with only
        essential compound properties.
        
        Args:
            bioactivities: List of bioactivity dictionaries
            max_compounds: Maximum number of unique compounds to fetch (None = no limit)
            rate_limit_delay: Seconds to wait between API calls (default: 0.1, ignored if parallel=True)
            parallel: Use parallel fetching for faster retrieval (default: True)
        
        Returns:
            List of enriched bioactivity dictionaries with compound properties added
            
        Example:
            # Get bioactivities for a target
            bioactivities, total = utils.get_bioactivities_for_target("CHEMBL203", limit=500)
            
            # Enrich with compound info (parallel, memory-efficient)
            enriched = utils.enrich_bioactivities_with_compound_info(
                bioactivities, 
                max_compounds=50,  # Limit API calls
                parallel=True  # Use parallel fetching
            )
            
            # Save enriched data
            utils.save_json(enriched, '/output/enriched_bioactivities.json')
        """
        if parallel:
            return self._enrich_bioactivities_parallel(bioactivities, max_compounds)
        else:
            return self._enrich_bioactivities_sequential(bioactivities, max_compounds, rate_limit_delay)
    
    def _enrich_bioactivities_parallel(
        self, 
        bioactivities: List[Dict[str, Any]], 
        max_compounds: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Parallel implementation of bioactivity enrichment.
        """
        # Extract unique compound IDs
        unique_compound_ids = []
        seen = set()
        for bioactivity in bioactivities:
            molecule_id = bioactivity.get('molecule_chembl_id')
            if molecule_id and molecule_id not in seen:
                unique_compound_ids.append(molecule_id)
                seen.add(molecule_id)
                if max_compounds and len(unique_compound_ids) >= max_compounds:
                    break
        
        print(f"Enriching {len(bioactivities)} bioactivities with compound information...")
        print(f"Fetching {len(unique_compound_ids)} unique compounds in parallel (max_workers={self.max_workers})...")
        
        # Fetch compounds in parallel
        compound_cache = {}
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_id = {
                executor.submit(self.get_compound_by_chembl_id, chembl_id=cid): cid 
                for cid in unique_compound_ids
            }
            
            completed = 0
            for future in as_completed(future_to_id):
                compound_id = future_to_id[future]
                try:
                    compound_info = future.result()
                    if 'error' not in compound_info:
                        compound_cache[compound_id] = compound_info
                    else:
                        compound_cache[compound_id] = None
                except Exception as e:
                    print(f"  Warning: Error fetching compound {compound_id}: {str(e)}")
                    compound_cache[compound_id] = None
                
                completed += 1
                if completed % 10 == 0:
                    print(f"  Fetched {completed}/{len(unique_compound_ids)} compounds...")
        
        print(f"✓ Fetched {len([v for v in compound_cache.values() if v])} compounds successfully")
        
        # Enrich bioactivities with cached compound data
        enriched_bioactivities = []
        for bioactivity in bioactivities:
            enriched = bioactivity.copy()
            molecule_id = bioactivity.get('molecule_chembl_id')
            
            if molecule_id and molecule_id in compound_cache:
                compound_info = compound_cache[molecule_id]
                if compound_info:
                    enriched['compound_name'] = compound_info.get('pref_name')
                    enriched['compound_smiles'] = compound_info.get('smiles')
                    enriched['compound_max_phase'] = compound_info.get('max_phase')
                    enriched['compound_molecular_weight'] = compound_info.get('molecular_weight')
                    enriched['compound_alogp'] = compound_info.get('alogp')
                    enriched['compound_psa'] = compound_info.get('psa')
                    enriched['compound_hba'] = compound_info.get('hba')
                    enriched['compound_hbd'] = compound_info.get('hbd')
            
            enriched_bioactivities.append(enriched)
        
        print(f"✓ Enriched {len(enriched_bioactivities)} bioactivities")
        return enriched_bioactivities
    
    def _enrich_bioactivities_sequential(
        self, 
        bioactivities: List[Dict[str, Any]], 
        max_compounds: Optional[int] = None,
        rate_limit_delay: float = 0.1
    ) -> List[Dict[str, Any]]:
        """
        Sequential implementation of bioactivity enrichment (original implementation).
        """
        import time
        
        # Track unique compounds we've already fetched to avoid duplicate API calls
        compound_cache = {}
        enriched_bioactivities = []
        compounds_fetched = 0
        
        print(f"Enriching {len(bioactivities)} bioactivities with compound information (sequential mode)...")
        
        for idx, bioactivity in enumerate(bioactivities, 1):
            # Create a copy to avoid modifying original
            enriched = bioactivity.copy()
            
            molecule_id = bioactivity.get('molecule_chembl_id')
            if not molecule_id:
                enriched_bioactivities.append(enriched)
                continue
            
            # Check if we've already fetched this compound
            if molecule_id in compound_cache:
                compound_info = compound_cache[molecule_id]
            else:
                # Check if we've hit the limit
                if max_compounds and compounds_fetched >= max_compounds:
                    enriched_bioactivities.append(enriched)
                    continue
                
                # Fetch compound information
                try:
                    compound_info = self.get_compound_by_chembl_id(chembl_id=molecule_id)
                    
                    if 'error' not in compound_info:
                        compound_cache[molecule_id] = compound_info
                        compounds_fetched += 1
                        
                        if compounds_fetched % 10 == 0:
                            print(f"  Fetched {compounds_fetched} unique compounds...")
                        
                        time.sleep(rate_limit_delay)
                    else:
                        compound_cache[molecule_id] = None
                        
                except Exception as e:
                    print(f"  Warning: Error fetching compound {molecule_id}: {str(e)}")
                    compound_cache[molecule_id] = None
            
            # Add selected compound properties to bioactivity
            if compound_info and compound_info is not None:
                enriched['compound_name'] = compound_info.get('pref_name')
                enriched['compound_smiles'] = compound_info.get('smiles')
                enriched['compound_max_phase'] = compound_info.get('max_phase')
                enriched['compound_molecular_weight'] = compound_info.get('molecular_weight')
                enriched['compound_alogp'] = compound_info.get('alogp')
                enriched['compound_psa'] = compound_info.get('psa')
                enriched['compound_hba'] = compound_info.get('hba')
                enriched['compound_hbd'] = compound_info.get('hbd')
            
            enriched_bioactivities.append(enriched)
        
        print(f"✓ Enriched {len(enriched_bioactivities)} bioactivities with info from {compounds_fetched} unique compounds")
        return enriched_bioactivities
    
    def search_compounds(self, *, query: str, limit: int = 500, filters: Optional[Dict[str, str]] = None):
        """
        Search for compounds by name, SMILES, or ChEMBL ID.
        
        Multi-word queries (e.g., "TAT peptide") search for ALL words in compound metadata,
        synonyms, and cross-references. This may return compounds without preferred names
        if the match is in synonyms or alternative identifiers.
        
        Args:
            query: Search query (compound name, SMILES, or ChEMBL ID) [KEYWORD-ONLY]
                  - Multi-word queries search for ALL words (e.g., "TAT peptide" finds compounds with both terms)
                  - Single words find broader matches (e.g., "TAT" finds compounds with just that term)
            limit: Maximum number of results to return (default: 500)
                  Note: The API may have many more total results; this limits retrieval
            filters: Optional dictionary of field filters to apply (e.g., {'max_phase__isnull': 'false'})
                    Common filters:
                    - 'max_phase': '4' (approved drugs only)
                    - 'max_phase__isnull': 'false' (compounds with development phase data)
                    - 'molecule_type': 'Small molecule' (specific molecule type)
                    Filter syntax: field__operator=value (operators: isnull, contains, icontains, in, etc.)
            
        Returns:
            Tuple of (results_list, total_count):
            - results_list: List of compound information dictionaries
            - total_count: Total number of matching compounds available (may be > len(results_list))
            
        Example:
            utils.search_compounds(query="aspirin", limit=100)
            
        Note:
            All arguments must be passed as keywords (keyword-only arguments).
            The method prints total available results vs. retrieved results.
            Many compounds may have pref_name=None if matched via synonyms/cross-references.
            # Basic search
            compounds, total = client.search_compounds("aspirin", limit=10)
            
            # Search only approved drugs
            compounds, total = client.search_compounds("kinase", limit=20, 
                                                       filters={'max_phase': '4'})
            
            # Match web interface behavior (compounds with clinical data)
            compounds, total = client.search_compounds("TAT peptide", limit=20,
                                                       filters={'max_phase__isnull': 'false'})
        """
        print(f"Searching ChEMBL for compounds matching '{query}' (limit: {limit})...")
        if filters:
            print(f"  Applying filters: {filters}")

        normalized_query = query.strip()
        compounds: List[Dict[str, Any]] = []
        total_count = None

        # Case 1: Direct ChEMBL ID lookup
        if self._looks_like_chembl_id(normalized_query):
            compound = self.get_compound_by_chembl_id(chembl_id=normalized_query.upper())
            if compound and 'error' not in compound:
                compounds.append(compound)
            print(f"✓ Found {len(compounds)} compound(s)")
            return compounds

        # Case 2: SMILES search
        if self._looks_like_smiles(normalized_query):
            params = {
                'molecule_structures__canonical_smiles__iexact': normalized_query
            }
            # Add any additional filters
            if filters:
                params.update(filters)
            molecules, total_count = self._fetch_paginated('molecule', params, 'molecules', limit)
        else:
            # Case 3: General search using documented ?q= endpoint, with name fallback
            search_params = {
                'q': normalized_query
            }
            # Add any additional filters
            if filters:
                search_params.update(filters)
            molecules, total_count = self._fetch_paginated('molecule/search', search_params, 'molecules', limit)

            if not molecules:
                # Fallback to preferred name contains filter if search yields nothing
                params = {'pref_name__icontains': normalized_query}
                if filters:
                    params.update(filters)
                molecules, total_count = self._fetch_paginated('molecule', params, 'molecules', limit)

        for mol in molecules:
            if not mol:  # Skip None entries
                continue
            compound_data = {
                "chembl_id": mol.get('molecule_chembl_id'),
                "pref_name": mol.get('pref_name'),
                "molecule_type": mol.get('molecule_type'),
                "max_phase": mol.get('max_phase'),
                "molecular_formula": (mol.get('molecule_properties') or {}).get('full_molformula'),
                "molecular_weight": (mol.get('molecule_properties') or {}).get('full_mwt'),
                "smiles": (mol.get('molecule_structures') or {}).get('canonical_smiles'),
                "inchi": (mol.get('molecule_structures') or {}).get('standard_inchi'),
                "inchi_key": (mol.get('molecule_structures') or {}).get('standard_inchi_key'),
                "num_ro5_violations": (mol.get('molecule_properties') or {}).get('num_ro5_violations'),
                "alogp": (mol.get('molecule_properties') or {}).get('alogp'),
                "psa": (mol.get('molecule_properties') or {}).get('psa')
            }
            compounds.append(compound_data)
        
        # Show total available vs retrieved
        if total_count and total_count > len(compounds):
            print(f"✓ Found {len(compounds)} compound(s) (out of {total_count} total matches - increase limit to retrieve more)")
        else:
            print(f"✓ Found {len(compounds)} compound(s)")
        
        # Return compounds and total count for metadata tracking
        return compounds, total_count
    
    def get_compound_by_chembl_id(self, *, chembl_id: str) -> Dict[str, Any]:
        """
        Get detailed compound information by ChEMBL ID.
        
        Args:
            chembl_id: ChEMBL compound ID (e.g., 'CHEMBL25')
            
        Returns:
            Dictionary containing detailed compound information
        """
        print(f"Fetching detailed information for compound {chembl_id}...")
        
        endpoint = f"molecule/{chembl_id}"
        result = self._make_request(endpoint)
        
        if 'error' in result:
            print(f"✗ Error fetching compound {chembl_id}: {result['error']}")
            return result
        
        print(f"✓ Retrieved compound information for {chembl_id}")
        
        mol = result
        # Handle case where molecule_properties or molecule_structures are null/None
        props = mol.get('molecule_properties') or {}
        structures = mol.get('molecule_structures') or {}
        
        return {
            "chembl_id": mol.get('molecule_chembl_id'),
            "pref_name": mol.get('pref_name'),
            "molecule_type": mol.get('molecule_type'),
            "max_phase": mol.get('max_phase'),  # Keep as string (can be '4', '4.0', '3', etc.)
            "therapeutic_flag": mol.get('therapeutic_flag'),
            "molecular_formula": props.get('full_molformula'),
            # Convert numeric properties to actual numbers for easier DataFrame operations
            "molecular_weight": self._safe_float(props.get('full_mwt')),
            "smiles": structures.get('canonical_smiles'),
            "inchi": structures.get('standard_inchi'),
            "inchi_key": structures.get('standard_inchi_key'),
            # Flatten commonly used properties for easier DataFrame operations (as numbers)
            "alogp": self._safe_float(props.get('alogp')),
            "psa": self._safe_float(props.get('psa')),
            "hba": self._safe_int(props.get('hba')),
            "hbd": self._safe_int(props.get('hbd')),
            "num_ro5_violations": self._safe_int(props.get('num_ro5_violations')),
            "rtb": self._safe_int(props.get('rtb')),
            "aromatic_rings": self._safe_int(props.get('aromatic_rings')),
            # Keep full properties dict for advanced users
            "properties": props,
            "synonyms": mol.get('molecule_synonyms') or [],
            "cross_references": mol.get('cross_references') or []
        }
    
    def get_compounds_by_chembl_ids(self, *, chembl_ids: List[str], parallel: bool = True) -> List[Dict[str, Any]]:
        """
        Fetch multiple compounds by ChEMBL IDs, optionally in parallel.
        
        Args:
            chembl_ids: List of ChEMBL compound IDs (e.g., ['CHEMBL25', 'CHEMBL1234'])
            parallel: Use parallel fetching (default: True)
            
        Returns:
            List of compound dictionaries (in same order as input IDs)
            
        Example:
            compound_ids = ['CHEMBL25', 'CHEMBL1234', 'CHEMBL5678']
            compounds = utils.get_compounds_by_chembl_ids(compound_ids, parallel=True)
        """
        if not parallel:
            return [self.get_compound_by_chembl_id(chembl_id=cid) for cid in chembl_ids]
        
        print(f"Fetching {len(chembl_ids)} compounds in parallel (max_workers={self.max_workers})...")
        
        compounds_dict = {}
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_id = {
                executor.submit(self.get_compound_by_chembl_id, chembl_id=cid): cid 
                for cid in chembl_ids
            }
            
            completed = 0
            for future in as_completed(future_to_id):
                compound_id = future_to_id[future]
                try:
                    compound_info = future.result()
                    compounds_dict[compound_id] = compound_info
                except Exception as e:
                    print(f"  Warning: Error fetching compound {compound_id}: {str(e)}")
                    compounds_dict[compound_id] = {"error": str(e), "chembl_id": compound_id}
                
                completed += 1
                if completed % 10 == 0:
                    print(f"  Fetched {completed}/{len(chembl_ids)} compounds...")
        
        # Return in original order
        compounds = [compounds_dict[cid] for cid in chembl_ids]
        print(f"✓ Fetched {len(compounds)} compounds")
        return compounds
    
    def search_targets(self, *, query: str, limit: int = 500):
        """
        Search for biological targets by name or ChEMBL ID.
        
        Multi-word queries search for ALL words in target metadata.
        
        Args:
            query: Search query (target name or ChEMBL ID) [KEYWORD-ONLY]
                  - Multi-word queries search for ALL words (e.g., "protein kinase" finds targets with both terms)
                  - Single words find broader matches
            limit: Maximum number of results to return (default: 500)
                  Note: The API may have many more total results; this limits retrieval
            
        Returns:
            List of target information dictionaries
            
        Example:
            utils.search_targets(query="EGFR", limit=100)
            
        Note:
            All arguments must be passed as keywords (keyword-only arguments).
            The method prints total available results vs. retrieved results.
        """
        print(f"Searching ChEMBL for targets matching '{query}' (limit: {limit})...")

        normalized_query = query.strip()
        total_count = None

        if self._looks_like_chembl_id(normalized_query):
            target = self.get_target_by_chembl_id(chembl_id=normalized_query.upper())
            if target and 'error' not in target:
                print("✓ Found 1 target")
                return [target]
            print("✓ Found 0 target(s)")
            return []

        targets_data, total_count = self._fetch_paginated('target/search', {'q': normalized_query}, 'targets', limit)

        if not targets_data:
            targets_data, total_count = self._fetch_paginated('target', {'pref_name__icontains': normalized_query}, 'targets', limit)

        targets: List[Dict[str, Any]] = []
        for target in targets_data:
            target_data = {
                "chembl_id": target.get('target_chembl_id'),
                "pref_name": target.get('pref_name'),
                "target_type": target.get('target_type'),
                "organism": target.get('organism'),
                "tax_id": target.get('tax_id'),
                "target_components": target.get('target_components', [])
            }
            targets.append(target_data)
        
        # Show total available vs retrieved
        if total_count and total_count > len(targets):
            print(f"✓ Found {len(targets)} target(s) (out of {total_count} total matches - increase limit to retrieve more)")
        else:
            print(f"✓ Found {len(targets)} target(s)")
        
        # Return targets and total count for metadata tracking
        return targets, total_count
    
    def get_target_by_chembl_id(self, *, chembl_id: str) -> Dict[str, Any]:
        """
        Get detailed target information by ChEMBL ID.
        
        Args:
            chembl_id: ChEMBL target ID (e.g., 'CHEMBL2095')
            
        Returns:
            Dictionary containing detailed target information
        """
        print(f"Fetching detailed information for target {chembl_id}...")
        
        endpoint = f"target/{chembl_id}"
        result = self._make_request(endpoint)
        
        if 'error' in result:
            print(f"✗ Error fetching target {chembl_id}: {result['error']}")
            return result
        
        print(f"✓ Retrieved target information for {chembl_id}")
        
        return {
            "chembl_id": result.get('target_chembl_id'),
            "pref_name": result.get('pref_name'),
            "target_type": result.get('target_type'),
            "organism": result.get('organism'),
            "tax_id": result.get('tax_id'),
            "target_components": result.get('target_components', []),
            "cross_references": result.get('cross_references', [])
        }
    
    def get_targets_by_chembl_ids(self, *, chembl_ids: List[str], parallel: bool = True) -> List[Dict[str, Any]]:
        """
        Fetch multiple targets by ChEMBL IDs, optionally in parallel.
        
        Args:
            chembl_ids: List of ChEMBL target IDs (e.g., ['CHEMBL203', 'CHEMBL1824'])
            parallel: Use parallel fetching (default: True)
            
        Returns:
            List of target dictionaries (in same order as input IDs)
            
        Example:
            target_ids = ['CHEMBL203', 'CHEMBL1824', 'CHEMBL2095']
            targets = utils.get_targets_by_chembl_ids(target_ids, parallel=True)
        """
        if not parallel:
            return [self.get_target_by_chembl_id(chembl_id=tid) for tid in chembl_ids]
        
        print(f"Fetching {len(chembl_ids)} targets in parallel (max_workers={self.max_workers})...")
        
        targets_dict = {}
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_id = {
                executor.submit(self.get_target_by_chembl_id, chembl_id=tid): tid 
                for tid in chembl_ids
            }
            
            completed = 0
            for future in as_completed(future_to_id):
                target_id = future_to_id[future]
                try:
                    target_info = future.result()
                    targets_dict[target_id] = target_info
                except Exception as e:
                    print(f"  Warning: Error fetching target {target_id}: {str(e)}")
                    targets_dict[target_id] = {"error": str(e), "chembl_id": target_id}
                
                completed += 1
                if completed % 10 == 0:
                    print(f"  Fetched {completed}/{len(chembl_ids)} targets...")
        
        # Return in original order
        targets = [targets_dict[tid] for tid in chembl_ids]
        print(f"✓ Fetched {len(targets)} targets")
        return targets
    
    def get_bioactivities_for_target(self, *, target_chembl_id: str, limit: int = 1000):
        """
        Get bioactivity data for a specific target.
        
        This method is used to retrieve bioactivity measurements for compounds tested against a target.
        Each bioactivity includes standard measurements (IC50, Ki, etc.) and pchembl_value when available.
        
        Args:
            target_chembl_id: ChEMBL target ID (e.g., 'CHEMBL203' for EGFR)
            limit: Maximum number of results to return (default: 1000)
                   Note: May be fewer total bioactivities available for the target
            
        Returns:
            Tuple of (activities_list, total_count):
            - activities_list: List of bioactivity data dictionaries, each containing:
                * molecule_chembl_id: Compound identifier
                * standard_type: Measurement type (IC50, Ki, Kd, etc.)
                * standard_value: Numeric value (converted to float)
                * standard_units: Units (nM, uM, etc.)
                * pchembl_value: Negative log of molar IC50/Ki/Kd (float or None)
                * assay_chembl_id: Assay identifier
                * ... and other fields
            - total_count: Total number of matching bioactivities available in ChEMBL
            
        Example:
            utils = ChEMBLUtils()
            activities, total = utils.get_bioactivities_for_target("CHEMBL203", limit=500)
            print(f"Retrieved {len(activities)} out of {total} total bioactivities")
            
            # Access pchembl_value safely
            for activity in activities:
                pchembl = activity.get('pchembl_value')
                if pchembl:
                    print(f"Compound {activity['molecule_chembl_id']}: pChEMBL = {pchembl}")
        """
        print(f"Fetching bioactivities for target {target_chembl_id} (limit: {limit})...")
        
        params = {
            'target_chembl_id': target_chembl_id
        }
        
        activity_list, total_count = self._fetch_paginated('activity', params, 'activities', limit)

        activities = []
        for activity in activity_list:
            activity_data = {
                "activity_id": activity.get('activity_id'),
                "molecule_chembl_id": activity.get('molecule_chembl_id'),
                "canonical_smiles": activity.get('canonical_smiles'),
                "target_chembl_id": activity.get('target_chembl_id'),
                "assay_chembl_id": activity.get('assay_chembl_id'),
                "assay_type": activity.get('assay_type'),
                "assay_description": activity.get('assay_description'),
                "standard_type": activity.get('standard_type'),
                # Convert numeric fields to actual numbers
                "standard_value": self._safe_float(activity.get('standard_value')),
                "standard_units": activity.get('standard_units'),
                "standard_relation": activity.get('standard_relation'),
                "pchembl_value": self._safe_float(activity.get('pchembl_value')),
                "activity_comment": activity.get('activity_comment'),
                "data_validity_comment": activity.get('data_validity_comment'),
                "bao_format": activity.get('bao_format'),
                "bao_label": activity.get('bao_label'),
                "type": activity.get('type')
            }
            activities.append(activity_data)
        
        # Show total available vs retrieved
        if total_count and total_count > len(activities):
            print(f"✓ Retrieved {len(activities)} bioactivity measurement(s) for target (out of {total_count} total)")
        else:
            print(f"✓ Retrieved {len(activities)} bioactivity measurement(s) for target")
        
        # Return activities and total count for metadata tracking
        return activities, total_count
    
    def get_bioactivities_for_compound(self, *, molecule_chembl_id: str, limit: int = 1000):
        """
        Get bioactivity data for a specific compound.
        
        Args:
            molecule_chembl_id: ChEMBL molecule ID
            limit: Maximum number of results to return (default: 1000)
            
        Returns:
            Tuple of (results_list, total_count):
            - results_list: List of bioactivity data dictionaries
            - total_count: Total number of matching bioactivities available
        """
        print(f"Fetching bioactivities for compound {molecule_chembl_id} (limit: {limit})...")
        
        params = {
            'molecule_chembl_id': molecule_chembl_id
        }
        
        activity_list, total_count = self._fetch_paginated('activity', params, 'activities', limit)

        activities = []
        for activity in activity_list:
            activity_data = {
                "activity_id": activity.get('activity_id'),
                "molecule_chembl_id": activity.get('molecule_chembl_id'),
                "canonical_smiles": activity.get('canonical_smiles'),
                "target_chembl_id": activity.get('target_chembl_id'),
                "assay_chembl_id": activity.get('assay_chembl_id'),
                "assay_type": activity.get('assay_type'),
                "assay_description": activity.get('assay_description'),
                "standard_type": activity.get('standard_type'),
                # Convert numeric fields to actual numbers
                "standard_value": self._safe_float(activity.get('standard_value')),
                "standard_units": activity.get('standard_units'),
                "standard_relation": activity.get('standard_relation'),
                "pchembl_value": self._safe_float(activity.get('pchembl_value')),
                "activity_comment": activity.get('activity_comment'),
                "bao_format": activity.get('bao_format'),
                "bao_label": activity.get('bao_label'),
                "type": activity.get('type')
            }
            activities.append(activity_data)
        
        # Show total available vs retrieved
        if total_count and total_count > len(activities):
            print(f"✓ Retrieved {len(activities)} bioactivity measurement(s) for compound (out of {total_count} total)")
        else:
            print(f"✓ Retrieved {len(activities)} bioactivity measurement(s) for compound")
        
        # Return activities and total count for metadata tracking
        return activities, total_count

    def search_bioactivities(self, *, filters: Dict[str, str], limit: int = 5000):
        """
        Search bioactivities with arbitrary filters on the ChEMBL activity endpoint.

        Use this for bulk data collection tasks such as gathering ADME training data,
        selectivity panels, or large-scale SAR datasets where you need to query by
        assay type, standard type, or other activity-level filters rather than by
        a single target or compound.

        Args:
            filters: Dictionary of ChEMBL activity API filter parameters. Common filters:
                - standard_type: Measurement type (e.g., 'IC50', 'Ki', 'LogD', 'Solubility',
                  'Caco2 Papp', 'CLint', 'F', '%Inhibition')
                - assay_type: 'B' (binding), 'F' (functional), 'A' (ADME), 'T' (toxicity),
                  'P' (physicochemical), 'U' (unassigned)
                - standard_units: e.g., 'nM', 'uM', '%'
                - standard_relation: '=', '>', '<', '>='
                - target_chembl_id: Filter to a specific target
                - molecule_chembl_id: Filter to a specific compound
                - pchembl_value__isnull: 'false' to require pChEMBL values
                - standard_value__isnull: 'false' to require numeric values
                - target_organism: e.g., 'Homo sapiens'
                Filters can use Django-style lookups: __gt, __gte, __lt, __lte,
                __in, __isnull, __contains, __icontains, __startswith, __endswith, __range.
            limit: Maximum number of results (default: 5000). For large ADME datasets
                set higher (e.g., 50000). Pagination is handled automatically.

        Returns:
            Tuple of (activities_list, total_count):
            - activities_list: List of bioactivity dictionaries with standard fields
            - total_count: Total matching results available in ChEMBL

        Examples:
            utils = ChEMBLUtils()

            # All ADME assay results with measured values
            adme, total = utils.search_bioactivities(
                filters={'assay_type': 'A', 'standard_value__isnull': 'false'},
                limit=25000
            )

            # LogD measurements for drug-like compounds
            logd, total = utils.search_bioactivities(
                filters={'standard_type': 'LogD', 'standard_value__isnull': 'false'},
                limit=10000
            )

            # High-quality IC50 data with pChEMBL values for a target
            ic50s, total = utils.search_bioactivities(
                filters={
                    'target_chembl_id': 'CHEMBL203',
                    'standard_type': 'IC50',
                    'pchembl_value__isnull': 'false',
                },
                limit=5000
            )

            # Solubility data
            sol, total = utils.search_bioactivities(
                filters={'standard_type': 'Solubility', 'assay_type': 'P'},
                limit=10000
            )
        """
        filter_desc = ', '.join(f'{k}={v}' for k, v in filters.items())
        print(f"Searching bioactivities with filters: {filter_desc} (limit: {limit})...")

        params = dict(filters)
        activity_list, total_count = self._fetch_paginated('activity', params, 'activities', limit)

        activities = []
        for activity in activity_list:
            activity_data = {
                "activity_id": activity.get('activity_id'),
                "molecule_chembl_id": activity.get('molecule_chembl_id'),
                "canonical_smiles": activity.get('canonical_smiles'),
                "target_chembl_id": activity.get('target_chembl_id'),
                "target_pref_name": activity.get('target_pref_name'),
                "target_organism": activity.get('target_organism'),
                "assay_chembl_id": activity.get('assay_chembl_id'),
                "assay_type": activity.get('assay_type'),
                "assay_description": activity.get('assay_description'),
                "standard_type": activity.get('standard_type'),
                "standard_value": self._safe_float(activity.get('standard_value')),
                "standard_units": activity.get('standard_units'),
                "standard_relation": activity.get('standard_relation'),
                "pchembl_value": self._safe_float(activity.get('pchembl_value')),
                "activity_comment": activity.get('activity_comment'),
                "data_validity_comment": activity.get('data_validity_comment'),
                "bao_format": activity.get('bao_format'),
                "bao_label": activity.get('bao_label'),
            }
            activities.append(activity_data)

        if total_count and total_count > len(activities):
            print(f"✓ Retrieved {len(activities)} bioactivities (out of {total_count} total matching)")
        else:
            print(f"✓ Retrieved {len(activities)} bioactivities")

        return activities, total_count

    def cross_reference_with_pdb(self, *, target_name: str) -> Dict[str, Any]:
        """
        Cross-reference a target with PDB structures.
        
        Args:
            target_name: Target name to search for
            
        Returns:
            Dictionary containing target info and associated PDB structures
        """
        print(f"Cross-referencing ChEMBL target '{target_name}' with PDB structures...")
        
        # Search for target
        targets, _total = self.search_targets(query=target_name, limit=5)
        
        if not targets:
            print(f"✗ No targets found for '{target_name}'")
            return {
                "status": "no_targets_found",
                "target_name": target_name,
                "targets": [],
                "pdb_references": []
            }
        
        print(f"Processing {len(targets)} target(s) for PDB cross-references...")
        
        # Get detailed information for each target
        results = []
        for i, target in enumerate(targets, 1):
            target_id = target['chembl_id']
            print(f"  [{i}/{len(targets)}] Checking {target['pref_name']} ({target_id}) for PDB structures...")
            
            detailed_target = self.get_target_by_chembl_id(chembl_id=target_id)
            
            # Extract PDB cross-references (catch multiple source labels)
            pdb_refs = []
            cross_refs = detailed_target.get('cross_references', [])
            for ref in cross_refs:
                source = (ref.get('xref_src') or '').lower()
                pdb_id = ref.get('xref_id')
                if not pdb_id or 'pdb' not in source:
                    continue

                if 'pdbe' in source:
                    pdb_url = f"https://www.ebi.ac.uk/pdbe/entry/pdb/{pdb_id}"
                else:
                    pdb_url = f"https://www.rcsb.org/structure/{pdb_id}"

                pdb_refs.append({
                    "pdb_id": pdb_id,
                    "source": ref.get('xref_src'),
                    "pdb_url": pdb_url
                })
            
            print(f"    Found {len(pdb_refs)} PDB structure(s)")
            
            results.append({
                "target": detailed_target,
                "pdb_references": pdb_refs
            })
        
        print(f"✓ Cross-reference complete: {len(results)} target(s) processed")
        
        return {
            "status": "success",
            "target_name": target_name,
            "results": results
        }
    
    def analyze_congeneric_series(self, *, target_chembl_id: str, output_dir: str, limit: int = 5000) -> Dict[str, Any]:
        """
        Analyze ligands for a target to identify congeneric series.
        A congeneric series is a set of compounds with similar core structures.

        Args:
            target_chembl_id: ChEMBL target ID [KEYWORD-ONLY]
            output_dir: Directory to save results (required)
            limit: Maximum number of bioactivities to retrieve (default: 5000). 
                   Higher values provide more complete data but take longer to process.

        Returns:
            Dictionary with the following structure:
            {
                'status': 'success',
                'target_chembl_id': str,
                'bioactivities_retrieved': int,
                'bioactivities_available': int,
                'total_ligands': int,
                'total_congeneric_groups': int,
                'congeneric_series': [
                    {
                        'connectivity_key': str,  # First 14 chars of InChI key
                        'series_size': int,
                        'ligands': [
                            {
                                'chembl_id': str,
                                'pref_name': str,
                                'smiles': str,
                                'molecular_weight': float,
                                'alogp': float,
                                'hba': int,
                                'hbd': int,
                                'psa': float,
                                'pchembl_value': float or None,  # ✅ Best (highest) pchembl_value from all activities
                                'primary_activity_type': str,  # Most common activity type
                                'activities': [...]  # Complete list of all bioactivity measurements
                            }
                        ]
                    }
                ]
            }
            
            ⚠️ IMPORTANT - Bioactivity Data:
            - Each ligand includes 'pchembl_value' (best/highest value from all activities)
            - Each ligand includes 'activities' list with all bioactivity measurements
            - Each ligand includes 'primary_activity_type' (most common activity type)
            - Use safe access: always check with .get() or .notna() in pandas
            - pchembl_value may be None if no valid bioactivity data exists
            
        Example:
            # ✅ Correct usage (keyword-only arguments)
            utils = ChEMBLUtils()
            results = utils.analyze_congeneric_series(target_chembl_id="CHEMBL203", 
                                                      output_dir="/output", 
                                                      limit=15000)
            
            # Access bioactivity data
            for series in results['congeneric_series']:
                for ligand in series['ligands']:
                    # pchembl_value is directly available (best value)
                    pchembl = ligand.get('pchembl_value')
                    
                    # Or access all activities for detailed analysis
                    for activity in ligand.get('activities', []):
                        pchembl_val = activity.get('pchembl_value')
                        activity_type = activity.get('standard_type')
        """
        os.makedirs(output_dir, exist_ok=True)

        print(f"\nAnalyzing congeneric series for target: {target_chembl_id}")
        print("=" * 60)

        # get_bioactivities_for_target returns (activities, total_count) tuple
        result = self.get_bioactivities_for_target(target_chembl_id=target_chembl_id, limit=limit)
        if isinstance(result, tuple):
            activities, total_count = result
        else:
            # Fallback for older API that might return just the list
            activities = result
            total_count = len(activities) if activities else 0
        
        if not activities:
            print(f"✗ No bioactivity data found for target {target_chembl_id}")
            return {
                "status": "no_activities_found",
                "target_chembl_id": target_chembl_id,
                "ligands": []
            }

        print(f"Step 1: Extracting unique ligands from {len(activities)} bioactivity measurements...")

        unique_ligands: Dict[str, Dict[str, Any]] = {}
        for activity in activities:
            mol_id = activity.get('molecule_chembl_id')
            if not mol_id:
                continue
            if mol_id not in unique_ligands:
                unique_ligands[mol_id] = {
                    "chembl_id": mol_id,
                    "activities": []
                }
            unique_ligands[mol_id]['activities'].append(activity)

        print(f"✓ Found {len(unique_ligands)} unique ligand(s)")
        print("\nStep 2: Fetching detailed information for each ligand...")

        ligand_details: List[Dict[str, Any]] = []
        for i, (mol_id, data) in enumerate(unique_ligands.items(), 1):
            if i % 10 == 0:
                print(f"  Progress: {i}/{len(unique_ligands)} ligands processed...")

            compound = self.get_compound_by_chembl_id(chembl_id=mol_id)
            if compound.get('error'):
                print(f"  ! Error fetching compound {mol_id}: {compound['error']}")
                continue

            # Store all activities
            compound['activities'] = data['activities']
            
            # Extract best pchembl_value for easier access (highest = most potent)
            pchembl_values = [self._safe_float(act.get('pchembl_value')) 
                            for act in data['activities'] 
                            if act.get('pchembl_value')]
            compound['pchembl_value'] = max(pchembl_values) if pchembl_values else None
            
            # Also extract most common activity type and units
            activity_types = [act.get('standard_type') for act in data['activities'] if act.get('standard_type')]
            if activity_types:
                from collections import Counter
                compound['primary_activity_type'] = Counter(activity_types).most_common(1)[0][0]
            
            ligand_details.append(compound)
            time.sleep(0.1)  # Rate limiting

        print(f"✓ Successfully retrieved details for {len(ligand_details)} ligand(s)")
        print("\nStep 3: Grouping ligands into congeneric series by structural similarity...")

        congeneric_groups: Dict[str, List[Dict[str, Any]]] = {}
        for ligand in ligand_details:
            inchi_key = ligand.get('inchi_key', '')
            if not inchi_key:
                continue
            connectivity = inchi_key[:14] if len(inchi_key) >= 14 else inchi_key
            congeneric_groups.setdefault(connectivity, []).append(ligand)

        congeneric_series = {k: v for k, v in congeneric_groups.items() if len(v) >= 2}

        print(f"✓ Identified {len(congeneric_series)} congeneric series (groups with ≥2 compounds)")

        if congeneric_series:
            print("\nCongeneric series summary:")
            for i, (key, ligands) in enumerate(
                sorted(congeneric_series.items(), key=lambda x: len(x[1]), reverse=True)[:5],
                1,
            ):
                print(f"  {i}. Series {key[:10]}...: {len(ligands)} compounds")

        # Calculate statistics on bioactivity data
        ligands_with_pchembl = sum(1 for l in ligand_details if l.get('pchembl_value'))
        
        results = {
            "status": "success",
            "target_chembl_id": target_chembl_id,
            "bioactivities_retrieved": len(activities),
            "bioactivities_available": total_count,
            "total_ligands": len(ligand_details),
            "ligands_with_pchembl": ligands_with_pchembl,
            "total_congeneric_groups": len(congeneric_series),
            "congeneric_series": [
                {
                    "connectivity_key": key,
                    "series_size": len(ligands),
                    "ligands": ligands,
                }
                for key, ligands in congeneric_series.items()
            ],
            "data_quality_note": (
                f"{ligands_with_pchembl}/{len(ligand_details)} ligands have pchembl_value data. "
                "Access via ligand['pchembl_value'] (best value) or ligand['activities'] (all measurements)."
            )
        }
        
        # Add warning if we didn't retrieve all available bioactivities
        if total_count and len(activities) < total_count:
            results['data_completeness_warning'] = (
                f"Retrieved {len(activities)} out of {total_count} available bioactivities. "
                f"Increase the limit parameter to analyze more data for comprehensive congeneric series analysis."
            )
        
        print(f"\n📊 Data quality: {ligands_with_pchembl}/{len(ligand_details)} ligands have pchembl_value")

        output_file = f"{output_dir}/congeneric_series_{target_chembl_id}.json"
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2)

        print("\n✓ Analysis complete!")
        print(f"✓ Results saved to: {output_file}")
        print("=" * 60)

        return results
    
    def cross_reference_ligands_with_pdb(self, *, target_name: str, output_dir: str) -> Dict[str, Any]:
        """
        Complete workflow: Cross-reference ChEMBL ligand data with PDB structures
        to identify congeneric series with minimal binding mode ambiguity.

        Args:
            target_name: Target name to search for
            output_dir: Directory to save results

        Returns:
            Dictionary containing comprehensive analysis results
        """
        os.makedirs(output_dir, exist_ok=True)

        print("\n" + "=" * 70)
        print("ChEMBL-PDB Cross-Reference Analysis")
        print(f"Target: {target_name}")
        print("=" * 70)

        print("\nSTEP 1: Searching for target and PDB cross-references...")
        pdb_data = self.cross_reference_with_pdb(target_name=target_name)

        if pdb_data['status'] != 'success' or not pdb_data['results']:
            print("\n✗ Analysis cannot continue: No targets or PDB structures found")
            return {
                "status": "no_targets_found",
                "target_name": target_name,
                "message": "No targets or PDB structures found",
            }

        print(f"\n✓ Found {len(pdb_data['results'])} target(s) to analyze")
        print("\nSTEP 2: Analyzing ligands for each target...")
        print("-" * 70)

        all_results: List[Dict[str, Any]] = []
        for i, target_data in enumerate(pdb_data['results'], 1):
            target = target_data['target']
            target_id = target['chembl_id']

            print(f"\n[Target {i}/{len(pdb_data['results'])}] {target['pref_name']} ({target_id})")
            print(f"Organism: {target.get('organism', 'N/A')}")
            print(f"PDB structures: {len(target_data['pdb_references'])}")

            series_analysis = self.analyze_congeneric_series(target_chembl_id=target_id, output_dir=output_dir)

            all_results.append(
                {
                    "target": target,
                    "pdb_references": target_data['pdb_references'],
                    "ligand_analysis": series_analysis,
                }
            )

        print("\nSTEP 3: Creating comprehensive report...")

        final_results = {
            "status": "completed",
            "target_name": target_name,
            "analysis_date": time.strftime("%Y-%m-%d"),
            "targets_analyzed": len(all_results),
            "results": all_results,
        }

        output_file = f"{output_dir}/final_results.json"
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(final_results, f, indent=2)

        self._create_analysis_report(final_results, output_dir)

        print(f"\n✓ Final results saved to: {output_file}")
        print(f"✓ Summary report saved to: {output_dir}/analysis_report.txt")
        print("\n" + "=" * 70)
        print("ANALYSIS COMPLETE")
        print("=" * 70)

        total_ligands = sum(
            r['ligand_analysis'].get('total_ligands', 0)
            for r in all_results
            if r['ligand_analysis']['status'] == 'success'
        )
        total_series = sum(
            r['ligand_analysis'].get('total_congeneric_groups', 0)
            for r in all_results
            if r['ligand_analysis']['status'] == 'success'
        )

        print(f"Targets analyzed: {len(all_results)}")
        print(f"Total ligands: {total_ligands}")
        print(f"Total congeneric series: {total_series}")
        print("=" * 70 + "\n")

        return final_results
    
    def _create_analysis_report(self, results: Dict[str, Any], output_dir: str):
        """
        Create a human-readable analysis report.
        
        Args:
            results: Analysis results dictionary
            output_dir: Output directory
        """
        report_lines = [
            "ChEMBL-PDB Cross-Reference Analysis Report",
            "=" * 50,
            f"Target: {results['target_name']}",
            f"Analysis Date: {results['analysis_date']}",
            f"Targets Analyzed: {results['targets_analyzed']}",
            "",
            "Summary:",
            "-" * 30
        ]
        
        for i, target_result in enumerate(results['results'], 1):
            target = target_result['target']
            pdb_refs = target_result['pdb_references']
            ligand_analysis = target_result['ligand_analysis']
            
            report_lines.append(f"\n{i}. {target['pref_name']} ({target['chembl_id']})")
            report_lines.append(f"   Organism: {target.get('organism', 'N/A')}")
            report_lines.append(f"   PDB Structures: {len(pdb_refs)}")
            
            for pdb in pdb_refs:
                report_lines.append(f"     - {pdb['pdb_id']}: {pdb['pdb_url']}")
            
            if ligand_analysis['status'] == 'success':
                report_lines.append(f"   Total Ligands: {ligand_analysis['total_ligands']}")
                report_lines.append(f"   Congeneric Series: {ligand_analysis['total_congeneric_groups']}")
                
                # List top 5 congeneric series
                series = ligand_analysis['congeneric_series'][:5]
                for j, s in enumerate(series, 1):
                    report_lines.append(f"     Series {j}: {s['series_size']} ligands (key: {s['connectivity_key'][:10]}...)")
        
        report_filename = f"{output_dir}/analysis_report.txt"
        with open(report_filename, 'w', encoding='utf-8') as f:
            f.write("\n".join(report_lines))

    @staticmethod
    def parse_pdb_header(pdb_file_path: str) -> Dict[str, Any]:
        """
        Parse PDB file header to extract protein/target information.
        
        Extracts key information from PDB HEADER, TITLE, COMPND, and SOURCE records
        that can be used to identify corresponding ChEMBL targets.
        
        Args:
            pdb_file_path: Path to PDB file
            
        Returns:
            Dictionary containing:
            - pdb_id: PDB identifier
            - classification: Molecule classification from HEADER
            - deposition_date: Date structure was deposited
            - title: Structure title/description
            - molecule_name: Molecule/protein name from COMPND
            - organism: Source organism from SOURCE
            - ec_number: EC number if available
            - uniprot_ids: List of UniProt IDs from DBREF records
            - ligands: List of HET (ligand) records with names and formulas
            
        Example:
            >>> info = ChEMBLUtils.parse_pdb_header("/input/1abc.pdb")
            >>> print(info['molecule_name'])
            >>> print(info['organism'])
            >>> # Use extracted info to search ChEMBL
            >>> utils = ChEMBLUtils()
            >>> targets, total = utils.search_targets(query=info['molecule_name'])
        """
        pdb_info = {
            'pdb_id': os.path.splitext(os.path.basename(pdb_file_path))[0].upper(),
            'classification': None,
            'deposition_date': None,
            'title': None,
            'molecule_name': None,
            'organism': None,
            'ec_number': None,
            'uniprot_ids': [],
            'ligands': [],
            'chain_info': []
        }
        
        try:
            with open(pdb_file_path, 'r', encoding='utf-8') as f:
                current_compnd = []
                current_source = []
                
                for line in f:
                    # Stop at ATOM records - header is complete
                    if line.startswith('ATOM  ') or line.startswith('HETATM'):
                        break
                    
                    record_type = line[0:6].strip()
                    content = line[10:].strip() if len(line) > 10 else ""
                    
                    if record_type == 'HEADER':
                        # HEADER format: classification (10-50), deposition date (50-59), ID code (62-66)
                        if len(line) >= 50:
                            pdb_info['classification'] = line[10:50].strip()
                        if len(line) >= 59:
                            pdb_info['deposition_date'] = line[50:59].strip()
                        if len(line) >= 66:
                            pdb_info['pdb_id'] = line[62:66].strip().upper()
                    
                    elif record_type == 'TITLE':
                        if pdb_info['title'] is None:
                            pdb_info['title'] = content
                        else:
                            pdb_info['title'] += ' ' + content
                    
                    elif record_type == 'COMPND':
                        # Compound/molecule information (can span multiple lines)
                        current_compnd.append(content)
                    
                    elif record_type == 'SOURCE':
                        # Source organism information
                        current_source.append(content)
                    
                    elif record_type == 'DBREF':
                        # Database cross-references (especially UniProt)
                        if len(line) >= 68:
                            database = line[26:32].strip()
                            db_id = line[33:41].strip()
                            if database == 'UNP' and db_id:
                                pdb_info['uniprot_ids'].append(db_id)
                    
                    elif record_type == 'HET':
                        # Heteroatom (ligand) records
                        if len(line) >= 30:
                            het_id = line[7:10].strip()
                            chain_id = line[12:13].strip()
                            num_atoms = line[20:25].strip()
                            description = line[30:].strip() if len(line) > 30 else ""
                            pdb_info['ligands'].append({
                                'het_id': het_id,
                                'chain': chain_id,
                                'num_atoms': num_atoms,
                                'description': description
                            })
                
                # Parse COMPND information (key-value pairs separated by semicolons)
                if current_compnd:
                    compnd_text = ' '.join(current_compnd)
                    for part in compnd_text.split(';'):
                        part = part.strip()
                        if ':' in part:
                            key, value = part.split(':', 1)
                            key = key.strip().lower()
                            value = value.strip()
                            
                            if key == 'molecule':
                                pdb_info['molecule_name'] = value
                            elif key == 'ec':
                                pdb_info['ec_number'] = value
                            elif key == 'chain':
                                pdb_info['chain_info'].append(value)
                
                # Parse SOURCE information
                if current_source:
                    source_text = ' '.join(current_source)
                    for part in source_text.split(';'):
                        part = part.strip()
                        if ':' in part:
                            key, value = part.split(':', 1)
                            key = key.strip().lower()
                            value = value.strip()
                            
                            if key == 'organism_scientific':
                                pdb_info['organism'] = value
                
                # Clean up title (remove extra spaces)
                if pdb_info['title']:
                    pdb_info['title'] = ' '.join(pdb_info['title'].split())
        
        except Exception as e:
            print(f"Warning: Error parsing PDB file {pdb_file_path}: {str(e)}")
            pdb_info['error'] = str(e)
        
        return pdb_info


# Convenience functions for direct usage
def search_compounds(query: str, limit: int = 500):
    """
    Convenience function to search for compounds.
    
    Args:
        query: Search query
        limit: Maximum number of results (default: 500)
        
    Returns:
        Tuple of (results_list, total_count)
    """
    utils = ChEMBLUtils()
    return utils.search_compounds(query=query, limit=limit)


def search_targets(query: str, limit: int = 500):
    """
    Convenience function to search for targets.
    
    Args:
        query: Search query
        limit: Maximum number of results (default: 500)
        
    Returns:
        Tuple of (results_list, total_count)
    """
    utils = ChEMBLUtils()
    return utils.search_targets(query=query, limit=limit)


def cross_reference_analysis(target_name: str, output_dir: str) -> Dict[str, Any]:
    """
    Convenience function for complete cross-reference analysis.
    
    Args:
        target_name: Target name to analyze
        output_dir: Output directory
        
    Returns:
        Analysis results dictionary
    """
    utils = ChEMBLUtils()
    return utils.cross_reference_ligands_with_pdb(target_name=target_name, output_dir=output_dir)


def parse_pdb_files(input_dir: str) -> List[Dict[str, Any]]:
    """
    Convenience function to parse all PDB files in a directory.
    
    Args:
        input_dir: Directory containing PDB files (default: /input)
        
    Returns:
        List of dictionaries containing parsed PDB header information
        
    Example:
        >>> pdb_files = parse_pdb_files("/input")
        >>> for pdb in pdb_files:
        ...     print(f"PDB: {pdb['pdb_id']}, Protein: {pdb['molecule_name']}")
        ...     print(f"Organism: {pdb['organism']}")
    """
    import glob
    
    pdb_files_list = glob.glob(os.path.join(input_dir, "*.pdb"))
    results = []
    
    print(f"Found {len(pdb_files_list)} PDB file(s) in {input_dir}")
    
    for pdb_file in sorted(pdb_files_list):
        print(f"  Parsing: {os.path.basename(pdb_file)}")
        pdb_info = ChEMBLUtils.parse_pdb_header(pdb_file)
        pdb_info['file_path'] = pdb_file
        results.append(pdb_info)
    
    return results

