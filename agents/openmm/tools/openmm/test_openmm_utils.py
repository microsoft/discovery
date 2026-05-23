#!/usr/bin/env python3
"""
Unit tests for openmm_utils.py - run with pytest.

These tests can be run locally in a virtual environment before Docker deployment.
They test parsing, analysis, file I/O, and utility functions without requiring
OpenMM or MDTraj (those are mocked where needed).

Usage:
    python -m venv .venv-openmm
    source .venv-openmm/bin/activate  # Linux/Mac
    # or: .venv-openmm\\Scripts\\activate  # Windows
    pip install pytest numpy matplotlib pandas
    pytest test_openmm_utils.py -v
"""

import pytest
import os
import sys
import json
import tempfile
import shutil
import numpy as np
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add module directory to path for local testing
sys.path.insert(0, os.path.dirname(__file__))


# ============= FIXTURES =============

@pytest.fixture
def tmp_dirs(tmp_path):
    """Create temporary input/output/work directories."""
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    work_dir = tmp_path / "workdir"
    input_dir.mkdir()
    output_dir.mkdir()
    work_dir.mkdir()
    return str(input_dir), str(output_dir), str(work_dir)


@pytest.fixture
def sample_pdb(tmp_path):
    """Create a minimal PDB file for testing."""
    pdb_content = """\
HEADER    TEST PROTEIN
ATOM      1  N   ALA A   1       1.000   2.000   3.000  1.00  0.00           N
ATOM      2  CA  ALA A   1       2.000   3.000   4.000  1.00  0.00           C
ATOM      3  C   ALA A   1       3.000   4.000   5.000  1.00  0.00           C
ATOM      4  O   ALA A   1       4.000   5.000   6.000  1.00  0.00           O
TER
END
"""
    pdb_file = tmp_path / "test.pdb"
    pdb_file.write_text(pdb_content)
    return str(pdb_file)


@pytest.fixture
def sample_log_csv(tmp_path):
    """Create a sample OpenMM StateDataReporter CSV log."""
    log_content = """\
#"Step","Time (ps)","Potential Energy (kJ/mole)","Kinetic Energy (kJ/mole)","Total Energy (kJ/mole)","Temperature (K)","Box Volume (nm^3)","Density (g/mL)","Speed (ns/day)"
1000,2.0,-50000.0,12000.0,-38000.0,298.5,125.0,1.01,50.5
2000,4.0,-50100.0,12100.0,-38000.0,300.1,124.8,1.01,51.2
3000,6.0,-50050.0,12050.0,-38000.0,299.3,124.9,1.01,50.8
4000,8.0,-50200.0,12200.0,-38000.0,301.5,124.7,1.01,49.9
5000,10.0,-50150.0,12150.0,-38000.0,300.8,124.8,1.01,50.1
"""
    log_file = tmp_path / "test.log"
    log_file.write_text(log_content)
    return str(log_file)


@pytest.fixture
def sample_log_unquoted(tmp_path):
    """Create log with unquoted column headers (alternative OpenMM format)."""
    log_content = """\
Step,Time (ps),Potential Energy (kJ/mole),Kinetic Energy (kJ/mole),Total Energy (kJ/mole),Temperature (K),Box Volume (nm^3),Density (g/mL),Speed (ns/day)
1000,2.0,-50000.0,12000.0,-38000.0,298.5,125.0,1.01,50.5
2000,4.0,-50100.0,12100.0,-38000.0,300.1,124.8,1.01,51.2
"""
    log_file = tmp_path / "test_unquoted.log"
    log_file.write_text(log_content)
    return str(log_file)


# ============= TEST SETUP FUNCTIONS =============

