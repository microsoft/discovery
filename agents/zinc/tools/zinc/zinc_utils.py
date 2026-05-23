"""
zinc_utils - Helper library for accessing the ZINC22 / CartBlanche REST API.

CartBlanche (https://cartblanche.docking.org) is the successor to ZINC15,
hosting 37B+ commercially available 3-D molecules for virtual screening.
This library wraps the REST API with retries, rate limiting, async-task
polling, and convenience functions.

Key API differences from ZINC15
-------------------------------
- Single-substance lookup is synchronous and returns SMILES, properties,
  vendor catalogs, and molecular formula in one response.
- Bulk lookup (multiple ZINC IDs) and SMILES-based similarity/exact search
  are *asynchronous*: the server returns a task UUID that must be polled.
- Name search and curated-subset browsing are NOT available.

Functions:
    get_substance(zinc_id)              - Sync lookup by ZINC ID (full detail)
    smiles_search(smiles, dist, db)     - Async SMILES exact/similarity search
    bulk_lookup(zinc_ids)               - Async batch lookup by ZINC IDs
"""

import requests
import json
import time
import sys
import traceback

__version__ = "2.0.0"

BASE_URL = "https://cartblanche.docking.org"
DEFAULT_TIMEOUT = 30
MAX_RETRIES = 3
RETRY_DELAY = 2
POLL_INTERVAL = 3        # seconds between task-status polls
POLL_MAX_ATTEMPTS = 60   # ~3 minutes max wait

# CartBlanche blocks bare python-requests User-Agent with 403
_SESSION = requests.Session()
_SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (compatible; ZINCUtils/2.0; +https://cartblanche.docking.org)",
    "Accept": "application/json",
})


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _normalize_zinc_id(zinc_id):
    """Normalize a ZINC ID to canonical format (e.g., ZINC000000000053).

    Accepts formats like 'ZINC53', 'ZINC000000000053', '53', 'zinc53'.
    Always returns uppercase with 12-digit zero-padded numeric part.
    """
    zinc_id = str(zinc_id).strip().upper()
    if not zinc_id.startswith("ZINC"):
        zinc_id = "ZINC" + zinc_id
    numeric = zinc_id[4:]
    if numeric.isdigit():
        zinc_id = "ZINC" + numeric.zfill(12)
    return zinc_id


def _get(url, params=None, timeout=DEFAULT_TIMEOUT):
    """Make a GET request with retries and error handling.

    Returns parsed JSON on success, None on 404, raises on persistent errors.
    """
    for attempt in range(MAX_RETRIES):
        try:
            resp = _SESSION.get(url, params=params, timeout=timeout)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.HTTPError:
            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt < MAX_RETRIES - 1:
                    wait = RETRY_DELAY * (attempt + 1)
                    print(f"[zinc_utils] HTTP {resp.status_code}, retrying in {wait}s...")
                    time.sleep(wait)
                    continue
            raise
        except requests.exceptions.Timeout:
            if attempt < MAX_RETRIES - 1:
                wait = RETRY_DELAY * (attempt + 1)
                print(f"[zinc_utils] Timeout, retrying in {wait}s...")
                time.sleep(wait)
                continue
            raise
        except requests.exceptions.ConnectionError:
            if attempt < MAX_RETRIES - 1:
                wait = RETRY_DELAY * (attempt + 1)
                print(f"[zinc_utils] Connection error, retrying in {wait}s...")
                time.sleep(wait)
                continue
            raise
    return None


def _post(url, data=None, timeout=DEFAULT_TIMEOUT):
    """Make a POST request with form data, retries, and error handling.

    Returns parsed JSON on success, raises on persistent errors.
    """
    for attempt in range(MAX_RETRIES):
        try:
            resp = _SESSION.post(url, data=data, timeout=timeout)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.HTTPError:
            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt < MAX_RETRIES - 1:
                    wait = RETRY_DELAY * (attempt + 1)
                    print(f"[zinc_utils] HTTP {resp.status_code}, retrying in {wait}s...")
                    time.sleep(wait)
                    continue
            raise
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
            if attempt < MAX_RETRIES - 1:
                wait = RETRY_DELAY * (attempt + 1)
                print(f"[zinc_utils] Network error, retrying in {wait}s...")
                time.sleep(wait)
                continue
            raise
    return None


