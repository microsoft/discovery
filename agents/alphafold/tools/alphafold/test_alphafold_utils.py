#!/usr/bin/env python3
"""Unit tests for alphafold_utils.py — run with pytest.

Tests cover FASTA I/O, sequence validation, PDB parsing, confidence metrics,
score file parsing, model ranking, and visualization. All tests run WITHOUT
ColabFold installed (no subprocess calls).
"""

import pytest
import os
import sys
import json
import tempfile
import shutil

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from alphafold_utils import (
    write_fasta,
    write_multimer_fasta,
    read_fasta,
    validate_sequence,
    validate_fasta,
    extract_plddt_from_pdb,
    extract_pae_matrix,
    compute_confidence_metrics,
    classify_confidence,
    parse_colabfold_output,
    rank_models,
    summarize_prediction,
    plot_plddt,
    plot_pae,
    plot_model_comparison,
    save_final_results,
)


@pytest.fixture
def tmp_dir():
    """Create temporary directory for test files."""
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d)


# ============= FASTA TESTS =============

class TestFastaUtils:
    def test_write_read_fasta(self, tmp_dir):
        seqs = {
            "protein1": "MKFLILLFNILCLFPVLAADNH",
            "protein2": "ACDEFGHIKLMNPQRSTVWY"
        }
        path = os.path.join(tmp_dir, "test.fasta")
        write_fasta(seqs, path)

        result = read_fasta(path)
        assert len(result) == 2
        assert result["protein1"] == "MKFLILLFNILCLFPVLAADNH"
        assert result["protein2"] == "ACDEFGHIKLMNPQRSTVWY"

    def test_write_fasta_cleans_whitespace(self, tmp_dir):
        seqs = {"prot": "MKF LIL\nLFN"}
        path = os.path.join(tmp_dir, "test.fasta")
        write_fasta(seqs, path)
        result = read_fasta(path)
        assert result["prot"] == "MKFLILLFN"

    def test_write_multimer_fasta(self, tmp_dir):
        chains = {"chainA": "MKFLILLFNILCLFPV", "chainB": "ACDEFGHIKLMNPQRS"}
        path = os.path.join(tmp_dir, "multimer.fasta")
        write_multimer_fasta(chains, path, "test_complex")

        with open(path) as f:
            content = f.read()
        assert "test_complex" in content
        assert ":" in content  # Chain separator
        assert "MKFLILLFNILCLFPV:ACDEFGHIKLMNPQRS" in content

    def test_read_fasta_missing_file(self):
        with pytest.raises(FileNotFoundError):
            read_fasta("/nonexistent/file.fasta")

    def test_read_empty_fasta(self, tmp_dir):
        path = os.path.join(tmp_dir, "empty.fasta")
        with open(path, 'w') as f:
            f.write("")
        result = read_fasta(path)
        assert len(result) == 0

    def test_read_fasta_multiline_sequence(self, tmp_dir):
        path = os.path.join(tmp_dir, "multi.fasta")
        with open(path, 'w') as f:
            f.write(">prot\nACDEFGHI\nKLMNPQRS\nTVWY\n")
        result = read_fasta(path)
        assert result["prot"] == "ACDEFGHIKLMNPQRSTVWY"


# ============= SEQUENCE VALIDATION TESTS =============

class TestSequenceValidation:
    def test_valid_sequence(self):
        valid, msg = validate_sequence("MKFLILLFNILCLFPVLAADNH")
        assert valid
        assert "22 residues" in msg

    def test_empty_sequence(self):
        valid, msg = validate_sequence("")
        assert not valid
        assert "Empty" in msg

    def test_whitespace_only(self):
        valid, msg = validate_sequence("   \n  ")
        assert not valid
        assert "Empty" in msg

    def test_short_sequence(self):
        valid, msg = validate_sequence("MKFLI")
        assert not valid
        assert "too short" in msg

    def test_long_sequence(self):
        valid, msg = validate_sequence("A" * 5000)
        assert not valid
        assert "too long" in msg

    def test_invalid_characters(self):
        valid, msg = validate_sequence("MKFLILLFNI12345LCLFPV")
        assert not valid
        assert "Invalid" in msg

    def test_extended_amino_acids(self):
        # X (unknown), U (selenocysteine) should be valid
        valid, msg = validate_sequence("MKFLILLFNXUCLFPVLAADNH")
        assert valid

    def test_validate_fasta(self, tmp_dir):
        path = os.path.join(tmp_dir, "test.fasta")
        with open(path, 'w') as f:
            f.write(">good\nMKFLILLFNILCLFPVLAADNH\n")
            f.write(">bad\nABC\n")  # too short
        result = validate_fasta(path)
        assert not result["valid"]
        assert result["sequences"]["good"]["valid"]
        assert not result["sequences"]["bad"]["valid"]


