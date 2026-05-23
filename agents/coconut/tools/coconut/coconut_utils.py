"""
coconut_utils.py -- Utility library for the COCONUT natural products database agent.

Wraps the COCONUT v2.0.0 public API (https://coconut.naturalproducts.net) for:
- Molecule text/structure search (SMILES, InChI, InChIKey, substructure, similarity, exact)
- Property-based filtering (molecular weight, logP, H-bond donors/acceptors, NP class, etc.)
- Tag-based browsing (by organism, citation, or data source collection)
- Bioschemas molecule detail retrieval

Public API endpoints used:
  POST /api/search         -- All search types (text, SMILES, filters, tags, etc.)
  GET  /api/schemas/bioschemas/{id} -- Detailed molecule data in Schema.org JSON-LD
"""

import json
import logging
import os
import shutil
import traceback
import time
from typing import Any, Dict, List, Optional, Union

import requests
import pandas as pd

# ======================================================================
# CONSTANTS
# ======================================================================

BASE_URL = "https://coconut.naturalproducts.net"
SEARCH_ENDPOINT = "/api/search"
BIOSCHEMAS_ENDPOINT = "/api/schemas/bioschemas"

DEFAULT_TIMEOUT = 60  # seconds
MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds

# Filter key mapping (short key -> database column)
# Use these short keys in the 'filters' search type: e.g. "mw:100..500 hba:0..10"
FILTER_MAP = {
    "mf": "molecular_formula",
    "mw": "molecular_weight",
    "emw": "exact_molecular_weight",
    "hac": "heavy_atom_count",
    "tac": "total_atom_count",
    "arc": "aromatic_rings_count",
    "rbc": "rotatable_bond_count",
    "mrc": "number_of_minimal_rings",
    "fc": "formal_charge",
    "cs": "contains_sugar",
    "crs": "contains_ring_sugars",
    "cls": "contains_linear_sugars",
    "np": "np_likeness",
    "qed": "qed_drug_likeliness",
    "alogp": "alogp",
    "topopsa": "topological_polar_surface_area",
    "fcsp3": "fractioncsp3",
    "hba": "hydrogen_bond_acceptors",
    "hbd": "hydrogen_bond_donors",
    "ro5v": "rule_of_5_violations",
    "lhba": "hydrogen_bond_acceptors_lipinski",
    "lhbd": "hydrogen_bond_donors_lipinski",
    "lro5v": "lipinski_rule_of_five_violations",
    "vdwv": "van_der_walls_volume",
    "ds": "found_in_databases",
    "class": "chemical_class",
    "subclass": "chemical_sub_class",
    "superclass": "chemical_super_class",
    "parent": "direct_parent_classification",
    "np_class": "np_classifier_class",
    "np_superclass": "np_classifier_superclass",
    "np_pathway": "np_classifier_pathway",
    "np_glycoside": "np_classifier_is_glycoside",
}

# Search type constants
SEARCH_TYPES = [
    "text",          # Default text search (name, synonyms, identifier)
    "smiles",        # SMILES structure search (also substructure)
    "inchi",         # InChI search
    "inchikey",      # InChIKey search
    "substructure",  # Substructure search by SMILES
    "exact",         # Exact structure match by SMILES
    "similarity",    # Tanimoto similarity search by SMILES
    "tags",          # Tag-based (organism, citation, dataSource)
    "filters",       # Property-based filters (key:value syntax)
]

# Tag types for tag-based search
TAG_TYPES = ["organisms", "citations", "dataSource"]


# ======================================================================
# SETUP / TEARDOWN (standard Discovery agent pattern)
# ======================================================================

_config = {
    "input_dir": "/input",
    "output_dir": "/output",
    "work_dir": "/app/workdir",
}


def quick_setup(input_dir='/input', output_dir='/output', work_dir='/app/workdir'):
    """Initialize logging, create directories, copy input files to workdir."""
    _config["input_dir"] = input_dir
    _config["output_dir"] = output_dir
    _config["work_dir"] = work_dir

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    for d in [input_dir, output_dir, work_dir]:
        os.makedirs(d, exist_ok=True)

    if os.path.isdir(input_dir):
        for f in os.listdir(input_dir):
            src = os.path.join(input_dir, f)
            dst = os.path.join(work_dir, f)
            if os.path.isfile(src) and not os.path.exists(dst):
                shutil.copy2(src, dst)

    logging.info("=" * 60)
    logging.info("COCONUT Agent -- quick_setup complete")
    logging.info("  input_dir  = %s", input_dir)
    logging.info("  output_dir = %s", output_dir)
    logging.info("  work_dir   = %s", work_dir)
    logging.info("=" * 60)