class TestQuickSetup:
    """Tests for quick_setup and related setup functions."""

    def test_quick_setup_creates_directories(self, tmp_dirs):
        """quick_setup should create output and work directories."""
        from openmm_utils import quick_setup
        input_dir, output_dir, work_dir = tmp_dirs
        # Remove output_dir so quick_setup creates it
        shutil.rmtree(output_dir)
        quick_setup(input_dir=input_dir, output_dir=output_dir, work_dir=work_dir)
        assert os.path.isdir(output_dir)
        assert os.path.isdir(work_dir)

    def test_quick_setup_copies_input_files(self, tmp_dirs):
        """quick_setup should copy input files to workdir."""
        from openmm_utils import quick_setup
        input_dir, output_dir, work_dir = tmp_dirs
        # Create a test file in input
        test_file = os.path.join(input_dir, "test.pdb")
        with open(test_file, 'w') as f:
            f.write("ATOM test\nEND\n")
        quick_setup(input_dir=input_dir, output_dir=output_dir, work_dir=work_dir)
        assert os.path.isfile(os.path.join(work_dir, "test.pdb"))

    def test_quick_setup_same_dirs(self, tmp_dirs):
        """quick_setup should not fail if input_dir == work_dir."""
        from openmm_utils import quick_setup
        input_dir, output_dir, _ = tmp_dirs
        quick_setup(input_dir=input_dir, output_dir=output_dir, work_dir=input_dir)


class TestCopyInputFiles:
    """Tests for copy_input_files with pattern filtering."""

    def test_copy_with_patterns(self, tmp_dirs):
        """copy_input_files should only copy matching patterns."""
        from openmm_utils import quick_setup, copy_input_files
        input_dir, output_dir, work_dir = tmp_dirs
        # Create mixed files
        for name in ["a.pdb", "b.xyz", "c.pdb", "d.txt"]:
            with open(os.path.join(input_dir, name), 'w') as f:
                f.write("test")
        quick_setup(input_dir=input_dir, output_dir=output_dir, work_dir=work_dir)
        # Clear workdir and copy with pattern
        for f in os.listdir(work_dir):
            os.remove(os.path.join(work_dir, f))
        copy_input_files(patterns=['*.pdb'])
        files = os.listdir(work_dir)
        assert "a.pdb" in files
        assert "c.pdb" in files
        assert "b.xyz" not in files


class TestCopyOutputs:
    """Tests for copy_outputs."""

    def test_copy_outputs_default_patterns(self, tmp_dirs):
        """copy_outputs should copy common file types."""
        from openmm_utils import quick_setup, copy_outputs
        input_dir, output_dir, work_dir = tmp_dirs
        quick_setup(input_dir=input_dir, output_dir=output_dir, work_dir=work_dir)
        # Create files in workdir
        for name in ["result.pdb", "traj.dcd", "energy.png", "notes.tmp"]:
            with open(os.path.join(work_dir, name), 'w') as f:
                f.write("test")
        copy_outputs()
        output_files = os.listdir(output_dir)
        assert "result.pdb" in output_files
        assert "traj.dcd" in output_files
        assert "energy.png" in output_files
        # .tmp not in default patterns
        assert "notes.tmp" not in output_files


# ============= TEST SAVE FINAL RESULTS =============

class TestSaveFinalResults:
    """Tests for save_final_results."""

    def test_saves_json(self, tmp_dirs):
        """save_final_results should write valid JSON to output_dir."""
        from openmm_utils import quick_setup, save_final_results
        input_dir, output_dir, work_dir = tmp_dirs
        quick_setup(input_dir=input_dir, output_dir=output_dir, work_dir=work_dir)
        results = {"energy_kj": -50000.0, "n_atoms": 1000}
        save_final_results(results, {"plot": "energy.png"}, {"plot": "Energy plot"})
        json_path = os.path.join(output_dir, "final_results.json")
        assert os.path.isfile(json_path)
        with open(json_path) as f:
            data = json.load(f)
        assert data["status"] == "completed"
        assert data["summary"]["energy_kj"] == -50000.0
        assert data["output_files"]["plot"] == "energy.png"

    def test_numpy_serialization(self, tmp_dirs):
        """save_final_results should handle numpy types."""
        from openmm_utils import quick_setup, save_final_results
        input_dir, output_dir, work_dir = tmp_dirs
        quick_setup(input_dir=input_dir, output_dir=output_dir, work_dir=work_dir)
        results = {
            "array": np.array([1.0, 2.0, 3.0]),
            "int_val": np.int64(42),
            "float_val": np.float64(3.14),
        }
        save_final_results(results)
        json_path = os.path.join(output_dir, "final_results.json")
        with open(json_path) as f:
            data = json.load(f)
        assert data["summary"]["array"] == [1.0, 2.0, 3.0]
        assert data["summary"]["int_val"] == 42
        assert abs(data["summary"]["float_val"] - 3.14) < 1e-10

    def test_failed_status(self, tmp_dirs):
        """save_final_results should accept custom status."""
        from openmm_utils import quick_setup, save_final_results
        input_dir, output_dir, work_dir = tmp_dirs
        quick_setup(input_dir=input_dir, output_dir=output_dir, work_dir=work_dir)
        save_final_results({"error": "something broke"}, status="failed")
        json_path = os.path.join(output_dir, "final_results.json")
        with open(json_path) as f:
            data = json.load(f)
        assert data["status"] == "failed"


