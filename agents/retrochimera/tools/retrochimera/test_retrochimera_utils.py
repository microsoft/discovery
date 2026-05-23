#!/usr/bin/env python3
"""Unit tests for retrochimera_utils.py -- run with pytest.

These tests exercise the utility functions that do NOT require the actual
RetroChimera model or its heavy dependencies (PyTorch, PyG, syntheseus).
Model-dependent tests are marked with @pytest.mark.model and skipped unless
the model is available.
"""

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(__file__))
import retrochimera_utils as utils
from retrochimera_utils import (
    _canonical_smiles,
    format_reactions_table,
    quick_setup,
    save_final_results,
    cleanup,
)


# ============= FIXTURES =============
@pytest.fixture
def tmp_dirs(tmp_path):
    """Create temporary input/output/work directories."""
    input_dir = str(tmp_path / "input")
    output_dir = str(tmp_path / "output")
    work_dir = str(tmp_path / "work")
    os.makedirs(input_dir)
    os.makedirs(output_dir)
    os.makedirs(work_dir)
    return input_dir, output_dir, work_dir


@pytest.fixture
def sample_result():
    """A sample single-step prediction result dict."""
    return {
        "target_smiles": "CN1C=NC2=C1C(=O)N(C(=O)N2C)C",
        "num_results": 3,
        "reactions": [
            {
                "rank": 1,
                "reactants": ["CN1C=NC2=C1C(=O)NC(=O)N2C", "CI"],
                "reactant_smiles_joined": "CN1C=NC2=C1C(=O)NC(=O)N2C.CI",
                "score": 1.234,
                "probability": 0.65,
                "individual_ranks": {"model_a": 0, "model_b": 1},
            },
            {
                "rank": 2,
                "reactants": ["CN1C(=O)N(C)C2=C1N=CN2", "CO"],
                "reactant_smiles_joined": "CN1C(=O)N(C)C2=C1N=CN2.CO",
                "score": 0.987,
                "probability": 0.25,
            },
            {
                "rank": 3,
                "reactants": ["O=C1NC(=O)C2=C(N1)N=CN2", "CI", "CI", "CI"],
                "reactant_smiles_joined": "O=C1NC(=O)C2=C(N1)N=CN2.CI.CI.CI",
                "score": 0.543,
                "probability": 0.10,
            },
        ],
        "elapsed_seconds": 1.23,
    }


# ============= SETUP TESTS =============
class TestSetup:
    def test_quick_setup_creates_dirs(self, tmp_dirs):
        input_dir, output_dir, work_dir = tmp_dirs
        # Write a test file in input_dir
        with open(os.path.join(input_dir, "test.smi"), "w") as f:
            f.write("CCO ethanol\n")

        quick_setup(input_dir=input_dir, output_dir=output_dir, work_dir=work_dir)

        assert os.path.isdir(work_dir)
        assert os.path.isdir(output_dir)
        # Input file should be copied to work dir
        assert os.path.exists(os.path.join(work_dir, "test.smi"))

    def test_quick_setup_same_dir_guard(self, tmp_dirs):
        """When input_dir == work_dir, should not crash."""
        _, output_dir, work_dir = tmp_dirs
        quick_setup(input_dir=work_dir, output_dir=output_dir, work_dir=work_dir)
        assert os.path.isdir(work_dir)


class TestSaveFinalResults:
    def test_saves_json(self, tmp_dirs):
        _, output_dir, work_dir = tmp_dirs
        quick_setup(input_dir=tmp_dirs[0], output_dir=output_dir, work_dir=work_dir)

        results = {"key_metric": 42, "reactions_found": 3}
        save_final_results(
            results,
            output_files={"plot": "/output/plot.png"},
            file_descriptions={"plot": "Probability bar chart"},
        )

        path = os.path.join(output_dir, "final_results.json")
        assert os.path.exists(path)
        with open(path) as f:
            data = json.load(f)
        assert data["status"] == "completed"
        assert data["summary"]["key_metric"] == 42
        assert "plot" in data["output_files"]

    def test_saves_with_error_status(self, tmp_dirs):
        _, output_dir, work_dir = tmp_dirs
        quick_setup(input_dir=tmp_dirs[0], output_dir=output_dir, work_dir=work_dir)

        save_final_results({"error": "something broke"}, status="failed")

        path = os.path.join(output_dir, "final_results.json")
        with open(path) as f:
            data = json.load(f)
        assert data["status"] == "failed"


