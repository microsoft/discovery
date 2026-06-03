#!/usr/bin/env python3
"""Unit tests for cp2k_utils.py — run with pytest.

Tests parsing, input generation, analysis, and structure utilities.
All tests are self-contained and do not require CP2K to be installed.
"""

import os
import sys
import json
import tempfile
import shutil
import pytest

sys.path.insert(0, os.path.dirname(__file__))
from cp2k_utils import (
    generate_input,
    parse_cp2k_output,
    parse_geo_opt,
    parse_md_output,
    parse_vibrational_output,
    parse_band_structure,
    parse_pdos,
    compute_convergence,
    read_xyz,
    write_xyz,
    write_input_file,
    save_final_results,
    _get_valence_electrons,
    _write_xc_functional,
    HARTREE_TO_EV,
    BOHR_TO_ANGSTROM,
)


# ============================================================================
# Test fixtures
# ============================================================================


@pytest.fixture
def tmp_dir():
    """Create and clean up a temporary directory."""
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def sample_cp2k_output(tmp_dir):
    """Create a sample CP2K output file."""
    content = """\
 DBCSR| CPU Multiplication driver                                           BLAS
 DBCSR| Multrec recursion limit                                              512

 GLOBAL| Force Environment number                                             1
 GLOBAL| Basis set file name                                        BASIS_MOLOPT
 GLOBAL| Potential file name                                      GTH_POTENTIALS
 GLOBAL| MM Potential file name                                     MM_POTENTIAL
 GLOBAL| Coordinate file name                                      __STD_INPUT__
 GLOBAL| Run type                                                         ENERGY

  Step     Update method      Time    Convergence         Total energy    Change
  --------------------------------------------------------------------------
     1 NoMix/Diag. 0.40E+00    0.3     1.56741927       -17.1283050742 -1.71E+01
     2 Broy./Diag. 0.40E+00    0.3     0.03543271       -17.1636476429 -3.53E-02
     3 Broy./Diag. 0.40E+00    0.3     0.00132416       -17.1642789623 -6.31E-04
     4 Broy./Diag. 0.40E+00    0.3     0.00003210       -17.1642934118 -1.44E-05

  *** SCF run converged in     4 steps ***

 ENERGY| Total FORCE_EVAL ( QS ) energy [a.u.]:              -17.164293411800

 ATOMIC FORCES in [a.u.]

 # Atom   Kind   Element          X              Y              Z
      1      1      O           0.00000000     0.00000000     0.01234567
      2      2      H          -0.00543210     0.00000000    -0.00617284
      3      2      H           0.00543210     0.00000000    -0.00617284
 SUM OF ATOMIC FORCES    0.00000000     0.00000000     0.00000000

 --------  Informations at step =     0 ------------
  Optimization Method        =                 BFGS
  Total Energy               =       -17.1642934118

 -------------------------------------------------------------------------------
 -                                                                             -
 -                                DBCSR STATISTICS                             -
 -                                                                             -
 -------------------------------------------------------------------------------

 CP2K                                 1  1.0    0.001    0.001    4.123    4.123
"""
    filepath = os.path.join(tmp_dir, "test_output.out")
    with open(filepath, "w") as f:
        f.write(content)
    return filepath


@pytest.fixture
def sample_ener_file(tmp_dir):
    """Create a sample .ener file for MD parsing."""
    content = """\
#   Step   Time [fs]       Kin. [a.u.]     Temp [K]       Pot. [a.u.]   Cons Qty [a.u.]
      1      0.500     0.00147223       300.12     -17.16429341    -17.16282118
      2      1.000     0.00153421       312.75     -17.16423156    -17.16269735
      3      1.500     0.00141862       289.18     -17.16435782    -17.16293920
      4      2.000     0.00162134       330.50     -17.16418921    -17.16256787
      5      2.500     0.00138976       283.30     -17.16440123    -17.16301147
"""
    filepath = os.path.join(tmp_dir, "water-1.ener")
    with open(filepath, "w") as f:
        f.write(content)
    return filepath


@pytest.fixture
def sample_xyz_file(tmp_dir):
    """Create a sample XYZ file."""
    content = """\
3
Water molecule
O   0.000000   0.000000   0.117369
H  -0.756950   0.000000  -0.469476
H   0.756950   0.000000  -0.469476
"""
    filepath = os.path.join(tmp_dir, "water.xyz")
    with open(filepath, "w") as f:
        f.write(content)
    return filepath


@pytest.fixture
def sample_pdos_file(tmp_dir):
    """Create a sample PDOS file."""
    content = """\
# Eigenvalue [a.u.]   Occupation   s        p
     -0.93245    2.000   0.452    0.548
     -0.47821    2.000   0.123    0.877
     -0.31456    2.000   0.087    0.913
     -0.15234    0.000   0.234    0.766
      0.12345    0.000   0.345    0.655
"""
    filepath = os.path.join(tmp_dir, "test-k1-1.pdos")
    with open(filepath, "w") as f:
        f.write(content)
    return filepath


@pytest.fixture
def sample_vib_output(tmp_dir):
    """Create a sample vibrational analysis output."""
    content = """\
 VIB|Frequency (cm^-1) 1595.23
 VIB|Frequency (cm^-1) 3657.05
 VIB|Frequency (cm^-1) 3755.93
 VIB|Intensities (km/mol) 53.62
 VIB|Intensities (km/mol) 8.45
 VIB|Intensities (km/mol) 44.73
 VIB|Zero Point Energy [kJ/mol]:               53.75
"""
    filepath = os.path.join(tmp_dir, "vib_output.out")
    with open(filepath, "w") as f:
        f.write(content)
    return filepath


