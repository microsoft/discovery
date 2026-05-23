#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PDBInsights_utils.py — Generic PDB harvesting, preparation & quality report (library)

This module provides reusable functions to:
- Search PDB entries by protein name or UniProt accession
- Fetch per-entry crystallographic/NMR metrics from mmCIF (resolution, R/Rfree, Rwork)
- Parse wwPDB validation XML (clashscore, Ramachandran/rotamer stats)
- Compute model-0 atoms/chains (avoids multi-model NMR double-counting)
- Retrieve biological assembly & symmetry metadata (RCSB)
- Classify domain coverage (ECD/TMD/ICD) using polymer_entity features with UniProt anchoring
- Detect binding partners (antibody/DARPin/peptide/ligands) generically
- Rank structures with quality heuristics (resolution, R-factors, validation metrics, context)

Standalone preparation utilities (file-based):
- download_pdb: Download PDB/mmCIF files from RCSB
- clean_structure: Remove heteroatoms, waters, filter chains using BioPython
- fix_structure_with_pdbfixer: Add missing atoms/residues, add hydrogens
- clean_and_fix_structure: Combined cleaning + fixing workflow

High-level workflows (text-based API):
- analyze_entries: Full analysis of PDB IDs with optional download/clean/protonate
- search_and_analyze_by_uniprot: Complete search → analyze workflow

