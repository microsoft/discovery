"""
Search utilities for querying RCSB PDB database.
"""
import requests
import json
from typing import List, Dict, Optional, Union
import pandas as pd
import os


def search_by_organism(organism: str, max_results: int = 500) -> List[str]:
    """
    Search for structures by organism name.
    
    Args:
        organism: Organism name (e.g., "Homo sapiens", "E. coli")
        max_results: Maximum number of results to return
    
    Returns:
        List of PDB IDs (empty list if search fails)
    """
    # RCSB API has a max of 100 rows per request
    rows_to_fetch = min(100, max_results)
    
    query = {
        "query": {
            "type": "terminal",
            "service": "text",
            "parameters": {
                "attribute": "rcsb_entity_source_organism.taxonomy_lineage.name",
                "operator": "contains_phrase",
                "value": organism
            }
        },
        "return_type": "entry",
        "request_options": {
            "results_content_type": ["experimental"],
            "sort": [{"sort_by": "score", "direction": "desc"}],
            "scoring_strategy": "combined",
            "paginate": {
                "start": 0,
                "rows": rows_to_fetch
            }
        }
    }
    
    url = "https://search.rcsb.org/rcsbsearch/v2/query"
    try:
        response = requests.post(url, json=query, timeout=30)
        response.raise_for_status()
        data = response.json()
        pdb_ids = [result["identifier"] for result in data.get("result_set", [])[:max_results]]
        return pdb_ids
    except requests.exceptions.HTTPError as e:
        print(f"⚠️ HTTP error searching for organism '{organism}': {e}")
        return []
    except requests.exceptions.RequestException as e:
        print(f"⚠️ Network error searching for organism '{organism}': {e}")
        return []
    except (KeyError, ValueError, json.JSONDecodeError) as e:
        print(f"⚠️ Error parsing search results for organism '{organism}': {e}")
        return []
    except Exception as e:
        print(f"⚠️ Unexpected error searching for organism '{organism}': {e}")
        return []


def search_by_resolution(min_resolution: float = 0.0, max_resolution: float = 2.0, max_results: int = 500) -> List[str]:
    """
    Search for structures by resolution range.
    
    Args:
        min_resolution: Minimum resolution in Angstroms
        max_resolution: Maximum resolution in Angstroms
        max_results: Maximum number of results to return
    
    Returns:
        List of PDB IDs (empty list if search fails)
    """
    # RCSB API has a max of 100 rows per request
    rows_to_fetch = min(100, max_results)
    
    query = {
        "query": {
            "type": "terminal",
            "service": "text",
            "parameters": {
                "attribute": "rcsb_entry_info.resolution_combined",
                "operator": "range",
                "value": {
                    "from": min_resolution,
                    "to": max_resolution,
                    "include_lower": True,
                    "include_upper": True
                }
            }
        },
        "return_type": "entry",
        "request_options": {
            "results_content_type": ["experimental"],
            "sort": [{"sort_by": "rcsb_entry_info.resolution_combined", "direction": "asc"}],
            "scoring_strategy": "combined",
            "paginate": {
                "start": 0,
                "rows": rows_to_fetch
            }
        }
    }
    
    url = "https://search.rcsb.org/rcsbsearch/v2/query"
    try:
        response = requests.post(url, json=query, timeout=30)
        response.raise_for_status()
        data = response.json()
        pdb_ids = [result["identifier"] for result in data.get("result_set", [])[:max_results]]
        return pdb_ids
    except requests.exceptions.HTTPError as e:
        print(f"⚠️ HTTP error searching by resolution ({min_resolution}-{max_resolution}Å): {e}")
        return []
    except requests.exceptions.RequestException as e:
        print(f"⚠️ Network error searching by resolution ({min_resolution}-{max_resolution}Å): {e}")
        return []
    except (KeyError, ValueError, json.JSONDecodeError) as e:
        print(f"⚠️ Error parsing search results for resolution range: {e}")
        return []
    except Exception as e:
        print(f"⚠️ Unexpected error searching by resolution: {e}")
        return []