# ============= pLDDT EXTRACTION TESTS =============

class TestPLDDTExtraction:
    def test_extract_plddt_from_pdb(self, tmp_dir):
        pdb_content = (
            "ATOM      1  N   ALA A   1       1.000   2.000   3.000  1.00 85.50           N\n"
            "ATOM      2  CA  ALA A   1       2.000   3.000   4.000  1.00 85.50           C\n"
            "ATOM      3  C   ALA A   1       3.000   4.000   5.000  1.00 85.50           C\n"
            "ATOM      4  N   GLY A   2       4.000   5.000   6.000  1.00 92.30           N\n"
            "ATOM      5  CA  GLY A   2       5.000   6.000   7.000  1.00 92.30           C\n"
            "ATOM      6  C   GLY A   2       6.000   7.000   8.000  1.00 92.30           C\n"
            "ATOM      7  N   VAL A   3       7.000   8.000   9.000  1.00 45.10           N\n"
            "ATOM      8  CA  VAL A   3       8.000   9.000  10.000  1.00 45.10           C\n"
            "END\n"
        )
        pdb_path = os.path.join(tmp_dir, "test.pdb")
        with open(pdb_path, 'w') as f:
            f.write(pdb_content)

        scores = extract_plddt_from_pdb(pdb_path)
        assert len(scores) == 3
        assert abs(scores[0] - 85.50) < 0.01
        assert abs(scores[1] - 92.30) < 0.01
        assert abs(scores[2] - 45.10) < 0.01

    def test_extract_plddt_multichain(self, tmp_dir):
        pdb_content = (
            "ATOM      1  CA  ALA A   1       1.000   2.000   3.000  1.00 80.00           C\n"
            "ATOM      2  CA  GLY B   1       4.000   5.000   6.000  1.00 90.00           C\n"
            "END\n"
        )
        pdb_path = os.path.join(tmp_dir, "multi.pdb")
        with open(pdb_path, 'w') as f:
            f.write(pdb_content)

        scores = extract_plddt_from_pdb(pdb_path)
        assert len(scores) == 2
        assert abs(scores[0] - 80.0) < 0.01
        assert abs(scores[1] - 90.0) < 0.01

    def test_extract_plddt_missing_file(self):
        with pytest.raises(FileNotFoundError):
            extract_plddt_from_pdb("/nonexistent.pdb")


# ============= CONFIDENCE METRICS TESTS =============

class TestConfidenceMetrics:
    def test_compute_confidence_monomer(self, tmp_dir):
        scores = {
            "plddt": [85.0, 92.0, 45.0, 78.0, 95.0],
            "ptm": 0.82,
            "pae": [[0, 5, 10], [5, 0, 8], [10, 8, 0]]
        }
        score_file = os.path.join(tmp_dir, "scores.json")
        with open(score_file, 'w') as f:
            json.dump(scores, f)

        metrics = compute_confidence_metrics(score_file)
        assert abs(metrics["mean_plddt"] - 79.0) < 0.1
        assert metrics["ptm"] == 0.82
        assert metrics["plddt_above_90"] == 40.0  # 2/5 * 100
        assert metrics["plddt_above_70"] == 80.0  # 4/5 * 100 (85, 92, 78, 95)
        assert "mean_pae" in metrics
        assert metrics["num_residues"] == 5

    def test_compute_confidence_multimer(self, tmp_dir):
        scores = {
            "plddt": [85.0],
            "ptm": 0.80,
            "iptm": 0.75
        }
        score_file = os.path.join(tmp_dir, "scores.json")
        with open(score_file, 'w') as f:
            json.dump(scores, f)

        metrics = compute_confidence_metrics(score_file)
        assert "ranking_confidence" in metrics
        expected = 0.8 * 0.75 + 0.2 * 0.80
        assert abs(metrics["ranking_confidence"] - expected) < 0.01
        assert metrics["iptm"] == 0.75

    def test_classify_confidence(self):
        assert "Very high" in classify_confidence(95)
        assert "Confident" in classify_confidence(80)
        assert "Low" in classify_confidence(60)
        assert "Very low" in classify_confidence(30)
        # Boundary tests
        assert "Very high" in classify_confidence(90)
        assert "Confident" in classify_confidence(70)
        assert "Low" in classify_confidence(50)
        assert "Very low" in classify_confidence(49.9)