No code runs at import time; there is no CLI main.
"""
from __future__ import annotations

import os
import io
import csv
import json
import time
import gzip
from typing import Any, Dict, List, Optional, Set, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from requests.adapters import HTTPAdapter, Retry

# Optional Biopython — functions degrade gracefully if not installed
try:
    from Bio.PDB import PDBParser, MMCIFParser, PDBIO, Select  # type: ignore
    from Bio.PDB.MMCIF2Dict import MMCIF2Dict  # type: ignore
    try:
        # Some versions provide a specific warning class for construction issues
        from Bio.PDB.PDBExceptions import PDBConstructionWarning  # type: ignore
    except Exception:
        PDBConstructionWarning = None  # type: ignore
except Exception:
    PDBParser = MMCIFParser = PDBIO = Select = MMCIF2Dict = None  # type: ignore
    PDBConstructionWarning = None  # type: ignore

# Optional PDBFixer/OpenMM — protonation is skipped if not installed
try:
    import pdbfixer  # type: ignore
    from openmm.app import PDBFile  # type: ignore
except Exception:
    pdbfixer = None  # type: ignore
    PDBFile = None   # type: ignore

import xml.etree.ElementTree as ET

# --- Endpoints ---
RCSB_SEARCH_URL = "https://search.rcsb.org/rcsbsearch/v2/query?json=true"
RCSB_GRAPHQL_URL = "https://data.rcsb.org/graphql"
RCSB_ENTRY_API  = "https://data.rcsb.org/rest/v1/core/entry/{pdbid}"
RCSB_ASSEMBLY_API = "https://data.rcsb.org/rest/v1/core/assembly/{pdbid}/{assembly_id}"
RCSB_SYMMETRY_API = "https://data.rcsb.org/rest/v1/core/symmetry/{pdbid}"
RCSB_ENTITY_API = "https://data.rcsb.org/rest/v1/core/polymer_entity/{pdbid}/{entid}"
RCSB_FILES_CIF = "https://files.rcsb.org/download/{pdbid}.cif"
RCSB_FILES_PDB = "https://files.rcsb.org/download/{pdbid}.pdb"
WWPDB_DIVIDED_CIF = "https://files.wwpdb.org/pub/pdb/data/structures/divided/mmCIF/{two}/{pdbid}.cif.gz"
WWPDB_VALIDATION_XML = "https://files.wwpdb.org/pub/pdb/validation_reports/{two}/{pdbid}/{pdbid}_validation.xml"


# --- HTTP session ---
def make_session() -> requests.Session:
    s = requests.Session()
    retries = Retry(
        total=5, backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET", "POST"]),
        raise_on_status=False,
    )
    s.mount("https://", HTTPAdapter(max_retries=retries))
    s.headers.update({"User-Agent": "PDBInsights-lib/0.4 (generic harvest)"})
    return s


SESSION = make_session()
UNIPROT_FEATURE_CACHE: Dict[str, Dict[str, Any]] = {}
VALIDATION_FETCH_STATE = {"disabled": False, "reason": ""}


def _location_value(loc: Optional[Dict[str, Any]]) -> Optional[int]:
    if not isinstance(loc, dict):
        return None
    for key in ("value", "start", "begin", "from", "pos", "beg_seq_id", "beg_seq_num"):
        val = loc.get(key)
        if isinstance(val, (int, float)):
            return int(val)
        if isinstance(val, str) and val.isdigit():
            return int(val)
    return None


def fetch_uniprot_topology(uniprot_id: str) -> Dict[str, Any]:
    if not uniprot_id:
        return {}
    if uniprot_id in UNIPROT_FEATURE_CACHE:
        return UNIPROT_FEATURE_CACHE[uniprot_id]
    url = f"https://rest.uniprot.org/uniprotkb/{uniprot_id}.json"
    features: List[Tuple[int, int]] = []
    sequence_length: Optional[int] = None
    try:
        resp = SESSION.get(url, timeout=30)
        if resp.ok:
            data = resp.json()
            sequence_value = (((data.get("sequence") or {}).get("value")) or "")
            if sequence_value:
                sequence_length = len(sequence_value)
            for feat in data.get("features", []):
                ftype = str(feat.get("type", ""))
                if ftype.upper() not in ("TRANSMEM", "TRANSMEMBRANE"):
                    continue
                loc = feat.get("location", {})
                start = _location_value(loc.get("start"))
                end = _location_value(loc.get("end"))
                if start is not None and end is not None:
                    features.append((int(start), int(end)))
    except Exception:
        pass
    topology = {"tmd_ranges": sorted(features), "sequence_length": sequence_length}
    UNIPROT_FEATURE_CACHE[uniprot_id] = topology
    return topology


# --- Utils ---
def ensure_dir(path: str) -> str:
    os.makedirs(path, exist_ok=True)
    return path


def fetch_text(url: str, timeout: int = 30) -> Optional[str]:
    r = SESSION.get(url, timeout=timeout)
    if not r.ok:
        return None
    return r.text


def fetch_binary(url: str, timeout: int = 5) -> Optional[bytes]:
    r = SESSION.get(url, timeout=timeout)
    if not r.ok:
        return None
    return r.content


def fetch_json(url: str, timeout: int = 30) -> Optional[Dict[str, Any]]:
    r = SESSION.get(url, timeout=timeout)
    if not r.ok:
        return None
    try:
        return r.json()
    except Exception:
        return None


def download_text(url: str, out_path: str) -> Optional[str]:
    try:
        txt = fetch_text(url)
        if not txt:
            return None
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(txt)
        return out_path
    except Exception:
        return None


def fetch_graphql(query: str, timeout: int = 60) -> Optional[Dict[str, Any]]:
    """Execute a GraphQL query against RCSB GraphQL API."""
    try:
        r = SESSION.post(RCSB_GRAPHQL_URL, json={"query": query}, timeout=timeout)
        if not r.ok:
            return None
        return r.json()
    except Exception:
        return None


def fetch_entries_batch(pdb_ids: List[str]) -> Dict[str, Dict[str, Any]]:
    """
    Fetch multiple entry records in a single GraphQL call.
    
    Returns dict mapping pdb_id -> entry_data
    """
    if not pdb_ids:
        return {}
    
    # Format PDB IDs for GraphQL query
    ids_str = ', '.join(f'"{pid.upper()}"' for pid in pdb_ids)
    
    query = f"""
    {{
      entries(entry_ids: [{ids_str}]) {{
        rcsb_id
        struct {{ title }}
        exptl {{ method }}
        rcsb_entry_container_identifiers {{
          polymer_entity_ids
          assembly_ids
        }}
      }}
    }}
    """
    
    result = fetch_graphql(query)
    if not result or "data" not in result or "entries" not in result["data"]:
        return {}
    
    # Convert to dict keyed by PDB ID
    entries_dict = {}
    for entry in result["data"]["entries"]:
        pdb_id = entry.get("rcsb_id")
        if pdb_id:
            entries_dict[pdb_id.upper()] = entry
    
    return entries_dict


def fetch_entities_batch(entity_ids: List[str]) -> Dict[str, Dict[str, Any]]:
    """
    Fetch multiple polymer entity records in a single GraphQL call.
    
    Args:
        entity_ids: List of entity IDs in format "PDBID_ENTITYID" (e.g., "1CRN_1", "2HHB_1")
    
    Returns dict mapping entity_id -> entity_data
    """
    if not entity_ids:
        return {}
    
    # Format entity IDs for GraphQL query
    ids_str = ', '.join(f'"{eid}"' for eid in entity_ids)
    
    query = f"""
    {{
      polymer_entities(entity_ids: [{ids_str}]) {{
        rcsb_id
        entity_poly {{ pdbx_seq_one_letter_code_can }}
        rcsb_polymer_entity_container_identifiers {{
          reference_sequence_identifiers {{
            database_name
            database_accession
          }}
        }}
        rcsb_polymer_entity_feature {{
          type
          description
        }}
      }}
    }}
    """
    
    result = fetch_graphql(query)
    if not result or "data" not in result or "polymer_entities" not in result["data"]:
        return {}
    
    # Convert to dict keyed by entity ID
    entities_dict = {}
    for entity in result["data"]["polymer_entities"]:
        entity_id = entity.get("rcsb_id")
        if entity_id:
            entities_dict[entity_id] = entity
    
    return entities_dict


# --- Standalone Structure Preparation Utilities ---
def download_pdb(pdb_id: str, out_dir: str, file_format: str = "pdb") -> Optional[str]:
    """
    Download PDB or mmCIF file from RCSB.
    
    Args:
        pdb_id: 4-character PDB identifier
        out_dir: Output directory (default: /output/pdbs)
        file_format: File format - 'pdb' or 'cif' (default: pdb)
    
    Returns:
        Path to downloaded file, or None if failed
    """
    ensure_dir(out_dir)
    pdb_id = pdb_id.upper()
    
    if file_format.lower() == "cif":
        url = RCSB_FILES_CIF.format(pdbid=pdb_id)
        ext = ".cif"
    else:
        url = RCSB_FILES_PDB.format(pdbid=pdb_id)
        ext = ".pdb"
    
    out_path = os.path.join(out_dir, f"{pdb_id}{ext}")
    return download_text(url, out_path)


def clean_structure(
    input_pdb: str,
    output_pdb: str,
    remove_hetatm: bool = True,
    remove_waters: bool = True,
    chain_ids: Optional[List[str]] = None
) -> str:
    """
    Clean PDB file using BioPython: remove heteroatoms, waters, filter chains.
    
    Args:
        input_pdb: Path to input PDB file
        output_pdb: Path to output cleaned PDB file
        remove_hetatm: Remove HETATM records (default: True)
        remove_waters: Remove water molecules (default: True)
        chain_ids: List of chain IDs to keep (default: None = keep all)
    
    Returns:
        Path to output file
    
    Raises:
        RuntimeError: If BioPython not available or structure would be empty
    """
    if not PDBParser or not PDBIO:
        raise RuntimeError("BioPython not available. Install: pip install biopython")
    
    class CleanSelector(Select):  # type: ignore
        def accept_residue(self, residue):  # type: ignore
            if remove_waters and residue.get_resname() == "HOH":
                return False
            if remove_hetatm and residue.id[0] != " ":
                return False
            return True
        
        def accept_chain(self, chain):  # type: ignore
            if chain_ids is None:
                return True
            return chain.id in chain_ids
    
    parser = PDBParser(QUIET=True)
    structure = parser.get_structure("input", input_pdb)
    
    # Verify not empty
    selector = CleanSelector()
    has_content = False
    for model in structure:
        for chain in model:
            if selector.accept_chain(chain):
                for residue in chain:
                    if selector.accept_residue(residue):
                        has_content = True
                        break
            if has_content:
                break
        if has_content:
            break
    
    if not has_content:
        raise ValueError("Cleaned structure would be empty. Input may not have protein atoms or all were filtered.")
    
    io_writer = PDBIO()
    io_writer.set_structure(structure)
    io_writer.save(output_pdb, selector)
    return output_pdb


def fix_structure_with_pdbfixer(
    pdb_path: str,
    out_fixed: str,
    add_hydrogens: bool = True,
    pH: float = 7.0
) -> Dict[str, int]:
    """
    Fix structure using PDBFixer: add missing atoms/residues, optionally add hydrogens.
    
    Args:
        pdb_path: Path to input PDB file
        out_fixed: Path to output fixed PDB file
        add_hydrogens: Add hydrogens at specified pH (default: True)
        pH: pH for hydrogen placement (default: 7.0)
    
    Returns:
        Dictionary with counts of missing residues and atoms that were fixed
    
    Raises:
        RuntimeError: If PDBFixer not available or file cannot be parsed
    """
    if not pdbfixer or not PDBFile:
        raise RuntimeError("PDBFixer/OpenMM not available. Install: pip install pdbfixer")
    
    try:
        fixer = pdbfixer.PDBFixer(filename=pdb_path)
    except Exception as e:
        raise RuntimeError(f"PDBFixer could not parse {pdb_path}. Error: {e}") from e
    
    missing_residues = fixer.findMissingResidues()
    fixer.findNonstandardResidues()
    fixer.replaceNonstandardResidues()
    missing_atoms = fixer.findMissingAtoms()
    fixer.addMissingAtoms()
    
    if add_hydrogens:
        try:
            fixer.addMissingHydrogens(pH)
        except Exception as e:
            print(f"Warning: Could not add hydrogens ({e}). Continuing without hydrogens.")
    
    with open(out_fixed, 'w', encoding='utf-8') as f:
        PDBFile.writeFile(fixer.topology, fixer.positions, f)
    
    return {
        "missing_residues_fixed": len(missing_residues) if missing_residues else 0,
        "missing_atoms_fixed": len(missing_atoms) if missing_atoms else 0,
        "chains": len(list(fixer.topology.chains()))
    }


def clean_and_fix_structure(
    input_pdb: str,
    output_pdb: str,
    remove_waters: bool = True,
    add_hydrogens: bool = True,
    chain_ids: Optional[List[str]] = None,
    pH: float = 7.0
) -> Dict[str, Any]:
    """
    Combined cleaning and fixing using PDBFixer (more robust than separate steps).
    
    Args:
        input_pdb: Path to input PDB file
        output_pdb: Path to output fixed PDB file
        remove_waters: Remove water molecules (default: True)
        add_hydrogens: Add hydrogens at specified pH (default: True)
        chain_ids: List of chain IDs to keep (default: None = keep all)
        pH: pH for hydrogen placement (default: 7.0)
    
    Returns:
        Dictionary with counts of missing residues/atoms fixed and chains kept
    
    Raises:
        RuntimeError: If PDBFixer not available or file cannot be parsed
    """
    if not pdbfixer or not PDBFile:
        raise RuntimeError("PDBFixer/OpenMM not available. Install: pip install pdbfixer")
    
    try:
        fixer = pdbfixer.PDBFixer(filename=input_pdb)
    except Exception as e:
        raise RuntimeError(f"PDBFixer could not parse {input_pdb}. Error: {e}") from e
    
    # Filter chains if specified
    if chain_ids:
        chains_to_remove = [chain for chain in fixer.topology.chains() 
                           if chain.id not in chain_ids]
        fixer.removeChains(chainIds=[chain.index for chain in chains_to_remove])
    
    # Remove heterogens (ligands) but optionally keep waters
    fixer.removeHeterogens(keepWater=not remove_waters)
    
    # Find and fix issues
    missing_residues = fixer.findMissingResidues()
    fixer.findNonstandardResidues()
    fixer.replaceNonstandardResidues()
    missing_atoms = fixer.findMissingAtoms()
    fixer.addMissingAtoms()
    
    if add_hydrogens:
        try:
            fixer.addMissingHydrogens(pH)
        except Exception as e:
            print(f"Warning: Could not add hydrogens ({e}). Continuing without hydrogens.")
    
    with open(output_pdb, 'w', encoding='utf-8') as f:
        PDBFile.writeFile(fixer.topology, fixer.positions, f)
    
    return {
        "missing_residues_fixed": len(missing_residues) if missing_residues else 0,
        "missing_atoms_fixed": len(missing_atoms) if missing_atoms else 0,
        "chains_kept": len(list(fixer.topology.chains()))
    }


# --- Search ---
def search_pdb_by_protein_name(protein_name: str, limit: int = 200) -> List[str]:
    """Search RCSB PDB by protein name using multiple search strategies.
    
    Args:
        protein_name: Protein name (e.g., "Erythropoietin Receptor", "hemoglobin")
        limit: Maximum number of PDB IDs to return
    
    Returns:
        List of PDB IDs
    """
    pdb_ids_set = set()
    
    # Strategy 1: Full text search
    payloads = [
        {
            "query": {
                "type": "terminal",
                "service": "full_text",
                "parameters": {"value": protein_name}
            },
            "return_type": "entry"
        }
    ]
    
    # Strategy 2: Entity name search
    payloads.append({
        "query": {
            "type": "terminal",
            "service": "text",
            "parameters": {
                "attribute": "rcsb_entity_names.name",
                "operator": "contains_words",
                "value": protein_name
            }
        },
        "return_type": "entry"
    })
    
    # Strategy 3: Struct title search
    payloads.append({
        "query": {
            "type": "terminal",
            "service": "text",
            "parameters": {
                "attribute": "struct.title",
                "operator": "contains_words",
                "value": protein_name
            }
        },
        "return_type": "entry"
    })
    
    for payload in payloads:
        try:
            r = SESSION.post(RCSB_SEARCH_URL, json=payload, timeout=30)
            if r.status_code == 200:
                data = r.json()
                for item in data.get("result_set", []):
                    pdb_ids_set.add(item["identifier"].upper())
                    if len(pdb_ids_set) >= limit:
                        break
        except Exception:
            continue
        if len(pdb_ids_set) >= limit:
            break
    
    return sorted(list(pdb_ids_set))[:limit]


def get_uniprot_ids_from_pdb(pdb_id: str) -> List[str]:
    """Get all UniProt IDs associated with a PDB entry.
    
    Args:
        pdb_id: PDB identifier
    
    Returns:
        List of UniProt IDs found in this structure
    """
    uniprot_ids = []
    try:
        entry_json = fetch_json(RCSB_ENTRY_API.format(pdbid=pdb_id.upper()))
        if not entry_json:
            return []
        
        # Get polymer entity IDs
        entity_ids = (entry_json.get("rcsb_entry_container_identifiers", {}) or {}).get("polymer_entity_ids", []) or []
        
        for entity_id in entity_ids:
            entity_json = fetch_json(RCSB_ENTITY_API.format(pdbid=pdb_id.upper(), entid=entity_id))

            if not entity_json:
                continue

            # Extract UniProt IDs
            ref_seqs = ((entity_json.get("rcsb_polymer_entity_container_identifiers", {}) or {})
                       .get("reference_sequence_identifiers", []) or [])

            for ref in ref_seqs:
                db_name = ref.get("database_name", "")
                if db_name in ("UniProt", "UNP"):
                    acc = ref.get("database_accession")
                    if acc and acc not in uniprot_ids:
                        uniprot_ids.append(acc)
    except Exception:
        pass
    
    return uniprot_ids


def search_and_get_uniprot_mapping(protein_name: str, limit: int = 50) -> Dict[str, Any]:
    """Search for PDB structures by protein name and extract all associated UniProt IDs.
    
    This is the recommended first step when the user provides a protein name instead of a UniProt ID.
    
    Args:
        protein_name: Protein name (e.g., "Erythropoietin Receptor")
        limit: Maximum number of PDB structures to check
    
    Returns:
        Dict with:
        - pdb_ids: List of PDB IDs found
        - uniprot_ids: List of unique UniProt IDs (most common first)
        - mapping: Dict of {pdb_id: [uniprot_ids]}
        - primary_uniprot: Most common UniProt ID (best guess for the protein)
    """
    # Search for PDB IDs
    pdb_ids = search_pdb_by_protein_name(protein_name, limit=limit)
    
    if not pdb_ids:
        return {
            "pdb_ids": [],
            "uniprot_ids": [],
            "mapping": {},
            "primary_uniprot": None
        }
    
    # Extract UniProt IDs from each PDB entry
    mapping = {}
    uniprot_count = {}
    
    for pdb_id in pdb_ids[:limit]:  # Limit API calls
        uniprot_ids = get_uniprot_ids_from_pdb(pdb_id)
        mapping[pdb_id] = uniprot_ids
        
        for uid in uniprot_ids:
            uniprot_count[uid] = uniprot_count.get(uid, 0) + 1
    
    # Sort UniProt IDs by frequency (most common first)
    unique_uniprot_ids = sorted(uniprot_count.keys(), key=lambda x: uniprot_count[x], reverse=True)
    
    return {
        "pdb_ids": pdb_ids,
        "uniprot_ids": unique_uniprot_ids,
        "mapping": mapping,
        "primary_uniprot": unique_uniprot_ids[0] if unique_uniprot_ids else None
    }


def search_pdb_by_uniprot(uniprot_id: str, limit: int = 200) -> List[str]:
    """Search RCSB PDB for structures with a given UniProt accession."""
    payload = {
        "query": {
            "type": "terminal",
            "service": "text",
            "parameters": {
                "attribute": "rcsb_polymer_entity_container_identifiers.reference_sequence_identifiers.database_accession",
                "operator": "in",
                "value": [uniprot_id],
            },
        },
        "return_type": "entry",
        "request_options": {
            "return_all_hits": True
        }
    }
    try:
        r = SESSION.post(RCSB_SEARCH_URL, json=payload, timeout=30)
        r.raise_for_status()
        data = r.json()
        pdb_ids = [item["identifier"] for item in data.get("result_set", [])[:limit]]
        return pdb_ids
    except Exception:
        return []


# --- Parsing metrics ---
def parse_metrics_from_mmcif_text(cif_text: str) -> Dict[str, Optional[float]]:
    """Return resolution, R_free, R_work parsed from mmCIF text (None if unavailable)."""
    out: Dict[str, Optional[float]] = {"resolution": None, "r_free": None, "r_work": None}
    if MMCIF2Dict is None or not cif_text:
        return out
    try:
        d = MMCIF2Dict(io.StringIO(cif_text))
        def _get(key: str) -> Optional[float]:
            v = d.get(key, [None])
            return float(v[0]) if v and v[0] not in (None, ".", "?", "") else None
        out["resolution"] = _get("_refine.ls_d_res_high")
        out["r_free"]     = _get("_refine.ls_R_factor_R_free")
        out["r_work"]     = _get("_refine.ls_R_factor_R_work")
    except Exception:
        pass
    return out


def fetch_validation_report(pdbid: str) -> Dict[str, Optional[float]]:
    """Return clashscore, Rama favored/outliers %, rotamer outliers % from wwPDB validation XML."""
    out: Dict[str, Any] = {
        "clashscore": None,
        "ramachandran_outliers_percent": None,
        "ramachandran_favored_percent": None,
        "rotamer_outliers_percent": None,
        "validation_source": "missing",
    }

    if VALIDATION_FETCH_STATE["disabled"]:
        reason = VALIDATION_FETCH_STATE.get("reason") or "disabled"
        out["validation_source"] = reason
        return out

    def _parse_float(val: Any) -> Optional[float]:
        try:
            return float(str(val).strip())
        except Exception:
            return None

    if not pdbid or len(pdbid) < 4:
        return out

    pdb_variants = {pdbid.lower(), pdbid.upper()}
    candidate_urls: List[str] = []
    for code in pdb_variants:
        try:
            two = code[1:3]
        except Exception:
            continue
        for two_variant in {two.lower(), two.upper()}:
            base = WWPDB_VALIDATION_XML.format(two=two_variant, pdbid=code)
            candidate_urls.append(base + ".gz")
            candidate_urls.append(base)

    # Deduplicate while preserving priority (always try gzipped payloads first).
    candidate_urls = list(dict.fromkeys(candidate_urls))

    xml_text: Optional[str] = None
    network_fail_reason: Optional[str] = None

    for url in candidate_urls:
        try:
            resp = requests.get(url, timeout=8, headers=SESSION.headers)
        except requests.Timeout:
            network_fail_reason = "timeout"
            continue
        except requests.RequestException as exc:
            network_fail_reason = exc.__class__.__name__
            continue
        if not resp.ok or not resp.content:
            status = resp.status_code
            if status in (503, 504):
                network_fail_reason = f"{status}"
            continue

        content_bytes = resp.content
        if url.endswith(".gz") or "gzip" in (resp.headers.get("Content-Type", "").lower()):
            # Validation reports are distributed as standalone gzip files, not HTTP-compressed payloads.
            try:
                content_bytes = gzip.decompress(content_bytes)
            except OSError:
                continue

        try:
            candidate_text = content_bytes.decode(resp.encoding or "utf-8", errors="ignore")
        except Exception:
            continue

        if "<html" in candidate_text.lower():
            continue
        xml_text = candidate_text
        break

    if not xml_text:
        if network_fail_reason:
            VALIDATION_FETCH_STATE["disabled"] = True
            VALIDATION_FETCH_STATE["reason"] = network_fail_reason
            print(
                f"    -> Validation reports unavailable ({network_fail_reason}); continuing without validation metrics",
                flush=True,
            )
        return out

    try:
        root = ET.fromstring(xml_text)
    except Exception:
        return out

    out["validation_source"] = "xml"

    attr_aliases: Dict[str, List[str]] = {
        "clashscore": ["clashscore"],
        "ramachandran_outliers_percent": ["percent-rama-outliers", "percent-ramachandran-outliers"],
        "ramachandran_favored_percent": ["percent-rama-favored", "percent-ramachandran-favored"],
        "ramachandran_allowed_percent": ["percent-rama-allowed", "percent-ramachandran-allowed"],
        "rotamer_outliers_percent": ["percent-rota-outliers", "percent-rotamer-outliers"],
    }

    temp_values: Dict[str, Optional[float]] = {key: None for key in attr_aliases}

    for elem in root.iter():
        attrs = elem.attrib
        if not attrs:
            continue
        for key, aliases in attr_aliases.items():
            if temp_values[key] is not None:
                continue
            for alias in aliases:
                if alias in attrs:
                    temp_values[key] = _parse_float(attrs.get(alias))
                    if temp_values[key] is not None:
                        break

    out["clashscore"] = temp_values.get("clashscore")
    out["ramachandran_outliers_percent"] = temp_values.get("ramachandran_outliers_percent")
    out["rotamer_outliers_percent"] = temp_values.get("rotamer_outliers_percent")
    out["ramachandran_favored_percent"] = temp_values.get("ramachandran_favored_percent")

    allowed = temp_values.get("ramachandran_allowed_percent")
    if out["ramachandran_favored_percent"] is None and allowed is not None and out["ramachandran_outliers_percent"] is not None:
        favored = 100.0 - allowed - out["ramachandran_outliers_percent"]
        out["ramachandran_favored_percent"] = round(favored, 2)

    return out


def compute_model0_geometry_from_cif_text(cif_text: str, pdbid: str) -> Dict[str, Optional[int]]:
    """Count chains and atoms in model 0 of the structure described by the mmCIF text."""
    if MMCIFParser is None:
        return {"chains": None, "atom_count": None}
    try:
        parser = MMCIFParser(QUIET=True)
        # Suppress noisy PDBConstructionWarning emitted by Biopython for discontinuous chains
        if PDBConstructionWarning is not None:
            import warnings
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", category=PDBConstructionWarning)
                structure = parser.get_structure(pdbid, io.StringIO(cif_text))
        else:
            structure = parser.get_structure(pdbid, io.StringIO(cif_text))
        model = next(structure.get_models())
        chains = sum(1 for _ in model.get_chains())
        atoms = sum(1 for _ in model.get_atoms())
        return {"chains": chains, "atom_count": atoms}
    except Exception:
        return {"chains": None, "atom_count": None}


# --- RCSB metadata ---
def analyze_biological_assembly(
    pdbid: str,
    uniprot_id: Optional[str] = None,
    entry_json: Optional[Dict[str, Any]] = None,
    entity_jsons: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Inspect biological assemblies and select the most relevant one for analysis."""

    info = {
        "biological_assembly_count": 0,
        "assembly_ids": [],
        "oligomeric_details": [],
        "symmetry": None,
        "analysis_assembly_id": None,
        "analysis_symmetry": None,
        "assembly_alternates": [],
    }

    try:
        entry = entry_json if entry_json is not None else (fetch_json(RCSB_ENTRY_API.format(pdbid=pdbid)) or {})
        if not entry:
            return info

        ids = entry.get("rcsb_entry_container_identifiers", {}).get("assembly_ids", []) or []
        info["assembly_ids"] = ids
        info["biological_assembly_count"] = len(ids)

        methods = [e.get("method", "") for e in entry.get("exptl", []) or []]
        is_nmr = any("NMR" in (m or "").upper() for m in methods)

        if not ids:
            if is_nmr:
                info["symmetry"] = "N/A"
            return info

        entry_entity_ids = entry.get("rcsb_entry_container_identifiers", {}).get("polymer_entity_ids", []) or []
        entity_rest_cache: Dict[str, Dict[str, Any]] = {}
        asym_to_entity: Dict[str, str] = {}
        target_entities: Set[str] = set()

        partner_keywords = ("erythropoietin", "epo", "fab", "darpin", "diabody", "nanobody", "peptide")

        for entid in entry_entity_ids:
            rest_json = fetch_json(RCSB_ENTITY_API.format(pdbid=pdbid, entid=entid)) or {}
            if rest_json:
                entity_rest_cache[str(entid)] = rest_json
                asym_ids = rest_json.get("rcsb_polymer_entity_container_identifiers", {}).get("asym_ids", []) or []
                for asym in asym_ids:
                    asym_to_entity[asym] = str(entid)
                if uniprot_id:
                    rest_ids = rest_json.get("rcsb_polymer_entity_container_identifiers", {}).get("uniprot_ids", []) or []
                    if any(isinstance(uid, str) and uid.upper() == uniprot_id.upper() for uid in rest_ids):
                        target_entities.add(str(entid))

            gql_key = f"{pdbid.upper()}_{entid}"
            gql_entity = entity_jsons.get(gql_key) if entity_jsons else None
            if uniprot_id and gql_entity and _entity_maps_to_uniprot(gql_entity, uniprot_id):
                target_entities.add(str(entid))

        sym_overall = fetch_json(RCSB_SYMMETRY_API.format(pdbid=pdbid)) or {}

        assembly_jsons: Dict[str, Dict[str, Any]] = {}
        assembly_entities: Dict[str, Set[str]] = {}
        assembly_partner_flags: Dict[str, bool] = {}
        assembly_symmetry: Dict[str, Optional[str]] = {}
        assembly_details: Dict[str, str] = {}

        def derive_symmetry(assembly_json: Dict[str, Any]) -> Optional[str]:
            struct_sym = assembly_json.get("rcsb_struct_symmetry") or []
            if isinstance(struct_sym, list) and struct_sym:
                sym0 = struct_sym[0].get("symbol") or struct_sym[0].get("kind")
                if sym0:
                    return sym0
            if sym_overall:
                sym0 = sym_overall.get("symbol") or sym_overall.get("kind")
                if sym0:
                    return sym0
            detail_text: Optional[str] = None
            struct_biol = assembly_json.get("pdbx_struct_assembly")
            if isinstance(struct_biol, list) and struct_biol:
                detail_text = struct_biol[0].get("details")
            elif isinstance(struct_biol, dict):
                detail_text = struct_biol.get("details")
            detail_text = detail_text or (assembly_json.get("rcsb_assembly_info", {}) or {}).get("assembly_form")
            if detail_text:
                upper = detail_text.upper()
                if "TETRAMER" in upper:
                    return "C4"
                if "TRIMER" in upper:
                    return "C3"
                if "DIMER" in upper:
                    return "C2"
            oligomeric = (assembly_json.get("rcsb_assembly_info", {}) or {}).get("oligomeric_state") or ""
            upper = oligomeric.upper()
            if "TETRAMER" in upper:
                return "C4"
            if "TRIMER" in upper:
                return "C3"
            if "DIMER" in upper:
                return "C2"
            return None

        def has_partner(entity_ids: Set[str]) -> bool:
            for entity_id in entity_ids:
                if target_entities and entity_id in target_entities:
                    continue
                rest_json = entity_rest_cache.get(entity_id)
                if not rest_json:
                    continue
                names = rest_json.get("rcsb_polymer_entity_container_identifiers", {}).get("entity_name")
                if isinstance(names, list):
                    descriptor = " ".join(names)
                else:
                    descriptor = names or ""
                classification = rest_json.get("entity_poly", {}).get("pdbx_description") or ""
                haystack = f"{descriptor} {classification}".lower()
                if any(keyword in haystack for keyword in partner_keywords):
                    return True
            return False

        for aid in ids:
            assembly_json = fetch_json(RCSB_ASSEMBLY_API.format(pdbid=pdbid, assembly_id=aid)) or {}
            assembly_jsons[aid] = assembly_json

            struct_biol = assembly_json.get("pdbx_struct_assembly")
            detail_text: Optional[str] = None
            if isinstance(struct_biol, list) and struct_biol:
                detail_text = struct_biol[0].get("details")
            elif isinstance(struct_biol, dict):
                detail_text = struct_biol.get("details")
            detail_text = detail_text or (assembly_json.get("rcsb_assembly_info", {}) or {}).get("assembly_form")
            if detail_text:
                assembly_details[aid] = detail_text

            polymers = assembly_json.get("rcsb_polymer_assembly") or []
            entity_ids: Set[str] = set()
            for polymer in polymers:
                for asym in polymer.get("asym_ids", []) or []:
                    ent = asym_to_entity.get(asym)
                    if ent:
                        entity_ids.add(str(ent))
            if not entity_ids:
                asym_ids = assembly_json.get("rcsb_assembly_container_identifiers", {}).get("asym_ids", []) or []
                for asym in asym_ids:
                    ent = asym_to_entity.get(asym)
                    if ent:
                        entity_ids.add(str(ent))

            assembly_entities[aid] = entity_ids
            assembly_partner_flags[aid] = has_partner(entity_ids)
            assembly_symmetry[aid] = derive_symmetry(assembly_json)

        info["oligomeric_details"] = [assembly_details[aid] for aid in ids if aid in assembly_details]

        def symmetry_priority(sym: Optional[str]) -> int:
            if not sym:
                return 10
            sym_upper = sym.upper()
            if sym_upper.startswith("D") or sym_upper.startswith("T") or sym_upper == "I":
                return 0
            if sym_upper.startswith("C"):
                try:
                    order = int(sym_upper[1:])
                except ValueError:
                    order = 9
                return 1 if order <= 4 else 3
            if sym_upper.startswith("H"):
                return 2
            return 5

        def assembly_sort_key(aid: str) -> Tuple[int, int, int, int, str]:
            entities = assembly_entities.get(aid, set())
            target_matches = len(entities & target_entities)
            partner_flag = assembly_partner_flags.get(aid, False)
            symmetry_rank = symmetry_priority(assembly_symmetry.get(aid))
            entity_count = len(entities) if entities else 999
            return (-target_matches, 0 if not partner_flag else 1, entity_count, symmetry_rank, aid)

        preferred_id = entry.get("rcsb_entry_info", {}).get("preferred_assembly_id")
        relevant_ids = [aid for aid in ids if not target_entities or (assembly_entities.get(aid) and (assembly_entities[aid] & target_entities))]
        candidate_ids = relevant_ids or ids

        chosen: Optional[str] = None
        if preferred_id and preferred_id in candidate_ids:
            chosen = preferred_id
        elif candidate_ids:
            chosen = sorted(candidate_ids, key=assembly_sort_key)[0]

        if not chosen and "1" in ids:
            chosen = "1"
        if not chosen and ids:
            chosen = ids[0]

        if chosen:
            info["analysis_assembly_id"] = chosen
            info["analysis_symmetry"] = assembly_symmetry.get(chosen) or sym_overall.get("symbol") or sym_overall.get("kind")
            info["symmetry"] = info["analysis_symmetry"]
            alternates = [aid for aid in candidate_ids if aid != chosen]
            if alternates:
                info["assembly_alternates"] = alternates
        else:
            info["symmetry"] = sym_overall.get("symbol") or sym_overall.get("kind")

    except Exception:
        pass

    return info


