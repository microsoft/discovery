"""
PDB utilities for downloading and retrieving information from RCSB PDB.
"""
import os
import requests
import json
from typing import List, Dict, Optional, Union
import pandas as pd


def download_structure(pdb_id: str, output_dir: str, format: str = "pdb") -> str:
    """
    Download a protein structure from RCSB PDB.
    
    Args:
        pdb_id: 4-character PDB identifier
        output_dir: Directory to save the structure file
        format: File format ("pdb" or "cif")
    
    Returns:
        Path to the downloaded structure file, or None if download failed
    """
    pdb_id = pdb_id.lower()
    
    if format.lower() == "pdb":
        url = f"https://files.rcsb.org/download/{pdb_id}.pdb"
        filename = f"{pdb_id}.pdb"
    elif format.lower() == "cif":
        url = f"https://files.rcsb.org/download/{pdb_id}.cif"
        filename = f"{pdb_id}.cif"
    else:
        raise ValueError("Format must be 'pdb' or 'cif'")
    
    os.makedirs(output_dir, exist_ok=True)
    filepath = os.path.join(output_dir, filename)
    
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        
        with open(filepath, 'w') as f:
            f.write(response.text)
        
        print(f"Downloaded: {pdb_id.upper()}")
        return filepath
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            print(f"⚠️ PDB ID '{pdb_id.upper()}' not found - skipping download")
            return None
        else:
            print(f"⚠️ HTTP error downloading '{pdb_id.upper()}': {e}")
            return None
    except requests.exceptions.RequestException as e:
        print(f"⚠️ Request error downloading '{pdb_id.upper()}': {e}")
        return None
    except Exception as e:
        print(f"⚠️ Unexpected error downloading '{pdb_id.upper()}': {e}")
        return None


def get_structure_metadata(pdb_id: str) -> Dict:
    """
    Retrieve comprehensive metadata for a PDB structure.
    
    Args:
        pdb_id: 4-character PDB identifier
    
    Returns:
        Dictionary containing structure metadata, or empty dict if not found
    """
    pdb_id = pdb_id.upper()
    url = f"https://data.rcsb.org/rest/v1/core/entry/{pdb_id}"
    
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            print(f"⚠️ PDB ID '{pdb_id}' not found in RCSB database")
            return {}
        else:
            print(f"⚠️ HTTP error fetching metadata for '{pdb_id}': {e}")
            return {}
    except requests.exceptions.RequestException as e:
        print(f"⚠️ Request error fetching metadata for '{pdb_id}': {e}")
        return {}
    except Exception as e:
        print(f"⚠️ Unexpected error fetching metadata for '{pdb_id}': {e}")
        return {}


def get_structure_info(pdb_id: str) -> Dict:
    """
    Get basic structure information including title, method, resolution.
    
    Args:
        pdb_id: 4-character PDB identifier
    
    Returns:
        Dictionary with basic structure information, or error info if not found
    """
    metadata = get_structure_metadata(pdb_id)
    
    # If metadata is empty, the PDB ID doesn't exist or couldn't be fetched
    if not metadata:
        return {
            "pdb_id": pdb_id.upper(),
            "title": "Structure not found",
            "experimental_method": "N/A",
            "resolution": "N/A",
            "deposition_date": "N/A",
            "classification": "N/A",
            "error": "PDB ID not found or unavailable"
        }
    
    info = {
        "pdb_id": pdb_id.upper(),
        "title": metadata.get("struct", {}).get("title", "N/A"),
        "experimental_method": metadata.get("exptl", [{}])[0].get("method", "N/A"),
        "resolution": metadata.get("refine", [{}])[0].get("ls_dres_high", "N/A"),  # CORRECTED: ls_dres_high (not ls_d_res_high)
        "deposition_date": metadata.get("rcsb_accession_info", {}).get("initial_release_date", "N/A"),
        "classification": metadata.get("struct_keywords", {}).get("pdbx_keywords", "N/A")
    }
    
    return info