# ============= PAE EXTRACTION TESTS =============

class TestPAEExtraction:
    def test_extract_pae_matrix(self, tmp_dir):
        scores = {"pae": [[0, 5, 10], [5, 0, 8], [10, 8, 0]]}
        score_file = os.path.join(tmp_dir, "scores.json")
        with open(score_file, 'w') as f:
            json.dump(scores, f)

        pae = extract_pae_matrix(score_file)
        assert pae is not None
        assert pae.shape == (3, 3)
        assert pae[0, 0] == 0
        assert pae[0, 2] == 10

    def test_extract_pae_missing_key(self, tmp_dir):
        scores = {"plddt": [85]}
        score_file = os.path.join(tmp_dir, "scores.json")
        with open(score_file, 'w') as f:
            json.dump(scores, f)

        pae = extract_pae_matrix(score_file)
        assert pae is None


# ============= RESULT PARSING TESTS =============

class TestResultParsing:
    def test_parse_empty_directory(self, tmp_dir):
        results = parse_colabfold_output(tmp_dir)
        assert results["pdb_files"] == []
        assert results["best_model"] is None
        assert results["num_models"] == 0

    def test_parse_with_models(self, tmp_dir):
        # Create mock PDB and score files
        for i in range(3):
            plddt_val = 70 + i * 10  # 70, 80, 90
            with open(os.path.join(tmp_dir, f"test_scores_rank_{i+1:03d}_model_0_seed_0.json"), 'w') as f:
                json.dump({"plddt": [plddt_val] * 50, "ptm": plddt_val / 100}, f)
            with open(os.path.join(tmp_dir, f"test_rank_{i+1:03d}_model_0_seed_0.pdb"), 'w') as f:
                f.write(f"ATOM      1  CA  ALA A   1       0.0 0.0 0.0 1.00 {plddt_val:.1f}\nEND\n")

        results = parse_colabfold_output(tmp_dir)
        assert len(results["pdb_files"]) == 3
        assert len(results["score_files"]) == 3
        assert results["best_model"] is not None
        assert results["num_models"] == 3

    def test_rank_models(self, tmp_dir):
        for i, plddt_val in enumerate([75, 90, 60], 1):
            with open(os.path.join(tmp_dir, f"test_scores_rank_{i:03d}.json"), 'w') as f:
                json.dump({"plddt": [plddt_val] * 10, "ptm": plddt_val / 100}, f)
            with open(os.path.join(tmp_dir, f"test_rank_{i:03d}.pdb"), 'w') as f:
                f.write(f"ATOM      1  CA  ALA A   1       0.0 0.0 0.0 1.00 {plddt_val:.1f}\nEND\n")

        ranked = rank_models(tmp_dir)
        assert len(ranked) == 3
        assert ranked[0]["mean_plddt"] == 90.0  # Best first
        assert ranked[0]["rank"] == 1
        assert ranked[-1]["mean_plddt"] == 60.0  # Worst last

    def test_summarize_prediction(self, tmp_dir):
        for i, plddt_val in enumerate([85, 92], 1):
            with open(os.path.join(tmp_dir, f"prot_scores_rank_{i:03d}.json"), 'w') as f:
                json.dump({"plddt": [plddt_val] * 20, "ptm": plddt_val / 100}, f)
            with open(os.path.join(tmp_dir, f"prot_rank_{i:03d}.pdb"), 'w') as f:
                f.write("ATOM      1  CA  ALA A   1       0.0 0.0 0.0 1.00 92.0\nEND\n")

        summary = summarize_prediction(tmp_dir)
        assert summary["num_models"] == 2
        assert summary["confidence_class"] is not None


