#!/usr/bin/env python3
"""
Tests for lammps_utils.py

Run with: python test_lammps_utils.py
Or: python -m pytest test_lammps_utils.py -v
"""

import os
import sys
import tempfile
import shutil
import unittest
import numpy as np

# Add current directory to path for import
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lammps_utils import (
    # Setup functions
    NUM_CORES, save_final_results,
    # Auto-detection
    get_atom_count_from_data_file, get_box_dimensions_from_data_file,
    get_data_file_from_input, auto_detect_atom_count, get_heat_flux_from_input,
    get_simulation_parameters_from_input,
    # Parametric studies
    modify_lammps_variable, create_parameter_sweep_inputs,
    # Thermal conductivity
    parse_temperature_profile, compute_thermal_conductivity_nemd,
    parse_hfacf, compute_thermal_conductivity_gk,
    analyze_energy_drift,
    # Trajectory & structural analysis
    parse_dump_file, parse_rdf_file, parse_msd_file,
    parse_density_profile, parse_gyration_file,
    # Transport & mechanical properties
    compute_diffusion_coefficient, parse_stress_strain,
    compute_elastic_modulus, compute_surface_tension,
    # Statistical analysis
    block_average, autocorrelation_function, parse_log_file,
    # Visualization
    plot_temperature_profile, plot_rdf, plot_msd, plot_stress_strain, plot_acf
)


class TestSetup(unittest.TestCase):
    """Test setup and configuration functions."""

    def test_num_cores_detected(self):
        """NUM_CORES should be a positive integer."""
        self.assertIsInstance(NUM_CORES, int)
        self.assertGreater(NUM_CORES, 0)


class TestSaveFinalResults(unittest.TestCase):
    """Test save_final_results function."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.original_dir = os.getcwd()
        # Create an output directory to simulate the container environment
        self.output_dir = os.path.join(self.test_dir, "output")
        os.makedirs(self.output_dir)
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.original_dir)
        shutil.rmtree(self.test_dir)

    def test_save_final_results_basic(self):
        """Test basic save_final_results functionality."""
        import json
        import lammps_utils
        # Temporarily change OUTPUT_DIR for testing
        original_output_dir = lammps_utils.OUTPUT_DIR
        lammps_utils.OUTPUT_DIR = self.output_dir

        try:
            results = {"thermal_conductivity": 0.075, "method": "NEMD"}
            output_path = save_final_results(results)

            self.assertTrue(os.path.exists(output_path))
            with open(output_path, 'r') as f:
                saved_data = json.load(f)

            self.assertEqual(saved_data["status"], "completed")
            self.assertEqual(saved_data["summary"]["thermal_conductivity"], 0.075)
            self.assertEqual(saved_data["summary"]["method"], "NEMD")
        finally:
            lammps_utils.OUTPUT_DIR = original_output_dir

    def test_save_final_results_with_files(self):
        """Test save_final_results with output files and descriptions."""
        import json
        import lammps_utils
        original_output_dir = lammps_utils.OUTPUT_DIR
        lammps_utils.OUTPUT_DIR = self.output_dir

        try:
            results = {"kappa": 0.08}
            output_files = {"plot": "/output/temp_profile.png"}
            file_descriptions = {"plot": "Temperature gradient plot"}

            output_path = save_final_results(results, output_files, file_descriptions)

            with open(output_path, 'r') as f:
                saved_data = json.load(f)

            self.assertIn("output_files", saved_data)
            self.assertEqual(saved_data["output_files"]["plot"], "/output/temp_profile.png")
            self.assertIn("file_descriptions", saved_data)
            self.assertEqual(saved_data["file_descriptions"]["plot"], "Temperature gradient plot")
        finally:
            lammps_utils.OUTPUT_DIR = original_output_dir

    def test_save_final_results_custom_status(self):
        """Test save_final_results with custom status."""
        import json
        import lammps_utils
        original_output_dir = lammps_utils.OUTPUT_DIR
        lammps_utils.OUTPUT_DIR = self.output_dir

        try:
            results = {"error": "Simulation failed"}
            output_path = save_final_results(results, status="failed")

            with open(output_path, 'r') as f:
                saved_data = json.load(f)

            self.assertEqual(saved_data["status"], "failed")
        finally:
            lammps_utils.OUTPUT_DIR = original_output_dir

    def test_save_final_results_numpy_types(self):
        """Test save_final_results handles NumPy types correctly."""
        import json
        import lammps_utils
        original_output_dir = lammps_utils.OUTPUT_DIR
        lammps_utils.OUTPUT_DIR = self.output_dir

        try:
            # Create results with various NumPy types
            results = {
                "kappa": np.float64(0.075),
                "n_atoms": np.int64(2000),
                "converged": np.bool_(True),
                "values": np.array([1.0, 2.0, 3.0]),
                "nested": {
                    "mean": np.float32(1.5),
                    "count": np.int32(100)
                }
            }
            output_path = save_final_results(results)

            # Should not raise TypeError
            with open(output_path, 'r') as f:
                saved_data = json.load(f)

            # Verify values were converted correctly
            self.assertAlmostEqual(saved_data["summary"]["kappa"], 0.075)
            self.assertEqual(saved_data["summary"]["n_atoms"], 2000)
            self.assertTrue(saved_data["summary"]["converged"])
            self.assertEqual(saved_data["summary"]["values"], [1.0, 2.0, 3.0])
            self.assertAlmostEqual(saved_data["summary"]["nested"]["mean"], 1.5, places=5)
            self.assertEqual(saved_data["summary"]["nested"]["count"], 100)
        finally:
            lammps_utils.OUTPUT_DIR = original_output_dir


class TestAtomCountDetection(unittest.TestCase):
    """Test automatic atom count detection functions."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.original_dir = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.original_dir)
        shutil.rmtree(self.test_dir)

    def test_get_atom_count_from_data_file(self):
        """Test parsing atom count from LAMMPS data file."""
        # Create a mock LAMMPS data file
        content = """LAMMPS data file via write_data

2000 atoms
1000 bonds
500 angles

3 atom types
2 bond types

0.0 50.0 xlo xhi
0.0 50.0 ylo yhi
0.0 100.0 zlo zhi

Masses

1 12.0
2 1.0
3 16.0

Atoms

1 1 1 0.0 1.0 2.0 3.0
"""
        with open("data.test", "w") as f:
            f.write(content)

        count = get_atom_count_from_data_file("data.test")
        self.assertEqual(count, 2000)

    def test_get_atom_count_large_system(self):
        """Test parsing atom count from a large system data file."""
        content = """LAMMPS Description

50000 atoms
25000 bonds

2 atom types

Atoms

"""
        with open("data.large", "w") as f:
            f.write(content)

        count = get_atom_count_from_data_file("data.large")
        self.assertEqual(count, 50000)

    def test_get_atom_count_file_not_found(self):
        """Test graceful handling of missing data file."""
        count = get_atom_count_from_data_file("nonexistent.data")
        self.assertIsNone(count)

    def test_get_atom_count_no_atoms_line(self):
        """Test handling of data file without atoms line."""
        content = """LAMMPS Description

2 atom types

Masses

1 12.0
"""
        with open("data.noatoms", "w") as f:
            f.write(content)

        count = get_atom_count_from_data_file("data.noatoms")
        self.assertIsNone(count)

    def test_get_data_file_from_input(self):
        """Test extracting data file path from input script."""
        content = """# LAMMPS input script
units lj
atom_style atomic
read_data data.lj
pair_style lj/cut 2.5
"""
        with open("in.test", "w") as f:
            f.write(content)

        # Create the data file so it can be found
        with open("data.lj", "w") as f:
            f.write("2000 atoms\n")

        data_file = get_data_file_from_input("in.test")
        self.assertIsNotNone(data_file)
        self.assertTrue(data_file.endswith("data.lj"))

    def test_get_data_file_with_path(self):
        """Test extracting data file with subdirectory path."""
        os.makedirs("inputs", exist_ok=True)
        content = """# LAMMPS input script
read_data inputs/data.system
"""
        with open("in.test", "w") as f:
            f.write(content)

        # Create the data file in subdirectory
        with open("inputs/data.system", "w") as f:
            f.write("5000 atoms\n")

        data_file = get_data_file_from_input("in.test")
        self.assertIsNotNone(data_file)
        self.assertIn("data.system", data_file)

    def test_get_data_file_no_read_data(self):
        """Test input script without read_data command."""
        content = """# LAMMPS input script
units lj
atom_style atomic
create_box 1 region
"""
        with open("in.nodata", "w") as f:
            f.write(content)

        data_file = get_data_file_from_input("in.nodata")
        self.assertIsNone(data_file)

    def test_get_data_file_quoted_filename(self):
        """Test extracting data file with quoted filename."""
        # Test double quotes
        content = """# LAMMPS input script
units lj
read_data "data.quoted"
"""
        with open("in.quoted", "w") as f:
            f.write(content)

        # Create the data file
        with open("data.quoted", "w") as f:
            f.write("2000 atoms\n")

        data_file = get_data_file_from_input("in.quoted")
        self.assertIsNotNone(data_file)
        self.assertTrue(data_file.endswith("data.quoted"))
        # Ensure no quotes in the path
        self.assertNotIn('"', data_file)

    def test_get_data_file_single_quoted(self):
        """Test extracting data file with single-quoted filename."""
        content = """# LAMMPS input script
read_data 'data.single'
"""
        with open("in.single", "w") as f:
            f.write(content)

        with open("data.single", "w") as f:
            f.write("1500 atoms\n")

        data_file = get_data_file_from_input("in.single")
        self.assertIsNotNone(data_file)
        self.assertTrue(data_file.endswith("data.single"))
        self.assertNotIn("'", data_file)

    def test_auto_detect_atom_count(self):
        """Test full auto-detection pipeline."""
        # Create data file
        data_content = """LAMMPS data file

3500 atoms
2 atom types

Atoms

"""
        with open("data.auto", "w") as f:
            f.write(data_content)

        # Create input file referencing data
        input_content = """# Test input
units lj
read_data data.auto
run 100
"""
        with open("in.auto", "w") as f:
            f.write(input_content)

        count = auto_detect_atom_count("in.auto")
        self.assertEqual(count, 3500)

    def test_auto_detect_returns_none_for_missing_files(self):
        """Test auto-detection returns None when files are missing."""
        content = """read_data missing.data"""
        with open("in.missing", "w") as f:
            f.write(content)

        count = auto_detect_atom_count("in.missing")
        self.assertIsNone(count)


