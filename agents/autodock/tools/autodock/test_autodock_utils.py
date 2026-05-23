#!/usr/bin/env python3
"""
Unit tests for autodock_utils.py - run with pytest.

These tests can be run locally in a virtual environment before Docker deployment.
They test parsing, analysis, and utility functions without requiring AutoDock Vina.

Usage:
    python -m venv .venv-autodock
    source .venv-autodock/bin/activate  # Linux/Mac
    # or: .venv-autodock\\Scripts\\activate  # Windows
    pip install pytest numpy matplotlib
    pytest test_autodock_utils.py -v
"""

import pytest
import os
import sys
import tempfile
import json
from pathlib import Path

# Add module directory to path for local testing
sys.path.insert(0, os.path.dirname(__file__))

from autodock_utils import (
    GridBox,
    DockingResult,
    DockingResults,
    calculate_grid_box_from_coords,
    create_grid_box,
    parse_vina_output,
    rank_docking_results,
    calculate_ligand_efficiency,
    detect_file_format,
    validate_pdbqt,
    split_pdbqt_models,
    extract_pose,
    count_heavy_atoms,
    read_pdb_coordinates,
    read_pdbqt_coordinates,
    batch_prepare_ligands,
    _prepare_single_ligand,
    extract_reference_ligand,
    calculate_grid_box_from_ligand,
    MAX_LIGAND_ATOMS,
    MAX_BOX_DIMENSION,
)


# ============= TEST DATA =============

SAMPLE_VINA_OUTPUT = """
#################################################################
# If you used AutoDock Vina in your work, please cite:          #
#                                                               #
# O. Trott, A. J. Olson,                                        #
# AutoDock Vina: improving the speed and accuracy of docking    #
# with a new scoring function, efficient optimization and       #
# multithreading, Journal of Computational Chemistry 31 (2010)  #
# 455-461                                                       #
#                                                               #
# DOI 10.1002/jcc.21334                                         #
#                                                               #
# Please see https://github.com/ccsb-scripps/AutoDock-Vina for  #
# more information.                                             #
#################################################################

Detecting 8 CPUs
Reading input ... done.
Setting up the scoring function ... done.
Analyzing the binding site ... done.
Using random seed: 42
Performing search ... done.
Refining results ... done.

mode |   affinity | dist from best mode
     | (kcal/mol) | rmsd l.b.| rmsd u.b.
-----+------------+----------+----------
   1       -10.3      0.000      0.000
   2        -9.8      1.234      2.456
   3        -9.2      2.345      3.567
   4        -8.7      3.456      4.678
   5        -8.1      4.567      5.789
Writing output ... done.
"""

SAMPLE_PDBQT_CONTENT = """MODEL        1
REMARK VINA RESULT:    -10.3      0.000      0.000
ATOM      1  C1  LIG     1      10.000  20.000  30.000  1.00  0.00    -0.050 C
ATOM      2  C2  LIG     1      11.000  21.000  31.000  1.00  0.00    -0.050 C
ATOM      3  O1  LIG     1      12.000  22.000  32.000  1.00  0.00    -0.300 OA
ATOM      4  N1  LIG     1      13.000  23.000  33.000  1.00  0.00    -0.200 NA
ATOM      5  H1  LIG     1      14.000  24.000  34.000  1.00  0.00     0.100 HD
ENDMDL
MODEL        2
REMARK VINA RESULT:     -9.8      1.234      2.456
ATOM      1  C1  LIG     1      10.500  20.500  30.500  1.00  0.00    -0.050 C
ATOM      2  C2  LIG     1      11.500  21.500  31.500  1.00  0.00    -0.050 C
ATOM      3  O1  LIG     1      12.500  22.500  32.500  1.00  0.00    -0.300 OA
ATOM      4  N1  LIG     1      13.500  23.500  33.500  1.00  0.00    -0.200 NA
ATOM      5  H1  LIG     1      14.500  24.500  34.500  1.00  0.00     0.100 HD
ENDMDL
"""

SAMPLE_PDB_CONTENT = """ATOM      1  N   ALA A   1      10.000  20.000  30.000  1.00  0.00           N
ATOM      2  CA  ALA A   1      11.000  21.000  31.000  1.00  0.00           C
ATOM      3  C   ALA A   1      12.000  22.000  32.000  1.00  0.00           C
ATOM      4  O   ALA A   1      13.000  23.000  33.000  1.00  0.00           O
ATOM      5  CB  ALA A   1      14.000  24.000  34.000  1.00  0.00           C
TER
END
"""