def quick_finish():
    """Copy workdir output files to output directory."""
    work_dir = _config["work_dir"]
    output_dir = _config["output_dir"]
    if os.path.isdir(work_dir):
        for f in os.listdir(work_dir):
            src = os.path.join(work_dir, f)
            dst = os.path.join(output_dir, f)
            if os.path.isfile(src) and not os.path.exists(dst):
                shutil.copy2(src, dst)
    logging.info("quick_finish complete -- files copied to output.")


def save_final_results(results, output_files=None, file_descriptions=None):
    """Save final results as JSON to output directory (MANDATORY for every script)."""
    output_dir = _config["output_dir"]
    payload = {"status": "success", "results": results}
    if output_files:
        payload["output_files"] = output_files
    if file_descriptions:
        payload["file_descriptions"] = file_descriptions

    out_path = os.path.join(output_dir, "final_results.json")
    with open(out_path, "w") as f:
        json.dump(payload, f, indent=2, default=str)
    logging.info("Final results saved to %s", out_path)
    return out_path


# ======================================================================
# CORE HTTP LAYER
# ======================================================================

def _api_post(endpoint, json_body, timeout=DEFAULT_TIMEOUT):
    """POST request to COCONUT API with retry logic."""
    url = BASE_URL + endpoint
    headers = {"Accept": "application/json", "Content-Type": "application/json"}

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logging.info("API POST %s (attempt %d/%d)", endpoint, attempt, MAX_RETRIES)
            resp = requests.post(url, json=json_body, headers=headers, timeout=timeout)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.HTTPError as e:
            logging.warning("HTTP %s on attempt %d: %s", resp.status_code, attempt, e)
            if resp.status_code in (429, 500, 502, 503, 504) and attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY * attempt)
                continue
            raise
        except requests.exceptions.RequestException as e:
            logging.warning("Request error on attempt %d: %s", attempt, e)
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY * attempt)
                continue
            raise


def _api_get(endpoint, params=None, timeout=DEFAULT_TIMEOUT):
    """GET request to COCONUT API with retry logic."""
    url = BASE_URL + endpoint
    headers = {"Accept": "application/json"}

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logging.info("API GET %s (attempt %d/%d)", endpoint, attempt, MAX_RETRIES)
            resp = requests.get(url, params=params, headers=headers, timeout=timeout)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.HTTPError as e:
            logging.warning("HTTP %s on attempt %d: %s", resp.status_code, attempt, e)
            if resp.status_code in (429, 500, 502, 503, 504) and attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY * attempt)
                continue
            raise
        except requests.exceptions.RequestException as e:
            logging.warning("Request error on attempt %d: %s", attempt, e)
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY * attempt)
                continue
            raise


# ======================================================================
# SEARCH API (POST /api/search)
# ======================================================================