class TestBoxDimensionsDetection(unittest.TestCase):
    """Test box dimensions detection from LAMMPS data files."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.original_dir = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.original_dir)
        shutil.rmtree(self.test_dir)

    def test_get_box_dimensions_basic(self):
        """Test parsing box dimensions from standard LAMMPS data file."""
        content = """LAMMPS data file via write_data

2000 atoms
1000 bonds

3 atom types

0.0 50.0 xlo xhi
-25.0 25.0 ylo yhi
0.0 100.0 zlo zhi

Masses

1 12.0

Atoms

1 1 1 0.0 1.0 2.0 3.0
"""
        with open("data.test", "w") as f:
            f.write(content)

        box = get_box_dimensions_from_data_file("data.test")

        self.assertIsNotNone(box)
        self.assertAlmostEqual(box['Lx'], 50.0)
        self.assertAlmostEqual(box['Ly'], 50.0)
        self.assertAlmostEqual(box['Lz'], 100.0)
        self.assertAlmostEqual(box['xlo'], 0.0)
        self.assertAlmostEqual(box['xhi'], 50.0)
        self.assertAlmostEqual(box['ylo'], -25.0)
        self.assertAlmostEqual(box['yhi'], 25.0)
        self.assertAlmostEqual(box['volume'], 50.0 * 50.0 * 100.0)

    def test_get_box_dimensions_lj_units(self):
        """Test parsing box dimensions from LJ-style data file."""
        content = """LAMMPS data file for LJ fluid

500 atoms
1 atom types

-5.29 5.29 xlo xhi
-5.29 5.29 ylo yhi
-10.58 10.58 zlo zhi

Atoms

"""
        with open("data.lj", "w") as f:
            f.write(content)

        box = get_box_dimensions_from_data_file("data.lj")

        self.assertIsNotNone(box)
        self.assertAlmostEqual(box['Lx'], 10.58, places=2)
        self.assertAlmostEqual(box['Ly'], 10.58, places=2)
        self.assertAlmostEqual(box['Lz'], 21.16, places=2)
        # Cross-sectional area for NEMD
        area = box['Lx'] * box['Ly']
        self.assertAlmostEqual(area, 111.9364, places=2)

    def test_get_box_dimensions_real_units(self):
        """Test parsing box dimensions from real units (SPC/E water) data file."""
        content = """LAMMPS data file for SPC/E water