# ============= TEST FIXTURES =============

@pytest.fixture
def temp_dir():
    """Create a temporary directory for test files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def sample_pdbqt_file(temp_dir):
    """Create a sample PDBQT file."""
    filepath = os.path.join(temp_dir, "ligand_out.pdbqt")
    with open(filepath, 'w') as f:
        f.write(SAMPLE_PDBQT_CONTENT)
    return filepath


@pytest.fixture
def sample_pdb_file(temp_dir):
    """Create a sample PDB file."""
    filepath = os.path.join(temp_dir, "receptor.pdb")
    with open(filepath, 'w') as f:
        f.write(SAMPLE_PDB_CONTENT)
    return filepath


# ============= GRID BOX TESTS =============

class TestGridBox:
    """Tests for GridBox class and related functions."""

    def test_grid_box_creation(self):
        """Test basic GridBox creation."""
        box = GridBox(
            center_x=10.0,
            center_y=20.0,
            center_z=30.0,
            size_x=25.0,
            size_y=25.0,
            size_z=25.0
        )
        assert box.center_x == 10.0
        assert box.center_y == 20.0
        assert box.center_z == 30.0
        assert box.size_x == 25.0

    def test_grid_box_to_dict(self):
        """Test GridBox serialization."""
        box = GridBox(10.0, 20.0, 30.0, 25.0, 25.0, 25.0)
        d = box.to_dict()
        assert d['center_x'] == 10.0
        assert d['size_x'] == 25.0

    def test_grid_box_to_vina_params(self):
        """Test Vina parameter generation."""
        box = GridBox(10.0, 20.0, 30.0, 25.0, 25.0, 25.0)
        params = box.to_vina_params()
        assert "--center_x 10.000" in params
        assert "--center_y 20.000" in params
        assert "--size_x 25.000" in params

    def test_calculate_grid_box_from_coords(self):
        """Test grid box calculation from coordinates."""
        coords = [
            (0.0, 0.0, 0.0),
            (10.0, 10.0, 10.0),
            (5.0, 5.0, 5.0)
        ]
        box = calculate_grid_box_from_coords(coords, padding=5.0)

        # Center should be at (5, 5, 5)
        assert abs(box.center_x - 5.0) < 0.001
        assert abs(box.center_y - 5.0) < 0.001
        assert abs(box.center_z - 5.0) < 0.001

        # Size should be 10 + 2*5 = 20
        assert abs(box.size_x - 20.0) < 0.001

    def test_calculate_grid_box_empty_coords(self):
        """Test error handling for empty coordinates."""
        with pytest.raises(ValueError, match="No coordinates"):
            calculate_grid_box_from_coords([])

    def test_create_grid_box(self):
        """Test grid box creation from center and size."""
        box = create_grid_box(
            center=(10.0, 20.0, 30.0),
            size=(25.0, 30.0, 35.0)
        )
        assert box.center_x == 10.0
        assert box.size_y == 30.0


# ============= PARSING TESTS =============

class TestParsing:
    """Tests for output parsing functions."""

    def test_parse_vina_output(self):
        """Test parsing Vina stdout."""
        poses = parse_vina_output(SAMPLE_VINA_OUTPUT)

        assert len(poses) == 5
        assert poses[0].mode == 1
        assert poses[0].affinity == -10.3
        assert poses[0].rmsd_lb == 0.0
        assert poses[0].rmsd_ub == 0.0

        assert poses[1].mode == 2
        assert poses[1].affinity == -9.8
        assert abs(poses[1].rmsd_lb - 1.234) < 0.001

    def test_parse_vina_output_empty(self):
        """Test parsing empty output."""
        poses = parse_vina_output("")
        assert len(poses) == 0

    def test_parse_vina_output_no_results(self):
        """Test parsing output with no docking results."""
        output = "Some random text without results"
        poses = parse_vina_output(output)
        assert len(poses) == 0

    def test_read_pdb_coordinates(self, sample_pdb_file):
        """Test reading coordinates from PDB file."""
        coords = read_pdb_coordinates(sample_pdb_file)
        assert len(coords) == 5
        assert coords[0] == (10.0, 20.0, 30.0)
        assert coords[1] == (11.0, 21.0, 31.0)

    def test_read_pdbqt_coordinates(self, sample_pdbqt_file):
        """Test reading coordinates from PDBQT file."""
        coords = read_pdbqt_coordinates(sample_pdbqt_file)
        # Should read from both models
        assert len(coords) == 10  # 5 atoms x 2 models


# ============= DOCKING RESULT TESTS =============

class TestDockingResults:
    """Tests for DockingResult and DockingResults classes."""

    def test_docking_result_creation(self):
        """Test DockingResult creation."""
        result = DockingResult(
            mode=1,
            affinity=-10.5,
            rmsd_lb=0.0,
            rmsd_ub=0.0
        )
        assert result.mode == 1
        assert result.affinity == -10.5

    def test_docking_result_to_dict(self):
        """Test DockingResult serialization."""
        result = DockingResult(1, -10.5, 0.0, 0.0)
        d = result.to_dict()
        assert d['mode'] == 1
        assert d['affinity'] == -10.5

    def test_docking_results_best_affinity(self):
        """Test automatic best affinity calculation."""
        poses = [
            DockingResult(1, -10.0, 0.0, 0.0),
            DockingResult(2, -9.5, 1.0, 2.0),
            DockingResult(3, -8.0, 2.0, 3.0)
        ]
        results = DockingResults(
            ligand_name="test_ligand",
            receptor_name="test_receptor",
            poses=poses,
            output_pdbqt="test_out.pdbqt"
        )
        assert results.best_affinity == -10.0

    def test_docking_results_to_dict(self):
        """Test DockingResults serialization."""
        poses = [DockingResult(1, -10.0, 0.0, 0.0)]
        results = DockingResults(
            ligand_name="ligand",
            receptor_name="receptor",
            poses=poses,
            output_pdbqt="out.pdbqt"
        )
        d = results.to_dict()
        assert d['ligand_name'] == "ligand"
        assert d['best_affinity_kcal_mol'] == -10.0
        assert d['num_poses'] == 1


class TestRanking:
    """Tests for result ranking functions."""

    def test_rank_docking_results(self):
        """Test ranking multiple docking results."""
        results = [
            DockingResults("lig1", "rec", [DockingResult(1, -8.0, 0, 0)], "o1.pdbqt"),
            DockingResults("lig2", "rec", [DockingResult(1, -10.0, 0, 0)], "o2.pdbqt"),
            DockingResults("lig3", "rec", [DockingResult(1, -9.0, 0, 0)], "o3.pdbqt"),
        ]

        ranked = rank_docking_results(results)

        assert len(ranked) == 3
        assert ranked[0]['rank'] == 1
        assert ranked[0]['ligand_name'] == "lig2"
        assert ranked[0]['best_affinity_kcal_mol'] == -10.0

        assert ranked[1]['ligand_name'] == "lig3"
        assert ranked[2]['ligand_name'] == "lig1"

    def test_rank_docking_results_empty(self):
        """Test ranking with no results."""
        ranked = rank_docking_results([])
        assert len(ranked) == 0


# ============= ANALYSIS TESTS =============

class TestAnalysis:
    """Tests for analysis functions."""

    def test_calculate_ligand_efficiency(self):
        """Test ligand efficiency calculation."""
        # LE = -(-10) / 20 = 0.5
        le = calculate_ligand_efficiency(-10.0, 20)
        assert abs(le - 0.5) < 0.001

    def test_calculate_ligand_efficiency_zero_atoms(self):
        """Test ligand efficiency with zero atoms."""
        le = calculate_ligand_efficiency(-10.0, 0)
        assert le == 0.0

    def test_count_heavy_atoms(self, sample_pdbqt_file):
        """Test counting heavy atoms."""
        count = count_heavy_atoms(sample_pdbqt_file)
        # Sample has 5 atoms per model, 1 is hydrogen
        # But we read both models, so expect 8 heavy atoms (4 per model)
        assert count == 8  # 4 heavy atoms x 2 models


# ============= FILE FORMAT TESTS =============

class TestFileFormats:
    """Tests for file format detection and conversion."""

    def test_detect_file_format(self):
        """Test file format detection."""
        assert detect_file_format("receptor.pdb") == "pdb"
        assert detect_file_format("ligand.pdbqt") == "pdbqt"
        assert detect_file_format("molecule.sdf") == "sdf"
        assert detect_file_format("compound.mol2") == "mol2"
        assert detect_file_format("smiles.smi") == "smi"
        assert detect_file_format("unknown.xyz") == "xyz"
        assert detect_file_format("file.abc") == "unknown"

    def test_validate_pdbqt_valid(self, sample_pdbqt_file):
        """Test PDBQT validation with valid file."""
        result = validate_pdbqt(sample_pdbqt_file)
        assert result['valid'] == True
        assert result['atom_count'] == 10  # 5 atoms x 2 models
        assert result['has_charges'] == True
        assert result['has_atom_types'] == True

    def test_validate_pdbqt_invalid(self, temp_dir):
        """Test PDBQT validation with invalid file."""
        invalid_file = os.path.join(temp_dir, "invalid.pdbqt")
        with open(invalid_file, 'w') as f:
            f.write("ATOM  1  C  LIG  1  10.0 20.0 30.0\n")  # Too short

        result = validate_pdbqt(invalid_file)
        assert result['valid'] == False
        assert len(result['issues']) > 0


# ============= MODEL SPLITTING TESTS =============

class TestModelSplitting:
    """Tests for multi-model PDBQT handling."""

    def test_split_pdbqt_models(self, sample_pdbqt_file, temp_dir):
        """Test splitting multi-model PDBQT."""
        output_files = split_pdbqt_models(sample_pdbqt_file, temp_dir)

        assert len(output_files) == 2
        assert all(os.path.exists(f) for f in output_files)

        # Check first pose file
        with open(output_files[0], 'r') as f:
            content = f.read()
            assert "MODEL        1" in content
            assert "-10.3" in content

    def test_extract_pose(self, sample_pdbqt_file, temp_dir):
        """Test extracting specific pose."""
        output_file = os.path.join(temp_dir, "pose1.pdbqt")
        result = extract_pose(sample_pdbqt_file, 1, output_file)

        assert os.path.exists(result)
        with open(result, 'r') as f:
            content = f.read()
            assert "MODEL        1" in content
            assert "-10.3" in content

    def test_extract_pose_invalid_number(self, sample_pdbqt_file):
        """Test extracting non-existent pose."""
        with pytest.raises(ValueError, match="not found"):
            extract_pose(sample_pdbqt_file, 99)


# ============= INTEGRATION TESTS =============

class TestIntegration:
    """Integration tests combining multiple functions."""

    def test_full_parsing_workflow(self):
        """Test complete parsing workflow."""
        # Parse Vina output
        poses = parse_vina_output(SAMPLE_VINA_OUTPUT)

        # Create DockingResults
        results = DockingResults(
            ligand_name="indinavir",
            receptor_name="1hsg",
            poses=poses,
            output_pdbqt="indinavir_out.pdbqt"
        )

        # Check results
        assert results.best_affinity == -10.3
        assert len(results.poses) == 5

        # Serialize and verify
        d = results.to_dict()
        assert d['best_affinity_kcal_mol'] == -10.3
        assert d['num_poses'] == 5

    def test_grid_box_workflow(self, sample_pdb_file):
        """Test grid box calculation workflow."""
        # Read coordinates
        coords = read_pdb_coordinates(sample_pdb_file)

        # Calculate grid box
        box = calculate_grid_box_from_coords(coords, padding=10.0)

        # Verify reasonable values
        assert 5.0 < box.center_x < 15.0
        assert 15.0 < box.center_y < 25.0
        assert 25.0 < box.center_z < 35.0

        # Box should be at least 20 Angstroms (10 padding on each side)
        assert box.size_x >= 20.0

    def test_results_summary_creation(self, temp_dir):
        """Test creating results summary."""
        # Create mock results
        results = [
            DockingResults("lig_a", "rec", [DockingResult(1, -10.5, 0, 0)], "a.pdbqt"),
            DockingResults("lig_b", "rec", [DockingResult(1, -8.2, 0, 0)], "b.pdbqt"),
            DockingResults("lig_c", "rec", [DockingResult(1, -9.7, 0, 0)], "c.pdbqt"),
        ]

        # Rank results
        ranked = rank_docking_results(results)

        # Verify ranking
        assert ranked[0]['ligand_name'] == "lig_a"
        assert ranked[1]['ligand_name'] == "lig_c"
        assert ranked[2]['ligand_name'] == "lig_b"


# ============= EDGE CASE TESTS =============

class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_empty_pdbqt_file(self, temp_dir):
        """Test handling empty PDBQT file."""
        empty_file = os.path.join(temp_dir, "empty.pdbqt")
        with open(empty_file, 'w') as f:
            f.write("")

        result = validate_pdbqt(empty_file)
        assert result['atom_count'] == 0
        assert result['valid'] == False

    def test_coords_with_negative_values(self):
        """Test grid box with negative coordinates."""
        coords = [
            (-50.0, -30.0, -10.0),
            (-40.0, -20.0, 0.0),
            (-45.0, -25.0, -5.0)
        ]
        box = calculate_grid_box_from_coords(coords, padding=5.0)

        assert box.center_x == -45.0
        assert box.center_y == -25.0
        assert box.center_z == -5.0

    def test_single_atom_coords(self):
        """Test grid box with single atom."""
        coords = [(10.0, 20.0, 30.0)]
        box = calculate_grid_box_from_coords(coords, padding=10.0)

        # Center should be at atom position
        assert box.center_x == 10.0
        assert box.center_y == 20.0
        assert box.center_z == 30.0

        # Size should be 2 * padding
        assert box.size_x == 20.0


# ============= BATCH LIGAND PREPARATION TESTS =============

class TestBatchPrepareLigands:
    """Tests for batch_prepare_ligands parallel ligand conversion."""

    def test_smiles_input_parallel(self, monkeypatch, temp_dir):
        """SMILES strings are routed to smiles_to_pdbqt."""
        converted = []

        def mock_prepare(args):
            name, input_value, output_path, is_smiles = args
            converted.append({"name": name, "is_smiles": is_smiles})
            # Create the output file to simulate success
            Path(output_path).touch()
            return {"name": name, "path": output_path, "error": None}

        monkeypatch.setattr("autodock_utils._prepare_single_ligand", mock_prepare)

        smiles_list = ["CCO", "CC(=O)O", "c1ccccc1"]
        paths, failures = batch_prepare_ligands(
            smiles_list, output_dir=temp_dir, parallel=False
        )

        assert len(paths) == 3
        assert len(failures) == 0
        assert all(c["is_smiles"] for c in converted)

    def test_dict_input_smiles(self, monkeypatch, temp_dir):
        """Dict with 'smiles' key is routed correctly with custom name."""
        converted = []

        def mock_prepare(args):
            name, input_value, output_path, is_smiles = args
            converted.append({"name": name, "input": input_value, "is_smiles": is_smiles})
            Path(output_path).touch()
            return {"name": name, "path": output_path, "error": None}

        monkeypatch.setattr("autodock_utils._prepare_single_ligand", mock_prepare)

        inputs = [
            {"smiles": "CCO", "name": "ethanol"},
            {"smiles": "CC(=O)O", "name": "acetic_acid"},
        ]
        paths, failures = batch_prepare_ligands(
            inputs, output_dir=temp_dir, parallel=False
        )

        assert len(paths) == 2
        assert converted[0]["name"] == "ethanol"
        assert converted[0]["is_smiles"] is True
        assert converted[1]["name"] == "acetic_acid"

    def test_dict_input_file(self, monkeypatch, temp_dir):
        """Dict with 'file' key routes to prepare_ligand."""
        converted = []

        def mock_prepare(args):
            name, input_value, output_path, is_smiles = args
            converted.append({"name": name, "is_smiles": is_smiles})
            Path(output_path).touch()
            return {"name": name, "path": output_path, "error": None}

        monkeypatch.setattr("autodock_utils._prepare_single_ligand", mock_prepare)

        sdf_file = os.path.join(temp_dir, "mol.sdf")
        Path(sdf_file).touch()

        inputs = [{"file": sdf_file, "name": "my_mol"}]
        paths, failures = batch_prepare_ligands(
            inputs, output_dir=temp_dir, parallel=False
        )

        assert len(paths) == 1
        assert converted[0]["name"] == "my_mol"
        assert converted[0]["is_smiles"] is False

    def test_file_path_input(self, monkeypatch, temp_dir):
        """Existing file path string is detected as file, not SMILES."""
        converted = []

        def mock_prepare(args):
            name, input_value, output_path, is_smiles = args
            converted.append({"name": name, "is_smiles": is_smiles})
            Path(output_path).touch()
            return {"name": name, "path": output_path, "error": None}

        monkeypatch.setattr("autodock_utils._prepare_single_ligand", mock_prepare)

        sdf_file = os.path.join(temp_dir, "compound.sdf")
        Path(sdf_file).touch()

        paths, failures = batch_prepare_ligands(
            [sdf_file], output_dir=temp_dir, parallel=False
        )

        assert len(paths) == 1
        assert converted[0]["is_smiles"] is False
        assert converted[0]["name"] == "compound"

    def test_skips_existing_pdbqt(self, monkeypatch, temp_dir):
        """Already-converted PDBQT files are skipped (idempotent)."""
        call_count = [0]

        def mock_prepare(args):
            call_count[0] += 1
            name, input_value, output_path, is_smiles = args
            Path(output_path).touch()
            return {"name": name, "path": output_path, "error": None}

        monkeypatch.setattr("autodock_utils._prepare_single_ligand", mock_prepare)

        # Pre-create one output file
        existing = os.path.join(temp_dir, "ligand_00000.pdbqt")
        Path(existing).touch()

        paths, failures = batch_prepare_ligands(
            ["CCO", "CC(=O)O"], output_dir=temp_dir, parallel=False
        )

        # First SMILES already has its output; only second should be converted
        assert call_count[0] == 1
        assert len(paths) == 2

    def test_error_propagation(self, monkeypatch, temp_dir):
        """Failed conversions are collected in failures list, not raised."""
        def mock_prepare(args):
            name, input_value, output_path, is_smiles = args
            if "bad" in name:
                return {"name": name, "path": None, "error": "obabel crash"}
            Path(output_path).touch()
            return {"name": name, "path": output_path, "error": None}

        monkeypatch.setattr("autodock_utils._prepare_single_ligand", mock_prepare)

        inputs = [
            {"smiles": "CCO", "name": "good"},
            {"smiles": "INVALID", "name": "bad_mol"},
            {"smiles": "c1ccccc1", "name": "benzene"},
        ]
        paths, failures = batch_prepare_ligands(
            inputs, output_dir=temp_dir, parallel=False
        )

        assert len(paths) == 2
        assert len(failures) == 1
        assert failures[0]["name"] == "bad_mol"
        assert "obabel crash" in failures[0]["error"]

    def test_parallel_default(self):
        """Verify signature defaults: parallel=True, max_workers=None."""
        import inspect
        sig = inspect.signature(batch_prepare_ligands)
        assert sig.parameters['parallel'].default is True
        assert sig.parameters['max_workers'].default is None


# ============= GRID BOX SAFETY TESTS =============

class TestGridBoxSafety:
    """Tests for grid box guardrails and extract_reference_ligand."""

    def test_extract_reference_ligand_auto_detect(self, temp_dir):
        """Auto-detects the largest HETATM group as the ligand."""
        pdb_content = (
            "ATOM      1  N   ALA A   1      10.000  20.000  30.000  1.00  0.00\n"
            "ATOM      2  CA  ALA A   1      11.000  21.000  31.000  1.00  0.00\n"
            "HETATM    3  C1  LIG A 500      15.000  25.000  35.000  1.00  0.00\n"
            "HETATM    4  C2  LIG A 500      16.000  26.000  36.000  1.00  0.00\n"
            "HETATM    5  O1  LIG A 500      17.000  27.000  37.000  1.00  0.00\n"
            "HETATM    6  O   HOH A 600      50.000  50.000  50.000  1.00  0.00\n"
            "END\n"
        )
        pdb_file = os.path.join(temp_dir, "receptor.pdb")
        with open(pdb_file, 'w') as f:
            f.write(pdb_content)

        output = os.path.join(temp_dir, "ligand.pdb")
        result = extract_reference_ligand(pdb_file, output_file=output)

        assert os.path.exists(result)
        with open(result) as f:
            content = f.read()
        assert "LIG" in content
        assert "HOH" not in content
        assert "ALA" not in content
        # Should have 3 HETATM lines + END
        lines = [l for l in content.strip().split('\n') if l.startswith('HETATM')]
        assert len(lines) == 3

    def test_extract_reference_ligand_specific_resname(self, temp_dir):
        """Extracts a specific ligand by residue name."""
        pdb_content = (
            "HETATM    1  C1  LZ9 A 500      15.000  25.000  35.000  1.00  0.00\n"
            "HETATM    2  C2  LZ9 A 500      16.000  26.000  36.000  1.00  0.00\n"
            "HETATM    3  C1  ATP A 501      20.000  30.000  40.000  1.00  0.00\n"
            "HETATM    4  C2  ATP A 501      21.000  31.000  41.000  1.00  0.00\n"
            "HETATM    5  C3  ATP A 501      22.000  32.000  42.000  1.00  0.00\n"
            "END\n"
        )
        pdb_file = os.path.join(temp_dir, "receptor.pdb")
        with open(pdb_file, 'w') as f:
            f.write(pdb_content)

        result = extract_reference_ligand(pdb_file, ligand_resname="LZ9",
                                          output_file=os.path.join(temp_dir, "lig.pdb"))
        with open(result) as f:
            content = f.read()
        assert "LZ9" in content
        assert "ATP" not in content

    def test_extract_reference_ligand_no_ligand(self, temp_dir):
        """Raises ValueError when PDB has no ligand HETATMs."""
        pdb_content = (
            "ATOM      1  N   ALA A   1      10.000  20.000  30.000  1.00  0.00\n"
            "HETATM    2  O   HOH A 600      50.000  50.000  50.000  1.00  0.00\n"
            "END\n"
        )
        pdb_file = os.path.join(temp_dir, "no_ligand.pdb")
        with open(pdb_file, 'w') as f:
            f.write(pdb_content)

        with pytest.raises(ValueError, match="No ligand HETATM"):
            extract_reference_ligand(pdb_file)

    def test_extract_reference_ligand_wrong_resname(self, temp_dir):
        """Raises ValueError for non-existent residue name."""
        pdb_content = (
            "HETATM    1  C1  LIG A 500      15.000  25.000  35.000  1.00  0.00\n"
            "END\n"
        )
        pdb_file = os.path.join(temp_dir, "receptor.pdb")
        with open(pdb_file, 'w') as f:
            f.write(pdb_content)

        with pytest.raises(ValueError, match="not found"):
            extract_reference_ligand(pdb_file, ligand_resname="XYZ")

    def test_grid_box_from_ligand_rejects_receptor(self, temp_dir):
        """Raises ValueError when a full receptor is passed instead of a ligand."""
        # Create a file with >200 atoms (simulating a receptor)
        lines = []
        for i in range(300):
            lines.append(
                f"ATOM  {i+1:5d}  CA  ALA A{i+1:4d}    "
                f"{10.0+i*0.1:8.3f}{20.0+i*0.1:8.3f}{30.0+i*0.1:8.3f}  1.00  0.00\n"
            )
        lines.append("END\n")
        big_file = os.path.join(temp_dir, "receptor.pdb")
        with open(big_file, 'w') as f:
            f.writelines(lines)

        with pytest.raises(ValueError, match="looks like a receptor"):
            calculate_grid_box_from_ligand(big_file)

    def test_grid_box_from_ligand_accepts_small_ligand(self, temp_dir):
        """Accepts a proper small ligand file."""
        pdb_content = (
            "HETATM    1  C1  LIG A 500      15.000  25.000  35.000  1.00  0.00\n"
            "HETATM    2  C2  LIG A 500      16.000  26.000  36.000  1.00  0.00\n"
            "HETATM    3  O1  LIG A 500      17.000  27.000  37.000  1.00  0.00\n"
            "END\n"
        )
        lig_file = os.path.join(temp_dir, "ligand.pdb")
        with open(lig_file, 'w') as f:
            f.write(pdb_content)

        box = calculate_grid_box_from_ligand(lig_file, padding=5.0)
        # Ligand spans 2 Å in each dim + 10 Å padding = 12 Å
        assert box.size_x == pytest.approx(12.0, abs=0.1)
        assert box.size_y == pytest.approx(12.0, abs=0.1)
        assert box.size_z == pytest.approx(12.0, abs=0.1)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