def search(query, search_type=None, limit=24, page=1, sort=None, tag_type=None):
    """Core search function -- all COCONUT searches go through this endpoint.

    Args:
        query: Search query string. Format depends on search_type:
            - text: molecule name or synonym (e.g. "caffeine")
            - smiles: SMILES string (e.g. "c1ccccc1")
            - inchi: InChI string (e.g. "InChI=1S/C8H10N4O2/...")
            - inchikey: InChIKey (e.g. "RYYVLZVUVIJVGH-UHFFFAOYSA-N")
            - exact: canonical SMILES for exact match
            - similarity: SMILES for Tanimoto similarity search
            - substructure: SMILES for substructure search
            - filters: key:value pairs (e.g. "mw:100..500 hba:0..10")
            - tags: tag value (organism name, DOI, or collection title)
            - None/auto: auto-detected from query format (CNP -> identifier,
              InChI= -> inchi, 27-char -> inchikey, etc.)
        search_type: One of: text, smiles, inchi, inchikey, substructure,
                     exact, similarity, tags, filters.
                     If None, the server auto-detects the type.
        limit: Results per page (1-100, default 24)
        page: Page number (1-indexed)
        sort: 'recent' or 'relevance' (optional)
        tag_type: Required when search_type='tags'. One of:
                  'organisms', 'citations', 'dataSource'

    Returns:
        dict with:
          - 'data': list of molecule dicts (identifier, canonical_smiles,
             name, iupac_name, annotation_level, organism_count, etc.)
          - 'total': total number of results
          - 'current_page': current page number
          - 'last_page': total number of pages
          - 'per_page': results per page
    """
    body = {"query": query, "limit": min(limit, 100), "page": max(page, 1)}
    if search_type:
        body["type"] = search_type
    if sort:
        body["sort"] = sort
    if tag_type:
        body["tagType"] = tag_type

    raw = _api_post(SEARCH_ENDPOINT, body)

    # Normalize the nested response
    data_wrapper = raw.get("data", {})
    if isinstance(data_wrapper, dict):
        return {
            "data": data_wrapper.get("data", []),
            "total": data_wrapper.get("total", 0),
            "current_page": data_wrapper.get("current_page", page),
            "last_page": data_wrapper.get("last_page", 1),
            "per_page": data_wrapper.get("per_page", limit),
        }
    return {"data": [], "total": 0, "current_page": page, "last_page": 1, "per_page": limit}


# ======================================================================
# MOLECULE SEARCH CONVENIENCE FUNCTIONS
# ======================================================================

def search_molecules(query, limit=24, page=1):
    """Search molecules by name/text (searches name, synonyms, identifier).

    Args:
        query: Text to search (e.g. "caffeine", "quercetin")
        limit: Results per page (max 100)
        page: Page number

    Returns:
        Normalized result dict with 'data', 'total', pagination info
    """
    return search(query, search_type="text", limit=limit, page=page)


def search_by_smiles(smiles, limit=24, page=1):
    """Search molecules by SMILES (structure + substructure search).

    Args:
        smiles: SMILES string
        limit: Results per page
        page: Page number

    Returns:
        Result dict (includes similarity scores)
    """
    return search(smiles, search_type="smiles", limit=limit, page=page)


def search_by_inchikey(inchikey, limit=10, page=1):
    """Search molecules by InChIKey.

    Args:
        inchikey: Standard InChIKey (full 27-char or partial 14-char)
        limit: Results per page
        page: Page number

    Returns:
        Result dict
    """
    return search(inchikey, search_type="inchikey", limit=limit, page=page)


def search_by_inchi(inchi, limit=10, page=1):
    """Search molecules by InChI string.

    Args:
        inchi: InChI string (with or without "InChI=" prefix)
        limit: Results per page
        page: Page number

    Returns:
        Result dict
    """
    return search(inchi, search_type="inchi", limit=limit, page=page)


def search_exact(smiles, limit=10, page=1):
    """Exact structure match by SMILES (stereo-aware).

    Args:
        smiles: Canonical SMILES
        limit: Results per page
        page: Page number

    Returns:
        Result dict (usually 0 or 1 result)
    """
    return search(smiles, search_type="exact", limit=limit, page=page)


def search_similarity(smiles, limit=24, page=1):
    """Tanimoto similarity search by SMILES.

    Args:
        smiles: SMILES query
        limit: Results per page
        page: Page number

    Returns:
        Result dict sorted by similarity (descending)
    """
    return search(smiles, search_type="similarity", limit=limit, page=page)


def search_substructure(smiles, limit=24, page=1):
    """Substructure search by SMILES.

    Args:
        smiles: SMILES substructure query
        limit: Results per page
        page: Page number

    Returns:
        Result dict of molecules containing the substructure
    """
    return search(smiles, search_type="substructure", limit=limit, page=page)


def search_by_identifier(identifier, limit=10, page=1):
    """Search by COCONUT identifier (e.g. 'CNP0228556').

    The server auto-detects CNP identifiers. No need to specify type.

    Args:
        identifier: COCONUT identifier (e.g. 'CNP0228556' or 'CNP0228556.0')
        limit: Results per page
        page: Page number

    Returns:
        Result dict
    """
    return search(identifier, search_type=None, limit=limit, page=page)