def search_by_experimental_method(method: str, max_results: int = 500) -> List[str]:
    """
    Search for structures by experimental method.
    
    Args:
        method: Experimental method (e.g., "X-RAY DIFFRACTION", "SOLUTION NMR", "ELECTRON MICROSCOPY")
        max_results: Maximum number of results to return
    
    Returns:
        List of PDB IDs (empty list if search fails)
    """
    # RCSB API has a max of 100 rows per request
    rows_to_fetch = min(100, max_results)
    
    query = {
        "query": {
            "type": "terminal",
            "service": "text",
            "parameters": {
                "attribute": "exptl.method",
                "operator": "exact_match",
                "value": method.upper()
            }
        },
        "return_type": "entry",
        "request_options": {
            "results_content_type": ["experimental"],
            "sort": [{"sort_by": "score", "direction": "desc"}],
            "scoring_strategy": "combined",
            "paginate": {
                "start": 0,
                "rows": rows_to_fetch
            }
        }
    }
    
    url = "https://search.rcsb.org/rcsbsearch/v2/query"
    try:
        response = requests.post(url, json=query, timeout=30)
        response.raise_for_status()
        data = response.json()
        pdb_ids = [result["identifier"] for result in data.get("result_set", [])[:max_results]]
        return pdb_ids
    except requests.exceptions.HTTPError as e:
        print(f"⚠️ HTTP error searching for experimental method '{method}': {e}")
        return []
    except requests.exceptions.RequestException as e:
        print(f"⚠️ Network error searching for experimental method '{method}': {e}")
        return []
    except (KeyError, ValueError, json.JSONDecodeError) as e:
        print(f"⚠️ Error parsing search results for experimental method: {e}")
        return []
    except Exception as e:
        print(f"⚠️ Unexpected error searching for experimental method: {e}")
        return []


def _rcsb_search(query_body: dict, protein_name: str, max_results: int) -> List[str]:
    """Execute a single paginated RCSB search query and return PDB IDs."""
    all_pdb_ids = []
    rows_per_request = min(100, max_results)
    url = "https://search.rcsb.org/rcsbsearch/v2/query"

    for start in range(0, max_results, rows_per_request):
        rows_needed = min(rows_per_request, max_results - start)
        query_body["request_options"]["paginate"] = {
            "start": start,
            "rows": rows_needed
        }

        response = None
        try:
            print(f"🔍 Requesting {rows_needed} results starting at {start} for protein '{protein_name}'")
            response = requests.post(url, json=query_body, timeout=30)

            if response.status_code == 204:
                # 204 = no results found for this query
                break

            if response.status_code != 200:
                try:
                    error_detail = response.json()
                    print(f"⚠️ API returned status {response.status_code}: {error_detail}")
                except Exception:
                    print(f"⚠️ API returned status {response.status_code}: {response.text[:200]}")
                break

            data = response.json()
            result_set = data.get("result_set", [])

            if not result_set:
                break

            pdb_ids = [result["identifier"] for result in result_set]
            all_pdb_ids.extend(pdb_ids)
            print(f"✅ Retrieved {len(pdb_ids)} results (total: {len(all_pdb_ids)})")

            if len(result_set) < rows_needed:
                break

        except requests.exceptions.HTTPError as e:
            if response is not None:
                try:
                    error_detail = response.json()
                    print(f"⚠️ HTTP error searching for protein '{protein_name}': {e}")
                    print(f"⚠️ Error details: {error_detail}")
                except Exception:
                    print(f"⚠️ HTTP error searching for protein '{protein_name}': {e}")
                    print(f"⚠️ Response text: {response.text[:500]}")
            else:
                print(f"⚠️ HTTP error searching for protein '{protein_name}': {e}")
            break
        except requests.exceptions.RequestException as e:
            print(f"⚠️ Network error searching for protein '{protein_name}': {e}")
            break
        except (KeyError, ValueError, json.JSONDecodeError) as e:
            print(f"⚠️ Error parsing search results for protein name: {e}")
            break
        except Exception as e:
            print(f"⚠️ Unexpected error searching for protein: {e}")
            break

    return all_pdb_ids[:max_results]