def _entity_maps_to_uniprot(entity_json: Dict[str, Any], uniprot_id: str) -> bool:
    ids = (entity_json.get("rcsb_polymer_entity_container_identifiers", {}) or {}) \
            .get("reference_sequence_identifiers", []) or []
    for rid in ids:
        if (rid.get("database_name") in ("UniProt", "UNP")) and (rid.get("database_accession") == uniprot_id):
            return True
    rest_ids = (entity_json.get("rcsb_polymer_entity_container_identifiers", {}) or {}).get("uniprot_ids", []) or []
    for acc in rest_ids:
        if isinstance(acc, str) and acc.upper() == uniprot_id.upper():
            return True
    return False


def _extract_uniprot_ranges(entity_json: Dict[str, Any], uniprot_id: str) -> List[Tuple[int, int]]:
    ranges: List[Tuple[int, int]] = []

    def _append_range(start: Optional[int], end: Optional[int], length: Optional[int] = None) -> None:
        if start is None:
            return
        if end is None and length is not None:
            end = start + int(length) - 1
        if end is None:
            return
        ranges.append((int(start), int(end)))

    ids = (entity_json.get("rcsb_polymer_entity_container_identifiers", {}) or {}).get("reference_sequence_identifiers", []) or []
    for rid in ids:
        if rid.get("database_accession") != uniprot_id:
            continue
        candidates: List[Dict[str, Any]] = []
        range_obj = rid.get("reference_sequence_range")
        if isinstance(range_obj, dict):
            candidates.append(range_obj)
        alignments = rid.get("reference_sequence_alignment") or rid.get("aligned_regions")
        if isinstance(alignments, list):
            for aln in alignments:
                if isinstance(aln, dict):
                    rng = aln.get("reference_sequence_range") or aln
                    if isinstance(rng, dict):
                        candidates.append(rng)
        for cand in candidates:
            start = None
            end = None
            length = _location_value({"value": cand.get("length")})
            for key in ("beg_seq_id", "begin", "start", "from", "beg_seq_num", "ref_beg_seq_id", "ref_seq_beg"):
                val = cand.get(key)
                if isinstance(val, (int, float)):
                    start = int(val)
                    break
                if isinstance(val, str) and val.isdigit():
                    start = int(val)
                    break
            for key in ("end_seq_id", "end", "to", "end_seq_num", "ref_end_seq_id", "ref_seq_end"):
                val = cand.get(key)
                if isinstance(val, (int, float)):
                    end = int(val)
                    break
                if isinstance(val, str) and val.isdigit():
                    end = int(val)
                    break
            _append_range(start, end, length)

    align_root = entity_json.get("rcsb_polymer_entity_align", {}) or {}
    align_records: List[Dict[str, Any]] = []
    if isinstance(align_root, dict):
        align_records.extend(align_root.get("reference_sequences", []) or [])
    elif isinstance(align_root, list):
        align_records.extend(align_root)

    for ref in align_records:
        acc = ref.get("database_accession") or ref.get("reference_database_accession")
        if acc != uniprot_id:
            continue
        rng = ref.get("reference_sequence_range")
        if isinstance(rng, dict):
            start = _location_value({"value": rng.get("beg_seq_id") or rng.get("begin")})
            end = _location_value({"value": rng.get("end_seq_id") or rng.get("end")})
            length = _location_value({"value": rng.get("length")})
            _append_range(start, end, length)
        aligned_regions = ref.get("aligned_regions") or []
        if isinstance(aligned_regions, list):
            for region in aligned_regions:
                if not isinstance(region, dict):
                    continue
                start = _location_value({"value": region.get("ref_beg_seq_id") or region.get("entity_beg_seq_id")})
                end = _location_value({"value": region.get("ref_end_seq_id") or region.get("entity_end_seq_id")})
                length = _location_value({"value": region.get("length")})
                _append_range(start, end, length)

    if ranges:
        ranges = sorted(set(ranges))
    return ranges

