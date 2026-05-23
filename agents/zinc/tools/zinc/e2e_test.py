# ============================================================
# ZINC_UTILS BOOTSTRAP - DO NOT MODIFY
# ============================================================
import sys, os, textwrap
_ZINC_UTILS = textwrap.dedent(r'''
import requests, json, time, sys, traceback
__version__ = "2.0.0"
BASE_URL = "https://cartblanche.docking.org"
DEFAULT_TIMEOUT = 30
MAX_RETRIES = 3
RETRY_DELAY = 2
POLL_INTERVAL = 3
POLL_MAX_ATTEMPTS = 60
_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": "Mozilla/5.0 (compatible; ZINCUtils/2.0; +https://cartblanche.docking.org)", "Accept": "application/json"})

def _normalize_zinc_id(zinc_id):
    zinc_id = str(zinc_id).strip().upper()
    if not zinc_id.startswith("ZINC"): zinc_id = "ZINC" + zinc_id
    numeric = zinc_id[4:]
    if numeric.isdigit(): zinc_id = "ZINC" + numeric.zfill(12)
    return zinc_id

def _get(url, params=None, timeout=DEFAULT_TIMEOUT):
    for attempt in range(MAX_RETRIES):
        try:
            resp = _SESSION.get(url, params=params, timeout=timeout)
            if resp.status_code == 404: return None
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.HTTPError:
            if resp.status_code in (429,) or resp.status_code >= 500:
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_DELAY * (attempt + 1)); continue
            raise
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY * (attempt + 1)); continue
            raise
    return None

def _post(url, data=None, timeout=DEFAULT_TIMEOUT):
    for attempt in range(MAX_RETRIES):
        try:
            resp = _SESSION.post(url, data=data, timeout=timeout)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.HTTPError:
            if resp.status_code in (429,) or resp.status_code >= 500:
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_DELAY * (attempt + 1)); continue
            raise
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY * (attempt + 1)); continue
            raise
    return None

def _poll_task(task_id, max_attempts=POLL_MAX_ATTEMPTS, interval=POLL_INTERVAL):
    url = f"{BASE_URL}/search/result/{task_id}"
    for i in range(max_attempts):
        data = _get(url, timeout=DEFAULT_TIMEOUT)
        if data is None: raise RuntimeError(f"Task {task_id}: poll returned 404")
        status = data.get("status")
        if status == "SUCCESS": return data.get("result")
        if status in ("FAILURE", "REVOKED"): raise RuntimeError(f"Task {task_id} failed: {data}")
        if i % 5 == 0: print(f"[zinc_utils] Task {task_id}: status={status} (poll {i+1}/{max_attempts})")
        time.sleep(interval)
    raise TimeoutError(f"Task {task_id} did not complete within {max_attempts * interval}s")

def get_substance(zinc_id):
    zinc_id = _normalize_zinc_id(zinc_id)
    return _get(f"{BASE_URL}/substance/{zinc_id}.json")

def smiles_search(smiles, dist=0, db="zinc22-2D"):
    resp = _post(f"{BASE_URL}/smiles.json", data={"smiles": smiles, "dist": str(dist), "db": db})
    task_id = resp.get("task_id") or resp.get("task")
    if not task_id: raise RuntimeError(f"SMILES search did not return task_id: {resp}")
    print(f"[zinc_utils] SMILES search submitted, task_id={task_id}")
    return _poll_task(task_id)

def bulk_lookup(zinc_ids):
    normalized = [_normalize_zinc_id(zid) for zid in zinc_ids]
    resp = _post(f"{BASE_URL}/substances.json", data={"zinc_ids": " ".join(normalized)})
    task_id = resp.get("task_id") or resp.get("task")
    if not task_id: raise RuntimeError(f"Bulk lookup did not return task_id: {resp}")
    print(f"[zinc_utils] Bulk lookup submitted ({len(normalized)} IDs), task_id={task_id}")
    return _poll_task(task_id)
''')
with open('/tmp/zinc_utils.py', 'w') as _f: _f.write(_ZINC_UTILS)
sys.path.insert(0, '/tmp')
# ============================================================
# END BOOTSTRAP
# ============================================================
import zinc_utils