3000 atoms
1000 molecules

3 atom types

0.0 31.0 xlo xhi
0.0 31.0 ylo yhi
0.0 62.0 zlo zhi

Atoms

"""
        with open("data.spce", "w") as f:
            f.write(content)

        box = get_box_dimensions_from_data_file("data.spce")

        self.assertIsNotNone(box)
        self.assertAlmostEqual(box['Lx'], 31.0)
        self.assertAlmostEqual(box['Ly'], 31.0)
        self.assertAlmostEqual(box['Lz'], 62.0)
        self.assertAlmostEqual(box['volume'], 31.0 * 31.0 * 62.0)

    def test_get_box_dimensions_triclinic(self):
        """Test parsing box dimensions from triclinic box (tilt factors ignored)."""
        content = """LAMMPS data file

1000 atoms

0.0 40.0 0.0 xlo xhi xy
0.0 40.0 0.0 ylo yhi xz
0.0 80.0 0.0 zlo zhi yz

Atoms

"""
        with open("data.triclinic", "w") as f:
            f.write(content)

        box = get_box_dimensions_from_data_file("data.triclinic")

        self.assertIsNotNone(box)
        self.assertAlmostEqual(box['Lx'], 40.0)
        self.assertAlmostEqual(box['Ly'], 40.0)
        self.assertAlmostEqual(box['Lz'], 80.0)

    def test_get_box_dimensions_file_not_found(self):
        """Test graceful handling of missing data file."""
        box = get_box_dimensions_from_data_file("nonexistent.data")
        self.assertIsNone(box)

    def test_get_box_dimensions_incomplete_bounds(self):
        """Test handling of data file with incomplete box bounds."""
        content = """LAMMPS data file

1000 atoms

0.0 50.0 xlo xhi
0.0 50.0 ylo yhi

Atoms

"""
        with open("data.incomplete", "w") as f:
            f.write(content)

        box = get_box_dimensions_from_data_file("data.incomplete")
        self.assertIsNone(box)


class TestHeatFluxDetection(unittest.TestCase):
    """Test heat flux detection from LAMMPS input scripts."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.original_dir = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.original_dir)
        shutil.rmtree(self.test_dir)

    def test_get_heat_flux_ehex(self):
        """Test parsing heat flux from fix ehex commands."""
        content = """# LAMMPS input for eHEX thermal conductivity
units lj
atom_style atomic

read_data data.lj

# Heat exchange regions
region hot block INF INF INF INF -5.0 -4.0
region cold block INF INF INF INF 4.0 5.0

# eHEX fixes - add/remove 0.15 energy per timestep
fix hot all ehex 1 0.15 region hot
fix cold all ehex 1 -0.15 region cold

run 100000
"""
        with open("in.ehex", "w") as f:
            f.write(content)

        flux_info = get_heat_flux_from_input("in.ehex")

        self.assertIsNotNone(flux_info)
        self.assertAlmostEqual(flux_info['heat_flux'], 0.15)
        self.assertEqual(flux_info['method'], 'ehex')
        self.assertIn('hot', flux_info['fix_ids'])
        self.assertIn('cold', flux_info['fix_ids'])
        self.assertIn(0.15, flux_info['raw_values'])
        self.assertIn(-0.15, flux_info['raw_values'])

    def test_get_heat_flux_heat(self):
        """Test parsing heat flux from fix heat commands."""
        content = """# LAMMPS input for HEX thermal conductivity
units lj

fix source all heat 1 0.5 region hot_region
fix sink all heat 1 -0.5 region cold_region

run 50000
"""
        with open("in.heat", "w") as f:
            f.write(content)

        flux_info = get_heat_flux_from_input("in.heat")

        self.assertIsNotNone(flux_info)
        self.assertAlmostEqual(flux_info['heat_flux'], 0.5)
        self.assertEqual(flux_info['method'], 'heat')

    def test_get_heat_flux_real_units(self):
        """Test parsing heat flux from real units simulation (SPC/E water)."""
        content = """# LAMMPS input for water thermal conductivity
units real
atom_style full

read_data data.spce

# Heat flux in kcal/mol/fs
fix hot all ehex 10 0.005 region hot
fix cold all ehex 10 -0.005 region cold

run 500000
"""
        with open("in.spce.ehex", "w") as f:
            f.write(content)

        flux_info = get_heat_flux_from_input("in.spce.ehex")

        self.assertIsNotNone(flux_info)
        self.assertAlmostEqual(flux_info['heat_flux'], 0.005)
        self.assertEqual(flux_info['method'], 'ehex')

    def test_get_heat_flux_with_inline_comments(self):
        """Test parsing with inline comments."""
        content = """
fix hot all ehex 1 0.25 region hot  # Add heat
fix cold all ehex 1 -0.25 region cold  # Remove heat
"""
        with open("in.comments", "w") as f:
            f.write(content)

        flux_info = get_heat_flux_from_input("in.comments")

        self.assertIsNotNone(flux_info)
        self.assertAlmostEqual(flux_info['heat_flux'], 0.25)

    def test_get_heat_flux_not_found(self):
        """Test when no heat flux fix is present."""
        content = """# LAMMPS input without heat flux
units lj
fix nve all nve
run 10000
"""
        with open("in.noheat", "w") as f:
            f.write(content)

        flux_info = get_heat_flux_from_input("in.noheat")
        self.assertIsNone(flux_info)

    def test_get_heat_flux_file_not_found(self):
        """Test graceful handling of missing input file."""
        flux_info = get_heat_flux_from_input("nonexistent.in")
        self.assertIsNone(flux_info)


class TestSimulationParameters(unittest.TestCase):
    """Test consolidated simulation parameter extraction."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.original_dir = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.original_dir)
        shutil.rmtree(self.test_dir)

    def test_get_simulation_parameters_lj(self):
        """Test extracting parameters from LJ simulation input."""
        # Create data file
        data_content = """LAMMPS data file

500 atoms
1 atom types

-5.29 5.29 xlo xhi
-5.29 5.29 ylo yhi
-10.58 10.58 zlo zhi

Atoms

"""
        with open("data.lj", "w") as f:
            f.write(data_content)

        # Create input file
        input_content = """# LJ thermal conductivity simulation
units lj
atom_style atomic
timestep 0.005

read_data data.lj

pair_style lj/cut 2.5
pair_coeff * * 1.0 1.0