def analyze_domain_coverage(pdbid: str, uniprot_id: Optional[str] = None, entry_json: Optional[Dict[str, Any]] = None, entity_jsons: Optional[Dict[str, Dict[str, Any]]] = None) -> Dict[str, Any]:
    """
    Infer domain presence (transmembrane/extracellular/cytoplasmic) using polymer_entity features.
    If uniprot_id is given, restrict to entities mapped to that UniProt; otherwise use all entities.
    
    Args:
        pdbid: PDB identifier
        uniprot_id: Optional UniProt ID to filter entities
        entry_json: Optional cached entry JSON to avoid duplicate API call
        entity_jsons: Optional dict of entity_id -> entity JSON to avoid duplicate API calls
    """
    info = {"has_transmembrane": False, "has_extracellular": False, "has_cytoplasmic": False,
        "primary_domain": "Unknown", "structure_type": "Unknown", "sequence_length": None}
    domain_votes = {"Full-length": False, "ECD": False, "Cytoplasmic": False}
    tmd_ranges: List[Tuple[int, int]] = []
    tmd_min: Optional[int] = None
    tmd_max: Optional[int] = None
    title_lower = ""
    all_aligned_ranges: List[Tuple[int, int]] = []
    uniprot_domain_votes: Dict[str, int] = {"Full-length": 0, "ECD": 0, "Cytoplasmic": 0, "TMD": 0}
    rest_entity_cache: Dict[str, Dict[str, Any]] = {}
    if uniprot_id:
        topology = fetch_uniprot_topology(uniprot_id)
        tmd_ranges = topology.get("tmd_ranges", []) or []
        if tmd_ranges:
            tmd_min = min(r[0] for r in tmd_ranges)
            tmd_max = max(r[1] for r in tmd_ranges)
    try:
        entry = entry_json if entry_json is not None else (fetch_json(RCSB_ENTRY_API.format(pdbid=pdbid)) or {})
        methods = [e.get("method", "") for e in entry.get("exptl", [])]
        if any("NMR" in (m or "").upper() for m in methods): info["structure_type"] = "NMR"
        elif any("RAY" in (m or "").upper() or "DIFFRACTION" in (m or "").upper() for m in methods):
            info["structure_type"] = "X-ray crystallography"
        elif any("ELECTRON" in (m or "").upper() for m in methods): info["structure_type"] = "Cryo-EM"

        # Also check title for domain keywords
        title_lower = (entry.get("struct", {}) or {}).get("title", "").lower()
        
        ent_ids = entry.get("rcsb_entry_container_identifiers", {}).get("polymer_entity_ids", []) or []
        for entid in ent_ids:
            cache_key = f"{pdbid.upper()}_{entid}"
            # Use cached entity JSON if available, otherwise fetch
            ej = entity_jsons.get(cache_key) if entity_jsons else None
            if ej is None:
                rest_ej = rest_entity_cache.get(str(entid))
                if rest_ej is None:
                    rest_ej = fetch_json(RCSB_ENTITY_API.format(pdbid=pdbid, entid=entid)) or {}
                    rest_entity_cache[str(entid)] = rest_ej
                ej = rest_ej
            if uniprot_id and not _entity_maps_to_uniprot(ej, uniprot_id):
                rest_ej = rest_entity_cache.get(str(entid))
                if rest_ej is None:
                    rest_ej = fetch_json(RCSB_ENTITY_API.format(pdbid=pdbid, entid=entid)) or {}
                    rest_entity_cache[str(entid)] = rest_ej
                if rest_ej and _entity_maps_to_uniprot(rest_ej, uniprot_id):
                    ej = rest_ej
                else:
                    continue
            if ej is None:
                continue
            seq = (ej.get("entity_poly", {}) or {}).get("pdbx_seq_one_letter_code_can", "")
            info["sequence_length"] = len(seq.replace("\n", "")) if seq else info["sequence_length"]
            
            # Get entity description
            desc = ((ej.get("rcsb_polymer_entity", {}) or {}).get("pdbx_description") or "").lower()
            
            # Collect feature names and types
            feats = ej.get("rcsb_polymer_entity_feature", []) or []
            names = " ".join((f.get("name", "") or "") for f in feats).lower()
            types = " ".join((f.get("type", "") or "") for f in feats).lower()
            
            # Combine all text sources for keyword matching
            blob = " ".join([names, types, desc, title_lower])

            aligned_ranges: List[Tuple[int, int]] = []
            if uniprot_id:
                aligned_ranges = _extract_uniprot_ranges(ej, uniprot_id)
                if not aligned_ranges:
                    rest_ej = rest_entity_cache.get(str(entid))
                    if rest_ej is None:
                        rest_ej = fetch_json(RCSB_ENTITY_API.format(pdbid=pdbid, entid=entid)) or {}
                        rest_entity_cache[str(entid)] = rest_ej
                    if rest_ej:
                        aligned_ranges = _extract_uniprot_ranges(rest_ej, uniprot_id)
                        if not ej:
                            ej = rest_ej
                if aligned_ranges:
                    all_aligned_ranges.extend(aligned_ranges)
                    domain_cats: Set[str] = set()
                    if tmd_ranges and tmd_min is not None and tmd_max is not None:
                        for start, end in aligned_ranges:
                            rng_len = max(1, end - start + 1)
                            max_overlap = 0
                            for tm_start, tm_end in tmd_ranges:
                                overlap_start = max(start, tm_start)
                                overlap_end = min(end, tm_end)
                                if overlap_end >= overlap_start:
                                    max_overlap = max(max_overlap, overlap_end - overlap_start + 1)
                            if max_overlap == 0:
                                if end < tmd_min:
                                    domain_cats.add("ECD")
                                elif start > tmd_max:
                                    domain_cats.add("Cytoplasmic")
                                else:
                                    domain_cats.add("Full-length")
                            else:
                                overlap_ratio = max_overlap / float(rng_len)
                                if overlap_ratio >= 0.2:
                                    domain_cats.add("TMD")
                                elif start < tmd_min and end > tmd_max:
                                    domain_cats.add("Full-length")
                                elif start > tmd_max:
                                    domain_cats.add("Cytoplasmic")
                                elif end < tmd_min:
                                    domain_cats.add("ECD")
                                elif start >= tmd_max:
                                    domain_cats.add("Cytoplasmic")
                                else:
                                    domain_cats.add("TMD")
                    if not domain_cats and tmd_ranges:
                        # Ranges exist but could not be localized relative to TMD span (rare numbering gaps)
                        domain_cats.add("Full-length")
                    for cat in domain_cats:
                        if cat == "TMD":
                            info["has_transmembrane"] = True
                        elif cat == "ECD":
                            info["has_extracellular"] = True
                        elif cat == "Cytoplasmic":
                            info["has_cytoplasmic"] = True
                        elif cat == "Full-length":
                            info["has_transmembrane"] = True
                            info["has_extracellular"] = True
                            info["has_cytoplasmic"] = True
                        if cat in uniprot_domain_votes:
                            uniprot_domain_votes[cat] += 1
                    if "TMD" in domain_cats and ("ECD" in domain_cats or "Cytoplasmic" in domain_cats):
                        uniprot_domain_votes["Full-length"] += 1
                    if "ECD" in domain_cats:
                        domain_votes["ECD"] = True
                    if "Cytoplasmic" in domain_cats:
                        domain_votes["Cytoplasmic"] = True
                    if "TMD" in domain_cats and ("ECD" in domain_cats or "Cytoplasmic" in domain_cats):
                        domain_votes["Full-length"] = True
            
            # Transmembrane keywords
            if any(t in blob for t in ("transmembrane", "tm domain", "membrane", "juxta-membrane", "juxtamembrane")):
                info["has_transmembrane"] = True
            
            # Extracellular keywords (expanded)
            if any(t in blob for t in (
                "extracellular", "ectodomain", "binding domain", "immunoglobulin-like",
                "fibronectin", "fn3", "ig-like", "receptor domain", "ligand binding",
                "ligand-binding", "ecd ", "cytokine-binding", "fibronectin type iii", "cytokine receptor"
            )):
                info["has_extracellular"] = True
            
            # Cytoplasmic keywords
            if any(t in blob for t in (
                "cytoplasmic", "intracellular", "box1", "box 1", "box2", "box 2", "jak", "ferm", 
                "sh2", "jm domain", "kinase domain"
            )):
                info["has_cytoplasmic"] = True
    except Exception:
        pass

    if all_aligned_ranges and tmd_ranges:
        overlaps_tmd = any(
            not (aln_end < tm_start or aln_start > tm_end)
            for aln_start, aln_end in all_aligned_ranges
            for tm_start, tm_end in tmd_ranges
        )
        if not overlaps_tmd:
            max_aligned_end = max(r[1] for r in all_aligned_ranges)
            min_aligned_start = min(r[0] for r in all_aligned_ranges)
            if tmd_min is not None and max_aligned_end < tmd_min:
                info["has_extracellular"] = True
                domain_votes["ECD"] = True
            elif tmd_max is not None and min_aligned_start > tmd_max:
                info["has_cytoplasmic"] = True
                domain_votes["Cytoplasmic"] = True

    ecd_title_tokens = ("erythropoietin", "epo", "fab", "diabody", "nanobody", "darpin")
    if info["primary_domain"] == "Unknown" and title_lower:
        if any(token in title_lower for token in ecd_title_tokens):
            info["has_extracellular"] = True
            domain_votes["ECD"] = True

    if uniprot_domain_votes["TMD"]:
        info["has_transmembrane"] = True
    if uniprot_domain_votes["ECD"]:
        info["has_extracellular"] = True
    if uniprot_domain_votes["Cytoplasmic"]:
        info["has_cytoplasmic"] = True

    primary_override: Optional[str] = None
    if uniprot_domain_votes["TMD"]:
        if uniprot_domain_votes["ECD"] or uniprot_domain_votes["Cytoplasmic"]:
            primary_override = "Full-length"
        else:
            primary_override = "TMD"
    elif uniprot_domain_votes["ECD"] and not uniprot_domain_votes["Cytoplasmic"]:
        primary_override = "ECD"
    elif uniprot_domain_votes["Cytoplasmic"] and not uniprot_domain_votes["ECD"]:
        primary_override = "Cytoplasmic"

    if not primary_override:
        if domain_votes["Full-length"]:
            primary_override = "Full-length"
        elif domain_votes["ECD"]:
            primary_override = "ECD"
        elif domain_votes["Cytoplasmic"]:
            primary_override = "Cytoplasmic"

    if primary_override:
        info["primary_domain"] = primary_override
    elif info["has_transmembrane"]:
        info["primary_domain"] = "TMD"
    elif info["has_extracellular"]:
        info["primary_domain"] = "ECD"
    elif info["has_cytoplasmic"]:
        info["primary_domain"] = "Cytoplasmic"
    return info


