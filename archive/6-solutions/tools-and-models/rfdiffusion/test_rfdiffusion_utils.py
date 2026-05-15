#!/usr/bin/env python3
"""Unit tests for rfdiffusion_utils.py — run with pytest.

Tests contig builders, PDB parsing, backbone metrics, and RMSD computation.
All tests run WITHOUT RFDiffusion installed (no GPU needed).
"""

import pytest
import os
import sys
import json
import tempfile
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from rfdiffusion_utils import (
    build_contigs_unconditional,
    build_contigs_binder,
    build_contigs_motif_scaffold,
    build_contigs_symmetric,
    parse_pdb,
    compute_backbone_metrics,
    compute_ca_rmsd,
    save_final_results,
    get_pdb_chain_info,
    analyze_designs,
)


# ===== Test PDB data =====
SAMPLE_PDB_1CHAIN = """\
ATOM      1  N   ALA A   1       1.000   2.000   3.000  1.00  0.00           N
ATOM      2  CA  ALA A   1       2.000   2.000   3.000  1.00  0.00           C
ATOM      3  C   ALA A   1       3.000   2.000   3.000  1.00  0.00           C
ATOM      4  O   ALA A   1       3.500   3.000   3.000  1.00  0.00           O
ATOM      5  N   GLY A   2       3.500   1.000   3.000  1.00  0.00           N
ATOM      6  CA  GLY A   2       5.800   2.000   3.000  1.00  0.00           C
ATOM      7  C   GLY A   2       6.000   2.000   3.000  1.00  0.00           C
ATOM      8  O   GLY A   2       6.500   3.000   3.000  1.00  0.00           O
ATOM      9  N   VAL A   3       6.500   1.000   3.000  1.00  0.00           N
ATOM     10  CA  VAL A   3       9.600   2.000   4.000  1.00  0.00           C
ATOM     11  C   VAL A   3      10.000   2.000   4.000  1.00  0.00           C
ATOM     12  O   VAL A   3      10.500   3.000   4.000  1.00  0.00           O
END
"""

SAMPLE_PDB_2CHAIN = """\
ATOM      1  N   ALA A   1       1.000   2.000   3.000  1.00  0.00           N
ATOM      2  CA  ALA A   1       2.000   2.000   3.000  1.00  0.00           C
ATOM      3  N   GLY A   2       3.500   1.000   3.000  1.00  0.00           N
ATOM      4  CA  GLY A   2       5.800   2.000   3.000  1.00  0.00           C
ATOM      5  N   ALA B   1      10.000  10.000  10.000  1.00  0.00           N
ATOM      6  CA  ALA B   1      11.000  10.000  10.000  1.00  0.00           C
ATOM      7  N   GLY B   2      13.000  10.000  10.000  1.00  0.00           N
ATOM      8  CA  GLY B   2      14.800  10.000  10.000  1.00  0.00           C
END
"""

SAMPLE_PDB_SHIFTED = """\
ATOM      1  N   ALA A   1       2.000   3.000   4.000  1.00  0.00           N
ATOM      2  CA  ALA A   1       3.000   3.000   4.000  1.00  0.00           C
ATOM      3  C   ALA A   1       4.000   3.000   4.000  1.00  0.00           C
ATOM      4  O   ALA A   1       4.500   4.000   4.000  1.00  0.00           O
ATOM      5  N   GLY A   2       4.500   2.000   4.000  1.00  0.00           N
ATOM      6  CA  GLY A   2       6.800   3.000   4.000  1.00  0.00           C
ATOM      7  C   GLY A   2       7.000   3.000   4.000  1.00  0.00           C
ATOM      8  O   GLY A   2       7.500   4.000   4.000  1.00  0.00           O
ATOM      9  N   VAL A   3       7.500   2.000   4.000  1.00  0.00           N
ATOM     10  CA  VAL A   3      10.600   3.000   5.000  1.00  0.00           C
ATOM     11  C   VAL A   3      11.000   3.000   5.000  1.00  0.00           C
ATOM     12  O   VAL A   3      11.500   4.000   5.000  1.00  0.00           O
END
"""


# ===== Contig Builder Tests =====

class TestContigBuildersUnconditional:
    def test_exact_length(self):
        assert build_contigs_unconditional(150) == '[150-150]'

    def test_range_tuple(self):
        assert build_contigs_unconditional((100, 200)) == '[100-200]'

    def test_range_list(self):
        assert build_contigs_unconditional([80, 120]) == '[80-120]'

    def test_single_residue(self):
        assert build_contigs_unconditional(1) == '[1-1]'

    def test_large_protein(self):
        assert build_contigs_unconditional(500) == '[500-500]'