fix nvt all nvt temp 1.0 1.0 0.1
fix hot all ehex 1 0.15 region hot
fix cold all ehex 1 -0.15 region cold

run 100000
"""
        with open("in.lj.ehex", "w") as f:
            f.write(input_content)

        params = get_simulation_parameters_from_input("in.lj.ehex")

        self.assertEqual(params['units'], 'lj')
        self.assertAlmostEqual(params['timestep'], 0.005)
        self.assertAlmostEqual(params['temperature'], 1.0)
        self.assertAlmostEqual(params['heat_flux'], 0.15)
        self.assertEqual(params['heat_flux_method'], 'ehex')
        self.assertIsNotNone(params['box'])
        self.assertAlmostEqual(params['box']['Lx'], 10.58, places=2)
        self.assertEqual(params['atom_count'], 500)

    def test_get_simulation_parameters_real_units(self):
        """Test extracting parameters from real units simulation (water)."""
        # Create data file
        data_content = """LAMMPS data file for SPC/E water

3000 atoms

0.0 31.0 xlo xhi
0.0 31.0 ylo yhi
0.0 62.0 zlo zhi

Atoms

"""
        with open("data.spce", "w") as f:
            f.write(data_content)

        input_content = """# SPC/E water thermal conductivity
units real
atom_style full
timestep 1.0

read_data data.spce

fix nvt all nvt temp 300.0 300.0 100.0
fix hot all ehex 10 0.005 region hot
fix cold all ehex 10 -0.005 region cold

run 500000
"""
        with open("in.spce.ehex", "w") as f:
            f.write(input_content)

        params = get_simulation_parameters_from_input("in.spce.ehex")

        self.assertEqual(params['units'], 'real')
        self.assertAlmostEqual(params['timestep'], 1.0)
        self.assertAlmostEqual(params['temperature'], 300.0)
        self.assertAlmostEqual(params['heat_flux'], 0.005)
        self.assertIsNotNone(params['box'])
        self.assertAlmostEqual(params['box']['volume'], 31.0 * 31.0 * 62.0)

    def test_get_simulation_parameters_variable_temp(self):
        """Test extracting temperature from variable definition."""
        input_content = """units lj
timestep 0.001
variable T equal 1.5
fix nve all nve
"""
        with open("in.nve", "w") as f:
            f.write(input_content)

        params = get_simulation_parameters_from_input("in.nve")

        self.assertEqual(params['units'], 'lj')
        self.assertAlmostEqual(params['timestep'], 0.001)
        self.assertAlmostEqual(params['temperature'], 1.5)

    def test_get_simulation_parameters_minimal(self):
        """Test with minimal input (only units)."""
        input_content = """units metal
run 1000
"""
        with open("in.minimal", "w") as f:
            f.write(input_content)

        params = get_simulation_parameters_from_input("in.minimal")

        self.assertEqual(params['units'], 'metal')
        self.assertIsNone(params['timestep'])
        self.assertIsNone(params['temperature'])
        self.assertIsNone(params['heat_flux'])

    def test_get_simulation_parameters_with_comments(self):
        """Test parsing with various comment styles."""
        input_content = """# Full line comment
units lj  # inline comment
timestep 0.005  # another inline comment
# More comments
variable temp equal 2.0
"""
        with open("in.comments", "w") as f:
            f.write(input_content)

        params = get_simulation_parameters_from_input("in.comments")

        self.assertEqual(params['units'], 'lj')
        self.assertAlmostEqual(params['timestep'], 0.005)
        self.assertAlmostEqual(params['temperature'], 2.0)


class TestParametricStudies(unittest.TestCase):
    """Test parametric study functions."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.original_dir = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.original_dir)
        shutil.rmtree(self.test_dir)

    def test_modify_lammps_variable(self):
        """Test modifying LAMMPS variable in script content."""
        content = """
# LAMMPS input script
variable dt equal 0.005
variable temp equal 1.0
variable nsteps equal 10000
"""
        # Modify timestep
        modified = modify_lammps_variable(content, "dt", 0.001)
        self.assertIn("variable dt equal 0.001", modified)
        self.assertIn("variable temp equal 1.0", modified)  # unchanged

        # Modify temperature
        modified = modify_lammps_variable(content, "temp", 2.5)
        self.assertIn("variable temp equal 2.5", modified)

    def test_modify_lammps_variable_with_whitespace(self):
        """Test handling various whitespace patterns."""
        content = "variable  dt   equal   0.005"
        modified = modify_lammps_variable(content, "dt", 0.01)
        self.assertIn("variable dt equal 0.01", modified)

    def test_create_parameter_sweep_inputs(self):
        """Test creating parameter sweep input files."""
        # Create original input file
        original_content = """
variable dt equal 0.005
variable temp equal 1.0
run 1000
"""
        with open("in.test", "w") as f:
            f.write(original_content)

        # Create sweep files
        values = [0.001, 0.005, 0.01]
        files = create_parameter_sweep_inputs("in.test", "dt", values)

        self.assertEqual(len(files), 3)

        for (filepath, value) in files:
            self.assertTrue(os.path.exists(filepath))
            with open(filepath) as f:
                content = f.read()
            self.assertIn(f"variable dt equal {value}", content)


class TestTemperatureProfile(unittest.TestCase):
    """Test temperature profile parsing and thermal conductivity."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.original_dir = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.original_dir)
        shutil.rmtree(self.test_dir)

    def test_parse_temperature_profile(self):
        """Test parsing temperature profile file."""
        # Create mock temperature profile (fix ave/chunk output)
        content = """# Chunk-averaged data for fix myavg
# Timestep Number-of-chunks Total-count
# Chunk Coord Ncount v_T
1 -15.0 33.5 0.95
2 -10.0 34.2 0.98
3 -5.0 33.8 1.02
4 0.0 34.0 1.05
5 5.0 33.9 1.08
6 10.0 34.1 1.12
7 15.0 33.7 1.15
"""
        with open("out.T", "w") as f:
            f.write(content)

        profile = parse_temperature_profile("out.T")

        self.assertEqual(profile.shape, (7, 2))
        self.assertAlmostEqual(profile[0, 0], -15.0)  # z coordinate
        self.assertAlmostEqual(profile[0, 1], 0.95)   # temperature
        self.assertAlmostEqual(profile[-1, 1], 1.15)

    def test_parse_temperature_profile_float_ncount(self):
        """Test parsing with float Ncount (time-averaged)."""
        content = """# Chunk data