def get_sequence_from_structure(pdb_id: str) -> Dict[str, str]:
    """
    Retrieve protein sequences from a PDB structure.
    
    Args:
        pdb_id: 4-character PDB identifier
    
    Returns:
        Dictionary mapping chain IDs to sequences, empty dict if not found
    """
    url = f"https://data.rcsb.org/rest/v1/core/polymer_entity/{pdb_id}"
    
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        
        data = response.json()
        sequences = {}
        
        for entity in data:
            if entity.get("type") == "polypeptide(L)":
                entity_id = entity["rcsb_id"]
                sequence = entity.get("entity_poly", {}).get("pdbx_seq_one_letter_code_can", "")
                sequences[entity_id] = sequence
        
        return sequences
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            print(f"⚠️ No sequence data found for PDB ID '{pdb_id}'")
            return {}
        else:
            print(f"⚠️ HTTP error fetching sequences for '{pdb_id}': {e}")
            return {}
    except requests.exceptions.RequestException as e:
        print(f"⚠️ Request error fetching sequences for '{pdb_id}': {e}")
        return {}
    except Exception as e:
        print(f"⚠️ Unexpected error fetching sequences for '{pdb_id}': {e}")
        return {}


def batch_download_structures(pdb_ids: List[str], output_dir: str, format: str = "pdb") -> List[str]:
    """
    Download multiple PDB structures.
    
    Args:
        pdb_ids: List of 4-character PDB identifiers
        output_dir: Directory to save structure files
        format: File format ("pdb" or "cif")
    
    Returns:
        List of paths to successfully downloaded structure files (excluding None values)
    """
    filepaths = []
    
    for pdb_id in pdb_ids:
        try:
            filepath = download_structure(pdb_id, output_dir, format)
            # Only add successfully downloaded files (download_structure returns None on failure)
            if filepath is not None:
                filepaths.append(filepath)
        except Exception as e:
            print(f"⚠️ Unexpected error downloading {pdb_id}: {str(e)}")
    
    return filepaths


def get_ligand_info(pdb_id: str) -> List[Dict]:
    """
    Get information about ligands bound to a protein structure.
    
    Args:
        pdb_id: 4-character PDB identifier
    
    Returns:
        List of dictionaries containing ligand information
    """
    ligands = []
    
    # First get the entry info to find nonpolymer entity IDs
    entry_url = f"https://data.rcsb.org/rest/v1/core/entry/{pdb_id}"
    
    try:
        entry_response = requests.get(entry_url, timeout=30)
        entry_response.raise_for_status()
        entry_data = entry_response.json()
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            print(f"⚠️ PDB ID '{pdb_id}' not found")
        else:
            print(f"⚠️ HTTP error fetching entry data for '{pdb_id}': {e}")
        return ligands
    except requests.exceptions.RequestException as e:
        print(f"⚠️ Network error fetching entry data for '{pdb_id}': {e}")
        return ligands
    except Exception as e:
        print(f"⚠️ Unexpected error fetching entry data for '{pdb_id}': {e}")
        return ligands
    
    # Get nonpolymer entity IDs from the container identifiers
    nonpolymer_entity_ids = entry_data.get("rcsb_entry_container_identifiers", {}).get("non_polymer_entity_ids", [])
    
    if not nonpolymer_entity_ids:
        # Silently return empty list - this is normal for apo structures
        return ligands
    
    # Fetch each nonpolymer entity
    for entity_id in nonpolymer_entity_ids:
        entity_url = f"https://data.rcsb.org/rest/v1/core/nonpolymer_entity/{pdb_id}/{entity_id}"
        
        try:
            entity_response = requests.get(entity_url, timeout=30)
            entity_response.raise_for_status()
            entity_data = entity_response.json()
            
            # Extract ligand information
            nonpoly_info = entity_data.get("pdbx_entity_nonpoly", {})
            rcsb_info = entity_data.get("rcsb_nonpolymer_entity", {})
            
            ligand_info = {
                "entity_id": entity_id,
                "comp_id": nonpoly_info.get("comp_id", "N/A"),
                "chemical_name": nonpoly_info.get("name", "N/A"),
                "description": rcsb_info.get("pdbx_description", "N/A"),
                "molecular_weight": rcsb_info.get("formula_weight", "N/A"),
                "molecule_count": rcsb_info.get("pdbx_number_of_molecules", "N/A")
            }
            ligands.append(ligand_info)
            
        except requests.exceptions.HTTPError as e:
            print(f"⚠️ Could not fetch ligand info for entity {entity_id}: {e}")
            continue
        except requests.exceptions.RequestException as e:
            print(f"⚠️ Network error fetching ligand {entity_id}: {e}")
            continue
        except Exception as e:
            print(f"⚠️ Unexpected error fetching ligand {entity_id}: {e}")
            continue
    
    return ligands