# ============= TEST FILE VALIDATION =============

class TestFileValidation:
    """Tests for input file validation in key functions."""

    def test_fix_pdb_missing_file(self, tmp_path):
        """fix_pdb should raise FileNotFoundError for missing input."""
        from openmm_utils import fix_pdb
        with pytest.raises(FileNotFoundError, match="Input PDB not found"):
            fix_pdb(str(tmp_path / "nonexistent.pdb"))

    def test_create_system_missing_file(self, tmp_path):
        """create_system should raise FileNotFoundError for missing input."""
        from openmm_utils import create_system
        with pytest.raises(FileNotFoundError, match="PDB file not found"):
            create_system(str(tmp_path / "nonexistent.pdb"))

    def test_create_system_from_amber_missing_prmtop(self, tmp_path):
        """create_system_from_amber should raise for missing prmtop."""
        from openmm_utils import create_system_from_amber
        inpcrd = tmp_path / "test.inpcrd"
        inpcrd.write_text("dummy")
        with pytest.raises(FileNotFoundError, match="AMBER prmtop file not found"):
            create_system_from_amber(str(tmp_path / "missing.prmtop"), str(inpcrd))

    def test_create_system_from_amber_missing_inpcrd(self, tmp_path):
        """create_system_from_amber should raise for missing inpcrd."""
        from openmm_utils import create_system_from_amber
        prmtop = tmp_path / "test.prmtop"
        prmtop.write_text("dummy")
        with pytest.raises(FileNotFoundError, match="AMBER inpcrd file not found"):
            create_system_from_amber(str(prmtop), str(tmp_path / "missing.inpcrd"))

    def test_load_trajectory_missing_traj(self, tmp_path):
        """load_trajectory should raise for missing trajectory file."""
        from openmm_utils import load_trajectory
        topo = tmp_path / "test.pdb"
        topo.write_text("ATOM 1 CA ALA A 1 0.0 0.0 0.0\nEND\n")
        with pytest.raises(FileNotFoundError, match="Trajectory file not found"):
            load_trajectory(str(tmp_path / "missing.dcd"), str(topo))

    def test_load_trajectory_missing_topology(self, tmp_path):
        """load_trajectory should raise for missing topology file."""
        from openmm_utils import load_trajectory
        traj = tmp_path / "test.dcd"
        traj.write_bytes(b"\x00")
        with pytest.raises(FileNotFoundError, match="Topology file not found"):
            load_trajectory(str(traj), str(tmp_path / "missing.pdb"))

    def test_parse_log_missing_file(self, tmp_path):
        """parse_log should raise for missing log file."""
        from openmm_utils import parse_log
        with pytest.raises(FileNotFoundError, match="Log file not found"):
            parse_log(str(tmp_path / "missing.log"))


# ============= TEST PARSE LOG =============