def search_by_protein_name(protein_name: str, max_results: int = 500) -> List[str]:
    """
    Search for structures by protein name.

    Uses a multi-tier strategy for robust matching:
    1. Exact phrase match on struct.title
    2. AND group: each word must appear in title (for multi-word queries)
    3. Entity description search (catches alternate protein names)
    4. Full-text search across all RCSB fields
    5. First word only on title (drops qualifiers)

    Args:
        protein_name: Protein name (e.g., "lysozyme", "Akt1 inhibitor")
        max_results: Maximum number of results to return

    Returns:
        List of PDB IDs (empty list if search fails)
    """
    base_opts = {
        "results_content_type": ["experimental"],
        "sort": [{"sort_by": "score", "direction": "desc"}],
        "scoring_strategy": "combined",
        "paginate": {"start": 0, "rows": min(100, max_results)}
    }

    # Strategy 1: Exact phrase match on title (fast, precise)
    print(f"🔍 Searching for '{protein_name}' (phrase match on title)...")
    q1 = {
        "query": {"type": "terminal", "service": "text",
                  "parameters": {"attribute": "struct.title",
                                 "operator": "contains_phrase",
                                 "value": protein_name}},
        "return_type": "entry", "request_options": dict(base_opts)
    }
    results = _rcsb_search(q1, protein_name, max_results)
    if results:
        print(f"✅ Found {len(results)} results (phrase match)")
        return results

    words = protein_name.split()
    if len(words) < 2:
        print(f"ℹ️ No results for '{protein_name}'")
        return []

    # Strategy 2: AND group — each word in title (any order)
    print(f"ℹ️ Phrase match returned 0, trying AND word match on title...")
    and_nodes = [
        {"type": "terminal", "service": "text",
         "parameters": {"attribute": "struct.title",
                        "operator": "contains_words", "value": w}}
        for w in words
    ]
    q2 = {
        "query": {"type": "group", "logical_operator": "and", "nodes": and_nodes},
        "return_type": "entry", "request_options": dict(base_opts)
    }
    results = _rcsb_search(q2, protein_name, max_results)
    if results:
        print(f"✅ Found {len(results)} results (AND words in title)")
        return results

    # Strategy 3: Entity description (macromolecule names)
    print(f"ℹ️ Title search returned 0, trying entity description...")
    q3 = {
        "query": {"type": "terminal", "service": "text",
                  "parameters": {"attribute": "rcsb_polymer_entity.pdbx_description",
                                 "operator": "contains_words",
                                 "value": words[0]}},
        "return_type": "entry", "request_options": dict(base_opts)
    }
    results = _rcsb_search(q3, words[0], max_results)
    if results:
        print(f"✅ Found {len(results)} results (entity description '{words[0]}')")
        return results

    # Strategy 4: Full-text search
    print(f"ℹ️ Entity search returned 0, trying full-text search...")
    q4 = {
        "query": {"type": "terminal", "service": "full_text",
                  "parameters": {"value": protein_name}},
        "return_type": "entry", "request_options": dict(base_opts)
    }
    results = _rcsb_search(q4, protein_name, max_results)
    if results:
        print(f"✅ Found {len(results)} results (full-text)")
        return results

    # Strategy 5: First word only on title
    primary = words[0]
    print(f"ℹ️ Full-text returned 0, trying title search for '{primary}' only...")
    q5 = {
        "query": {"type": "terminal", "service": "text",
                  "parameters": {"attribute": "struct.title",
                                 "operator": "contains_phrase",
                                 "value": primary}},
        "return_type": "entry", "request_options": dict(base_opts)
    }
    results = _rcsb_search(q5, primary, max_results)
    if results:
        print(f"✅ Found {len(results)} results (title '{primary}')")
        return results

    print(f"ℹ️ No results found for '{protein_name}' with any strategy")
    return []


def search_by_ligand(ligand_name: str, max_results: int = 500) -> List[str]:
    """
    Search for structures containing a specific ligand.
    
    Args:
        ligand_name: Ligand name or ID (e.g., "ATP", "HEME")
        max_results: Maximum number of results to return
    
    Returns:
        List of PDB IDs (empty list if search fails)
    """
    query = {
        "query": {
            "type": "terminal",
            "service": "text",
            "parameters": {
                "attribute": "rcsb_binding_affinity.comp_id",
                "operator": "exact_match",
                "value": ligand_name.upper()
            }
        },
        "return_type": "entry",
        "request_options": {
            "results_content_type": ["experimental"],
            "sort": [{"sort_by": "score", "direction": "desc"}],
            "scoring_strategy": "combined",
            "paginate": {
                "start": 0,
                "rows": min(100, max_results)
            }
        }
    }
    
    url = "https://search.rcsb.org/rcsbsearch/v2/query"
    try:
        response = requests.post(url, json=query, timeout=30)
        response.raise_for_status()
        data = response.json()
        pdb_ids = [result["identifier"] for result in data.get("result_set", [])[:max_results]]
        return pdb_ids
    except requests.exceptions.HTTPError as e:
        print(f"⚠️ HTTP error searching for ligand '{ligand_name}': {e}")
        return []
    except requests.exceptions.RequestException as e:
        print(f"⚠️ Network error searching for ligand '{ligand_name}': {e}")
        return []
    except (KeyError, ValueError, json.JSONDecodeError) as e:
        print(f"⚠️ Error parsing search results for ligand: {e}")
        return []
    except Exception as e:
        print(f"⚠️ Unexpected error searching for ligand: {e}")
        return []