def save_metadata_to_json(pdb_id: str, output_dir: str) -> str:
    """
    Save complete structure metadata to a JSON file.
    
    Args:
        pdb_id: 4-character PDB identifier
        output_dir: Directory to save the JSON file
    
    Returns:
        Path to the saved JSON file
    """
    metadata = get_structure_metadata(pdb_id)
    
    os.makedirs(output_dir, exist_ok=True)
    filepath = os.path.join(output_dir, f"{pdb_id.lower()}_metadata.json")
    
    with open(filepath, 'w') as f:
        json.dump(metadata, f, indent=2)
    
    return filepath


def get_publication_info(pdb_id: str) -> Dict:
    """
    Get publication information for a PDB structure.
    
    Args:
        pdb_id: 4-character PDB identifier
    
    Returns:
        Dictionary containing publication information
    """
    metadata = get_structure_metadata(pdb_id)
    
    citation = metadata.get("citation", [{}])[0]
    
    pub_info = {
        "title": citation.get("title", "N/A"),
        "authors": citation.get("rcsb_authors", []),
        "journal": citation.get("journal_abbrev", "N/A"),
        "year": citation.get("year", "N/A"),
        "doi": citation.get("pdbx_database_id_DOI", "N/A"),
        "pmid": citation.get("pdbx_database_id_PubMed", "N/A")
    }
    
    return pub_info


def batch_get_metadata_with_progress(pdb_ids: List[str], show_progress: bool = True) -> Dict[str, Dict]:
    """
    Retrieve metadata for multiple PDB structures with progress indicators.
    
    Args:
        pdb_ids: List of PDB identifiers
        show_progress: Whether to print progress updates (default: True)
    
    Returns:
        Dictionary mapping PDB IDs to their metadata dictionaries
    """
    metadata_dict = {}
    total = len(pdb_ids)
    
    if show_progress:
        print(f"📊 Fetching metadata for {total} structures...")
    
    for i, pdb_id in enumerate(pdb_ids, 1):
        metadata = get_structure_metadata(pdb_id)
        metadata_dict[pdb_id] = metadata
        
        # Show progress every 10 structures or at milestones
        if show_progress and (i % 10 == 0 or i == total or i == 1):
            print(f"   ⏳ Progress: {i}/{total} structures processed ({i*100//total}%)")
    
    if show_progress:
        print(f"✅ Metadata retrieval complete!")
    
    return metadata_dict


def batch_get_ligands_with_progress(pdb_ids: List[str], show_progress: bool = True) -> Dict[str, List[Dict]]:
    """
    Retrieve ligand information for multiple PDB structures with progress indicators.
    
    Args:
        pdb_ids: List of PDB identifiers
        show_progress: Whether to print progress updates (default: True)
    
    Returns:
        Dictionary mapping PDB IDs to their ligand info lists
    """
    ligands_dict = {}
    total = len(pdb_ids)
    
    if show_progress:
        print(f"🧪 Checking ligands for {total} structures...")
    
    for i, pdb_id in enumerate(pdb_ids, 1):
        ligands = get_ligand_info(pdb_id)
        ligands_dict[pdb_id] = ligands
        
        # Show progress every 10 structures or at milestones
        if show_progress and (i % 10 == 0 or i == total or i == 1):
            ligand_count = sum(len(ligs) for ligs in ligands_dict.values())
            print(f"   ⏳ Progress: {i}/{total} structures checked ({i*100//total}%) - {ligand_count} ligands found")
    
    if show_progress:
        total_ligands = sum(len(ligs) for ligs in ligands_dict.values())
        print(f"✅ Ligand check complete! Found ligands in {sum(1 for ligs in ligands_dict.values() if ligs)} structures")
    
    return ligands_dict