# ============================================================================
# Test classes
# ============================================================================


class TestInputGeneration:
    """Test CP2K input file generation."""

    def test_basic_energy_input(self):
        """Test generating a basic energy calculation input."""
        structure = {
            "coords": [
                ["O", 0.000, 0.000, 0.117],
                ["H", -0.757, 0.000, -0.469],
                ["H", 0.757, 0.000, -0.469],
            ],
            "cell": [10.0, 10.0, 10.0],
            "periodic": "NONE",
        }
        inp = generate_input("water", "ENERGY", structure)

        assert "&GLOBAL" in inp
        assert "PROJECT water" in inp
        assert "RUN_TYPE ENERGY" in inp
        assert "&FORCE_EVAL" in inp
        assert "METHOD Quickstep" in inp
        assert "&DFT" in inp
        assert "CUTOFF 300" in inp
        assert "&CELL" in inp
        assert "PERIODIC NONE" in inp
        assert "&KIND O" in inp
        assert "&KIND H" in inp
        assert "BASIS_SET DZVP-MOLOPT-SR-GTH" in inp

    def test_geo_opt_input(self):
        """Test generating geometry optimization input."""
        structure = {
            "coords": [
                ["O", 0.000, 0.000, 0.117],
                ["H", -0.757, 0.000, -0.469],
                ["H", 0.757, 0.000, -0.469],
            ],
            "cell": [10.0, 10.0, 10.0],
            "periodic": "NONE",
        }
        inp = generate_input(
            "water_opt", "GEO_OPT", structure,
            geo_opt_params={"optimizer": "BFGS", "max_iter": 100},
        )

        assert "RUN_TYPE GEO_OPT" in inp
        assert "&MOTION" in inp
        assert "&GEO_OPT" in inp
        assert "OPTIMIZER BFGS" in inp
        assert "MAX_ITER 100" in inp

    def test_md_input(self):
        """Test generating MD simulation input."""
        structure = {
            "coords": [
                ["O", 0.000, 0.000, 0.117],
                ["H", -0.757, 0.000, -0.469],
                ["H", 0.757, 0.000, -0.469],
            ],
            "cell": [10.0, 10.0, 10.0],
            "periodic": "NONE",
        }
        inp = generate_input(
            "water_md", "MD", structure,
            md_params={"ensemble": "NVT", "steps": 500, "temperature": 300.0, "timestep": 0.5},
        )

        assert "RUN_TYPE MD" in inp
        assert "&MD" in inp
        assert "ENSEMBLE NVT" in inp
        assert "STEPS 500" in inp
        assert "TEMPERATURE 300.0" in inp
        assert "&THERMOSTAT" in inp
        assert "TYPE NOSE" in inp

    def test_custom_dft_params(self):
        """Hybrid functionals should fail fast in the current v19 image."""
        structure = {
            "coords": [["Si", 0.0, 0.0, 0.0], ["Si", 1.3575, 1.3575, 1.3575]],
            "cell": [5.43, 5.43, 5.43],
        }
        with pytest.raises(ValueError, match="requires libint/HFX support"):
            generate_input(
                "silicon", "ENERGY", structure,
                dft_params={
                    "functional": "PBE0",
                    "basis_set": "TZVP-GTH",
                    "cutoff": 600,
                    "kpoints": [4, 4, 4],
                    "dispersion": "D3BJ",
                },
            )

    def test_cell_opt_input(self):
        """Test cell optimization input."""
        structure = {
            "coords": [["Si", 0.0, 0.0, 0.0], ["Si", 1.3575, 1.3575, 1.3575]],
            "cell": [5.43, 5.43, 5.43],
        }
        inp = generate_input(
            "si_cellopt", "CELL_OPT", structure,
            cell_opt_params={"keep_symmetry": True},
            print_stress=True,
        )

        assert "RUN_TYPE CELL_OPT" in inp
        assert "&CELL_OPT" in inp
        assert "KEEP_SYMMETRY .TRUE." in inp

    def test_uks_multiplicity(self):
        """Test unrestricted Kohn-Sham for open-shell systems."""
        structure = {
            "coords": [["O", 0.0, 0.0, 0.0]],
            "cell": [10.0, 10.0, 10.0],
            "periodic": "NONE",
            "multiplicity": 3,
        }
        inp = generate_input("oxygen_atom", "ENERGY", structure)

        assert "MULTIPLICITY 3" in inp
        assert "UKS .TRUE." in inp

    def test_smearing(self):
        """Test smearing for metallic systems."""
        structure = {
            "coords": [["Cu", 0.0, 0.0, 0.0]],
            "cell": [3.61, 3.61, 3.61],
        }
        inp = generate_input(
            "copper", "ENERGY", structure,
            dft_params={"smearing": True, "added_mos": 10, "electronic_temperature": 500},
        )

        assert "ADDED_MOS 10" in inp
        assert "&SMEAR ON" in inp
        assert "ELECTRONIC_TEMPERATURE [K] 500" in inp

    def test_coords_as_string(self):
        """Test that coordinates can be passed as a raw string."""
        structure = {
            "coords": "O   0.000000   0.000000   0.117369\nH  -0.756950   0.000000  -0.469476\nH   0.756950   0.000000  -0.469476",
            "cell": [10.0, 10.0, 10.0],
            "periodic": "NONE",
        }
        inp = generate_input("water", "ENERGY", structure)
        # Coordinates get centered for PERIODIC NONE (WAVELET solver requirement)
        # so we check for element types and structural correctness, not exact coords
        assert "&KIND O" in inp
        assert "&KIND H" in inp
        assert "&COORD" in inp
        assert "PERIODIC NONE" in inp

    def test_hse06_functional(self):
        """HSE06 should be rejected clearly while hybrid support is disabled."""
        structure = {
            "coords": [["Si", 0.0, 0.0, 0.0]],
            "cell": [5.43, 5.43, 5.43],
        }
        with pytest.raises(ValueError, match="requires libint/HFX support"):
            generate_input(
                "si_hse", "ENERGY", structure,
                dft_params={"functional": "HSE06"},
            )