def search_by_formula(formula, limit=24, page=1):
    """Search by molecular formula (e.g. 'C8H10N4O2').

    The server auto-detects molecular formula format.

    Args:
        formula: Molecular formula string
        limit: Results per page
        page: Page number

    Returns:
        Result dict
    """
    return search(formula, search_type=None, limit=limit, page=page)


# ======================================================================
# PROPERTY-BASED FILTERING (filter search type)
# ======================================================================

def search_by_filters(filter_query, limit=24, page=1):
    """Search molecules using property filters.

    The filter query uses short key:value syntax. Multiple filters are
    AND-combined (space-separated). OR is also supported.

    Filter key reference (short_key -> database column):
        mw      -> molecular_weight         (range: "mw:100..500")
        emw     -> exact_molecular_weight
        alogp   -> alogp                    (range: "alogp:0..5")
        topopsa -> topological_polar_surface_area
        hac     -> heavy_atom_count
        tac     -> total_atom_count
        hba     -> hydrogen_bond_acceptors  (range: "hba:0..10")
        hbd     -> hydrogen_bond_donors     (range: "hbd:0..5")
        rbc     -> rotatable_bond_count
        arc     -> aromatic_rings_count
        mrc     -> number_of_minimal_rings
        fc      -> formal_charge
        fcsp3   -> fractioncsp3
        vdwv    -> van_der_walls_volume
        qed     -> qed_drug_likeliness      (range: "qed:0.5..1")
        np      -> np_likeness
        cs      -> contains_sugar           (bool: "cs:true")
        crs     -> contains_ring_sugars
        cls     -> contains_linear_sugars
        ro5v    -> rule_of_5_violations
        lro5v   -> lipinski_rule_of_five_violations
        lhba    -> hydrogen_bond_acceptors_lipinski
        lhbd    -> hydrogen_bond_donors_lipinski
        mf      -> molecular_formula        (text: "mf:C8H10N4O2")
        class       -> chemical_class       (text: "class:Flavonoids")
        subclass    -> chemical_sub_class
        superclass  -> chemical_super_class
        parent      -> direct_parent_classification
        np_class    -> np_classifier_class
        np_superclass -> np_classifier_superclass
        np_pathway  -> np_classifier_pathway
        np_glycoside -> np_classifier_is_glycoside

    Value formats:
        Numeric range: "key:min..max"  (e.g. "mw:200..500")
        Boolean: "key:true" or "key:false"
        Text: "key:value" (case-insensitive partial match)
        Multiple words: replace spaces with + (e.g. "class:Amino+acids")

    Combining:
        AND: space-separated (e.g. "mw:100..500 hba:0..10 hbd:0..5")
        OR: "OR" keyword (e.g. "mw:100..200 OR mw:400..500")

    Args:
        filter_query: Filter string (e.g. "mw:100..500 hba:0..10")
        limit: Results per page (max 100)
        page: Page number

    Returns:
        Result dict with matching molecules
    """
    return search(filter_query, search_type="filters", limit=limit, page=page)


def get_drug_like_molecules(max_mw=500, max_hba=10, max_hbd=5, limit=24, page=1):
    """Get drug-like natural products (Lipinski Ro5 compliant).

    Args:
        max_mw: Max molecular weight (default 500)
        max_hba: Max H-bond acceptors (default 10)
        max_hbd: Max H-bond donors (default 5)
        limit: Results per page
        page: Page number

    Returns:
        Result dict with drug-like NPs
    """
    query = f"mw:0..{max_mw} hba:0..{max_hba} hbd:0..{max_hbd}"
    return search_by_filters(query, limit=limit, page=page)


def get_molecules_by_np_pathway(pathway, limit=24, page=1):
    """Get molecules by NP Classifier pathway.

    Common pathways: Terpenoids, Alkaloids, Polyketides, Shikimates and Phenylpropanoids,
    Fatty acids, Amino acids and Peptides, Carbohydrates

    Args:
        pathway: NP Classifier pathway name
        limit: Results per page
        page: Page number

    Returns:
        Result dict
    """
    q = "np_pathway:" + pathway.replace(" ", "+")
    return search_by_filters(q, limit=limit, page=page)