class TestParseLog:
    """Tests for parse_log function."""

    def test_parse_standard_log(self, sample_log_csv):
        """parse_log should parse standard OpenMM CSV log correctly."""
        from openmm_utils import parse_log
        result = parse_log(sample_log_csv)
        assert 'step' in result
        assert 'time_ps' in result
        assert 'potential_energy_kj' in result
        assert 'kinetic_energy_kj' in result
        assert 'total_energy_kj' in result
        assert 'temperature_K' in result
        assert len(result['step']) == 5
        np.testing.assert_array_almost_equal(result['step'], [1000, 2000, 3000, 4000, 5000])
        np.testing.assert_array_almost_equal(result['time_ps'], [2.0, 4.0, 6.0, 8.0, 10.0])

    def test_parse_unquoted_log(self, sample_log_unquoted):
        """parse_log should handle unquoted column headers."""
        from openmm_utils import parse_log
        result = parse_log(sample_log_unquoted)
        assert 'step' in result
        assert 'potential_energy_kj' in result
        assert len(result['step']) == 2

    def test_parse_log_energy_values(self, sample_log_csv):
        """parse_log should return correct energy values."""
        from openmm_utils import parse_log
        result = parse_log(sample_log_csv)
        assert result['potential_energy_kj'][0] == -50000.0
        assert result['kinetic_energy_kj'][0] == 12000.0
        assert result['temperature_K'][0] == pytest.approx(298.5)

    def test_parse_log_empty_csv(self, tmp_path):
        """parse_log should raise on empty/invalid CSV."""
        from openmm_utils import parse_log
        empty_log = tmp_path / "empty.log"
        empty_log.write_text("no,valid,columns\n1,2,3\n")
        with pytest.raises(ValueError, match="Could not identify any columns"):
            parse_log(str(empty_log))


# ============= TEST VISUALIZATION =============

class TestPlotEnergy:
    """Tests for plot_energy function."""

    def test_plot_energy_creates_file(self, sample_log_csv, tmp_path):
        """plot_energy should create a PNG file."""
        from openmm_utils import parse_log, plot_energy
        log_data = parse_log(sample_log_csv)
        output_file = str(tmp_path / "energy.png")
        result = plot_energy(log_data, output_file)
        assert os.path.isfile(output_file)
        assert result == output_file

    def test_plot_energy_custom_properties(self, sample_log_csv, tmp_path):
        """plot_energy should handle custom property selection."""
        from openmm_utils import parse_log, plot_energy
        log_data = parse_log(sample_log_csv)
        output_file = str(tmp_path / "temp.png")
        plot_energy(log_data, output_file, properties=['temperature_K'])
        assert os.path.isfile(output_file)

    def test_plot_energy_no_properties(self, tmp_path):
        """plot_energy should handle missing properties gracefully."""
        from openmm_utils import plot_energy
        log_data = {'step': np.array([1, 2, 3])}  # No plottable energy data
        output_file = str(tmp_path / "empty.png")
        plot_energy(log_data, output_file)
        # Should return without error (returns output_file path)


class TestPlotRmsd:
    """Tests for plot_rmsd function."""

    def test_plot_rmsd_creates_file(self, tmp_path):
        """plot_rmsd should create a PNG file."""
        from openmm_utils import plot_rmsd
        rmsd_data = {
            'rmsd_nm': [0.1, 0.15, 0.2, 0.18, 0.22],
            'time_ps': [0, 2, 4, 6, 8],
            'mean_nm': 0.17,
            'std_nm': 0.04,
            'selection': 'protein and name CA',
        }
        output_file = str(tmp_path / "rmsd.png")
        result = plot_rmsd(rmsd_data, output_file)
        assert os.path.isfile(output_file)
        assert result == output_file


class TestPlotRmsf:
    """Tests for plot_rmsf function."""

    def test_plot_rmsf_creates_file(self, tmp_path):
        """plot_rmsf should create a PNG file."""
        from openmm_utils import plot_rmsf
        rmsf_data = {
            'rmsf_nm': [0.05, 0.12, 0.08, 0.15, 0.07],
            'residue_indices': [0, 1, 2, 3, 4],
            'mean_nm': 0.094,
            'max_nm': 0.15,
            'max_residue': 3,
        }
        output_file = str(tmp_path / "rmsf.png")
        result = plot_rmsf(rmsf_data, output_file)
        assert os.path.isfile(output_file)
        assert result == output_file