class TestContigBuildersBinder:
    def test_basic_binder(self):
        result = build_contigs_binder('A', 1, 100, (70, 100))
        assert result == '[A1-100/0 70-100]'

    def test_exact_binder_length(self):
        result = build_contigs_binder('B', 10, 200, 80)
        assert result == '[B10-200/0 80-80]'

    def test_custom_gap(self):
        result = build_contigs_binder('A', 1, 50, 60, gap=5)
        assert result == '[A1-50/5 60-60]'

    def test_short_target(self):
        result = build_contigs_binder('C', 1, 20, (30, 50))
        assert result == '[C1-20/0 30-50]'


class TestContigBuildersMotif:
    def test_basic_scaffold(self):
        result = build_contigs_motif_scaffold('A163-181', (10, 40), (10, 40))
        assert result == '[10-40/A163-181/10-40]'

    def test_exact_scaffold_lengths(self):
        result = build_contigs_motif_scaffold('B50-75', 20, 30)
        assert result == '[20-20/B50-75/30-30]'

    def test_mixed_range_types(self):
        result = build_contigs_motif_scaffold('A1-10', (5, 15), 20)
        assert result == '[5-15/A1-10/20-20]'


class TestContigBuildersSymmetric:
    def test_exact_length(self):
        assert build_contigs_symmetric(100) == '[100-100]'

    def test_range(self):
        assert build_contigs_symmetric((80, 120)) == '[80-120]'


# ===== PDB Parsing Tests =====

class TestPDBParsing:
    @pytest.fixture
    def pdb_1chain(self, tmp_path):
        f = tmp_path / "test1.pdb"
        f.write_text(SAMPLE_PDB_1CHAIN)
        return str(f)

    @pytest.fixture
    def pdb_2chain(self, tmp_path):
        f = tmp_path / "test2.pdb"
        f.write_text(SAMPLE_PDB_2CHAIN)
        return str(f)

    def test_parse_single_chain(self, pdb_1chain):
        result = parse_pdb(pdb_1chain)
        assert result['num_chains'] == 1
        assert result['total_residues'] == 3
        assert 'A' in result['chains']
        assert result['chains']['A']['num_residues'] == 3
        assert len(result['ca_coords']) == 3

    def test_parse_two_chains(self, pdb_2chain):
        result = parse_pdb(pdb_2chain)
        assert result['num_chains'] == 2
        assert 'A' in result['chains']
        assert 'B' in result['chains']
        assert result['chains']['A']['num_residues'] == 2
        assert result['chains']['B']['num_residues'] == 2
        assert len(result['ca_coords']) == 4

    def test_parse_missing_file(self):
        with pytest.raises(FileNotFoundError):
            parse_pdb("nonexistent_file.pdb")

    def test_ca_coords_shape(self, pdb_1chain):
        result = parse_pdb(pdb_1chain)
        assert result['ca_coords'].shape == (3, 3)

    def test_residue_range(self, pdb_1chain):
        result = parse_pdb(pdb_1chain)
        assert result['chains']['A']['residue_range'] == (1, 3)

    def test_atom_count(self, pdb_1chain):
        result = parse_pdb(pdb_1chain)
        assert result['total_atoms'] == 12


# ===== Backbone Metrics Tests =====

class TestBackboneMetrics:
    @pytest.fixture
    def pdb_file(self, tmp_path):
        f = tmp_path / "test.pdb"
        f.write_text(SAMPLE_PDB_1CHAIN)
        return str(f)

    def test_metrics_keys(self, pdb_file):
        metrics = compute_backbone_metrics(pdb_file)
        expected_keys = [
            'num_residues', 'num_chains', 'radius_of_gyration',
            'end_to_end_distance', 'compactness', 'ca_distance_mean',
            'ca_distance_std', 'total_atoms'
        ]
        for key in expected_keys:
            assert key in metrics, f"Missing key: {key}"

    def test_num_residues(self, pdb_file):
        metrics = compute_backbone_metrics(pdb_file)
        assert metrics['num_residues'] == 3

    def test_rg_positive(self, pdb_file):
        metrics = compute_backbone_metrics(pdb_file)
        assert metrics['radius_of_gyration'] > 0

    def test_rg_reasonable(self, pdb_file):
        metrics = compute_backbone_metrics(pdb_file)
        # For 3 residues spread over ~8 Angstroms
        assert 0.5 < metrics['radius_of_gyration'] < 10.0

    def test_end_to_end_positive(self, pdb_file):
        metrics = compute_backbone_metrics(pdb_file)
        assert metrics['end_to_end_distance'] > 0

    def test_compactness_positive(self, pdb_file):
        metrics = compute_backbone_metrics(pdb_file)
        assert metrics['compactness'] > 0

    def test_ca_distance_mean_positive(self, pdb_file):
        metrics = compute_backbone_metrics(pdb_file)
        assert metrics['ca_distance_mean'] > 0

    def test_empty_pdb(self, tmp_path):
        f = tmp_path / "empty.pdb"
        f.write_text("END\n")
        metrics = compute_backbone_metrics(str(f))
        assert 'error' in metrics


