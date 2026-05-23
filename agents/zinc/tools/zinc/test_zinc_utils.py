"""
test_zinc_utils.py - Unit tests for the ZINC helper library (CartBlanche / ZINC22).

Tests both the internal helpers (normalize, request) and public API functions
against the live CartBlanche API. Requires network access.
"""

import sys
import os
import json
import traceback
import time

# Add parent directory to path so we can import zinc_utils
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import zinc_utils


def test_normalize_zinc_id():
    """Test ZINC ID normalization."""
    print("TEST: _normalize_zinc_id")

    assert zinc_utils._normalize_zinc_id("53") == "ZINC000000000053"
    assert zinc_utils._normalize_zinc_id("ZINC53") == "ZINC000000000053"
    assert zinc_utils._normalize_zinc_id("zinc53") == "ZINC000000000053"
    assert zinc_utils._normalize_zinc_id("ZINC000000000053") == "ZINC000000000053"
    assert zinc_utils._normalize_zinc_id("  ZINC53  ") == "ZINC000000000053"
    assert zinc_utils._normalize_zinc_id("3807804") == "ZINC000003807804"

    print("  PASSED: All normalization cases correct")
    return True


def test_get_substance():
    """Test substance lookup by ZINC ID (sync, full detail)."""
    print("TEST: get_substance('ZINC000000000053')")

    sub = zinc_utils.get_substance("ZINC000000000053")
    assert sub is not None, "Aspirin (ZINC53) should exist"
    assert "smiles" in sub, "Response must have 'smiles'"
    assert "C(=O)" in sub["smiles"], f"Aspirin SMILES should contain C(=O), got: {sub['smiles']}"

    print(f"  PASSED: {sub.get('zinc_id', 'ZINC53')} -> {sub['smiles'][:60]}")
    return True


def test_get_substance_properties():
    """Test that single-substance response includes tranche_details."""
    print("TEST: get_substance returns tranche_details")

    sub = zinc_utils.get_substance("ZINC000000000053")
    assert sub is not None, "Substance not found"
    td = sub.get("tranche_details", {})
    assert td, "tranche_details should be present and non-empty"
    # Expect at least molecular weight or logP
    assert "mwt" in td or "logp" in td, f"tranche_details missing mwt/logp: {list(td.keys())}"

    print(f"  PASSED: mwt={td.get('mwt')}, logp={td.get('logp')}")
    return True


def test_get_substance_catalogs():
    """Test that single-substance response includes vendor catalogs."""
    print("TEST: get_substance returns catalogs")

    sub = zinc_utils.get_substance("ZINC000000000053")
    assert sub is not None, "Substance not found"
    cats = sub.get("catalogs", [])
    assert isinstance(cats, list), f"catalogs should be a list, got {type(cats)}"
    assert len(cats) > 0, "Aspirin should be available from at least one vendor"

    print(f"  PASSED: {len(cats)} vendor(s)")
    return True


def test_get_substance_not_found():
    """Test lookup of non-existent substance."""
    print("TEST: get_substance (non-existent)")

    sub = zinc_utils.get_substance("ZINC999999999999")
    assert sub is None, "Non-existent ZINC ID should return None"

    print("  PASSED: Returns None for non-existent ID")
    return True


def test_smiles_search_exact():
    """Test SMILES exact-match search (dist=0)."""
    print("TEST: smiles_search (exact, dist=0)")

    hits = zinc_utils.smiles_search("CC(=O)Oc1ccccc1C(=O)O", dist=0)
    assert isinstance(hits, (list, dict)), f"Should return list or dict, got {type(hits)}"
    if isinstance(hits, list):
        print(f"  PASSED: Exact search returned {len(hits)} hit(s)")
    else:
        print(f"  PASSED: Exact search returned result (type={type(hits).__name__})")
    return True


def test_bulk_lookup():
    """Test async bulk lookup of multiple ZINC IDs."""
    print("TEST: bulk_lookup with 2 IDs")

    ids = ["ZINC000000000053", "ZINC000003807804"]
    res = zinc_utils.bulk_lookup(ids)
    assert isinstance(res, (list, dict)), f"Should return list or dict, got {type(res)}"
    if isinstance(res, list):
        assert len(res) > 0, "Bulk result should not be empty"
        print(f"  PASSED: Looked up {len(res)} substances")
    else:
        print(f"  PASSED: Bulk result returned (type={type(res).__name__})")
    return True


def test_version():
    """Test that version is 2.x for CartBlanche."""
    print("TEST: version check")

    assert zinc_utils.__version__.startswith("2."), f"Expected version 2.x, got {zinc_utils.__version__}"

    print(f"  PASSED: version={zinc_utils.__version__}")
    return True


def test_base_url():
    """Test that BASE_URL points to CartBlanche, not ZINC15."""
    print("TEST: BASE_URL check")

    assert "cartblanche" in zinc_utils.BASE_URL, f"BASE_URL should be CartBlanche, got {zinc_utils.BASE_URL}"
    assert "zinc15" not in zinc_utils.BASE_URL.lower(), "BASE_URL should NOT point to zinc15"

    print(f"  PASSED: BASE_URL={zinc_utils.BASE_URL}")
    return True


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def main():
    tests = [
        test_normalize_zinc_id,
        test_version,
        test_base_url,
        test_get_substance,
        test_get_substance_properties,
        test_get_substance_catalogs,
        test_get_substance_not_found,
        test_smiles_search_exact,
        test_bulk_lookup,
    ]

    passed = 0
    failed = 0
    errors = []

    print(f"Running {len(tests)} tests against CartBlanche API...")
    print("=" * 60)

    for test_fn in tests:
        try:
            result = test_fn()
            if result:
                passed += 1
            else:
                failed += 1
                errors.append(f"{test_fn.__name__}: returned False")
        except Exception as e:
            failed += 1
            errors.append(f"{test_fn.__name__}: {e}")
            traceback.print_exc()
        # Small delay between tests to be kind to the API
        time.sleep(0.3)

    print("=" * 60)
    print(f"Results: {passed} passed, {failed} failed out of {len(tests)}")

    if errors:
        print("\nFailures:")
        for err in errors:
            print(f"  - {err}")

    # Write results to output if running in container
    output_dir = "/output"
    if os.path.isdir(output_dir):
        summary = {
            "total": len(tests),
            "passed": passed,
            "failed": failed,
            "errors": errors,
        }
        with open(f"{output_dir}/test_results.json", "w") as f:
            json.dump(summary, f, indent=2)
        print(f"\nTest results saved to {output_dir}/test_results.json")

    return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)