def get_molecules_by_np_class(np_class, limit=24, page=1):
    """Get molecules by NP Classifier class.

    Args:
        np_class: NP Classifier class name
        limit: Results per page
        page: Page number

    Returns:
        Result dict
    """
    q = "np_class:" + np_class.replace(" ", "+")
    return search_by_filters(q, limit=limit, page=page)


def get_molecules_by_np_superclass(np_superclass, limit=24, page=1):
    """Get molecules by NP Classifier superclass.

    Args:
        np_superclass: NP Classifier superclass name
        limit: Results per page
        page: Page number

    Returns:
        Result dict
    """
    q = "np_superclass:" + np_superclass.replace(" ", "+")
    return search_by_filters(q, limit=limit, page=page)


def get_molecules_by_chemical_class(chemical_class, limit=24, page=1):
    """Get molecules by ClassyFire chemical class.

    Args:
        chemical_class: ClassyFire chemical class name
        limit: Results per page
        page: Page number

    Returns:
        Result dict
    """
    q = "class:" + chemical_class.replace(" ", "+")
    return search_by_filters(q, limit=limit, page=page)


def get_molecules_with_sugar(sugar_type="any", limit=24, page=1):
    """Get sugar-containing natural products.

    Args:
        sugar_type: 'any' (cs), 'ring' (crs), or 'linear' (cls)
        limit: Results per page
        page: Page number

    Returns:
        Result dict
    """
    key_map = {"any": "cs", "ring": "crs", "linear": "cls"}
    key = key_map.get(sugar_type, "cs")
    return search_by_filters(f"{key}:true", limit=limit, page=page)


def filter_by_molecular_weight(min_mw, max_mw, limit=24, page=1):
    """Filter molecules by molecular weight range.

    Args:
        min_mw: Minimum molecular weight
        max_mw: Maximum molecular weight
        limit: Results per page
        page: Page number

    Returns:
        Result dict
    """
    return search_by_filters(f"mw:{min_mw}..{max_mw}", limit=limit, page=page)


def filter_by_logp(min_logp, max_logp, limit=24, page=1):
    """Filter molecules by ALogP range.

    Args:
        min_logp: Minimum ALogP
        max_logp: Maximum ALogP
        limit: Results per page
        page: Page number

    Returns:
        Result dict
    """
    return search_by_filters(f"alogp:{min_logp}..{max_logp}", limit=limit, page=page)


# ======================================================================
# TAG-BASED SEARCH (organisms, citations, data sources)
# ======================================================================

def search_by_organism(organism_name, limit=24, page=1):
    """Search natural products by source organism name.

    Args:
        organism_name: Organism name (e.g. "Cannabis", "Artemisia annua")
        limit: Results per page
        page: Page number

    Returns:
        Result dict with molecules from the given organism
    """
    return search(organism_name, search_type="tags", tag_type="organisms",
                  limit=limit, page=page)


def search_by_citation(citation_query, limit=24, page=1):
    """Search natural products by literature citation (DOI or title).

    Args:
        citation_query: DOI or title text
        limit: Results per page
        page: Page number

    Returns:
        Result dict with molecules from matching citations
    """
    return search(citation_query, search_type="tags", tag_type="citations",
                  limit=limit, page=page)


def search_by_data_source(collection_title, limit=24, page=1):
    """Search natural products by data source collection.

    Common collections: ChEMBL NPs, NPAtlas, KNApSaCK, UNPD, DNP, etc.

    Args:
        collection_title: Exact collection title
        limit: Results per page
        page: Page number

    Returns:
        Result dict with molecules from the collection
    """
    return search(collection_title, search_type="tags", tag_type="dataSource",
                  limit=limit, page=page)


# ======================================================================
# BIOSCHEMAS ENDPOINT (detailed molecule data)
# ======================================================================

def get_molecule_schema(identifier):
    """Get detailed molecule data via Bioschemas JSON-LD endpoint.

    Returns comprehensive data including name, SMILES, InChI, InChIKey,
    molecular formula, collections, and Schema.org structured data.

    Args:
        identifier: COCONUT identifier (e.g. 'CNP0228556.0')
                    If no '.X' suffix, '.0' is appended automatically.

    Returns:
        dict with Schema.org JSON-LD molecule data
    """
    if "." not in str(identifier):
        identifier = str(identifier) + ".0"
    return _api_get(f"{BIOSCHEMAS_ENDPOINT}/{identifier}")