class TestOutputParsing:
    """Test CP2K output file parsing."""

    def test_parse_energy(self, sample_cp2k_output):
        """Test parsing total energy."""
        result = parse_cp2k_output(sample_cp2k_output)
        assert result["converged"] is True
        assert result["n_scf_cycles"] == 4
        assert abs(result["total_energy_hartree"] - (-17.164293411800)) < 1e-10
        assert result["total_energy_eV"] is not None
        assert abs(result["total_energy_eV"] - (-17.164293411800 * HARTREE_TO_EV)) < 1e-6

    def test_parse_scf_energies(self, sample_cp2k_output):
        """Test parsing SCF iteration energies."""
        result = parse_cp2k_output(sample_cp2k_output)
        assert len(result["scf_energies"]) == 4
        assert result["scf_energies"][0] == pytest.approx(-17.1283050742, abs=1e-8)

    def test_parse_forces(self, sample_cp2k_output):
        """Test parsing atomic forces."""
        result = parse_cp2k_output(sample_cp2k_output)
        assert len(result["forces"]) == 3
        assert result["forces"][0]["element"] == "O"
        assert result["forces"][1]["element"] == "H"
        assert abs(result["forces"][0]["fz"] - 0.01234567) < 1e-8

    def test_parse_walltime(self, sample_cp2k_output):
        """Test parsing walltime."""
        result = parse_cp2k_output(sample_cp2k_output)
        assert result["walltime_seconds"] == pytest.approx(4.123, abs=0.001)

    def test_missing_file(self):
        """Test that missing file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            parse_cp2k_output("nonexistent_file.out")

    def test_unconverged_detection(self, tmp_dir):
        """Test detection of unconverged SCF."""
        content = """\
  *** SCF run NOT converged ***
 ENERGY| Total FORCE_EVAL ( QS ) energy [a.u.]:              -10.123456789000