1 -10.0 33.0979 0.98
2 0.0 34.5123 1.02
3 10.0 33.8456 1.06
"""
        with open("out.T", "w") as f:
            f.write(content)

        profile = parse_temperature_profile("out.T")
        self.assertEqual(profile.shape, (3, 2))

    def test_compute_thermal_conductivity_nemd(self):
        """Test NEMD thermal conductivity computation."""
        # Create linear temperature profile
        z = np.linspace(-20, 20, 20)
        dT_dz = 0.01  # Temperature gradient
        T = 1.0 + dT_dz * z
        T_profile = np.column_stack([z, T])

        heat_flux = 0.15
        area = 100.0

        result = compute_thermal_conductivity_nemd(T_profile, heat_flux, area)

        self.assertIn('kappa', result)
        self.assertIn('kappa_std_err', result)
        self.assertIn('dT_dz', result)
        self.assertIn('r_squared', result)

        # For linear profile, R² should be close to 1
        self.assertGreater(result['r_squared'], 0.99)

        # Check thermal conductivity: κ = J / (A * dT/dz)
        expected_kappa = heat_flux / (area * dT_dz)
        self.assertAlmostEqual(result['kappa'], expected_kappa, places=2)

        # Standard error should be small for perfect linear data
        self.assertLess(result['kappa_std_err'], result['kappa'] * 0.1)


class TestGreenKubo(unittest.TestCase):
    """Test Green-Kubo thermal conductivity functions."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.original_dir = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.original_dir)
        shutil.rmtree(self.test_dir)

    def test_parse_hfacf(self):
        """Test parsing heat flux autocorrelation file with block structure."""
        # Create mock HFACF output (fix ave/correlate with ave running)
        # Format: Block header "Timestep Nwindows", then data rows
        content = """# Time-correlated data for fix myacf
# Timestep Number-of-time-windows
# Row TimeDelta Ncount c_flux[1]*c_flux[1] c_flux[2]*c_flux[2] c_flux[3]*c_flux[3]
1000 5
1 0 100 1.5 1.4 1.6
2 10 100 1.2 1.1 1.3
3 20 100 0.9 0.85 1.0
4 30 100 0.6 0.55 0.7
5 40 100 0.3 0.28 0.35
"""
        with open("out.hfacf", "w") as f:
            f.write(content)

        data = parse_hfacf("out.hfacf")

        self.assertEqual(data.shape[0], 5)  # 5 time points
        self.assertEqual(data.shape[1], 4)  # timestep, Jx, Jy, Jz
        # Check that timestep comes from TimeDelta column (column 1)
        self.assertAlmostEqual(data[0, 0], 0)   # First time delta
        self.assertAlmostEqual(data[1, 0], 10)  # Second time delta

    def test_parse_hfacf_multiple_blocks(self):
        """Test parsing HFACF with multiple blocks (ave running) - should use final block."""
        # Simulate running average output with 2 blocks
        content = """# Time-correlated data for fix myacf
# Header info
1000 3
1 0 10 100.0 100.0 100.0
2 5 10 50.0 50.0 50.0
3 10 10 25.0 25.0 25.0
2000 3
1 0 20 200.0 200.0 200.0
2 5 20 100.0 100.0 100.0
3 10 20 50.0 50.0 50.0
"""
        with open("out.hfacf_blocks", "w") as f:
            f.write(content)

        # Default: use final block
        data = parse_hfacf("out.hfacf_blocks")
        self.assertEqual(data.shape[0], 3)  # 3 time points from final block
        self.assertAlmostEqual(data[0, 1], 200.0)  # Final block has 200.0

        # Explicit: use all blocks
        data_all = parse_hfacf("out.hfacf_blocks", use_final_block=False)
        self.assertEqual(data_all.shape[0], 6)  # All 6 time points

    def test_parse_hfacf_empty_file(self):
        """Test parsing empty HFACF file returns proper empty array."""
        content = """# Comments only
# No data
"""
        with open("empty_hfacf.dat", "w") as f:
            f.write(content)

        data = parse_hfacf("empty_hfacf.dat")

        # Should return empty 2D array with shape (0, 4)
        self.assertEqual(data.shape, (0, 4))

    def test_compute_thermal_conductivity_gk(self):
        """Test Green-Kubo thermal conductivity computation."""
        # Create simple test data with constant ACF for predictable integral
        # This makes the math easy to verify:
        # - Total ACF = 1 + 1 + 1 = 3 (constant)
        # - Time range: 0 to 40, dt = 10 → t = [0, 10, 20, 30, 40]
        # - Integral of constant 3 over [0, 40] = 3 × 40 = 120
        # - kappa = (1 / 3Vk_B T²) × integral = (1 / (3 × 1000 × 1 × 1)) × 120 = 0.04
        time_deltas = np.array([0, 1, 2, 3, 4])  # Will be multiplied by timestep=10
        acf_x = np.ones(5)
        acf_y = np.ones(5)
        acf_z = np.ones(5)

        hfacf_data = np.column_stack([time_deltas, acf_x, acf_y, acf_z])

        result = compute_thermal_conductivity_gk(
            hfacf_data,
            volume=1000.0,
            temp=1.0,
            timestep=10.0  # timestep multiplies time_delta
        )

        self.assertIn('kappa', result)
        self.assertIn('kappa_std_err', result)
        self.assertIn('r_squared', result)
        self.assertIn('integral', result)
        self.assertIn('acf_data', result)
        self.assertIn('kappa_x', result)
        self.assertIn('kappa_y', result)
        self.assertIn('kappa_z', result)

        # Verify the formula: kappa = (1 / 3Vk_B T²) × integral
        # integral = 120 (trapz of 3 over [0, 40])
        # kappa = 120 / (3 × 1000) = 0.04
        self.assertAlmostEqual(result['kappa'], 0.04, places=5)

    def test_compute_thermal_conductivity_gk_parameter_aliases(self):
        """Test that both temperature/temp and timestep/dt work."""
        hfacf_data = np.array([[0, 1.0, 1.0, 1.0], [10, 0.5, 0.5, 0.5]])

        # Using temperature and timestep
        result1 = compute_thermal_conductivity_gk(
            hfacf_data, volume=1000.0, temperature=1.0, timestep=0.005
        )

        # Using temp and dt aliases
        result2 = compute_thermal_conductivity_gk(
            hfacf_data, volume=1000.0, temp=1.0, dt=0.005
        )

        self.assertAlmostEqual(result1['kappa'], result2['kappa'])