# ======================================================================
# PAGINATION AND BATCH HELPERS
# ======================================================================

def fetch_all_pages(search_func, max_pages=10, **kwargs):
    """Auto-paginate through a search function and collect all results.

    Args:
        search_func: Any search function that accepts 'page' kwarg
        max_pages: Maximum number of pages to fetch (safety limit)
        **kwargs: Additional arguments passed to the search function

    Returns:
        List of all molecule dicts across pages
    """
    all_results = []
    for page_num in range(1, max_pages + 1):
        logging.info("Fetching page %d/%d...", page_num, max_pages)
        try:
            resp = search_func(page=page_num, **kwargs)
            data = resp.get("data", [])
            if not data:
                logging.info("No more data at page %d. Total: %d", page_num, len(all_results))
                break
            all_results.extend(data)
            last_page = resp.get("last_page", max_pages)
            if page_num >= last_page:
                logging.info("Reached last page (%d). Total: %d", last_page, len(all_results))
                break
        except Exception as e:
            logging.error("Error on page %d: %s", page_num, e)
            break
    return all_results


def batch_search_molecules(names, limit_per_query=5):
    """Search for multiple molecules by name.

    Args:
        names: List of molecule names to search
        limit_per_query: Results per individual search

    Returns:
        List of {name, results, count} dicts
    """
    results = []
    for i, name in enumerate(names):
        logging.info("Searching '%s' (%d/%d)", name, i + 1, len(names))
        try:
            resp = search_molecules(name, limit=limit_per_query)
            results.append({
                "query": name,
                "results": resp.get("data", []),
                "count": resp.get("total", 0),
            })
        except Exception as e:
            results.append({"query": name, "results": [], "count": 0, "error": str(e)})
        if i < len(names) - 1:
            time.sleep(0.3)
    return results


def batch_lookup_identifiers(identifiers):
    """Look up multiple molecules by COCONUT identifier.

    Args:
        identifiers: List of COCONUT identifiers (e.g. ['CNP0228556', 'CNP0106880'])

    Returns:
        List of molecule dicts (one per identifier)
    """
    results = []
    for i, ident in enumerate(identifiers):
        logging.info("Looking up %s (%d/%d)", ident, i + 1, len(identifiers))
        try:
            resp = search_by_identifier(ident, limit=5)
            data = resp.get("data", [])
            if data:
                mol = data[0]
                mol["_lookup_id"] = ident
                results.append(mol)
            else:
                results.append({"_lookup_id": ident, "error": "not found"})
        except Exception as e:
            results.append({"_lookup_id": ident, "error": str(e)})
        if i < len(identifiers) - 1:
            time.sleep(0.3)
    return results


# ======================================================================
# DATA CONVERSION UTILITIES
# ======================================================================

def results_to_dataframe(results):
    """Convert search results to a pandas DataFrame.

    Args:
        results: Either a search response dict (with 'data' key)
                 or a list of molecule dicts

    Returns:
        pandas DataFrame
    """
    if isinstance(results, dict):
        data = results.get("data", [])
    else:
        data = results

    if not data:
        return pd.DataFrame()

    if isinstance(data, list):
        return pd.json_normalize(data)
    elif isinstance(data, dict):
        return pd.DataFrame([data])
    return pd.DataFrame()


def export_results_to_csv(results, filename="coconut_results.csv"):
    """Export results to a CSV file in the output directory.

    Args:
        results: Search response dict or list of molecule dicts
        filename: Output filename

    Returns:
        Full path to the saved CSV file
    """
    df = results_to_dataframe(results)
    out_path = os.path.join(_config["output_dir"], filename)
    df.to_csv(out_path, index=False)
    logging.info("Exported %d rows to %s", len(df), out_path)
    return out_path


def export_results_to_json(results, filename="coconut_results.json"):
    """Export results to a JSON file in the output directory.

    Args:
        results: Search response dict or list of molecule dicts
        filename: Output filename

    Returns:
        Full path to the saved JSON file
    """
    if isinstance(results, dict):
        data = results.get("data", results)
    else:
        data = results
    out_path = os.path.join(_config["output_dir"], filename)
    with open(out_path, "w") as f:
        json.dump(data, f, indent=2, default=str)
    logging.info("Exported to %s", out_path)
    return out_path