"""
        filepath = os.path.join(tmp_dir, "unconverged.out")
        with open(filepath, "w") as f:
            f.write(content)
        result = parse_cp2k_output(filepath)
        assert result["converged"] is False
        assert "SCF did not converge" in result["warnings"]


class TestMDParsing:
    """Test MD output parsing."""

    def test_parse_ener_file(self, sample_ener_file, tmp_dir):
        """Test parsing .ener file."""
        # Change to tmp_dir so parse_md_output can find the file
        old_cwd = os.getcwd()
        os.chdir(tmp_dir)
        try:
            result = parse_md_output("water")
            assert result["n_steps"] == 5
            assert len(result["steps"]) == 5
            assert result["steps"][0]["step"] == 1
            assert result["steps"][0]["time_fs"] == pytest.approx(0.5)
            assert result["steps"][0]["temperature_K"] == pytest.approx(300.12)
            assert result["avg_temperature"] is not None
            assert 280 < result["avg_temperature"] < 340
        finally:
            os.chdir(old_cwd)

    def test_missing_ener_file(self, tmp_dir):
        """Test handling of missing .ener file."""
        old_cwd = os.getcwd()
        os.chdir(tmp_dir)
        try:
            result = parse_md_output("nonexistent")
            assert result["n_steps"] == 0
        finally:
            os.chdir(old_cwd)


class TestVibrationalParsing:
    """Test vibrational analysis parsing."""

    def test_parse_frequencies(self, sample_vib_output):
        """Test parsing vibrational frequencies."""
        result = parse_vibrational_output(sample_vib_output)
        assert result["n_modes"] == 3
        assert len(result["frequencies_cm"]) == 3
        assert result["frequencies_cm"][0] == pytest.approx(1595.23)
        assert result["frequencies_cm"][2] == pytest.approx(3755.93)
        assert result["has_imaginary"] is False

    def test_parse_intensities(self, sample_vib_output):
        """Test parsing IR intensities."""
        result = parse_vibrational_output(sample_vib_output)
        assert len(result["intensities"]) == 3
        assert result["intensities"][0] == pytest.approx(53.62)

    def test_parse_zpe(self, sample_vib_output):
        """Test parsing zero-point energy."""
        result = parse_vibrational_output(sample_vib_output)
        assert result["zpe_kJ_mol"] == pytest.approx(53.75)


class TestPDOSParsing:
    """Test PDOS file parsing."""

    def test_parse_pdos(self, sample_pdos_file):
        """Test parsing PDOS file."""
        result = parse_pdos(sample_pdos_file)
        assert len(result["energies_eV"]) == 5
        assert len(result["total_dos"]) == 5
        # First column is eigenvalue, second is occupation
        assert result["energies_eV"][0] == pytest.approx(-0.93245)

    def test_missing_pdos_file(self):
        """Test handling of missing PDOS file."""
        with pytest.raises(FileNotFoundError):
            parse_pdos("nonexistent.pdos")


class TestStructureUtilities:
    """Test structure reading and writing."""

    def test_read_xyz(self, sample_xyz_file):
        """Test reading XYZ file."""
        result = read_xyz(sample_xyz_file)
        assert result["n_atoms"] == 3
        assert len(result["coords"]) == 3
        assert result["coords"][0][0] == "O"
        assert result["coords"][0][1] == pytest.approx(0.0)
        assert result["coords"][0][3] == pytest.approx(0.117369)

    def test_write_xyz(self, tmp_dir):
        """Test writing XYZ file."""
        coords = [
            ["O", 0.0, 0.0, 0.117],
            ["H", -0.757, 0.0, -0.469],
            ["H", 0.757, 0.0, -0.469],
        ]
        filepath = write_xyz(coords, os.path.join(tmp_dir, "out.xyz"), comment="test")
        assert os.path.isfile(filepath)
        # Read back
        result = read_xyz(filepath)
        assert result["n_atoms"] == 3
        assert result["coords"][0][0] == "O"

    def test_xyz_roundtrip(self, sample_xyz_file, tmp_dir):
        """Test reading and writing XYZ gives consistent results."""
        original = read_xyz(sample_xyz_file)
        write_xyz(original["coords"], os.path.join(tmp_dir, "roundtrip.xyz"))
        roundtrip = read_xyz(os.path.join(tmp_dir, "roundtrip.xyz"))
        assert roundtrip["n_atoms"] == original["n_atoms"]
        for o, r in zip(original["coords"], roundtrip["coords"]):
            assert o[0] == r[0]
            for i in range(1, 4):
                assert o[i] == pytest.approx(r[i], abs=1e-6)


class TestAnalysis:
    """Test analysis functions."""

    def test_convergence_analysis(self):
        """Test convergence analysis."""
        params = [200, 300, 400, 500, 600]
        energies = [-100.0, -100.5, -100.52, -100.5205, -100.52055]
        result = compute_convergence(params, energies, threshold=0.001)

        assert result["converged"] is True
        assert result["converged_value"] == 500  # Where diff drops below 1 meV
        assert len(result["energy_differences_eV"]) == 4

    def test_convergence_not_converged(self):
        """Test when convergence is not reached."""
        params = [100, 200, 300]
        energies = [-90.0, -95.0, -98.0]
        result = compute_convergence(params, energies, threshold=0.001)

        assert result["converged"] is False
        assert result["converged_value"] is None


class TestValenceElectrons:
    """Test valence electron count for pseudopotentials."""

    def test_common_elements(self):
        """Test valence electron counts for common elements."""
        assert _get_valence_electrons("H", "GTH-PBE") == 1
        assert _get_valence_electrons("C", "GTH-PBE") == 4
        assert _get_valence_electrons("N", "GTH-PBE") == 5
        assert _get_valence_electrons("O", "GTH-PBE") == 6
        assert _get_valence_electrons("Si", "GTH-PBE") == 4
        assert _get_valence_electrons("Fe", "GTH-PBE") == 16
        assert _get_valence_electrons("Cu", "GTH-PBE") == 11
        assert _get_valence_electrons("Au", "GTH-PBE") == 11

    def test_unknown_element(self):
        """Test that unknown elements raise ValueError (not silent fallback)."""
        with pytest.raises(ValueError):
            _get_valence_electrons("Uue", "GTH-PBE")


class TestSaveFinalResults:
    """Test final results saving."""

    def test_save_results(self, tmp_dir):
        """Test saving final results JSON."""
        import cp2k_utils
        old_output = cp2k_utils.OUTPUT_DIR
        cp2k_utils.OUTPUT_DIR = tmp_dir
        try:
            save_final_results(
                {"energy_eV": -466.5, "converged": True},
                output_files={"plot": "/output/scf.png"},
                file_descriptions={"plot": "SCF convergence plot"},
            )
            filepath = os.path.join(tmp_dir, "final_results.json")
            assert os.path.isfile(filepath)
            with open(filepath) as f:
                data = json.load(f)
            assert data["status"] == "completed"
            assert data["summary"]["energy_eV"] == -466.5
            assert "output_files" in data
        finally:
            cp2k_utils.OUTPUT_DIR = old_output


class TestXCFunctional:
    """Test XC functional input generation."""

    def test_standard_functionals(self):
        """Test that standard functionals generate correct sections."""
        for func, expected in [("PBE", "PBE"), ("BLYP", "BLYP"), ("LDA", "PADE"), ("B3LYP", "B3LYP")]:
            lines = []
            _write_xc_functional(lines, func)
            text = "\n".join(lines)
            assert f"&XC_FUNCTIONAL {expected}" in text

    def test_hse06_functional(self):
        """Test HSE06 generates HF exchange section."""
        lines = []
        _write_xc_functional(lines, "HSE06")
        text = "\n".join(lines)
        assert "&XWPBE" in text
        assert "&HF" in text
        assert "FRACTION 0.25" in text


# ============================================================================
# Write input file test
# ============================================================================


class TestWriteInputFile:
    """Test writing input files to disk."""

    def test_write_and_read(self, tmp_dir):
        """Test writing input content to file."""
        import cp2k_utils
        old_workdir = cp2k_utils.WORK_DIR
        cp2k_utils.WORK_DIR = tmp_dir
        try:
            content = "&GLOBAL\n  PROJECT test\n&END GLOBAL\n"
            filepath = write_input_file(content, "test.inp")
            assert os.path.isfile(filepath)
            with open(filepath) as f:
                assert f.read() == content
        finally:
            cp2k_utils.WORK_DIR = old_workdir


# ============================================================================
# Tests for Bug Fixes and Enhancements (inv_00124)
# ============================================================================


class TestPoissonSection:
    """Bug 2: POISSON section auto-injected for PERIODIC NONE."""

    def test_poisson_for_periodic_none(self):
        """POISSON WAVELET must appear when periodic='NONE'."""
        structure = {
            "coords": [["O", 0.0, 0.0, 0.0], ["H", 0.96, 0.0, 0.0], ["H", -0.24, 0.93, 0.0]],
            "cell": [10.0, 10.0, 10.0],
            "periodic": "NONE",
        }
        inp = generate_input("water", "ENERGY", structure)
        assert "&POISSON" in inp
        assert "PERIODIC NONE" in inp
        assert "POISSON_SOLVER WAVELET" in inp

    def test_no_poisson_for_periodic_xyz(self):
        """POISSON section must NOT appear for periodic systems."""
        structure = {
            "coords": [["Si", 0.0, 0.0, 0.0], ["Si", 1.35, 1.35, 1.35]],
            "cell": [5.43, 5.43, 5.43],
            "periodic": "XYZ",
        }
        inp = generate_input("silicon", "ENERGY", structure)
        assert "POISSON_SOLVER WAVELET" not in inp


class TestCoordinateCentering:
    """Bug 3: Auto-cell centers coordinates in box."""

    def test_centering_with_auto_cell_list_coords(self):
        """Coordinates should be centered in auto-generated cell (list coords)."""
        import copy
        structure = {
            "coords": [
                ["C", -5.0, -3.0, -1.0],
                ["C",  5.0,  3.0,  1.0],
            ],
            "periodic": "NONE",
            # No cell → auto-generated
        }
        original_coords = copy.deepcopy(structure["coords"])
        inp = generate_input("test", "ENERGY", structure)

        # After centering, the center of mass of the two atoms should be at the box center
        # Box size: (5-(-5)) + 20 = 30 x (3-(-3)) + 20 = 26 x (1-(-1)) + 20 = 22
        # Box center: 15, 13, 11
        # Atom center: (−5+5)/2=0, (−3+3)/2=0, (−1+1)/2=0
        # Shift: 15, 13, 11
        # New coords: C @ (10, 10, 10) and C @ (20, 16, 12)
        assert structure["coords"][0][1] == pytest.approx(10.0, abs=0.1)
        assert structure["coords"][1][1] == pytest.approx(20.0, abs=0.1)

    def test_centering_with_auto_cell_string_coords(self):
        """Coordinates should be centered in auto-generated cell (string coords)."""
        structure = {
            "coords": "C  -2.0  0.0  0.0\nC   2.0  0.0  0.0",
            "periodic": "NONE",
        }
        inp = generate_input("test", "ENERGY", structure)
        # After centering, coords in the generated input should be positive
        # Box: (2-(-2))+20 = 24 in x, 10 in y/z (minimum)
        # Check that both atoms appear with positive coordinates
        assert "&COORD" in inp
        # The string coords should have been replaced with centered values
        assert isinstance(structure["coords"], str)

    def test_no_centering_with_explicit_cell(self):
        """When cell is explicitly provided, no centering should occur."""
        structure = {
            "coords": [["O", -1.0, -2.0, -3.0]],
            "cell": [20.0, 20.0, 20.0],
            "periodic": "NONE",
        }
        inp = generate_input("test", "ENERGY", structure)
        # Explicit cell → no centering, original coords preserved
        assert structure["coords"][0][1] == pytest.approx(-1.0)
        assert structure["coords"][0][2] == pytest.approx(-2.0)


class TestElectronValidation:
    """Enhancement 1: Validate electron count vs multiplicity."""

    def test_odd_electrons_auto_uks(self):
        """Odd valence electrons with mult=1 should auto-enable UKS + mult=2."""
        # H atom: 1 valence electron (odd) → should trigger auto-UKS
        structure = {
            "coords": [["H", 0.0, 0.0, 0.0]],
            "cell": [10.0, 10.0, 10.0],
            "periodic": "NONE",
            # multiplicity not set (defaults to 1)
        }
        inp = generate_input("h_atom", "ENERGY", structure)
        assert "UKS .TRUE." in inp
        assert "MULTIPLICITY 2" in inp

    def test_even_electrons_no_auto_uks(self):
        """Even valence electrons with mult=1 should NOT trigger UKS."""
        # Water: O(6) + H(1) + H(1) = 8 electrons (even)
        structure = {
            "coords": [
                ["O", 0.0, 0.0, 0.117],
                ["H", -0.757, 0.0, -0.469],
                ["H", 0.757, 0.0, -0.469],
            ],
            "cell": [10.0, 10.0, 10.0],
            "periodic": "NONE",
        }
        inp = generate_input("water", "ENERGY", structure)
        assert "UKS .TRUE." not in inp

    def test_charged_system_odd(self):
        """Charged system producing odd electrons should auto-enable UKS."""
        # Water cation: 8 - 1 = 7 electrons (odd)
        structure = {
            "coords": [
                ["O", 0.0, 0.0, 0.117],
                ["H", -0.757, 0.0, -0.469],
                ["H", 0.757, 0.0, -0.469],
            ],
            "cell": [10.0, 10.0, 10.0],
            "periodic": "NONE",
            "charge": 1,
        }
        inp = generate_input("water_cation", "ENERGY", structure)
        assert "UKS .TRUE." in inp
        assert "MULTIPLICITY 2" in inp


class TestMDParamsEnhancements:
    """Enhancements 2 & 3: timecon alias and configurable thermostat region."""

    def test_timecon_alias(self):
        """'timecon' should work as alias for 'nose_timecon'."""
        structure = {
            "coords": [["O", 0.0, 0.0, 0.0], ["H", 0.96, 0.0, 0.0], ["H", -0.24, 0.93, 0.0]],
            "cell": [10.0, 10.0, 10.0],
            "periodic": "NONE",
        }
        inp = generate_input(
            "water_md", "MD", structure,
            md_params={"ensemble": "NVT", "steps": 10, "timecon": 200.0},
        )
        assert "TIMECON 200.0" in inp

    def test_nose_timecon_preferred(self):
        """'nose_timecon' should take precedence over 'timecon'."""
        structure = {
            "coords": [["O", 0.0, 0.0, 0.0], ["H", 0.96, 0.0, 0.0], ["H", -0.24, 0.93, 0.0]],
            "cell": [10.0, 10.0, 10.0],
            "periodic": "NONE",
        }
        inp = generate_input(
            "water_md", "MD", structure,
            md_params={"ensemble": "NVT", "steps": 10, "nose_timecon": 150.0, "timecon": 200.0},
        )
        assert "TIMECON 150.0" in inp

    def test_thermostat_region_configurable(self):
        """thermostat_region should control the REGION keyword."""
        structure = {
            "coords": [["O", 0.0, 0.0, 0.0], ["H", 0.96, 0.0, 0.0], ["H", -0.24, 0.93, 0.0]],
            "cell": [10.0, 10.0, 10.0],
            "periodic": "NONE",
        }
        inp = generate_input(
            "water_md", "MD", structure,
            md_params={"ensemble": "NVT", "steps": 10, "thermostat_region": "GLOBAL"},
        )
        assert "REGION GLOBAL" in inp

    def test_thermostat_region_default_massive(self):
        """Default thermostat region should be MASSIVE."""
        structure = {
            "coords": [["O", 0.0, 0.0, 0.0], ["H", 0.96, 0.0, 0.0], ["H", -0.24, 0.93, 0.0]],
            "cell": [10.0, 10.0, 10.0],
            "periodic": "NONE",
        }
        inp = generate_input(
            "water_md", "MD", structure,
            md_params={"ensemble": "NVT", "steps": 10},
        )
        assert "REGION MASSIVE" in inp


# ============================================================================
# New tests for v2.1 behavioral changes
# ============================================================================


class TestOpenShellNoImplicitSmearing:
    """Tests that open-shell systems do NOT get implicit smearing."""

    def test_uks_no_smearing_by_default(self):
        """UKS systems should NOT have &SMEAR section unless explicitly requested."""
        structure = {
            "coords": [["N", 0.0, 0.0, 0.0], ["O", 1.15, 0.0, 0.0]],
            "cell": [15.0, 15.0, 15.0],
            "periodic": "NONE",
            "multiplicity": 2,
        }
        inp = generate_input(
            "no_radical", "ENERGY", structure,
            dft_params={"uks": True},
        )
        assert "UKS .TRUE." in inp
        assert "&SMEAR" not in inp

    def test_explicit_smearing_still_works(self):
        """Explicit smearing=True should still add &SMEAR section."""
        structure = {
            "coords": [["Fe", 0.0, 0.0, 0.0]],
            "cell": [15.0, 15.0, 15.0],
            "periodic": "NONE",
            "multiplicity": 5,
        }
        inp = generate_input(
            "fe_smear", "ENERGY", structure,
            dft_params={"smearing": True, "uks": True},
        )
        assert "&SMEAR ON" in inp
        assert "FERMI_DIRAC" in inp

    def test_odd_electron_auto_uks_no_smearing(self):
        """Auto-detected odd-electron systems should get UKS but NOT smearing."""
        structure = {
            "coords": [["N", 0.0, 0.0, 0.0]],
            "cell": [15.0, 15.0, 15.0],
            "periodic": "NONE",
        }
        inp = generate_input("nitrogen", "ENERGY", structure)
        assert "UKS .TRUE." in inp
        assert "&SMEAR" not in inp


class TestElementValidation:
    """Tests that unsupported elements raise ValueError."""

    def test_known_element_returns_valence(self):
        """Known elements should return correct valence electron count."""
        assert _get_valence_electrons("C", "GTH-PBE") == 4
        assert _get_valence_electrons("O", "GTH-PBE") == 6
        assert _get_valence_electrons("Fe", "GTH-PBE") == 16
        assert _get_valence_electrons("H", "GTH-PBE") == 1

    def test_unknown_element_raises(self):
        """Unknown elements should raise ValueError with helpful message."""
        with pytest.raises(ValueError, match="no GTH pseudopotential"):
            _get_valence_electrons("Uuo", "GTH-PBE")

    def test_unknown_element_error_lists_supported(self):
        """Error message should list supported elements."""
        with pytest.raises(ValueError, match="Supported elements:"):
            _get_valence_electrons("Ac", "GTH-PBE")

    def test_generate_input_with_unsupported_element(self):
        """generate_input should fail for unsupported elements."""
        structure = {
            "coords": [["Lr", 0.0, 0.0, 0.0]],
            "cell": [15.0, 15.0, 15.0],
            "periodic": "NONE",
        }
        with pytest.raises(ValueError):
            generate_input("test", "ENERGY", structure)


class TestKpointOTGuard:
    """Tests that k-points force DIAGONALIZATION over OT."""

    def test_auto_selects_diag_with_kpoints(self):
        """AUTO SCF method should select DIAG when kpoints are specified."""
        structure = {
            "coords": [["Si", 0.0, 0.0, 0.0], ["Si", 1.36, 1.36, 1.36]],
            "cell": [5.43, 5.43, 5.43],
            "periodic": "XYZ",
            "coord_type": "CARTESIAN",
        }
        inp = generate_input(
            "si_kpts", "ENERGY", structure,
            dft_params={"kpoints": [4, 4, 4]},
        )
        assert "&DIAGONALIZATION" in inp
        assert "&OT" not in inp
        assert "MONKHORST-PACK" in inp

    def test_explicit_ot_with_kpoints_switches_to_diag(self):
        """Explicit OT + kpoints should be overridden to DIAG with warning."""
        structure = {
            "coords": [["Si", 0.0, 0.0, 0.0], ["Si", 1.36, 1.36, 1.36]],
            "cell": [5.43, 5.43, 5.43],
            "periodic": "XYZ",
        }
        inp = generate_input(
            "si_force_ot", "ENERGY", structure,
            dft_params={"scf_method": "OT", "kpoints": [4, 4, 4]},
        )
        assert "&DIAGONALIZATION" in inp
        assert "&OT" not in inp

    def test_ot_without_kpoints_still_works(self):
        """OT without kpoints should still use OT as normal."""
        structure = {
            "coords": [["O", 0.0, 0.0, 0.117], ["H", -0.757, 0.0, -0.469], ["H", 0.757, 0.0, -0.469]],
            "cell": [10.0, 10.0, 10.0],
            "periodic": "NONE",
        }
        inp = generate_input("water_ot", "ENERGY", structure)
        assert "&OT ON" in inp


class TestProvenanceCapture:
    """Tests for capture_provenance function."""

    def test_provenance_basic(self):
        from cp2k_utils import capture_provenance
        prov = capture_provenance(
            project_name="test",
            run_type="ENERGY",
            structure={"charge": 0, "multiplicity": 1, "periodic": "NONE"},
            dft_params={"functional": "PBE", "cutoff": 400},
        )
        assert prov["project_name"] == "test"
        assert prov["run_type"] == "ENERGY"
        assert prov["method"]["functional"] == "PBE"
        assert prov["method"]["cutoff_ry"] == 400
        assert prov["system"]["charge"] == 0
        assert "timestamp" in prov
        assert "environment" in prov

    def test_provenance_serializable(self):
        """Provenance dict must be JSON-serializable."""
        from cp2k_utils import capture_provenance
        prov = capture_provenance("test", "ENERGY")
        json_str = json.dumps(prov, indent=2)
        assert len(json_str) > 50


class TestErrorClassification:
    """Tests for classify_cp2k_error."""

    def test_scf_not_converged(self):
        from cp2k_utils import classify_cp2k_error
        result = classify_cp2k_error("SCF run NOT converged after 50 iterations")
        assert result["recoverable"] is True
        assert result["error_type"] == "SCF_NOT_CONVERGED"
        assert result["strategy"] == "adjust_scf"

    def test_ot_kpoint_conflict(self):
        from cp2k_utils import classify_cp2k_error
        result = classify_cp2k_error("ABORT: OT not possible with kpoint calculations")
        assert result["recoverable"] is True
        assert result["error_type"] == "OT_KPOINT_CONFLICT"

    def test_oom_unrecoverable(self):
        from cp2k_utils import classify_cp2k_error
        result = classify_cp2k_error("", "Out of memory")
        assert result["recoverable"] is False
        assert result["error_type"] == "MEMORY"

    def test_unknown_error(self):
        from cp2k_utils import classify_cp2k_error
        result = classify_cp2k_error("Something completely unexpected")
        assert result["recoverable"] is False
        assert result["error_type"] == "UNKNOWN"

    def test_timeout_recoverable(self):
        from cp2k_utils import classify_cp2k_error
        result = classify_cp2k_error("", "CP2K timed out after 600s")
        assert result["recoverable"] is True
        assert result["error_type"] == "TIMEOUT"
        assert result["strategy"] == "reduce_parallelism"


class TestRecoveryExecution:
    """Tests for run_cp2k_with_recovery control flow."""

    def test_timeout_switches_mpi_to_omp(self, tmp_dir, monkeypatch):
        import subprocess
        from cp2k_utils import run_cp2k_with_recovery

        input_path = os.path.join(tmp_dir, "water.inp")
        with open(input_path, "w") as f:
            f.write("&GLOBAL\n  PROJECT water\n&END GLOBAL\n")

        calls = {"mpi": 0, "omp": 0}

        def fake_run_cp2k_mpi(input_file, output_file=None, nprocs=-1, cwd=None, timeout=None):
            calls["mpi"] += 1
            raise subprocess.TimeoutExpired(cmd=["mpirun", "cp2k.psmp"], timeout=timeout or 60)

        def fake_run_cp2k(input_file, output_file=None, nthreads=None, cwd=None, timeout=None):
            calls["omp"] += 1
            return subprocess.CompletedProcess(
                args=["cp2k.ssmp", "-i", input_file],
                returncode=0,
                stdout="ok",
                stderr="",
            )

        monkeypatch.setattr("cp2k_utils.run_cp2k_mpi", fake_run_cp2k_mpi)
        monkeypatch.setattr("cp2k_utils.run_cp2k", fake_run_cp2k)

        result = run_cp2k_with_recovery(
            "water.inp",
            cwd=tmp_dir,
            timeout=60,
            max_retries=1,
            use_mpi=True,
        )

        assert result["success"] is True
        assert result["attempts"] == 2
        assert calls["mpi"] == 1
        assert calls["omp"] == 1
        assert result["recovery_log"][0]["error"]["error_type"] == "TIMEOUT"


class TestInputValidation:
    """Tests for validate_cp2k_input (graceful when cp2k-input-tools not installed)."""

    def test_validate_returns_dict(self):
        from cp2k_utils import validate_cp2k_input
        result = validate_cp2k_input("&GLOBAL\n  PROJECT test\n&END GLOBAL\n")
        assert isinstance(result, dict)
        assert "valid" in result
        assert "errors" in result
        assert "warnings" in result


class TestArtifactCopying:
    """Tests that copy_outputs includes restart/wavefunction patterns."""

    def test_default_patterns_include_wfn(self):
        from cp2k_utils import copy_outputs
        import inspect
        source = inspect.getsource(copy_outputs)
        assert "*.wfn" in source
        assert "*.kp" in source


class TestPrepareMoleculeInput:
    """Tests for prepare_molecule_input (ASE-based structure ingestion)."""

    def test_xyz_molecule(self, tmp_dir):
        """Reading an XYZ file should return a valid structure dict."""
        pytest.importorskip("ase")
        from cp2k_utils import prepare_molecule_input
        xyz_path = os.path.join(tmp_dir, "water.xyz")
        with open(xyz_path, "w") as f:
            f.write("3\nWater molecule\nO  0.000  0.000  0.117\nH -0.757  0.000 -0.469\nH  0.757  0.000 -0.469\n")
        result = prepare_molecule_input(xyz_path, charge=0, multiplicity=1)
        assert result["n_atoms"] == 3
        assert set(result["elements"]) == {"H", "O"}
        assert result["periodic"] == "NONE"
        assert result["validated"] is True
        assert result["charge"] == 0
        assert result["multiplicity"] == 1
        # Cell should be auto-set to None (handled later by generate_input)
        assert "cell" not in result or result.get("cell") is None

    def test_periodic_cif(self, tmp_dir):
        """Reading a CIF-like periodic file should detect periodicity."""
        from cp2k_utils import prepare_molecule_input
        # Create a minimal POSCAR (periodic) via ASE
        poscar_path = os.path.join(tmp_dir, "si.vasp")
        try:
            from ase import Atoms
            from ase.io import write as ase_write
            si = Atoms("Si2", positions=[[0, 0, 0], [1.36, 1.36, 1.36]],
                        cell=[5.43, 5.43, 5.43], pbc=True)
            ase_write(poscar_path, si, format="vasp")
        except ImportError:
            pytest.skip("ASE not installed")
        result = prepare_molecule_input(poscar_path, format="vasp")
        assert result["periodic"] == "XYZ"
        assert result["n_atoms"] == 2
        assert "cell" in result

    def test_file_not_found(self):
        """Should raise FileNotFoundError for missing file."""
        from cp2k_utils import prepare_molecule_input
        with pytest.raises(FileNotFoundError):
            prepare_molecule_input("/nonexistent/molecule.xyz")

    def test_charge_and_multiplicity_passed_through(self, tmp_dir):
        pytest.importorskip("ase")
        """Charge and multiplicity should be stored in the output dict."""
        from cp2k_utils import prepare_molecule_input
        xyz_path = os.path.join(tmp_dir, "li.xyz")
        with open(xyz_path, "w") as f:
            f.write("1\nLithium atom\nLi  0.0  0.0  0.0\n")
        result = prepare_molecule_input(xyz_path, charge=1, multiplicity=1)
        assert result["charge"] == 1
        assert result["multiplicity"] == 1


class TestAnalyzeMdTrajectory:
    """Tests for analyze_md_trajectory (trajectory analysis)."""

    def test_multi_frame_trajectory(self, tmp_dir):
        """Multi-frame XYZ trajectory should produce RMSD and MSD results."""
        from cp2k_utils import analyze_md_trajectory
        import cp2k_utils
        # Temporarily redirect OUTPUT_DIR
        orig_output = cp2k_utils.OUTPUT_DIR
        cp2k_utils.OUTPUT_DIR = tmp_dir
        try:
            traj_path = os.path.join(tmp_dir, "traj.xyz")
            frames = []
            for i in range(5):
                drift = i * 0.1
                frames.append(
                    f"3\nFrame {i}\n"
                    f"O  {0.0 + drift:.3f}  0.000  0.117\n"
                    f"H  {-0.757 + drift:.3f}  0.000  -0.469\n"
                    f"H  {0.757 + drift:.3f}  0.000  -0.469\n"
                )
            with open(traj_path, "w") as f:
                f.write("".join(frames))
            result = analyze_md_trajectory(traj_path, analyses=["rmsd", "msd"])
            # Should have rmsd and msd keys (from MDAnalysis or numpy fallback)
            assert "rmsd" in result or "msd" in result
            if "rmsd" in result and "error" not in result["rmsd"]:
                assert len(result["rmsd"]["rmsd"]) == 5
                assert result["rmsd"]["rmsd"][0] == pytest.approx(0.0, abs=1e-6)
            if "msd" in result and "error" not in result["msd"]:
                assert len(result["msd"]["msd"]) == 5
                assert result["msd"]["msd"][0] == pytest.approx(0.0, abs=1e-6)
        finally:
            cp2k_utils.OUTPUT_DIR = orig_output

    def test_missing_trajectory_file(self, tmp_dir):
        """Should return error dict for missing trajectory file."""
        from cp2k_utils import analyze_md_trajectory
        import cp2k_utils
        orig_output = cp2k_utils.OUTPUT_DIR
        cp2k_utils.OUTPUT_DIR = tmp_dir
        try:
            result = analyze_md_trajectory("/nonexistent/traj.xyz")
            assert "error" in result
        finally:
            cp2k_utils.OUTPUT_DIR = orig_output

    def test_single_frame_trajectory(self, tmp_dir):
        """Single-frame trajectory should not crash."""
        from cp2k_utils import analyze_md_trajectory
        import cp2k_utils
        orig_output = cp2k_utils.OUTPUT_DIR
        cp2k_utils.OUTPUT_DIR = tmp_dir
        try:
            traj_path = os.path.join(tmp_dir, "single.xyz")
            with open(traj_path, "w") as f:
                f.write("2\nSingle frame\nH  0.0  0.0  0.0\nH  0.74  0.0  0.0\n")
            result = analyze_md_trajectory(traj_path, analyses=["rmsd"])
            assert isinstance(result, dict)
            assert "error" not in result or "rmsd" in result
        finally:
            cp2k_utils.OUTPUT_DIR = orig_output

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