def detect_ligands_and_partners(pdbid: str, uniprot_id: Optional[str] = None, entry_json: Optional[Dict[str, Any]] = None, entity_jsons: Optional[Dict[str, Dict[str, Any]]] = None) -> Dict[str, Any]:
    """
    Detect presence of ligands/partners using title cues and polymer entity counts.
    If uniprot_id is given, polymer entities not mapped to that UniProt are considered partners.
    
    Args:
        pdbid: PDB identifier
        uniprot_id: Optional UniProt ID to filter entities
        entry_json: Optional cached entry JSON to avoid duplicate API call
        entity_jsons: Optional dict of entity_id -> entity JSON to avoid duplicate API calls
    """
    info = {"has_ligand": False, "has_peptide": False, "has_antibody": False, "has_binding_partner": False,
            "ligand_class": [], "binding_partners": []}
    try:
        entry = entry_json if entry_json is not None else (fetch_json(RCSB_ENTRY_API.format(pdbid=pdbid)) or {})
        title = (entry.get("struct", {}) or {}).get("title", "").lower()
        engineered_terms = {
            "darpin": "darpin",
            "diabody": "diabody",
            "nanobody": "nanobody",
            "fab": "fab",
            "tetrabody": "diabody"
        }
        if any(k in title for k in engineered_terms.keys()):
            info["has_antibody"] = True
            if "engineered-protein" not in info["ligand_class"]:
                info["ligand_class"].append("engineered-protein")
            for token, label in engineered_terms.items():
                if token in title and label not in info["ligand_class"]:
                    info["ligand_class"].append(label)
        if any(k in title for k in ("peptide", "agonist", "antagonist", "hormone")):
            info["has_peptide"] = True
            if "peptide" not in info["ligand_class"]:
                info["ligand_class"].append("peptide")

        ent_ids = entry.get("rcsb_entry_container_identifiers", {}).get("polymer_entity_ids", []) or []
        non_target_entities = []
        for entid in ent_ids:
            cache_key = f"{pdbid.upper()}_{entid}"
            # Use cached entity JSON if available, otherwise fetch
            ej = entity_jsons.get(cache_key) if entity_jsons else None
            if ej is None:
                ej = fetch_json(RCSB_ENTITY_API.format(pdbid=pdbid, entid=entid)) or {}
            if uniprot_id:
                if not _entity_maps_to_uniprot(ej, uniprot_id):
                    label = ej.get("rcsb_polymer_entity", {}).get("pdbx_description") \
                            or ej.get("entity", {}).get("pdbx_description")
                    non_target_entities.append(label or f"entity_{entid}")
            else:
                # Without UniProt anchoring, treat multiple polymer entities as partners
                pass
        if (uniprot_id and non_target_entities) or (not uniprot_id and len(ent_ids) > 1):
            info["has_binding_partner"] = True
            info["binding_partners"] = non_target_entities
            info["ligand_class"].append("partner-protein")
    except Exception:
        pass
    info["has_ligand"] = bool(info["has_antibody"] or info["has_peptide"] or info["has_binding_partner"])
    return info


def classify_context(domain: Dict[str, Any], partners: Dict[str, Any], entry_title: str = "") -> str:
    """High-level bucket for reporting; generic tokens only."""
    if domain.get("primary_domain") in {"TMD", "Full-length"}:
        return "TMD"
    if domain.get("primary_domain") == "ECD":
        return "ECD (ligand-bound)" if partners.get("has_ligand") else "ECD (unliganded)"
    if domain.get("primary_domain") == "Cytoplasmic":
        return "ICD / partner-peptide"
    # Title-based fallback
    lt = entry_title.lower()
    if "transmembrane" in lt or "membrane" in lt:
        return "TMD"
    if any(k in lt for k in ("peptide", "antibody", "darpin", "nanobody", "agonist", "antagonist", "ligand")):
        return "ECD (ligand-bound)"
    return "Unknown"


