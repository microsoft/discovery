#!/usr/bin/env python3
"""Unit tests for aizynthfinder_utils.py -- run with ``pytest -v``.

Tests pure-Python logic (config generation, checkpointing, summarisation,
SMILES loading) *without* requiring AiZynthFinder to be installed.
All tests complete in < 30 seconds.
"""

import json
import os
import shutil
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(__file__))

import aizynthfinder_utils as utils  # noqa: E402


# ═══════════════════════════════════  FIXTURES  ══════════════════════════════
@pytest.fixture()
def temp_dir():
    """Provide a fresh temporary directory; clean up after test."""
    d = tempfile.mkdtemp(prefix="azf_test_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture()
def sample_results():
    """Four representative batch results (2 solved, 1 unsolved, 1 error)."""
    return [
        {
            "smiles": "CCO",
            "is_solved": True,
            "search_time": 5.2,
            "n_routes": 3,
            "n_solved_routes": 2,
            "stats": {"number_of_nodes": 50},
            "routes": [{"index": 0, "score": 0.95}],
            "stock_info": {},
            "trees": [{"dummy": "tree1"}],
        },
        {
            "smiles": "c1ccccc1",
            "is_solved": True,
            "search_time": 2.1,
            "n_routes": 5,
            "n_solved_routes": 4,
            "stats": {"number_of_nodes": 30},
            "routes": [{"index": 0, "score": 0.99}],
            "stock_info": {},
            "trees": [{"dummy": "tree2"}],
        },
        {
            "smiles": "CC(=O)Oc1ccccc1C(=O)O",
            "is_solved": False,
            "search_time": 120.0,
            "n_routes": 1,
            "n_solved_routes": 0,
            "stats": {},
            "routes": [],
            "stock_info": {},
            "trees": [],
        },
        {
            "smiles": "INVALID",
            "error": "Invalid SMILES",
            "is_solved": False,
            "search_time": 0,
        },
    ]


# ═══════════════════════════════  CONFIG GENERATION  ═════════════════════════
class TestCreateConfig:
    """Tests for ``create_config``."""

    def test_default_config(self, temp_dir):
        utils.WORK_DIR = temp_dir
        path = utils.create_config(
            model_dir="/fake/models",
            output_path=os.path.join(temp_dir, "config.yml"),
        )
        assert os.path.isfile(path)
        import yaml
        cfg = yaml.safe_load(open(path))
        assert "search" in cfg
        assert "expansion" in cfg
        assert "filter" in cfg
        assert "stock" in cfg
        assert cfg["search"]["iteration_limit"] == 100
        assert cfg["search"]["time_limit"] == 120
        assert cfg["search"]["max_transforms"] == 6
        assert cfg["search"]["algorithm"] == "mcts"
        assert cfg["search"]["algorithm_config"]["C"] == 1.4

    def test_custom_search_params(self, temp_dir):
        utils.WORK_DIR = temp_dir
        path = utils.create_config(
            model_dir="/fake",
            search_params={"iteration_limit": 500, "time_limit": 300, "C": 2.0},
            output_path=os.path.join(temp_dir, "cfg.yml"),
        )
        import yaml
        cfg = yaml.safe_load(open(path))
        assert cfg["search"]["iteration_limit"] == 500
        assert cfg["search"]["time_limit"] == 300
        assert cfg["search"]["algorithm_config"]["C"] == 2.0

    def test_expansion_policy_paths(self, temp_dir):
        utils.WORK_DIR = temp_dir
        path = utils.create_config(
            model_dir="/app/models",
            expansion_policies=["uspto", "ringbreaker"],
            output_path=os.path.join(temp_dir, "cfg.yml"),
        )
        import yaml
        cfg = yaml.safe_load(open(path))
        # Use os.path.join for cross-platform path comparison
        assert cfg["expansion"]["uspto"] == [
            os.path.join("/app/models", "uspto_model.onnx"),
            os.path.join("/app/models", "uspto_templates.csv.gz"),
        ]
        assert cfg["expansion"]["ringbreaker"] == [
            os.path.join("/app/models", "uspto_ringbreaker_model.onnx"),
            os.path.join("/app/models", "uspto_ringbreaker_templates.csv.gz"),
        ]

    def test_custom_stock(self, temp_dir):
        utils.WORK_DIR = temp_dir
        path = utils.create_config(
            model_dir="/fake",
            stock_files={"my_stock": "/data/custom.hdf5"},
            output_path=os.path.join(temp_dir, "cfg.yml"),
        )
        import yaml
        cfg = yaml.safe_load(open(path))
        assert cfg["stock"] == {"my_stock": "/data/custom.hdf5"}

    def test_unknown_policy_skipped(self, temp_dir):
        utils.WORK_DIR = temp_dir
        path = utils.create_config(
            model_dir="/fake",
            expansion_policies=["nonexistent"],
            output_path=os.path.join(temp_dir, "cfg.yml"),
        )
        import yaml
        cfg = yaml.safe_load(open(path))
        assert cfg["expansion"] == {}

    def test_filter_policy_paths(self, temp_dir):
        utils.WORK_DIR = temp_dir
        path = utils.create_config(
            model_dir="/app/models",
            filter_policies=["uspto"],
            output_path=os.path.join(temp_dir, "cfg.yml"),
        )
        import yaml
        cfg = yaml.safe_load(open(path))
        assert cfg["filter"]["uspto"] == os.path.join("/app/models", "uspto_filter_model.onnx")


# ══════════════════════════════  SEARCH OVERRIDES  ═══════════════════════════
class TestSearchOverrides:
    """Tests for ``_apply_search_overrides``."""

    def test_flat_overrides(self, temp_dir):
        utils.WORK_DIR = temp_dir
        import yaml
        base = {
            "search": {"iteration_limit": 100, "time_limit": 120},
            "expansion": {"u": ["/a.onnx", "/b.csv"]},
        }
        base_path = os.path.join(temp_dir, "base.yml")
        yaml.dump(base, open(base_path, "w"))

        out = utils._apply_search_overrides(
            base_path, {"iteration_limit": 500, "time_limit": 600}
        )
        cfg = yaml.safe_load(open(out))
        assert cfg["search"]["iteration_limit"] == 500
        assert cfg["search"]["time_limit"] == 600
        # untouched fields preserved
        assert cfg["expansion"]["u"] == ["/a.onnx", "/b.csv"]

    def test_nested_C_override(self, temp_dir):
        utils.WORK_DIR = temp_dir
        import yaml
        base = {"search": {"algorithm_config": {"C": 1.4}}}
        base_path = os.path.join(temp_dir, "b.yml")
        yaml.dump(base, open(base_path, "w"))

        out = utils._apply_search_overrides(base_path, {"C": 3.0})
        cfg = yaml.safe_load(open(out))
        assert cfg["search"]["algorithm_config"]["C"] == 3.0


# ══════════════════════════════  CHECKPOINTING  ══════════════════════════════
class TestCheckpoint:
    """Tests for checkpoint save / load."""

    def test_round_trip(self, temp_dir):
        ckpt = os.path.join(temp_dir, "ckpt.jsonl")
        r1 = {"smiles": "CCO", "is_solved": True, "search_time": 5.0}
        r2 = {"smiles": "c1ccccc1", "is_solved": False, "search_time": 120.0}
        utils._save_checkpoint(ckpt, r1)
        utils._save_checkpoint(ckpt, r2)
        results, smiles = utils._load_checkpoint(ckpt)
        assert len(results) == 2
        assert "CCO" in smiles
        assert "c1ccccc1" in smiles

    def test_nonexistent(self, temp_dir):
        results, smiles = utils._load_checkpoint(os.path.join(temp_dir, "nope.jsonl"))
        assert results == []
        assert smiles == set()

    def test_corrupted_file(self, temp_dir):
        ckpt = os.path.join(temp_dir, "bad.jsonl")
        with open(ckpt, "w") as f:
            f.write("NOT JSON\n")
        results, smiles = utils._load_checkpoint(ckpt)
        assert results == []
        assert smiles == set()

    def test_trees_excluded(self, temp_dir):
        ckpt = os.path.join(temp_dir, "ckpt.jsonl")
        utils._save_checkpoint(ckpt, {
            "smiles": "CCO",
            "trees": [{"big": list(range(1000))}],
        })
        with open(ckpt) as f:
            saved = json.loads(f.readline())
        assert "trees" not in saved


# ═══════════════════════════  BATCH SUMMARISATION  ═══════════════════════════
class TestSummarize:
    """Tests for ``summarize_batch_results``."""

    def test_standard_batch(self, sample_results):
        s = utils.summarize_batch_results(sample_results)
        assert s["total_molecules"] == 4
        assert s["solved"] == 2
        assert s["errors"] == 1
        assert s["unsolved"] == 1
        assert s["solve_rate"] == 0.5
        assert s["max_search_time"] == 120.0
        assert s["avg_search_time"] > 0

    def test_empty(self):
        s = utils.summarize_batch_results([])
        assert s["total_molecules"] == 0
        assert s["solve_rate"] == 0

    def test_all_solved(self):
        r = [
            {"smiles": "CCO", "is_solved": True, "search_time": 3.0, "n_routes": 5},
            {"smiles": "CCC", "is_solved": True, "search_time": 4.0, "n_routes": 3},
        ]
        s = utils.summarize_batch_results(r)
        assert s["solve_rate"] == 1.0
        assert s["errors"] == 0
        assert s["avg_routes"] == 4.0

    def test_all_errors(self):
        r = [
            {"smiles": "X", "error": "bad", "is_solved": False, "search_time": 0},
            {"smiles": "Y", "error": "bad", "is_solved": False, "search_time": 0},
        ]
        s = utils.summarize_batch_results(r)
        assert s["errors"] == 2
        assert s["solved"] == 0
        assert s["avg_search_time"] == 0


# ═══════════════════════════  FINAL-RESULTS I/O  ════════════════════════════
class TestFinalResults:
    """Tests for ``save_final_results``."""

    def test_writes_correctly(self, temp_dir):
        utils.OUTPUT_DIR = temp_dir
        utils.save_final_results(
            results={"solved": 5, "total": 10},
            output_files={"plot": "/output/plot.png"},
            file_descriptions={"plot": "Summary plot"},
        )
        path = os.path.join(temp_dir, "final_results.json")
        assert os.path.isfile(path)
        data = json.load(open(path))
        assert data["status"] == "completed"
        assert data["summary"]["solved"] == 5
        assert data["output_files"]["plot"] == "/output/plot.png"

    def test_custom_status(self, temp_dir):
        utils.OUTPUT_DIR = temp_dir
        utils.save_final_results(results={}, status="failed")
        data = json.load(open(os.path.join(temp_dir, "final_results.json")))
        assert data["status"] == "failed"


# ═══════════════════════════  SMILES HELPERS  ════════════════════════════════
class TestSmiles:
    """Tests for SMILES loading."""

    def test_load_smiles_from_file(self, temp_dir):
        fp = os.path.join(temp_dir, "smiles.txt")
        with open(fp, "w") as f:
            f.write("CCO\n# comment\nc1ccccc1\n\nCC(=O)O\n")
        result = utils.load_smiles_from_file(fp)
        assert result == ["CCO", "c1ccccc1", "CC(=O)O"]

    def test_load_empty_file(self, temp_dir):
        fp = os.path.join(temp_dir, "empty.txt")
        with open(fp, "w") as f:
            f.write("")
        assert utils.load_smiles_from_file(fp) == []


# ═════════════════════════  INCREMENTAL RESULTS  ═════════════════════════════
class TestIncrementalResults:
    """Tests for ``_save_incremental_results``."""

    def test_excludes_trees(self, temp_dir):
        utils.OUTPUT_DIR = temp_dir
        results = [
            {"smiles": "CCO", "is_solved": True, "trees": [{"big": "data"}]},
        ]
        utils._save_incremental_results(results)
        path = os.path.join(temp_dir, "results_partial.json")
        data = json.load(open(path))
        assert len(data) == 1
        assert "trees" not in data[0]


# ═════════════════════════  ERROR RESULT HELPER  ═════════════════════════════
class TestErrorResult:
    """Tests for ``_error_result``."""

    def test_structure(self):
        r = utils._error_result("BAD", "something broke")
        assert r["smiles"] == "BAD"
        assert r["error"] == "something broke"
        assert r["is_solved"] is False
        assert r["search_time"] == 0
        assert r["n_routes"] == 0
        assert r["trees"] == []


# ═══════════════════════════  SERIALISATION  ═════════════════════════════════
class TestSerialisable:
    """Tests for ``_serialisable``."""

    def test_nan_handling(self):
        assert utils._serialisable(float("nan")) is None

    def test_nested_dict(self):
        d = {"a": 1, "b": [2, 3], "c": {"d": 4.123456789}}
        s = utils._serialisable(d)
        assert s["a"] == 1
        assert s["b"] == [2, 3]
        assert s["c"]["d"] == round(4.123456789, 6)

    def test_non_serialisable_fallback(self):
        class Obj:
            def __str__(self):
                return "custom_obj"
        assert utils._serialisable(Obj()) == "custom_obj"


# ═════════════════════════  DEFAULT CONSTANTS  ═══════════════════════════════
class TestConstants:
    """Verify defaults are sensible."""

    def test_search_params(self):
        assert utils.DEFAULT_SEARCH_PARAMS["iteration_limit"] == 100
        assert utils.DEFAULT_SEARCH_PARAMS["time_limit"] == 120
        assert utils.DEFAULT_SEARCH_PARAMS["max_transforms"] == 6
        assert utils.DEFAULT_SEARCH_PARAMS["C"] == 1.4

    def test_available_policies(self):
        assert "uspto" in utils.AVAILABLE_EXPANSION_POLICIES
        assert "ringbreaker" in utils.AVAILABLE_EXPANSION_POLICIES
        assert "uspto" in utils.AVAILABLE_FILTER_POLICIES
        assert "zinc" in utils.AVAILABLE_STOCKS


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