class TestEnergyAnalysis(unittest.TestCase):
    """Test energy drift analysis."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.original_dir = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.original_dir)
        shutil.rmtree(self.test_dir)

    def test_analyze_energy_drift(self):
        """Test energy drift analysis."""
        # Create mock energy file with small drift
        timesteps = np.arange(0, 10000, 100)
        energy = -5000.0 + 0.001 * timesteps + np.random.normal(0, 0.1, len(timesteps))

        content = "# Energy output\n"
        for t, e in zip(timesteps, energy):
            content += f"{int(t)} {e:.6f}\n"

        with open("out.E", "w") as f:
            f.write(content)

        result = analyze_energy_drift("out.E")

        self.assertIn('drift_rate', result)
        self.assertIn('relative_drift_percent', result)
        self.assertIn('initial_energy', result)
        self.assertIn('final_energy', result)

        # Drift rate should be close to 0.001
        self.assertAlmostEqual(result['drift_rate'], 0.001, places=3)


class TestDumpFileParsing(unittest.TestCase):
    """Test LAMMPS dump file parsing."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.original_dir = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.original_dir)
        shutil.rmtree(self.test_dir)

    def test_parse_dump_file_single_frame(self):
        """Test parsing single frame from dump file."""
        content = """ITEM: TIMESTEP
1000
ITEM: NUMBER OF ATOMS
3
ITEM: BOX BOUNDS pp pp pp
0.0 10.0
0.0 10.0
0.0 10.0
ITEM: ATOMS id type x y z
1 1 1.0 2.0 3.0
2 1 4.0 5.0 6.0
3 2 7.0 8.0 9.0
"""
        with open("dump.lammpstrj", "w") as f:
            f.write(content)

        frame = parse_dump_file("dump.lammpstrj")

        self.assertEqual(frame['timestep'], 1000)
        self.assertEqual(frame['natoms'], 3)
        self.assertEqual(len(frame['columns']), 5)
        self.assertEqual(frame['atoms'].shape, (3, 5))
        self.assertAlmostEqual(frame['atoms'][0, 2], 1.0)  # x of atom 1

    def test_parse_dump_file_multiple_frames(self):
        """Test parsing all frames from dump file."""
        content = """ITEM: TIMESTEP
0
ITEM: NUMBER OF ATOMS
2
ITEM: BOX BOUNDS pp pp pp
0.0 10.0
0.0 10.0
0.0 10.0
ITEM: ATOMS id type x y z
1 1 1.0 1.0 1.0
2 1 2.0 2.0 2.0
ITEM: TIMESTEP
100
ITEM: NUMBER OF ATOMS
2
ITEM: BOX BOUNDS pp pp pp
0.0 10.0
0.0 10.0
0.0 10.0
ITEM: ATOMS id type x y z
1 1 1.1 1.1 1.1
2 1 2.1 2.1 2.1
"""
        with open("dump.lammpstrj", "w") as f:
            f.write(content)

        frames = parse_dump_file("dump.lammpstrj", frame='all')

        self.assertEqual(len(frames), 2)
        self.assertEqual(frames[0]['timestep'], 0)
        self.assertEqual(frames[1]['timestep'], 100)


class TestRDFParsing(unittest.TestCase):
    """Test RDF file parsing."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.original_dir = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.original_dir)
        shutil.rmtree(self.test_dir)

    def test_parse_rdf_file(self):
        """Test parsing RDF output file."""
        content = """# RDF output
# Row r g(r) coord
1 0.5 0.0 0.0
2 1.0 0.5 0.1
3 1.5 2.5 0.8
4 2.0 1.2 1.5
5 2.5 1.05 2.3
6 3.0 1.01 3.2
"""
        with open("rdf.dat", "w") as f:
            f.write(content)

        data = parse_rdf_file("rdf.dat")

        self.assertEqual(len(data['r']), 6)
        self.assertAlmostEqual(data['r'][0], 0.5)
        self.assertAlmostEqual(data['g_r'][2], 2.5)  # First peak
        self.assertIsNotNone(data['coord'])


class TestMSDParsing(unittest.TestCase):
    """Test MSD file parsing and diffusion coefficient."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.original_dir = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.original_dir)
        shutil.rmtree(self.test_dir)

    def test_parse_msd_file(self):
        """Test parsing MSD output file."""
        # MSD format: timestep msd_x msd_y msd_z msd_total
        content = """# MSD output
0 0.0 0.0 0.0 0.0
100 0.5 0.4 0.6 1.5
200 1.0 0.9 1.1 3.0
300 1.5 1.4 1.6 4.5
400 2.0 1.9 2.1 6.0
"""
        with open("msd.dat", "w") as f:
            f.write(content)

        data = parse_msd_file("msd.dat")

        self.assertEqual(len(data['time']), 5)
        self.assertEqual(len(data['msd']), 5)
        self.assertAlmostEqual(data['msd'][-1], 6.0)
        self.assertIsNotNone(data['msd_components'])

    def test_compute_diffusion_coefficient(self):
        """Test diffusion coefficient computation from MSD."""
        # Create linear MSD data: MSD = 6*D*t for 3D
        D_expected = 0.1
        timestep = 0.001
        time = np.arange(0, 1000, 10)
        msd = 6 * D_expected * time * timestep  # MSD = 6Dt

        msd_data = {'time': time, 'msd': msd}

        result = compute_diffusion_coefficient(msd_data, timestep=timestep, dimensions=3)

        self.assertIn('D', result)
        self.assertIn('D_std_err', result)
        self.assertIn('r_squared', result)

        # D should be close to expected value
        self.assertAlmostEqual(result['D'], D_expected, places=2)
        self.assertGreater(result['r_squared'], 0.99)