# --- Optional cleaning / protonation ---
class SelectFiltered(Select if Select else object):  # type: ignore
    def __init__(self, chain_ids=None, remove_hetatm=True, remove_waters=True):
        self.chain_ids = set(chain_ids or [])
        self.remove_hetatm = remove_hetatm
        self.remove_waters = remove_waters

    def accept_chain(self, chain):
        if Select is None: return True
        return (not self.chain_ids) or (chain.get_id() in self.chain_ids)

    def accept_residue(self, residue):
        if Select is None: return True
        hetflag = residue.id[0]; resname = residue.get_resname()
        if self.remove_waters and resname in {"HOH", "WAT"}: return False
        if self.remove_hetatm and hetflag != " ": return False
        return True

    def accept_atom(self, atom):
        if Select is None: return True
        alt = atom.get_altloc()
        return alt in {"", "A", "1"}


def clean_and_protonate_cif_text(cif_text: str, pH: float = 7.4) -> Optional[str]:
    """
    If PDBFixer+OpenMM are installed, return a cleaned, protonated PDB text built from the mmCIF.
    
    Strategy: Convert mmCIF → PDB text → PDBFixer → protonated PDB text
    Returns None if unavailable or on failure.
    """
    if pdbfixer is None or PDBFile is None or MMCIFParser is None or PDBIO is None:
        return None
    try:
        # Step 1: Parse mmCIF text with BioPython
        parser = MMCIFParser(QUIET=True)
        structure = parser.get_structure("temp", io.StringIO(cif_text))
        
        # Step 2: Convert to PDB format text
        pdb_io = PDBIO()
        pdb_io.set_structure(structure)
        pdb_buffer = io.StringIO()
        pdb_io.save(pdb_buffer)
        pdb_text = pdb_buffer.getvalue()
        
        # Step 3: Use PDBFixer on the PDB text
        pdb_buffer2 = io.StringIO(pdb_text)
        fixer = pdbfixer.PDBFixer(pdbfile=pdb_buffer2)
        fixer.removeHeterogens(True)
        fixer.findMissingResidues()
        fixer.findMissingAtoms()
        fixer.addMissingAtoms()
        fixer.addMissingHydrogens(pH)
        
        # Step 4: Write out protonated structure
        out = io.StringIO()
        PDBFile.writeFile(fixer.topology, fixer.positions, out, keepIds=True)
        return out.getvalue()
    except Exception as e:
        # Silently fail - this is optional functionality
        # Common issues: malformed structures, missing atoms, incompatible formats
        return None