def advanced_search(search_criteria: Dict, max_results: int = 500) -> List[str]:
    """
    Perform advanced search with multiple criteria.
    
    Args:
        search_criteria: Dictionary with search parameters
        max_results: Maximum number of results to return
    
    Returns:
        List of PDB IDs
    """
    queries = []
    
    # Build query components based on criteria
    if "organism" in search_criteria:
        queries.append({
            "type": "terminal",
            "service": "text",
            "parameters": {
                "attribute": "rcsb_entity_source_organism.taxonomy_lineage.name",
                "operator": "contains_phrase",
                "value": search_criteria["organism"]
            }
        })
    
    if "resolution_range" in search_criteria:
        res_range = search_criteria["resolution_range"]
        queries.append({
            "type": "terminal",
            "service": "text",
            "parameters": {
                "attribute": "rcsb_entry_info.resolution_combined",
                "operator": "range",
                "value": {
                    "from": res_range.get("min", 0.0),
                    "to": res_range.get("max", 10.0),
                    "include_lower": True,
                    "include_upper": True
                }
            }
        })
    
    if "experimental_method" in search_criteria:
        queries.append({
            "type": "terminal",
            "service": "text",
            "parameters": {
                "attribute": "exptl.method",
                "operator": "exact_match",
                "value": search_criteria["experimental_method"].upper()
            }
        })
    
    if "protein_name" in search_criteria:
        queries.append({
            "type": "terminal",
            "service": "text",
            "parameters": {
                "attribute": "struct.title",
                "operator": "contains_phrase",
                "value": search_criteria["protein_name"]
            }
        })
    
    # Combine queries with AND logic
    if len(queries) == 1:
        combined_query = queries[0]
    else:
        combined_query = {
            "type": "group",
            "logical_operator": "and",
            "nodes": queries
        }
    
    query = {
        "query": combined_query,
        "return_type": "entry",
        "request_options": {
            "results_content_type": ["experimental"],
            "sort": [{"sort_by": "score", "direction": "desc"}],
            "scoring_strategy": "combined",
            "paginate": {
                "start": 0,
                "rows": min(100, max_results)
            }
        }
    }
    
    url = "https://search.rcsb.org/rcsbsearch/v2/query"
    try:
        response = requests.post(url, json=query, timeout=30)
        response.raise_for_status()
        data = response.json()
        pdb_ids = [result["identifier"] for result in data.get("result_set", [])[:max_results]]
        return pdb_ids
    except requests.exceptions.HTTPError as e:
        print(f"⚠️ HTTP error in advanced search: {e}")
        return []
    except requests.exceptions.RequestException as e:
        print(f"⚠️ Network error in advanced search: {e}")
        return []
    except (KeyError, ValueError, json.JSONDecodeError) as e:
        print(f"⚠️ Error parsing advanced search results: {e}")
        return []
    except Exception as e:
        print(f"⚠️ Unexpected error in advanced search: {e}")
        return []


def get_similar_structures(pdb_id: str, similarity_threshold: float = 0.7, max_results: int = 500) -> List[Dict]:
    """
    Find structurally similar proteins using RCSB structure similarity search.
    
    Args:
        pdb_id: Reference PDB ID
        similarity_threshold: Similarity threshold (0-1)
        max_results: Maximum number of results to return
    
    Returns:
        List of dictionaries with similar structure information
    """
    query = {
        "query": {
            "type": "terminal",
            "service": "structure",
            "parameters": {
                "operator": "strict_shape_match",
                "value": {
                    "entry_id": pdb_id.upper(),
                    "assembly_id": "1"
                }
            }
        },
        "return_type": "entry",
        "request_options": {
            "results_content_type": ["experimental"],
            "sort": [{"sort_by": "score", "direction": "desc"}],
            "paginate": {
                "start": 0,
                "rows": min(100, max_results)
            }
        }
    }
    
    url = "https://search.rcsb.org/rcsbsearch/v2/query"
    try:
        response = requests.post(url, json=query, timeout=30)
        response.raise_for_status()
        data = response.json()
        
        similar_structures = []
        for result in data.get("result_set", [])[:max_results]:
            if result.get("score", 0) >= similarity_threshold:
                similar_structures.append({
                    "pdb_id": result["identifier"],
                    "similarity_score": result.get("score", 0)
                })
        
        return similar_structures
    except requests.exceptions.HTTPError as e:
        print(f"⚠️ HTTP error finding similar structures to '{pdb_id}': {e}")
        return []
    except requests.exceptions.RequestException as e:
        print(f"⚠️ Network error finding similar structures to '{pdb_id}': {e}")
        return []
    except (KeyError, ValueError, json.JSONDecodeError) as e:
        print(f"⚠️ Error parsing similarity search results: {e}")
        return []
    except Exception as e:
        print(f"⚠️ Unexpected error finding similar structures: {e}")
        return []