class TestStatisticalAnalysis(unittest.TestCase):
    """Test statistical analysis functions."""

    def test_block_average(self):
        """Test block averaging for error estimation."""
        # Create correlated data
        np.random.seed(42)
        n = 1000
        data = np.cumsum(np.random.randn(n)) / np.sqrt(n) + 100  # Mean ~100

        result = block_average(data, num_blocks=10)

        self.assertIn('mean', result)
        self.assertIn('std_err', result)
        self.assertIn('block_means', result)
        self.assertEqual(len(result['block_means']), 10)

    def test_autocorrelation_function(self):
        """Test autocorrelation function computation."""
        # Create exponentially correlated data
        np.random.seed(42)
        n = 1000
        tau = 20
        noise = np.random.randn(n)
        data = np.zeros(n)
        data[0] = noise[0]
        alpha = np.exp(-1/tau)
        for i in range(1, n):
            data[i] = alpha * data[i-1] + np.sqrt(1-alpha**2) * noise[i]

        result = autocorrelation_function(data, max_lag=100)

        self.assertIn('lag', result)
        self.assertIn('acf', result)
        self.assertIn('correlation_time', result)
        self.assertIn('effective_samples', result)

        # ACF at lag 0 should be 1
        self.assertAlmostEqual(result['acf'][0], 1.0)

        # ACF should decay
        self.assertLess(result['acf'][50], result['acf'][10])


class TestMechanicalProperties(unittest.TestCase):
    """Test mechanical property analysis functions."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.original_dir = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.original_dir)
        shutil.rmtree(self.test_dir)

    def test_parse_stress_strain(self):
        """Test stress-strain data extraction from log file."""
        # Create mock LAMMPS log file
        content = """LAMMPS log file
Step Temp Press Lz Pzz
0 300 0 100.0 0.0
100 300 -50 100.5 -50.0
200 300 -100 101.0 -100.0
300 300 -150 101.5 -150.0
400 300 -200 102.0 -200.0
Loop time of 10.5 seconds
"""
        with open("tensile.log", "w") as f:
            f.write(content)

        result = parse_stress_strain("tensile.log", strain_component='Lz', stress_component='Pzz')

        self.assertIn('strain', result)
        self.assertIn('stress', result)
        self.assertIn('L0', result)

        self.assertAlmostEqual(result['L0'], 100.0)
        # Strain = (L - L0) / L0
        self.assertAlmostEqual(result['strain'][0], 0.0)
        self.assertAlmostEqual(result['strain'][-1], 0.02)  # 2% strain

    def test_compute_elastic_modulus(self):
        """Test Young's modulus computation."""
        # Create linear stress-strain data
        strain = np.linspace(0, 0.05, 50)
        E_expected = 100.0  # Young's modulus
        stress = E_expected * strain

        ss_data = {'strain': strain, 'stress': stress, 'L0': 100.0}

        result = compute_elastic_modulus(ss_data, strain_range=(0, 0.02))

        self.assertIn('E', result)
        self.assertIn('r_squared', result)

        self.assertAlmostEqual(result['E'], E_expected, places=1)
        self.assertGreater(result['r_squared'], 0.99)


class TestSurfaceTension(unittest.TestCase):
    """Test surface tension computation."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.original_dir = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.original_dir)
        shutil.rmtree(self.test_dir)

    def test_compute_surface_tension(self):
        """Test surface tension from pressure tensor."""
        # Create mock log file with pressure tensor
        # For a slab: gamma = Lz/2 * (Pzz - 0.5*(Pxx + Pyy))
        np.random.seed(42)
        n_steps = 100
        Lz = 50.0
        Pzz = np.random.normal(-1.0, 0.1, n_steps)  # Normal pressure
        Pxx = np.random.normal(0.0, 0.1, n_steps)   # Tangential
        Pyy = np.random.normal(0.0, 0.1, n_steps)   # Tangential

        content = "Step Pxx Pyy Pzz Lz\n"
        for i in range(n_steps):
            content += f"{i*100} {Pxx[i]:.4f} {Pyy[i]:.4f} {Pzz[i]:.4f} {Lz:.4f}\n"
        content += "Loop time of 5.0 seconds\n"

        with open("slab.log", "w") as f:
            f.write(content)

        result = compute_surface_tension("slab.log", box_normal='z')

        self.assertIn('gamma', result)
        self.assertIn('gamma_std_err', result)
        self.assertIn('P_normal', result)
        self.assertIn('P_tangential', result)


class TestDensityProfile(unittest.TestCase):
    """Test density profile parsing."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.original_dir = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.original_dir)
        shutil.rmtree(self.test_dir)

    def test_parse_density_profile(self):
        """Test parsing density profile file."""
        content = """# Density profile
# Chunk Coord Ncount density
1 -20.0 50 0.8
2 -10.0 55 0.85
3 0.0 60 0.9
4 10.0 55 0.85
5 20.0 50 0.8
"""
        with open("density.dat", "w") as f:
            f.write(content)

        data = parse_density_profile("density.dat")

        self.assertEqual(len(data['coord']), 5)
        self.assertAlmostEqual(data['coord'][2], 0.0)
        self.assertAlmostEqual(data['density'][2], 0.9)


class TestGyrationParsing(unittest.TestCase):
    """Test radius of gyration parsing."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.original_dir = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.original_dir)
        shutil.rmtree(self.test_dir)

    def test_parse_gyration_file(self):
        """Test parsing gyration output file."""
        content = """# Gyration data
# Timestep Rg
0 5.2
1000 5.3
2000 5.1
3000 5.4
4000 5.2
"""
        with open("gyration.dat", "w") as f:
            f.write(content)

        data = parse_gyration_file("gyration.dat")

        self.assertEqual(len(data['time']), 5)
        self.assertEqual(len(data['Rg']), 5)
        self.assertAlmostEqual(data['Rg'][0], 5.2)


class TestLogParsing(unittest.TestCase):
    """Test LAMMPS log file parsing."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.original_dir = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.original_dir)
        shutil.rmtree(self.test_dir)

    def test_parse_log_file(self):
        """Test parsing thermodynamic data from log file."""
        content = """LAMMPS (29 Oct 2020)
Reading data file ...
  2000 atoms

Step Temp Press PotEng KinEng TotEng
0 1.0 0.5 -5000.0 500.0 -4500.0
100 1.02 0.48 -5010.0 510.0 -4500.0
200 0.98 0.52 -4990.0 490.0 -4500.0
300 1.01 0.49 -5005.0 505.0 -4500.0
Loop time of 5.5 on 4 procs

Performance: 1000.0 tau/day
"""
        with open("simulation.log", "w") as f:
            f.write(content)

        data = parse_log_file("simulation.log")

        self.assertIn('Step', data)
        self.assertIn('Temp', data)
        self.assertIn('TotEng', data)

        self.assertEqual(len(data['Step']), 4)
        self.assertAlmostEqual(data['Temp'][0], 1.0)
        self.assertAlmostEqual(data['TotEng'][0], -4500.0)

    def test_parse_log_file_with_columns_filter(self):
        """Test parsing with column filter."""
        content = """Step Temp Press TotEng
0 1.0 0.5 -4500.0
100 1.02 0.48 -4500.0
Loop time
"""
        with open("test.log", "w") as f:
            f.write(content)

        data = parse_log_file("test.log", columns=['Temp', 'TotEng'])

        self.assertIn('Temp', data)
        self.assertIn('TotEng', data)
        self.assertNotIn('Press', data)
        self.assertNotIn('Step', data)