# --- Scoring / ranking ---
def calculate_quality_score(r: Dict[str, Any]) -> float:
    """Compute quality score used for ranking (lower is better)."""
    def _safe(value: Any, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    res = _safe(r.get("resolution"), 99.0)
    rfree = _safe(r.get("r_free"), 0.0)
    rwork = _safe(r.get("r_work"), rfree)
    gap = rfree - rwork

    engineered_penalty = 0.0
    ligand_classes = {str(x).lower() for x in (r.get("ligand_class") or [])}
    if "engineered-protein" in ligand_classes:
        engineered_penalty = 0.15

    validation_missing = 0.0
    validation_source = (r.get("validation_source") or "").lower()
    if validation_source in ("", "missing"):
        validation_missing = 0.1

    score = res
    if res > 3.5:
        score += 0.5
    if gap > 0.07:
        score += 0.4
    score += engineered_penalty
    score += validation_missing
    return score


def _score_tuple(r: Dict[str, Any]) -> Tuple:
    """Score tuple for ranking with deterministic tie-breakers."""
    score = r.get("quality_score")
    if not isinstance(score, (float, int)):
        score = calculate_quality_score(r)
        r["quality_score"] = score

    def _safe(value: Any, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    clash = _safe(r.get("clashscore"), 999.0)
    rama_out = _safe(r.get("ramachandran_outliers_percent"), 999.0)
    atom_count = float(r.get("atom_count") or 0.0)
    return (float(score), clash, rama_out, -atom_count)


def rank_best(entries: List[Dict[str, Any]], biological_context: bool = True) -> Optional[Dict[str, Any]]:
    """Return the single entry with minimal score according to _score_tuple."""
    if not entries:
        return None
    _ = biological_context  # retained for API compatibility
    return min(entries, key=lambda r: _score_tuple(r))


# --- Core analysis ---
def analyze_entries(
    pdb_ids: List[str],
    *,
    uniprot_id: Optional[str] = None,
    outdir: Optional[str] = None,
    download: bool = True,
    clean: bool = False,
    protonate: bool = False,
) -> Dict[str, Any]:
    """
    Analyze a list of PDB IDs. When uniprot_id is provided, feature/domain and partner assignments anchor to it.

    Returns a summary dict with keys: results (list), counts (dict), best_overall (dict), json/csv paths if written.
    """
    t0 = time.time()
    results: List[Dict[str, Any]] = []

    # Print initial search results
    unique_pdb_ids = sorted({p.upper() for p in pdb_ids})
    print(f"\nFound {len(unique_pdb_ids)} structures to analyze")
    if len(unique_pdb_ids) > 10:
        print(f"  First 10: {', '.join(unique_pdb_ids[:10])}")
        print(f"  ... and {len(unique_pdb_ids) - 10} more")
    else:
        print(f"  PDB IDs: {', '.join(unique_pdb_ids)}")
    print()

    cif_dir = pdb_dir = clean_pdb_dir = None
    if outdir:
        cif_dir = ensure_dir(os.path.join(outdir, "cif"))
        pdb_dir = ensure_dir(os.path.join(outdir, "pdb"))
        clean_pdb_dir = ensure_dir(os.path.join(outdir, "pdb_clean"))

    # **OPTIMIZATION**: Batch-fetch all entry metadata via GraphQL (1 call instead of N)
    t_start = time.time()
    print("  Fetching entry metadata...")
    entries_batch = fetch_entries_batch(unique_pdb_ids)
    print(f"  ✓ Entry metadata fetched in {time.time()-t_start:.2f}s")
    
    # **OPTIMIZATION**: Collect all entity IDs and batch-fetch them (1 call instead of N*M)
    t_start = time.time()
    print("  Fetching entity metadata...")
    all_entity_ids = []
    for pdbid in unique_pdb_ids:
        entry_data = entries_batch.get(pdbid.upper(), {})
        ent_ids = entry_data.get("rcsb_entry_container_identifiers", {}).get("polymer_entity_ids", []) or []
        for entid in ent_ids:
            all_entity_ids.append(f"{pdbid.upper()}_{entid}")
    
    entities_batch = fetch_entities_batch(all_entity_ids)
    print(f"  ✓ Entity metadata fetched in {time.time()-t_start:.2f}s")
    print(f"  Analyzing {len(unique_pdb_ids)} structures...\n")

    # **OPTIMIZATION**: Pre-fetch all mmCIF files and validation reports in parallel (major speedup!)
    t_start = time.time()
    print("  Downloading mmCIF files and validation reports...")
    cif_cache: Dict[str, str] = {}
    pdb_cache: Dict[str, str] = {}
    validation_cache: Dict[str, Dict[str, Optional[float]]] = {}

    download_state = {"rcsb_disabled": False}

    def disable_primary(reason: str) -> None:
        if not download_state["rcsb_disabled"]:
            download_state["rcsb_disabled"] = True
            print(
                f"    -> RCSB primary downloads disabled ({reason}); switching to wwPDB mirror",
                flush=True,
            )

    def fetch_cif_for_structure(pdbid: str) -> Tuple[str, str]:
        """Fetch mmCIF text for a single structure."""
        cif_text = ""
        if not download_state["rcsb_disabled"]:
            url = RCSB_FILES_CIF.format(pdbid=pdbid)
            try:
                resp = SESSION.get(url, timeout=5)
                if resp.ok and resp.text:
                    cif_text = resp.text
                else:
                    status = resp.status_code
                    if status == 504:
                        disable_primary("504 Gateway Timeout")
                    elif status and 500 <= status < 600:
                        disable_primary(f"{status} server error")
            except requests.Timeout:
                disable_primary("timeout")
            except requests.RequestException as exc:
                disable_primary(exc.__class__.__name__)

        if not cif_text:
            pdb_lower = pdbid.lower()
            two = pdb_lower[1:3]
            fallback_url = WWPDB_DIVIDED_CIF.format(two=two, pdbid=pdb_lower)
            blob = fetch_binary(fallback_url, timeout=10)
            if blob:
                try:
                    cif_text = gzip.decompress(blob).decode("utf-8")
                    print(f"    -> Fallback mmCIF fetched from wwPDB for {pdbid}", flush=True)
                except Exception:
                    print(f"    -> Fallback wwPDB download failed to decompress for {pdbid}", flush=True)
                    cif_text = ""
            else:
                print(f"    -> Fallback mmCIF unavailable at wwPDB for {pdbid}", flush=True)
        return (pdbid, cif_text)
    
    def fetch_validation_for_structure(pdbid: str) -> Tuple[str, Dict[str, Optional[float]]]:
        """Fetch validation report for a single structure."""
        validation = fetch_validation_report(pdbid)
        return (pdbid, validation)
    
    # Parallel download using ThreadPoolExecutor (much faster!)
    with ThreadPoolExecutor(max_workers=10) as executor:
        # Submit all CIF downloads
        cif_futures = {executor.submit(fetch_cif_for_structure, pdbid): pdbid for pdbid in unique_pdb_ids}
        validation_futures = {executor.submit(fetch_validation_for_structure, pdbid): pdbid for pdbid in unique_pdb_ids}
        pdb_futures = {}
        if outdir and download:
            def fetch_pdb_for_structure(pdbid: str) -> Tuple[str, str]:
                if download_state["rcsb_disabled"]:
                    return (pdbid, "")
                pdb_text = fetch_text(RCSB_FILES_PDB.format(pdbid=pdbid), timeout=5) or ""
                return (pdbid, pdb_text)
            pdb_futures = {executor.submit(fetch_pdb_for_structure, pdbid): pdbid for pdbid in unique_pdb_ids}
        
        # Collect results as they complete
        for future in as_completed(cif_futures):
            pdbid, cif_text = future.result()
            cif_cache[pdbid] = cif_text
        
        for future in as_completed(validation_futures):
            pdbid, validation = future.result()
            validation_cache[pdbid] = validation

        for future in as_completed(pdb_futures):
            pdbid, pdb_text = future.result()
            pdb_cache[pdbid] = pdb_text
    
    print(f"  ✓ Downloaded {len(cif_cache)} mmCIF files and {len(validation_cache)} validation reports in {time.time()-t_start:.2f}s")
    t_start = time.time()
    print("  Processing analysis...\n")

    def _process_structure(item: Tuple[int, str]) -> Tuple[int, Dict[str, Any], str]:
        idx, pdbid = item
        entry: Dict[str, Any] = {"pdb_id": pdbid}

        # Use pre-fetched mmCIF text from cache (no network I/O!)
        t_step = time.time()
        cif_text = cif_cache.get(pdbid, "")
        entry.update(parse_metrics_from_mmcif_text(cif_text))
        t_parse_metrics = time.time() - t_step

        t_step = time.time()
        entry.update(compute_model0_geometry_from_cif_text(cif_text, pdbid))
        t_parse_geometry = time.time() - t_step

        # Use pre-fetched validation report from cache (no network I/O!)
        entry.update(validation_cache.get(pdbid, {}))

        # Use GraphQL batch data (already fetched once for all structures)
        ent_json = entries_batch.get(pdbid.upper(), {})

        # Extract title and methods from cached entry JSON
        entry["title"] = (ent_json.get("struct", {}) or {}).get("title", "")
        methods = ent_json.get("exptl", []) or []
        entry["method"] = ",".join([m.get("method", "") for m in methods] if isinstance(methods, list) else [])

        # Use GraphQL batch entity data (already fetched once for all entities)
        ent_ids = ent_json.get("rcsb_entry_container_identifiers", {}).get("polymer_entity_ids", []) or []
        entity_jsons = {
            f"{pdbid.upper()}_{entid}": entities_batch.get(f"{pdbid.upper()}_{entid}", {})
            for entid in ent_ids
        }

        # Pass cached entry JSON and entity JSONs to avoid duplicate fetches
        t_step = time.time()
        entry.update(
            analyze_biological_assembly(
                pdbid,
                uniprot_id=uniprot_id,
                entry_json=ent_json,
                entity_jsons=entity_jsons,
            )
        )
        t_assembly = time.time() - t_step

        t_step = time.time()
        dom = analyze_domain_coverage(pdbid, uniprot_id=uniprot_id, entry_json=ent_json, entity_jsons=entity_jsons)
        partners = detect_ligands_and_partners(pdbid, uniprot_id=uniprot_id, entry_json=ent_json, entity_jsons=entity_jsons)
        t_analysis = time.time() - t_step

        entry.update(dom)
        entry.update(partners)
        entry["context"] = classify_context(dom, partners, entry["title"])
        if entry.get("context") == "Unknown" and entry.get("has_ligand"):
            partner_text = " ".join(entry.get("binding_partners") or [])
            ligand_text = " ".join(entry.get("ligand_class") or [])
            combined = " ".join([partner_text, entry.get("title", ""), ligand_text]).lower()
            if any(token in combined for token in ("epo", "erythropoietin", "darpin", "diabody", "fab", "nanobody")):
                entry["context"] = "ECD (ligand-bound)"
                if entry.get("primary_domain") == "Unknown" and entry.get("has_extracellular"):
                    entry["primary_domain"] = "ECD"
                    entry["has_extracellular"] = True

        if entry.get("context", "").startswith("ECD") and entry.get("primary_domain") in (None, "", "Unknown"):
            entry["primary_domain"] = "ECD"
            entry["has_extracellular"] = True

        r_free_val = entry.get("r_free")
        r_work_val = entry.get("r_work")
        if isinstance(r_free_val, (float, int)) and isinstance(r_work_val, (float, int)):
            entry["delta_r"] = r_free_val - r_work_val

        # Optional downloads
        if outdir and download:
            cif_path = os.path.join(cif_dir, f"{pdbid}.cif")  # type: ignore
            if cif_text:
                with open(cif_path, "w", encoding="utf-8") as cif_file:
                    cif_file.write(cif_text)
            else:
                download_text(RCSB_FILES_CIF.format(pdbid=pdbid), cif_path)
            pdb_path = os.path.join(pdb_dir, f"{pdbid}.pdb")  # type: ignore
            pdb_text = pdb_cache.get(pdbid, "")
            if pdb_text:
                with open(pdb_path, "w", encoding="utf-8") as pdb_file:
                    pdb_file.write(pdb_text)
            else:
                download_text(RCSB_FILES_PDB.format(pdbid=pdbid), pdb_path)

            if clean and MMCIFParser and PDBIO:
                try:
                    parser = MMCIFParser(QUIET=True)
                    structure = parser.get_structure(pdbid, io.StringIO(cif_text))
                    model = next(structure.get_models())
                    io_writer = PDBIO()
                    io_writer.set_structure(model)
                    out_clean_path = os.path.join(clean_pdb_dir, f"{pdbid}_clean.pdb")  # type: ignore
                    io_writer.save(out_clean_path, SelectFiltered())
                    entry["clean_pdb"] = out_clean_path
                except Exception:
                    entry["clean_pdb"] = None

            if protonate:
                entry["protonated_pdb"] = None

        res_str = f"{entry.get('resolution')} Å" if entry.get('resolution') else "N/A"
        method_str = entry.get('method', 'Unknown').split(',')[0]
        domain_str = entry.get('primary_domain', 'Unknown')
        ligand_str = "Yes" if entry.get('has_ligand') else "No"
        context_str = entry.get('context', 'Unknown')
        t_struct_total = t_parse_metrics + t_parse_geometry + t_assembly + t_analysis

        entry["quality_score"] = calculate_quality_score(entry)

        # Backwards-compatibility alias: some callers expect 'biological_context'
        # while this module uses 'context' as the canonical field name.
        # Populate the alias here so external scripts referencing
        # entry['biological_context'] will not KeyError.
        try:
            entry["biological_context"] = entry.get("context")
        except Exception:
            entry["biological_context"] = None

        log_line = (
            f"  [{idx}/{len(unique_pdb_ids)}] {pdbid}: Res={res_str}, Method={method_str}, "
            f"Domain={domain_str}, Context={context_str}, Ligand={ligand_str} "
            f"(parse:{t_parse_metrics:.2f}s+{t_parse_geometry:.2f}s, "
            f"assembly:{t_assembly:.2f}s, analysis:{t_analysis:.2f}s = {t_struct_total:.2f}s)"
        )

        return idx, entry, log_line

    structure_results: Dict[int, Tuple[Dict[str, Any], str]] = {}
    with ThreadPoolExecutor(max_workers=min(8, len(unique_pdb_ids))) as executor:
        futures = [executor.submit(_process_structure, (idx, pdbid)) for idx, pdbid in enumerate(unique_pdb_ids, 1)]
        for fut in as_completed(futures):
            idx, entry, log_line = fut.result()
            structure_results[idx] = (entry, log_line)

    for idx in range(1, len(unique_pdb_ids) + 1):
        entry, log_line = structure_results[idx]
        print(log_line)
        results.append(entry)

    # Calculate counts
    counts = {
        "ECD_unliganded": sum(1 for r in results if r.get("context") == "ECD (unliganded)"),
        "ECD_ligand":     sum(1 for r in results if r.get("context") == "ECD (ligand-bound)"),
        "TMD":            sum(1 for r in results if r.get("context") == "TMD"),
        "ICD_partner":    sum(1 for r in results if r.get("context") == "ICD / partner-peptide"),
        "Unknown":        sum(1 for r in results if r.get("context") == "Unknown"),
    }
    
    # Print categorization summary
    print(f"  ✓ All structures analyzed in {time.time()-t_start:.2f}s\n")
    print(f"{'='*80}")
    print("STRUCTURE CATEGORIZATION:")
    print(f"  ECD unliganded: {counts['ECD_unliganded']} structures")
    print(f"  ECD ligand-bound: {counts['ECD_ligand']} structures")
    print(f"  TMD structures: {counts['TMD']} structures")
    print(f"  ICD/partner: {counts['ICD_partner']} structures")
    print(f"  Unknown context: {counts['Unknown']} structures")

    score_formula = (
        "Score = resolution + 0.5 (if resolution > 3.5 Å) + 0.4 (if ΔR > 0.07) "
        "+ 0.15 (if engineered ligand) + 0.1 (if validation missing)"
    )
    print(f"\n{score_formula}")

    warnings: List[Tuple[str, str, str]] = []
    for r in results:
        issues: List[str] = []
        res_val = r.get("resolution")
        if isinstance(res_val, (float, int)) and res_val > 3.5:
            issues.append(f"resolution {res_val:.2f} Å > 3.5 Å")
        delta_val = r.get("delta_r")
        if isinstance(delta_val, (float, int)) and delta_val > 0.07:
            issues.append(f"ΔR {delta_val:.3f} > 0.07")
        clash_val = r.get("clashscore")
        if isinstance(clash_val, (float, int)) and clash_val > 30:
            issues.append(f"clashscore {clash_val:.1f} > 30")
        rama_out = r.get("ramachandran_outliers_percent")
        if isinstance(rama_out, (float, int)) and rama_out > 1.0:
            issues.append(f"Ramachandran outliers {rama_out:.1f}% > 1%")
        if issues:
            warnings.append((r.get("pdb_id", "????"), r.get("context", "Unknown"), "; ".join(issues)))

    print(f"\nWARNINGS:")
    if warnings:
        header = f"  {'PDB':<6}{'Context':<25}Issues"
        print(header)
        print("  " + "-" * (len(header) - 2))
        for pdb_id, context, issue_text in warnings:
            print(f"  {pdb_id:<6}{context:<25}{issue_text}")
    else:
        print("  None")
    
    best = rank_best(results)
    best_native = None
    best_engineered = None
    best_ecd_unlig = None
    best_tmd = None
    best_icd = None
    
    # Helper function to print structure details with validation metrics
    def print_structure_details(structure: Dict[str, Any], prefix: str = "  "):
        print(f"{prefix}PDB ID: {structure['pdb_id']}")
        score_val = structure.get("quality_score")
        if isinstance(score_val, (float, int)):
            print(f"{prefix}Score: {score_val:.2f}")
        res = structure.get('resolution')
        if res:
            res_tags: List[str] = []
            if res >= 4.0:
                res_tags.append("low-res")
            line = f"{prefix}Resolution: {res} Å"
            if res_tags:
                line += f" ({', '.join(res_tags)})"
            print(line)
        else:
            print(f"{prefix}Resolution: N/A (likely NMR)")
        
        r_free_val = structure.get('r_free')
        r_work_val = structure.get('r_work')
        if isinstance(r_free_val, (float, int)):
            r_work_display = f"{r_work_val:.4f}" if isinstance(r_work_val, (float, int)) else "N/A"
            delta = None
            if isinstance(r_work_val, (float, int)):
                delta = r_free_val - r_work_val
            delta_display = f"{delta:.4f}" if isinstance(delta, (float, int)) else "N/A"
            line = f"{prefix}R-free: {r_free_val:.4f}, R-work: {r_work_display}, ΔR={delta_display}"
            if isinstance(delta, (float, int)) and delta > 0.07:
                line += f" (wide R-gap {delta:.3f})"
            print(line)
        
        validation_source = (structure.get('validation_source') or 'missing')
        clash_val = structure.get('clashscore')
        clash = clash_val if isinstance(clash_val, (float, int)) else None
        rama_out_val = structure.get('ramachandran_outliers_percent')
        rama_fav_val = structure.get('ramachandran_favored_percent')
        rama_out = rama_out_val if isinstance(rama_out_val, (float, int)) else None
        rama_fav = rama_fav_val if isinstance(rama_fav_val, (float, int)) else None
        rotamer_val = structure.get('rotamer_outliers_percent')

        if str(validation_source).lower() == 'xml':
            if clash is not None:
                print(f"{prefix}Clashscore: {clash:.2f}" + (" ⚠️" if clash > 10 else " ✓"))
            if rama_out is not None or rama_fav is not None:
                fav_display = f"{rama_fav:.1f}%" if rama_fav is not None else "N/A"
                out_display = f"{rama_out:.1f}%" if rama_out is not None else "N/A"
                rama_line = f"{prefix}Ramachandran: favored {fav_display}, outliers {out_display}"
                if rama_out is not None:
                    rama_line += " ⚠️" if rama_out > 1.0 else " ✓"
                else:
                    rama_line += " ✓"
                print(rama_line)
            if isinstance(rotamer_val, (float, int)):
                print(f"{prefix}Rotamer outliers: {rotamer_val:.1f}%" + (" ⚠️" if rotamer_val > 1.0 else " ✓"))
            if clash is None and rama_out is None and not isinstance(rotamer_val, (float, int)):
                print(f"{prefix}Validation: data unavailable (xml)")
        else:
            reason = validation_source if validation_source else "missing"
            print(f"{prefix}Validation: unavailable ({reason})")
        
        # Ligand classification
        ligand_classes = structure.get('ligand_class', [])
        if ligand_classes:
            ligand_str = ", ".join(ligand_classes)
            if "engineered-protein" in ligand_classes:
                ligand_str += " 🔧 (engineered)"
            print(f"{prefix}Ligand class: {ligand_str}")
        
        print(f"{prefix}Method: {structure.get('method', 'Unknown')}")
        print(f"{prefix}Context: {structure.get('context', 'Unknown')}")
        analysis_assembly = structure.get('analysis_assembly_id')
        symmetry = structure.get('analysis_symmetry') or structure.get('symmetry') or "unknown"
        if analysis_assembly:
            line = f"{prefix}Assembly: {analysis_assembly} (symmetry: {symmetry})"
            alternates = structure.get('assembly_alternates') or []
            if alternates:
                line += f"; alternates: {', '.join(alternates)}"
            print(line)
        else:
            print(f"{prefix}Assembly: N/A (symmetry: {symmetry})")
        print(f"{prefix}Title: {structure.get('title', '')[:80]}...")
    
    # Print best structure details
    if best:
        print(f"\n{'='*80}")
        print("BEST OVERALL STRUCTURE (all contexts):")
        print_structure_details(best)
        
        # Context-specific best structures
        print(f"\n{'='*80}")
        print("CONTEXT-SPECIFIC BEST STRUCTURES:")
        print(f"{'='*80}")
        
        # Native ligand ECD (highest priority for biological studies)
        if counts['ECD_ligand'] > 0:
            ecd_ligand = [r for r in results if r.get('context') == 'ECD (ligand-bound)']
            native_ecd = [r for r in ecd_ligand if 'engineered-protein' not in (r.get('ligand_class') or [])]
            engineered_ecd = [r for r in ecd_ligand if 'engineered-protein' in (r.get('ligand_class') or [])]
            
            if native_ecd:
                best_native = rank_best(native_ecd, biological_context=True)
                if best_native:
                    print(f"\n🏆 BEST NATIVE LIGAND ECD (physiological complex):")
                    print_structure_details(best_native)
            
            if engineered_ecd:
                best_engineered = rank_best(engineered_ecd, biological_context=False)
                if best_engineered:
                    print(f"\n🔧 BEST ENGINEERED LIGAND ECD (Fab/DARPin/diabody):")
                    print_structure_details(best_engineered)
        
        if counts['ECD_unliganded'] > 0:
            ecd_unlig = [r for r in results if r.get('context') == 'ECD (unliganded)']
            best_ecd_unlig = rank_best(ecd_unlig)
            if best_ecd_unlig:
                print(f"\n🔓 BEST ECD UNLIGANDED (inactive reference):")
                print_structure_details(best_ecd_unlig)
        
        if counts['TMD'] > 0:
            tmd = [r for r in results if r.get('context') == 'TMD']
            best_tmd = rank_best(tmd)
            if best_tmd:
                print(f"\n🧬 BEST TMD (membrane environment):")
                print_structure_details(best_tmd)
        
        if counts['ICD_partner'] > 0:
            icd = [r for r in results if r.get('context') == 'ICD / partner-peptide']
            best_icd = rank_best(icd)
            if best_icd:
                print(f"\n🔗 BEST ICD/CYTOPLASMIC (signaling complex):")
                print_structure_details(best_icd)
    else:
        print(f"\n⚠️  No structures passed quality filters")

    if protonate and outdir and clean_pdb_dir:
        result_by_id = {r["pdb_id"]: r for r in results}
        ids_to_protonate = set()

        def _collect(struct: Optional[Dict[str, Any]]) -> None:
            if struct:
                ids_to_protonate.add(struct["pdb_id"])

        _collect(best)
        _collect(best_native)
        _collect(best_engineered)
        _collect(best_ecd_unlig)
        _collect(best_tmd)
        _collect(best_icd)

        if ids_to_protonate:
            print(f"\n  Protonating {len(ids_to_protonate)} representative structures...")

            def _protonate(pid: str) -> Tuple[str, Optional[str], Optional[str]]:
                cif_text = cif_cache.get(pid, "")
                if not cif_text:
                    return (pid, None, "Missing mmCIF text")
                prot = clean_and_protonate_cif_text(cif_text)
                if not prot:
                    return (pid, None, "Could not add hydrogens")
                outp = os.path.join(clean_pdb_dir, f"{pid}_protonated.pdb")  # type: ignore
                with open(outp, "w", encoding="utf-8") as f:
                    f.write(prot)
                return (pid, outp, None)

            with ThreadPoolExecutor(max_workers=min(4, len(ids_to_protonate))) as executor:
                for pid, outp, err in executor.map(_protonate, sorted(ids_to_protonate)):
                    if err:
                        print(f"    ⚠️  {err} ({pid})")
                        continue
                    result = result_by_id.get(pid)
                    if result is not None:
                        result["protonated_pdb"] = outp

            print("  ✓ Protonation finished.\n")
    
    elapsed = round(time.time() - t0, 2)
    print(f"\n{'='*80}")
    print(f"Analysis completed in {elapsed}s")
    print(f"{'='*80}\n")

    summary = {
        "found": len(results),
        "results": results,
        "best_overall": best,
        "counts": counts,
        "elapsed_sec": elapsed,
    }

    if outdir:
        json_path = os.path.join(outdir, "all_structures.json")
        with open(json_path, "w", encoding="utf-8") as jf:
            json.dump(summary, jf, indent=2)

        csv_path = os.path.join(outdir, "all_structures.csv")
        columns = [
            "pdb_id", "title", "method", "context",
            "resolution", "r_work", "r_free", "delta_r",
            "clashscore", "ramachandran_outliers_percent", "ramachandran_favored_percent", "rotamer_outliers_percent",
            "validation_source",
            "chains", "atom_count",
            "biological_assembly_count", "assembly_ids", "analysis_assembly_id", "assembly_alternates", "oligomeric_details", "symmetry", "analysis_symmetry",
            "primary_domain", "sequence_length", "quality_score",
            "has_ligand", "has_peptide", "has_antibody", "has_binding_partner", "ligand_class", "binding_partners",
            "clean_pdb", "protonated_pdb"
        ]
        with open(csv_path, "w", newline="", encoding="utf-8") as cf:
            w = csv.DictWriter(cf, fieldnames=columns)
            w.writeheader()
            for r in results:
                row = {k: r.get(k, "") for k in columns}
                for k in ("assembly_ids", "assembly_alternates", "oligomeric_details", "ligand_class", "binding_partners"):
                    v = row.get(k)
                    if isinstance(v, list):
                        row[k] = ";".join(str(x) for x in v)
                w.writerow(row)
        summary["json"] = json_path
        summary["csv"] = csv_path

    return summary


def search_and_analyze_by_uniprot(
    uniprot_id: str,
    *,
    limit: int = 200,
    outdir: Optional[str] = None,
    download: bool = True,
    clean: bool = False,
    protonate: bool = False,
) -> Dict[str, Any]:
    """
    Convenience wrapper: search by UniProt, then analyze.
    """
    pdb_ids = search_pdb_by_uniprot(uniprot_id, limit=limit)
    return analyze_entries(
        pdb_ids,
        uniprot_id=uniprot_id,
        outdir=outdir,
        download=download,
        clean=clean,
        protonate=protonate,
    )


def filter_results_by_metrics(
    results: List[Dict[str, Any]],
    resolution_lt: Optional[float] = None,
    r_free_lt: Optional[float] = None,
    require_both: bool = True,
) -> List[Dict[str, Any]]:
    """
    Safely filter a list of result dicts by numeric metrics.

    - If a metric is missing (None or non-numeric), that entry is treated as not meeting
      the threshold for that metric.
    - By default `require_both=True` requires that both metrics pass; set to False to
      include entries that meet either threshold.

    Returns a new list of entries that satisfy the requested numeric thresholds.
    """
    out: List[Dict[str, Any]] = []
    for r in results:
        res_val = r.get("resolution")
        rfree_val = r.get("r_free")

        res_ok = True if resolution_lt is None else (
            isinstance(res_val, (int, float)) and float(res_val) < float(resolution_lt)
        )
        rfree_ok = True if r_free_lt is None else (
            isinstance(rfree_val, (int, float)) and float(rfree_val) < float(r_free_lt)
        )

        if require_both:
            if res_ok and rfree_ok:
                out.append(r)
        else:
            if res_ok or rfree_ok:
                out.append(r)
    return out


def get_high_quality_structures(
    uniprot_id: str,
    limit: int = 200,
    resolution_lt: float = 3.0,
    r_free_lt: float = 0.25,
    outdir: Optional[str] = None,
    download: bool = False,
    clean: bool = False,
    protonate: bool = False,
) -> List[Dict[str, Any]]:
    """
    High-level helper: search and analyze by UniProt ID, then safely return
    entries passing resolution and R-free thresholds. Missing numeric metrics
    are treated as non-passing.
    """
    summary = search_and_analyze_by_uniprot(
        uniprot_id, limit=limit, outdir=outdir, download=download, clean=clean, protonate=protonate
    )
    results = summary.get("results", [])
    filtered = filter_results_by_metrics(results, resolution_lt=resolution_lt, r_free_lt=r_free_lt, require_both=True)
    return filtered


__all__ = [
    # Core session and utilities
    "make_session",
    "ensure_dir",
    
    # Search functions
    "search_pdb_by_protein_name",
    "search_pdb_by_uniprot",
    "get_uniprot_ids_from_pdb",
    "search_and_get_uniprot_mapping",
    
    # Metrics parsing from mmCIF text
    "parse_metrics_from_mmcif_text",
    "compute_model0_geometry_from_cif_text",
    "fetch_validation_report",
    
    # Analysis functions (work with PDB IDs, not files)
    "analyze_biological_assembly",
    "analyze_domain_coverage",
    "detect_ligands_and_partners",
    "classify_context",
    
    # Structure cleaning and protonation (from mmCIF text)
    "clean_and_protonate_cif_text",
    
    # Ranking
    "rank_best",
    
    # High-level workflows (recommended entry points)
    "analyze_entries",
    "search_and_analyze_by_uniprot",
]