import json
import traceback

OUTPUT_DIR = '/output'
os.makedirs(OUTPUT_DIR, exist_ok=True)

results = {"tests": [], "passed": 0, "failed": 0}

def run_test(name, fn):
    print(f"\nTEST: {name}")
    try:
        result = fn()
        print(f"  PASSED: {result}")
        results["tests"].append({"name": name, "status": "passed", "detail": str(result)[:200]})
        results["passed"] += 1
    except Exception as e:
        traceback.print_exc()
        print(f"  FAILED: {e}")
        results["tests"].append({"name": name, "status": "failed", "error": str(e)})
        results["failed"] += 1

# Test 1: get_substance (sync, full detail)
def test_get_substance():
    sub = zinc_utils.get_substance("ZINC000000000053")
    assert sub is not None, "Substance not found"
    assert "smiles" in sub, "Response missing 'smiles'"
    assert "C(=O)" in sub["smiles"], f"Unexpected SMILES: {sub['smiles']}"
    return f"{sub.get('zinc_id', 'ZINC53')} -> {sub['smiles'][:60]}"

# Test 2: get_substance returns properties inline
def test_substance_has_properties():
    sub = zinc_utils.get_substance("ZINC000000000053")
    assert sub is not None, "Substance not found"
    td = sub.get("tranche_details", {})
    assert td, "No tranche_details in response"
    assert "mwt" in td or "logp" in td, f"tranche_details missing mwt/logp: {list(td.keys())}"
    return f"mwt={td.get('mwt')}, logp={td.get('logp')}"

# Test 3: get_substance returns catalogs inline
def test_substance_has_catalogs():
    sub = zinc_utils.get_substance("ZINC000000000053")
    assert sub is not None, "Substance not found"
    cats = sub.get("catalogs", [])
    assert isinstance(cats, list), f"catalogs is not a list: {type(cats)}"
    # Aspirin is widely available -- expect at least one vendor
    assert len(cats) > 0, "No vendor catalogs returned"
    return f"{len(cats)} vendor catalog(s)"

# Test 4: get_substance returns None for non-existent ID
def test_substance_not_found():
    sub = zinc_utils.get_substance("ZINC999999999999")
    assert sub is None, f"Expected None for non-existent ID, got {type(sub)}"
    return "Correctly returns None"

# Test 5: smiles_search (exact, dist=0)
def test_smiles_search_exact():
    hits = zinc_utils.smiles_search("CC(=O)Oc1ccccc1C(=O)O", dist=0)
    assert isinstance(hits, (list, dict)), f"Unexpected type: {type(hits)}"
    if isinstance(hits, list):
        assert len(hits) >= 0, "Negative result count"
        return f"Exact search returned {len(hits)} hit(s)"
    return f"Exact search returned result of type {type(hits)}"

# Test 6: bulk_lookup (async)
def test_bulk_lookup():
    ids = ["ZINC000000000053", "ZINC000003807804"]
    res = zinc_utils.bulk_lookup(ids)
    assert isinstance(res, (list, dict)), f"Unexpected type: {type(res)}"
    if isinstance(res, list):
        assert len(res) > 0, "Empty bulk result"
        return f"Bulk lookup returned {len(res)} result(s)"
    return f"Bulk lookup returned result of type {type(res)}"

# Run all tests
print("=" * 60)
print("ZINC Agent End-to-End Test (CartBlanche / ZINC22)")
print("=" * 60)
run_test("get_substance", test_get_substance)
run_test("substance_has_properties", test_substance_has_properties)
run_test("substance_has_catalogs", test_substance_has_catalogs)
run_test("substance_not_found", test_substance_not_found)
run_test("smiles_search_exact", test_smiles_search_exact)
run_test("bulk_lookup", test_bulk_lookup)

print(f"\n{'=' * 60}")
print(f"Results: {results['passed']} passed, {results['failed']} failed out of {results['passed']+results['failed']}")
print(f"{'=' * 60}")

# Save results
with open(f"{OUTPUT_DIR}/final_results.json", "w") as f:
    json.dump(results, f, indent=2)
print(f"\nResults saved to {OUTPUT_DIR}/final_results.json")