def save_search_results(search_results: List[str], search_type: str, output_dir: str) -> str:
    """
    Save search results to a CSV file.
    
    Args:
        search_results: List of PDB IDs
        search_type: Description of the search performed
        output_dir: Directory to save the results
    
    Returns:
        Path to the saved CSV file
    """
    os.makedirs(output_dir, exist_ok=True)
    
    # Create DataFrame
    df = pd.DataFrame({
        "pdb_id": search_results,
        "search_type": [search_type] * len(search_results)
    })
    
    # Add index
    df.reset_index(drop=True, inplace=True)
    df.index.name = "rank"
    
    # Save to CSV
    filename = f"search_results_{search_type.replace(' ', '_').lower()}.csv"
    filepath = os.path.join(output_dir, filename)
    df.to_csv(filepath)
    
    return filepath


def get_weekly_releases() -> List[str]:
    """
    Get PDB IDs of structures released in the past week.
    
    Returns:
        List of recently released PDB IDs
    """
    from datetime import datetime, timedelta
    
    # Calculate date one week ago
    one_week_ago = datetime.now() - timedelta(days=7)
    date_string = one_week_ago.strftime("%Y-%m-%d")
    
    query = {
        "query": {
            "type": "terminal",
            "service": "text",
            "parameters": {
                "attribute": "rcsb_accession_info.initial_release_date",
                "operator": "greater_or_equal",
                "value": date_string
            }
        },
        "return_type": "entry",
        "request_options": {
            "results_content_type": ["experimental"],
            "sort": [{"sort_by": "rcsb_accession_info.initial_release_date", "direction": "desc"}],
            "paginate": {
                "start": 0,
                "rows": 1000
            }
        }
    }
    
    url = "https://search.rcsb.org/rcsbsearch/v2/query"
    try:
        response = requests.post(url, json=query, timeout=30)
        response.raise_for_status()
        data = response.json()
        pdb_ids = [result["identifier"] for result in data.get("result_set", [])]
        return pdb_ids
    except requests.exceptions.HTTPError as e:
        print(f"⚠️ HTTP error fetching weekly releases: {e}")
        return []
    except requests.exceptions.RequestException as e:
        print(f"⚠️ Network error fetching weekly releases: {e}")
        return []
    except (KeyError, ValueError, json.JSONDecodeError) as e:
        print(f"⚠️ Error parsing weekly release results: {e}")
        return []
    except Exception as e:
        print(f"⚠️ Unexpected error fetching weekly releases: {e}")
        return []


def search_by_author(author_name: str, max_results: int = 500) -> List[str]:
    """
    Search for structures by author name.
    
    Args:
        author_name: Author name (last name, first name)
        max_results: Maximum number of results to return
    
    Returns:
        List of PDB IDs
    """
    query = {
        "query": {
            "type": "terminal",
            "service": "text",
            "parameters": {
                "attribute": "audit_author.name",
                "operator": "contains_phrase",
                "value": author_name
            }
        },
        "return_type": "entry",
        "request_options": {
            "results_content_type": ["experimental"],
            "sort": [{"sort_by": "score", "direction": "desc"}],
            "scoring_strategy": "combined",
            "paginate": {
                "start": 0,
                "rows": min(100, max_results)
            }
        }
    }
    
    url = "https://search.rcsb.org/rcsbsearch/v2/query"
    try:
        response = requests.post(url, json=query, timeout=30)
        response.raise_for_status()
        data = response.json()
        pdb_ids = [result["identifier"] for result in data.get("result_set", [])[:max_results]]
        return pdb_ids
    except requests.exceptions.HTTPError as e:
        print(f"⚠️ HTTP error searching for author '{author_name}': {e}")
        return []
    except requests.exceptions.RequestException as e:
        print(f"⚠️ Network error searching for author '{author_name}': {e}")
        return []
    except (KeyError, ValueError, json.JSONDecodeError) as e:
        print(f"⚠️ Error parsing author search results: {e}")
        return []
    except Exception as e:
        print(f"⚠️ Unexpected error searching for author: {e}")
        return []