class TestVisualization(unittest.TestCase):
    """Test visualization functions."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.original_dir = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.original_dir)
        shutil.rmtree(self.test_dir)

    def test_plot_temperature_profile(self):
        """Test temperature profile plotting."""
        z = np.linspace(-20, 20, 20)
        T = 1.0 + 0.01 * z
        T_profile = np.column_stack([z, T])

        output_file = plot_temperature_profile(T_profile, "temp_profile.png")

        self.assertTrue(os.path.exists(output_file))
        self.assertGreater(os.path.getsize(output_file), 0)

    def test_plot_rdf(self):
        """Test RDF plotting."""
        r = np.linspace(0.5, 5.0, 50)
        g_r = 1 + 2 * np.exp(-(r - 1.5)**2 / 0.1) - 0.5 * np.exp(-r)

        rdf_data = {'r': r, 'g_r': g_r, 'coord': None}

        output_file = plot_rdf(rdf_data, "rdf.png")

        self.assertTrue(os.path.exists(output_file))
        self.assertGreater(os.path.getsize(output_file), 0)

    def test_plot_msd(self):
        """Test MSD plotting."""
        time = np.arange(0, 1000, 10)
        msd = 0.6 * time  # Linear MSD for diffusion

        msd_data = {'time': time, 'msd': msd}

        output_file = plot_msd(msd_data, timestep=0.001, output_file="msd.png")

        self.assertTrue(os.path.exists(output_file))
        self.assertGreater(os.path.getsize(output_file), 0)

    def test_plot_msd_with_fit(self):
        """Test MSD plotting with diffusion fit."""
        time = np.arange(0, 1000, 10)
        msd = 0.6 * time

        msd_data = {'time': time, 'msd': msd}
        fit_result = {'D': 0.1, 'fit_region': (0.5, 1.0)}

        output_file = plot_msd(msd_data, timestep=0.001, output_file="msd_fit.png", fit_result=fit_result)

        self.assertTrue(os.path.exists(output_file))

    def test_plot_stress_strain(self):
        """Test stress-strain plotting."""
        strain = np.linspace(0, 0.1, 100)
        stress = 100 * strain * (1 - 0.5 * strain)  # Nonlinear

        ss_data = {'strain': strain, 'stress': stress}

        output_file = plot_stress_strain(ss_data, "stress_strain.png")

        self.assertTrue(os.path.exists(output_file))
        self.assertGreater(os.path.getsize(output_file), 0)

    def test_plot_acf(self):
        """Test ACF plotting."""
        lag = np.arange(100)
        acf = np.exp(-lag / 20)

        acf_data = {'lag': lag, 'acf': acf, 'correlation_time': 20}

        output_file = plot_acf(acf_data, "acf.png")

        self.assertTrue(os.path.exists(output_file))
        self.assertGreater(os.path.getsize(output_file), 0)


class TestEdgeCases(unittest.TestCase):
    """Test edge cases and error handling."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.original_dir = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.original_dir)
        shutil.rmtree(self.test_dir)

    def test_parse_empty_file(self):
        """Test parsing empty files."""
        with open("empty.dat", "w") as f:
            f.write("")

        # These should return empty arrays, not crash
        rdf = parse_rdf_file("empty.dat")
        self.assertEqual(len(rdf['r']), 0)

        msd = parse_msd_file("empty.dat")
        self.assertEqual(len(msd['time']), 0)

    def test_parse_comments_only_file(self):
        """Test parsing file with only comments."""
        with open("comments.dat", "w") as f:
            f.write("# Comment 1\n# Comment 2\n# Comment 3\n")

        rdf = parse_rdf_file("comments.dat")
        self.assertEqual(len(rdf['r']), 0)

    def test_block_average_small_data(self):
        """Test block averaging with limited data."""
        data = np.array([1.0, 2.0, 3.0, 4.0, 5.0])

        result = block_average(data, num_blocks=2)

        self.assertEqual(len(result['block_means']), 2)

    def test_compute_gk_missing_params(self):
        """Test Green-Kubo with missing parameters raises error."""
        hfacf_data = np.array([[0, 1.0, 1.0, 1.0]])

        with self.assertRaises(ValueError):
            compute_thermal_conductivity_gk(hfacf_data, volume=1000.0)

    def test_compute_gk_empty_data(self):
        """Test Green-Kubo with empty HFACF data raises helpful error."""
        hfacf_data = np.empty((0, 4))

        with self.assertRaises(ValueError) as context:
            compute_thermal_conductivity_gk(hfacf_data, volume=1000.0, temp=1.0, timestep=0.005)

        self.assertIn("empty", str(context.exception).lower())

    def test_compute_gk_1d_data(self):
        """Test Green-Kubo with 1D data raises helpful error."""
        hfacf_data = np.array([1.0, 2.0, 3.0])  # Wrong shape

        with self.assertRaises(ValueError) as context:
            compute_thermal_conductivity_gk(hfacf_data, volume=1000.0, temp=1.0, timestep=0.005)

        self.assertIn("2D", str(context.exception))


def run_tests():
    """Run all tests and return results."""
    # Create test suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Add all test classes
    test_classes = [
        TestSetup,
        TestAtomCountDetection,
        TestParametricStudies,
        TestTemperatureProfile,
        TestGreenKubo,
        TestEnergyAnalysis,
        TestDumpFileParsing,
        TestRDFParsing,
        TestMSDParsing,
        TestStatisticalAnalysis,
        TestMechanicalProperties,
        TestSurfaceTension,
        TestDensityProfile,
        TestGyrationParsing,
        TestLogParsing,
        TestVisualization,
        TestEdgeCases,
    ]

    for test_class in test_classes:
        tests = loader.loadTestsFromTestCase(test_class)
        suite.addTests(tests)

    # Run tests with verbosity
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    return result


if __name__ == '__main__':
    result = run_tests()

    # Exit with appropriate code
    sys.exit(0 if result.wasSuccessful() else 1)