# ============= FORMATTING TESTS =============
class TestFormatReactionsTable:
    def test_basic_format(self, sample_result):
        table = format_reactions_table(sample_result)
        assert "Target:" in table
        assert "Rank" in table
        assert "65.0%" in table
        assert "CN1C=NC2=C1C(=O)NC(=O)N2C.CI" in table

    def test_empty_reactions(self):
        result = {
            "target_smiles": "C",
            "num_results": 0,
            "reactions": [],
        }
        table = format_reactions_table(result)
        assert "Target: C" in table
        assert "Predictions: 0" in table

    def test_all_ranks_present(self, sample_result):
        table = format_reactions_table(sample_result)
        assert "1    " in table
        assert "2    " in table
        assert "3    " in table


# ============= CLEANUP TESTS =============
class TestCleanup:
    def test_cleanup_no_crash(self):
        """Cleanup should not crash even if scratch dir doesn't exist."""
        cleanup(deep=False)
        cleanup(deep=True)


# ============= SMILES VALIDATION TESTS =============
class TestValidation:
    """Tests for SMILES validation (uses only basic string checks,
    no RDKit/syntheseus required)."""

    def test_validate_smiles_stub(self):
        """validate_smiles requires rdkit or syntheseus, so we test
        graceful behavior when neither is available."""
        # The function should be importable
        from retrochimera_utils import validate_smiles
        # If rdkit is available, test it; otherwise just ensure no crash
        result = validate_smiles("CCO")
        # Can be True (rdkit available) or False (rdkit not available)
        assert isinstance(result, bool)

    def test_validate_smiles_list_stub(self):
        from retrochimera_utils import validate_smiles_list
        valid, invalid = validate_smiles_list(["CCO", "invalid_not_smiles!!!"])
        assert isinstance(valid, list)
        assert isinstance(invalid, list)


class TestSearchRoutes:
    def test_search_routes_uses_upstream_syntheseus_cli_args(self, tmp_path, monkeypatch):
        """Verify _search_routes_single builds the right args and passes them to _run_search_subprocess."""
        scratch_dir = tmp_path / "scratch"
        scratch_dir.mkdir()
        inventory = tmp_path / "inventory.smi"
        inventory.write_text("C\nCCO\n")
        captured = {}

        def fake_subprocess(args, target_smiles, time_limit_s, scratch_dir):
            captured["args"] = args
            captured["target_smiles"] = target_smiles
            captured["time_limit_s"] = time_limit_s
            # Create a fake output dir with stats.json so the caller can parse it
            out_dir = Path(scratch_dir) / "RetroChimera"
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "stats.json").write_text(json.dumps({"smiles": "CCO"}))
            return out_dir

        monkeypatch.setattr(utils, "_run_search_subprocess", fake_subprocess)
        monkeypatch.setattr(utils, "SCRATCH_DIR", str(scratch_dir))

        result = utils._search_routes_single(
            "CCO",
            num_routes=2,
            time_limit_s=3,
            inventory_smiles_file=str(inventory),
            num_top_results=7,
            device="cpu",
            max_expansion_depth=4,
        )

        args = captured["args"]
        assert "model_class=RetroChimera" in args
        assert "search_target=CCO" in args
        assert f"inventory_smiles_file={inventory}" in args
        assert "time_limit_s=3" in args
        assert "num_top_results=7" in args
        assert "append_timestamp_to_dir=False" in args
        assert "save_graph=True" in args
        assert "num_routes_to_plot=0" in args
        assert "use_gpu=False" in args
        assert "retro_star_config.max_expansion_depth=4" in args
        assert not any(arg.startswith("search_targets=") for arg in args)
        assert not any(arg.startswith("output_dir=") for arg in args)
        assert captured["target_smiles"] == "CCO"
        assert captured["time_limit_s"] == 3
        assert result["stats"] == {"smiles": "CCO"}
        assert "error" not in result

    def test_search_routes_reports_missing_inventory(self, tmp_path, monkeypatch):
        scratch_dir = tmp_path / "scratch"
        scratch_dir.mkdir()
        monkeypatch.setattr(utils, "SCRATCH_DIR", str(scratch_dir))

        result = utils._search_routes_single("CCO", inventory_smiles_file=str(tmp_path / "missing.smi"))

        assert result["num_routes_found"] == 0
        assert "Inventory file not found" in result["error"]