# ===== RMSD Tests =====

class TestRMSD:
    @pytest.fixture
    def identical_pdbs(self, tmp_path):
        f1 = tmp_path / "pdb1.pdb"
        f2 = tmp_path / "pdb2.pdb"
        f1.write_text(SAMPLE_PDB_1CHAIN)
        f2.write_text(SAMPLE_PDB_1CHAIN)
        return str(f1), str(f2)

    @pytest.fixture
    def different_pdbs(self, tmp_path):
        f1 = tmp_path / "orig.pdb"
        f2 = tmp_path / "shifted.pdb"
        f1.write_text(SAMPLE_PDB_1CHAIN)
        f2.write_text(SAMPLE_PDB_SHIFTED)
        return str(f1), str(f2)

    def test_identical_rmsd_zero(self, identical_pdbs):
        rmsd = compute_ca_rmsd(identical_pdbs[0], identical_pdbs[1])
        assert abs(rmsd) < 1e-6

    def test_different_rmsd_positive(self, different_pdbs):
        rmsd = compute_ca_rmsd(different_pdbs[0], different_pdbs[1])
        assert rmsd > 0

    def test_rmsd_is_float(self, identical_pdbs):
        rmsd = compute_ca_rmsd(identical_pdbs[0], identical_pdbs[1])
        assert isinstance(rmsd, float)

    def test_mismatched_atoms_raises(self, tmp_path):
        f1 = tmp_path / "short.pdb"
        f2 = tmp_path / "long.pdb"
        f1.write_text(SAMPLE_PDB_1CHAIN)
        f2.write_text(SAMPLE_PDB_2CHAIN)
        with pytest.raises(ValueError, match="CA atom count mismatch"):
            compute_ca_rmsd(str(f1), str(f2))


# ===== Save Results Tests =====

class TestSaveResults:
    def test_save_basic(self, tmp_path):
        import rfdiffusion_utils
        orig_dir = rfdiffusion_utils.OUTPUT_DIR
        rfdiffusion_utils.OUTPUT_DIR = str(tmp_path)
        try:
            save_final_results(
                {'num_designs': 10, 'best_rg': 12.5},
                {'plot': '/output/plot.png'},
                {'plot': 'Metrics plot'}
            )
            result_file = tmp_path / 'final_results.json'
            assert result_file.exists()
            data = json.loads(result_file.read_text())
            assert data['status'] == 'completed'
            assert data['summary']['num_designs'] == 10
            assert data['output_files']['plot'] == '/output/plot.png'
        finally:
            rfdiffusion_utils.OUTPUT_DIR = orig_dir

    def test_save_with_error_status(self, tmp_path):
        import rfdiffusion_utils
        orig_dir = rfdiffusion_utils.OUTPUT_DIR
        rfdiffusion_utils.OUTPUT_DIR = str(tmp_path)
        try:
            save_final_results(
                {'error': 'Something failed'},
                status='failed'
            )
            data = json.loads((tmp_path / 'final_results.json').read_text())
            assert data['status'] == 'failed'
        finally:
            rfdiffusion_utils.OUTPUT_DIR = orig_dir


# ===== Chain Info Tests =====

class TestChainInfo:
    def test_single_chain(self, tmp_path):
        f = tmp_path / "test.pdb"
        f.write_text(SAMPLE_PDB_1CHAIN)
        info = get_pdb_chain_info(str(f))
        assert 'A' in info
        assert info['A']['start'] == 1
        assert info['A']['end'] == 3
        assert info['A']['num_residues'] == 3

    def test_two_chains(self, tmp_path):
        f = tmp_path / "test.pdb"
        f.write_text(SAMPLE_PDB_2CHAIN)
        info = get_pdb_chain_info(str(f))
        assert 'A' in info
        assert 'B' in info
        assert info['B']['start'] == 1
        assert info['B']['end'] == 2


# ===== Analyze Designs Tests =====

class TestAnalyzeDesigns:
    def test_no_files_returns_empty(self, tmp_path):
        result = analyze_designs(str(tmp_path / "nonexistent_prefix"))
        assert result == []

    def test_analyze_single_design(self, tmp_path):
        # Create a fake design PDB
        pdb_file = tmp_path / "design_0.pdb"
        pdb_file.write_text(SAMPLE_PDB_1CHAIN)
        prefix = str(tmp_path / "design")
        metrics = analyze_designs(prefix)
        assert len(metrics) == 1
        assert metrics[0]['num_residues'] == 3
        assert 'filename' in metrics[0]


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