# ============= VISUALIZATION TESTS =============

class TestVisualization:
    def test_plot_plddt(self, tmp_dir):
        scores = [85.0, 92.0, 45.0, 78.0, 95.0, 30.0, 65.0, 88.0]
        output = os.path.join(tmp_dir, "plddt.png")
        result = plot_plddt(scores, output)
        assert os.path.exists(output)
        assert os.path.getsize(output) > 0
        assert result == output

    def test_plot_pae(self, tmp_dir):
        pae = np.random.uniform(0, 20, (10, 10))
        output = os.path.join(tmp_dir, "pae.png")
        result = plot_pae(pae, output)
        assert os.path.exists(output)
        assert os.path.getsize(output) > 0
        assert result == output

    def test_plot_model_comparison(self, tmp_dir):
        models = [
            {"rank": 1, "mean_plddt": 90, "ptm": 0.9},
            {"rank": 2, "mean_plddt": 80, "ptm": 0.8},
            {"rank": 3, "mean_plddt": 70, "ptm": 0.7},
        ]
        output = os.path.join(tmp_dir, "comparison.png")
        result = plot_model_comparison(models, output)
        assert os.path.exists(output)
        assert os.path.getsize(output) > 0

    def test_plot_model_comparison_multimer(self, tmp_dir):
        models = [
            {"rank": 1, "mean_plddt": 90, "ptm": 0.9, "iptm": 0.85},
            {"rank": 2, "mean_plddt": 80, "ptm": 0.8, "iptm": 0.75},
        ]
        output = os.path.join(tmp_dir, "comparison_multi.png")
        result = plot_model_comparison(models, output)
        assert os.path.exists(output)
        assert os.path.getsize(output) > 0


# ============= FINAL RESULTS TESTS =============

class TestFinalResults:
    def test_save_final_results(self, tmp_dir):
        import alphafold_utils
        orig = alphafold_utils.OUTPUT_DIR
        alphafold_utils.OUTPUT_DIR = tmp_dir

        results = {"mean_plddt": 85.5, "num_models": 5}
        output_files = {"best_model": "/output/rank_001.pdb"}
        save_final_results(results, output_files)

        alphafold_utils.OUTPUT_DIR = orig

        result_file = os.path.join(tmp_dir, "final_results.json")
        assert os.path.exists(result_file)
        with open(result_file) as f:
            data = json.load(f)
        assert data["status"] == "completed"
        assert data["summary"]["mean_plddt"] == 85.5
        assert "output_files" in data

    def test_save_final_results_numpy(self, tmp_dir):
        """Test that numpy types are properly serialized."""
        import alphafold_utils
        orig = alphafold_utils.OUTPUT_DIR
        alphafold_utils.OUTPUT_DIR = tmp_dir

        results = {
            "plddt": np.float64(85.5),
            "count": np.int64(10),
            "array": np.array([1.0, 2.0, 3.0]),
        }
        save_final_results(results)

        alphafold_utils.OUTPUT_DIR = orig

        result_file = os.path.join(tmp_dir, "final_results.json")
        with open(result_file) as f:
            data = json.load(f)
        assert data["summary"]["plddt"] == 85.5
        assert data["summary"]["count"] == 10
        assert data["summary"]["array"] == [1.0, 2.0, 3.0]

    def test_save_final_results_failed(self, tmp_dir):
        import alphafold_utils
        orig = alphafold_utils.OUTPUT_DIR
        alphafold_utils.OUTPUT_DIR = tmp_dir

        save_final_results({"error": "test error"}, status="failed")

        alphafold_utils.OUTPUT_DIR = orig

        result_file = os.path.join(tmp_dir, "final_results.json")
        with open(result_file) as f:
            data = json.load(f)
        assert data["status"] == "failed"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