class TestPublicAPI:
    """Verify the public API names exist and are callable."""

    def test_predict_precursors_is_exported(self):
        assert hasattr(utils, "predict_precursors")
        assert callable(utils.predict_precursors)

    def test_find_routes_is_exported(self):
        assert hasattr(utils, "find_routes")
        assert callable(utils.find_routes)

    def test_old_names_are_internal(self):
        """Old public names should now be private."""
        assert not hasattr(utils, "predict_single_step")
        assert not hasattr(utils, "batch_predict_single_step")
        assert not hasattr(utils, "search_routes") or utils.search_routes.__name__.startswith("_")
        # Internal versions should exist
        assert hasattr(utils, "_search_routes_single")

    def test_find_routes_checkpoint(self, tmp_path, monkeypatch):
        """find_routes writes a checkpoint file after each molecule."""
        monkeypatch.setattr(utils, "OUTPUT_DIR", str(tmp_path))
        checkpoint = tmp_path / "cp.json"

        # Mock _search_routes_single to return a fake result (canonical target_smiles)
        def fake_search(smiles, **kw):
            return {
                "target_smiles": _canonical_smiles(smiles),
                "num_routes_found": 1,
                "routes": [{"route_id": "route_01"}],
                "elapsed_seconds": 0.1,
                "search_params": {},
            }

        monkeypatch.setattr(utils, "_search_routes_single", fake_search)

        successes, failures = utils.find_routes(
            ["CCO", "c1ccccc1"],
            checkpoint_path=str(checkpoint),
        )

        assert len(successes) == 2
        assert len(failures) == 0
        assert checkpoint.exists()
        data = json.loads(checkpoint.read_text())
        assert len(data["results"]) == 2

    def test_find_routes_checkpoint_resume_canonical(self, tmp_path, monkeypatch):
        """Checkpoint resume recognises non-canonical SMILES variants of the same molecule."""
        monkeypatch.setattr(utils, "OUTPUT_DIR", str(tmp_path))
        checkpoint = tmp_path / "cp.json"
        call_count = 0

        def fake_search(smiles, **kw):
            nonlocal call_count
            call_count += 1
            return {
                "target_smiles": _canonical_smiles(smiles),
                "num_routes_found": 1,
                "routes": [{"route_id": "route_01"}],
                "elapsed_seconds": 0.1,
                "search_params": {},
            }

        monkeypatch.setattr(utils, "_search_routes_single", fake_search)

        # First run with canonical ethanol
        utils.find_routes(["CCO"], checkpoint_path=str(checkpoint))
        assert call_count == 1

        # Second run with a non-canonical ethanol variant -- should be skipped
        # if rdkit is available; re-run if not (both are acceptable)
        call_count = 0
        successes, failures = utils.find_routes(
            ["OCC"], checkpoint_path=str(checkpoint)
        )
        assert len(successes) == 1
        assert len(failures) == 0
        # With rdkit: OCC canonicalises to CCO → checkpoint hit → 0 calls
        # Without rdkit: OCC != CCO → cache miss → 1 call
        try:
            from rdkit import Chem
            assert call_count == 0, "Expected checkpoint hit for canonical match"
        except ImportError:
            assert call_count == 1, "Without rdkit, non-canonical input should re-run"


# ============= VISUALIZATION TESTS =============
HAS_RDKIT = False
try:
    from rdkit import Chem
    HAS_RDKIT = True
except ImportError:
    pass

HAS_GRAPHVIZ = False
try:
    import graphviz
    HAS_GRAPHVIZ = True
except ImportError:
    pass


@pytest.fixture
def sample_route():
    """A sample multi-step route result dict with a reaction_tree."""
    return {
        "route_id": "route_01",
        "n_steps": 2,
        "solved": True,
        "reaction_tree": {
            "type": "reaction",
            "smiles": "CC(=O)OC1=CC=CC=C1C(=O)O",
            "metadata": {},
            "children": [
                {
                    "type": "reaction",
                    "smiles": "OC1=CC=CC=C1C(=O)O",
                    "metadata": {},
                    "children": [
                        {"type": "mol", "smiles": "OC1=CC=CC=C1", "in_stock": True, "solved": True},
                        {"type": "mol", "smiles": "O=C(O)Cl", "in_stock": True, "solved": True},
                    ],
                },
                {"type": "mol", "smiles": "CC(=O)Cl", "in_stock": True, "solved": True},
            ],
        },
    }