class TestPlotSecondaryStructure:
    """Tests for plot_secondary_structure function."""

    def test_plot_ss_creates_file(self, tmp_path):
        """plot_secondary_structure should create a PNG file."""
        from openmm_utils import plot_secondary_structure
        ss_data = {
            'helix_fraction': [0.3, 0.31, 0.29, 0.30],
            'sheet_fraction': [0.2, 0.19, 0.21, 0.20],
            'coil_fraction': [0.5, 0.50, 0.50, 0.50],
        }
        output_file = str(tmp_path / "ss.png")
        result = plot_secondary_structure(ss_data, output_file)
        assert os.path.isfile(output_file)
        assert result == output_file


# ============= TEST CLEANUP =============

class TestCleanup:
    """Tests for openmm_cleanup function."""

    def test_cleanup_no_error(self):
        """openmm_cleanup should run without error."""
        from openmm_utils import openmm_cleanup
        openmm_cleanup(deep=False)

    def test_deep_cleanup(self):
        """openmm_cleanup with deep=True should not error."""
        from openmm_utils import openmm_cleanup
        openmm_cleanup(deep=True)


# ============= TEST CONSTANTS =============

class TestConstants:
    """Tests for module-level constants."""

    def test_kj_to_kcal_conversion(self):
        """Conversion factor should be approximately correct."""
        from openmm_utils import _KJ_PER_MOL_TO_KCAL
        # 1 kJ/mol = 0.239006 kcal/mol
        assert abs(_KJ_PER_MOL_TO_KCAL - 0.239006) < 1e-6

    def test_default_directories(self):
        """Default directory constants should be set."""
        import openmm_utils
        assert openmm_utils.SCRATCH_DIR == "/tmp/openmm_scratch"


# ============= TEST EDGE CASES =============

class TestEdgeCases:
    """Edge case and boundary condition tests."""

    def test_save_final_results_empty(self, tmp_dirs):
        """save_final_results should handle empty results dict."""
        from openmm_utils import quick_setup, save_final_results
        input_dir, output_dir, work_dir = tmp_dirs
        quick_setup(input_dir=input_dir, output_dir=output_dir, work_dir=work_dir)
        save_final_results({})
        json_path = os.path.join(output_dir, "final_results.json")
        with open(json_path) as f:
            data = json.load(f)
        assert data["summary"] == {}

    def test_save_final_results_nested_numpy(self, tmp_dirs):
        """save_final_results should handle nested numpy arrays."""
        from openmm_utils import quick_setup, save_final_results
        input_dir, output_dir, work_dir = tmp_dirs
        quick_setup(input_dir=input_dir, output_dir=output_dir, work_dir=work_dir)
        results = {
            "nested": {
                "arr": np.array([1, 2, 3]),
                "val": np.float32(1.5),
            },
            "list_of_np": [np.int64(1), np.int64(2)],
        }
        save_final_results(results)
        json_path = os.path.join(output_dir, "final_results.json")
        with open(json_path) as f:
            data = json.load(f)
        assert data["summary"]["nested"]["arr"] == [1, 2, 3]

    def test_copy_input_files_no_input_dir(self, tmp_dirs):
        """copy_input_files should handle missing input dir gracefully."""
        from openmm_utils import quick_setup, copy_input_files
        _, output_dir, work_dir = tmp_dirs
        nonexistent = os.path.join(work_dir, "no_such_input")
        quick_setup(input_dir=nonexistent, output_dir=output_dir, work_dir=work_dir)
        # Should not raise
        copy_input_files()

    def test_plot_rmsd_no_time(self, tmp_path):
        """plot_rmsd should work without time_ps key."""
        from openmm_utils import plot_rmsd
        rmsd_data = {
            'rmsd_nm': [0.1, 0.2, 0.3],
            'mean_nm': 0.2,
            'selection': 'all',
        }
        output_file = str(tmp_path / "rmsd_no_time.png")
        plot_rmsd(rmsd_data, output_file)
        assert os.path.isfile(output_file)