def _poll_task(task_id, max_attempts=POLL_MAX_ATTEMPTS, interval=POLL_INTERVAL):
    """Poll an async task until completion.

    CartBlanche async endpoints (bulk lookup, SMILES search) return a task
    UUID on submission. This function polls ``/search/result/{task_id}``
    until the result is ready or the maximum number of attempts is reached.

    Args:
        task_id: UUID string returned by the async endpoint.
        max_attempts: Maximum number of poll cycles (default: 60).
        interval: Seconds between polls (default: 3).

    Returns:
        The ``result`` field from the completed task response.

    Raises:
        TimeoutError: If the task does not complete within max_attempts.
        RuntimeError: If the task response indicates an unexpected status.
    """
    url = f"{BASE_URL}/search/result/{task_id}"
    for i in range(max_attempts):
        data = _get(url, timeout=DEFAULT_TIMEOUT)
        if data is None:
            raise RuntimeError(f"Task {task_id}: poll returned 404")
        status = data.get("status")
        if status == "SUCCESS":
            return data.get("result")
        if status in ("FAILURE", "REVOKED"):
            raise RuntimeError(f"Task {task_id} failed with status={status}: {data}")
        # Still pending / in progress
        progress = data.get("progress", "")
        if i % 5 == 0:
            print(f"[zinc_utils] Task {task_id}: status={status} progress={progress} (poll {i+1}/{max_attempts})")
        time.sleep(interval)
    raise TimeoutError(f"Task {task_id} did not complete within {max_attempts * interval}s")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_substance(zinc_id):
    """Get a single substance by its ZINC ID (synchronous, full detail).

    The CartBlanche single-substance endpoint returns SMILES, molecular
    formula, tranche details (logp, mwt, inchi, inchikey, heavy_atoms),
    ring count, heteroatom count, and vendor catalog entries in a single
    response. There is no need to call separate protomers/catalogs endpoints.

    Args:
        zinc_id: ZINC identifier in any format (e.g., 'ZINC000000000053',
                 'ZINC53', or just '53').
def get_substance(zinc_id):
    """Get a single substance by its ZINC ID (synchronous, full detail).

    The CartBlanche single-substance endpoint returns SMILES, molecular
    formula, tranche details (logp, mwt, inchi, inchikey, heavy_atoms),
    ring count, heteroatom count, and vendor catalog entries in a single
    response. There is no need to call separate protomers/catalogs endpoints.

    Args:
        zinc_id: ZINC identifier in any format (e.g., 'ZINC000000000053',
                 'ZINC53', or just '53').

    Returns:
        Dict with keys: zinc_id, smiles, mol_formula, tranche_details,
        catalogs, rings, hetero_atoms, db. Returns None if not found.

        tranche_details: dict with logp (float), mwt (float), inchi (str),
            inchikey (str), heavy_atoms (int).
        catalogs: list of vendor dicts, each with keys catalog_name, price,
            quantity, shipping, supplier_code, unit, url, purchase.

    Example:
        >>> sub = get_substance('ZINC000000000053')
        >>> print(sub['smiles'])
        CC(=O)Oc1ccccc1C(=O)O
        >>> print(sub['tranche_details']['mwt'])
        180.159
    """
    Submits an asynchronous search task and polls until results are ready.
    dist=0 performs exact-match lookup; dist>0 performs Tanimoto similarity
    search (larger dist = more permissive, but slower -- can take 30s+).
def smiles_search(smiles, dist=0, db="zinc22-2D"):
    """Search CartBlanche by SMILES (exact or similarity).

    Submits an asynchronous search task and polls until results are ready.
    dist=0 performs exact-match lookup; dist>0 performs Tanimoto similarity
    search (larger dist = more permissive, but slower -- can take 30s+).

    Args:
        smiles: SMILES string of the query molecule.
        dist: Maximum Tanimoto distance (0 = exact match, 1-4 for similarity).
              Default: 0.
        db: Database to search. Default: 'zinc22-2D'.

    Returns:
        Dict with keys: zinc22 (list of matching substance dicts),
        zinc22_missing (list), hostname, logs. Access the hit list via
        result["zinc22"].

        Note: CartBlanche does NOT reject invalid SMILES server-side.
        Invalid input completes without error but returns an empty
        zinc22 list.

    Raises:
        TimeoutError: If the search does not complete within the polling window.
        RuntimeError: If the search task fails.

    Example:
        >>> result = smiles_search('CC(=O)Oc1ccccc1C(=O)O', dist=0)
        >>> hits = result['zinc22']
        >>> print(len(hits))
    """
    task_id = resp.get("task_id") or resp.get("task")
    if not task_id:
        raise RuntimeError(f"SMILES search did not return a task id: {resp}")
    print(f"[zinc_utils] SMILES search submitted, task_id={task_id}")
def bulk_lookup(zinc_ids):
    """Look up multiple ZINC IDs in a single async request.

    Submits a batch request to CartBlanche and polls until results are
    ready.

    Args:
        zinc_ids: List of ZINC identifiers (any format).

    Returns:
        Dict with keys: zinc20 (list of substance dicts) and missing
        (list of ZINC IDs not found). Access results via
        result["zinc20"].

    Raises:
        TimeoutError: If the batch task does not complete within the polling window.
        RuntimeError: If the batch task fails.

    Example:
        >>> ids = ['ZINC000000000053', 'ZINC000003807804']
        >>> result = bulk_lookup(ids)
        >>> for sub in result['zinc20']:
        ...     print(sub.get('zinc_id'), sub.get('smiles'))
    """
        RuntimeError: If the batch task fails.

    Example:
        >>> ids = ['ZINC000000000053', 'ZINC000003807804']
        >>> results = bulk_lookup(ids)
        >>> for r in results:
        ...     print(r.get('zinc_id'), r.get('smiles'))
    """
    normalized = [_normalize_zinc_id(zid) for zid in zinc_ids]
    url = f"{BASE_URL}/substances.json"
    payload = {"zinc_ids": " ".join(normalized)}
    resp = _post(url, data=payload)
    task_id = resp.get("task_id") or resp.get("task")
    if not task_id:
        raise RuntimeError(f"Bulk lookup did not return a task id: {resp}")
    print(f"[zinc_utils] Bulk lookup submitted ({len(normalized)} IDs), task_id={task_id}")
    return _poll_task(task_id)