class TestRenderReactionDiagram:
    @pytest.mark.skipif(not HAS_RDKIT, reason="rdkit not available")
    def test_renders_pngs_for_each_reaction(self, tmp_path, sample_result, monkeypatch):
        monkeypatch.setattr(utils, "OUTPUT_DIR", str(tmp_path))
        paths = utils.render_reaction_diagram(sample_result, output_dir=str(tmp_path))
        assert len(paths) == 3
        for p in paths:
            assert os.path.exists(p)
            assert os.path.getsize(p) > 100  # non-trivial PNG

    @pytest.mark.skipif(not HAS_RDKIT, reason="rdkit not available")
    def test_filenames_match_rank(self, tmp_path, sample_result, monkeypatch):
        monkeypatch.setattr(utils, "OUTPUT_DIR", str(tmp_path))
        paths = utils.render_reaction_diagram(sample_result, output_dir=str(tmp_path))
        basenames = [os.path.basename(p) for p in paths]
        assert "reaction_rank01.png" in basenames
        assert "reaction_rank02.png" in basenames
        assert "reaction_rank03.png" in basenames

    def test_no_crash_without_reactions(self, tmp_path, monkeypatch):
        monkeypatch.setattr(utils, "OUTPUT_DIR", str(tmp_path))
        result = {"target_smiles": "CCO", "reactions": []}
        # Should not crash even if rdkit is missing -- returns empty list
        try:
            paths = utils.render_reaction_diagram(result, output_dir=str(tmp_path))
            assert paths == []
        except ImportError:
            pass  # rdkit not available, acceptable


class TestRenderRouteTree:
    @pytest.mark.skipif(not (HAS_RDKIT and HAS_GRAPHVIZ),
                        reason="rdkit and graphviz required")
    def test_renders_svg(self, tmp_path, sample_route, monkeypatch):
        monkeypatch.setattr(utils, "OUTPUT_DIR", str(tmp_path))
        out = str(tmp_path / "test_route.svg")
        result = utils.render_route_tree(sample_route, output_file=out, fmt="svg")
        assert result is not None
        assert os.path.exists(out)
        content = open(out).read()
        assert "<svg" in content

    @pytest.mark.skipif(not HAS_GRAPHVIZ, reason="graphviz required")
    def test_returns_none_without_tree(self, tmp_path, monkeypatch):
        monkeypatch.setattr(utils, "OUTPUT_DIR", str(tmp_path))
        route = {"route_id": "route_01", "nodes": []}
        result = utils.render_route_tree(route)
        assert result is None


class TestGenerateHtmlReport:
    def test_single_step_report_contains_images(self, tmp_path, sample_result, monkeypatch):
        monkeypatch.setattr(utils, "OUTPUT_DIR", str(tmp_path))
        monkeypatch.setattr(utils, "INPUT_DIR", str(tmp_path))
        out = str(tmp_path / "report.html")
        utils.generate_html_report([sample_result], output_file=out)
        assert os.path.exists(out)
        content = open(out).read()
        assert "<!DOCTYPE html>" in content
        assert "Retrosynthesis Predictions" in content
        if HAS_RDKIT:
            assert "data:image/png;base64," in content

    def test_route_report_contains_trees(self, tmp_path, sample_route, monkeypatch):
        monkeypatch.setattr(utils, "OUTPUT_DIR", str(tmp_path))
        monkeypatch.setattr(utils, "INPUT_DIR", str(tmp_path))
        route_result = {
            "target_smiles": "CC(=O)OC1=CC=CC=C1C(=O)O",
            "num_routes_found": 1,
            "routes": [sample_route],
            "elapsed_seconds": 5.0,
        }
        out = str(tmp_path / "report.html")
        utils.generate_html_report([route_result], output_file=out)
        assert os.path.exists(out)
        content = open(out).read()
        assert "Synthesis Routes" in content
        assert "route_01" in content
        if HAS_GRAPHVIZ:
            assert "<svg" in content

    def test_empty_results(self, tmp_path, monkeypatch):
        monkeypatch.setattr(utils, "OUTPUT_DIR", str(tmp_path))
        monkeypatch.setattr(utils, "INPUT_DIR", str(tmp_path))
        out = str(tmp_path / "report.html")
        utils.generate_html_report([], output_file=out)
        assert os.path.exists(out)
        content = open(out).read()
        assert "<!DOCTYPE html>" in content


class TestMolToBase64:
    @pytest.mark.skipif(not HAS_RDKIT, reason="rdkit not available")
    def test_valid_smiles_returns_string(self):
        result = utils._mol_to_base64_png("CCO")
        assert result is not None
        assert len(result) > 100  # non-trivial base64

    def test_invalid_smiles_returns_none(self):
        result = utils._mol_to_base64_png("not_a_smiles!!!")
        assert result is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
