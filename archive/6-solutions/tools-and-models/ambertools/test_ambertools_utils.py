#!/usr/bin/env python3
"""
Tests for ambertools_utils.py

Run with: python -m pytest test_ambertools_utils.py -v
Or: python test_ambertools_utils.py
"""

import os
import sys
import json
import tempfile
import shutil
import unittest

# Set matplotlib backend before any imports that might trigger it
os.environ['MPLBACKEND'] = 'Agg'

import numpy as np

# Add current directory to path for import
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ambertools_utils import (
    # Config
    NUM_CORES, FF_LEAPRC_MAP, WATER_MODEL_MAP, WATER_BOX_MAP,
    # Setup
    save_final_results, NumpyJSONEncoder,
    # Preparation
    write_tleap_script, write_minimization_input, write_heating_input,
    write_equilibration_input, write_production_input,
    # Parsing
    parse_mdout, parse_cpptraj_dat, parse_hbond_output, parse_tleap_log,
    # Analysis
    analyze_energy, block_average,
    # Visualization
    plot_energy, plot_rmsd, plot_rmsf, plot_hbonds, plot_rdf, plot_secondary_structure,
)


# ============= SAMPLE DATA GENERATORS =============

def make_mdout_minimization(filepath):
    """Create a sample sander minimization output file."""
    content = """
   1.  RESOURCE   USE:

   NSTEP       ENERGY          RMS            GMAX         NAME    NUMBER
      1      -3.4567E+04     1.2345E+01     5.6789E+01     O       1234
   NSTEP       ENERGY          RMS            GMAX         NAME    NUMBER
    500      -4.5678E+04     3.4567E+00     1.2345E+01     CA      5678
   NSTEP       ENERGY          RMS            GMAX         NAME    NUMBER
   1000      -4.8901E+04     9.8765E-01     3.4567E+00     N       9012

   FINAL RESULTS


                    FINAL RESULTS

   Minimization exiting with status: Converged
"""
    with open(filepath, 'w') as f:
        f.write(content)


def make_mdout_dynamics(filepath):
    """Create a sample sander MD output file."""
    content = """
   NSTEP =        0   TIME(PS) =       0.000  TEMP(K) =     0.00  PRESS =     0.0
 Etot   =    -34567.1234  EKtot   =         0.0000  EPtot      =    -34567.1234
 BOND   =       123.4567  ANGLE   =       234.5678  DIHED      =       345.6789
 1-4 NB =       456.7890  1-4 EEL =      1234.5678  VDWAALS    =     -5678.9012
 EELEC  =    -31234.5678  EHBOND  =         0.0000  RESTRAINT  =         0.0000
 EKCMT  =         0.0000  VIRIAL  =         0.0000  VOLUME     =    123456.7890
                                                    Density    =         0.9980
 Ewald error estimate:   0.1234E-04
 ------------------------------------------------------------------------------

   NSTEP =      500   TIME(PS) =       1.000  TEMP(K) =   298.15  PRESS =   -12.3
 Etot   =    -28901.2345  EKtot   =      5678.9012  EPtot      =    -34580.1357
 BOND   =       234.5678  ANGLE   =       345.6789  DIHED      =       456.7890
 1-4 NB =       567.8901  1-4 EEL =      1345.6789  VDWAALS    =     -5789.0123
 EELEC  =    -31345.6789  EHBOND  =         0.0000  RESTRAINT  =         0.0000
 EKCMT  =      2345.6789  VIRIAL  =      2456.7890  VOLUME     =    123400.1234
 PRESS  =       -12.3000
                                                    Density    =         0.9985
 Ewald error estimate:   0.1234E-04
 ------------------------------------------------------------------------------

   NSTEP =     1000   TIME(PS) =       2.000  TEMP(K) =   300.00  PRESS =     5.6
 Etot   =    -28890.3456  EKtot   =      5690.1234  EPtot      =    -34580.4690
 BOND   =       240.1234  ANGLE   =       350.2345  DIHED      =       460.3456
 1-4 NB =       570.4567  1-4 EEL =      1350.5678  VDWAALS    =     -5800.1234
 EELEC  =    -31350.2345  EHBOND  =         0.0000  RESTRAINT  =         0.0000
 EKCMT  =      2350.1234  VIRIAL  =      2300.5678  VOLUME     =    123450.5678
 PRESS  =         5.6000
                                                    Density    =         0.9982
 Ewald error estimate:   0.1234E-04
 ------------------------------------------------------------------------------
"""
    with open(filepath, 'w') as f:
        f.write(content)


def make_cpptraj_rmsd(filepath):
    """Create a sample cpptraj RMSD output file."""
    content = """#Frame rmsd_calc
1 0.000
2 1.234
3 1.567
4 1.890
5 2.123
6 2.345
7 2.456
8 2.567
9 2.678
10 2.789
"""
    with open(filepath, 'w') as f:
        f.write(content)


def make_cpptraj_rmsf(filepath):
    """Create a sample cpptraj RMSF output file."""
    content = """#Atom rmsf_calc
1 0.456
2 0.567
3 0.678
4 0.890
5 1.234
6 1.567
7 1.123
8 0.890
9 0.678
10 0.567
"""
    with open(filepath, 'w') as f:
        f.write(content)


def make_cpptraj_hbond_avg(filepath):
    """Create a sample cpptraj hbond avgout file."""
    content = """#Acceptor DonorH Donor Frames Frac AvgDist AvgAng
:1@O :5@H :5@N 80 0.8000 2.890 165.234
:3@OD1 :7@HG :7@SG 45 0.4500 3.012 158.567
:10@O :2@H :2@N 90 0.9000 2.845 170.123
"""
    with open(filepath, 'w') as f:
        f.write(content)


def make_cpptraj_rdf(filepath):
    """Create a sample cpptraj RDF output file."""
    content = """#Bin rdf_calc
0.100 0.000
0.200 0.012
0.300 0.045
0.400 0.123
0.500 0.345
1.000 0.890
1.500 1.234
2.000 1.567
2.500 2.345
2.700 3.456
2.800 2.890
3.000 1.890
3.500 1.234
4.000 1.056
5.000 1.012
6.000 1.001
"""
    with open(filepath, 'w') as f:
        f.write(content)


def make_cpptraj_distance(filepath):
    """Create a sample cpptraj distance output file."""
    content = """#Frame dist_calc
1 3.456
2 3.567
3 3.678
4 3.789
5 3.890
6 3.345
7 3.234
8 3.456
9 3.567
10 3.678
"""
    with open(filepath, 'w') as f:
        f.write(content)


def make_tleap_log(filepath):
    """Create a sample tleap log file."""
    content = """Welcome to LEaP!
Loading parameters: /opt/conda/dat/leap/parm/parm10.dat
Loading library: /opt/conda/dat/leap/lib/amino12.lib
Loading: ./system_clean.pdb
WARNING: The unperturbed charge of the unit: -2.000000 is not zero.
Total atoms in mol: 1234
Total residues in mol: 80
Writing parm file: system.prmtop
Writing coordinate file: system.inpcrd
   Quit
"""
    with open(filepath, 'w') as f:
        f.write(content)


def make_cpptraj_secstruct(filepath):
    """Create a sample cpptraj secondary structure output file."""
    content = """#Frame ss_helix ss_sheet ss_coil
1 0.45 0.15 0.40
2 0.47 0.13 0.40
3 0.48 0.12 0.40
4 0.46 0.14 0.40
5 0.45 0.15 0.40
"""
    with open(filepath, 'w') as f:
        f.write(content)


# ============= TEST CLASSES =============

class TestSetup(unittest.TestCase):
    """Test configuration and constants."""

    def test_num_cores_detected(self):
        """NUM_CORES should be a positive integer."""
        self.assertIsInstance(NUM_CORES, int)
        self.assertGreater(NUM_CORES, 0)

    def test_ff_leaprc_map_completeness(self):
        """FF_LEAPRC_MAP should contain all major force fields."""
        required_ffs = ['ff14SB', 'ff19SB', 'GAFF', 'GAFF2', 'OL15', 'RNA.OL3', 'Lipid21']
        for ff in required_ffs:
            self.assertIn(ff, FF_LEAPRC_MAP, f"Missing force field: {ff}")
            self.assertTrue(FF_LEAPRC_MAP[ff].startswith('leaprc.'),
                            f"FF {ff} leaprc should start with 'leaprc.'")

    def test_water_model_map_completeness(self):
        """WATER_MODEL_MAP should contain all major water models."""
        required_waters = ['TIP3P', 'SPC/E', 'OPC', 'TIP4P-Ew']
        for wm in required_waters:
            self.assertIn(wm, WATER_MODEL_MAP, f"Missing water model: {wm}")
            self.assertTrue(WATER_MODEL_MAP[wm].startswith('leaprc.water.'),
                            f"Water model {wm} leaprc should start with 'leaprc.water.'")

    def test_water_box_map_completeness(self):
        """WATER_BOX_MAP should have an entry for every WATER_MODEL_MAP key."""
        for wm in WATER_MODEL_MAP:
            self.assertIn(wm, WATER_BOX_MAP, f"Missing water box for model: {wm}")
            self.assertTrue(WATER_BOX_MAP[wm].endswith('BOX'),
                            f"Water box {wm} should end with 'BOX'")


class TestSaveFinalResults(unittest.TestCase):
    """Test save_final_results function."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.original_dir = os.getcwd()
        self.output_dir = os.path.join(self.test_dir, "output")
        os.makedirs(self.output_dir)

    def tearDown(self):
        os.chdir(self.original_dir)
        shutil.rmtree(self.test_dir)

    def test_save_final_results_basic(self):
        """Test basic save_final_results functionality."""
        import ambertools_utils
        orig = ambertools_utils.OUTPUT_DIR
        orig_configured = ambertools_utils._DIRS_CONFIGURED
        ambertools_utils.OUTPUT_DIR = self.output_dir
        ambertools_utils._DIRS_CONFIGURED = True
        try:
            results = {"energy": -45678.0, "method": "minimization"}
            path = save_final_results(results)
            self.assertTrue(os.path.exists(path))
            with open(path, 'r') as f:
                data = json.load(f)
            self.assertEqual(data['status'], 'completed')
            self.assertEqual(data['summary']['energy'], -45678.0)
        finally:
            ambertools_utils.OUTPUT_DIR = orig
            ambertools_utils._DIRS_CONFIGURED = orig_configured

    def test_save_final_results_with_files(self):
        """Test save_final_results with output files."""
        import ambertools_utils
        orig = ambertools_utils.OUTPUT_DIR
        orig_configured = ambertools_utils._DIRS_CONFIGURED
        ambertools_utils.OUTPUT_DIR = self.output_dir
        ambertools_utils._DIRS_CONFIGURED = True
        try:
            results = {"rmsd_mean": 2.5}
            output_files = {"plot": "/output/rmsd.png"}
            file_descriptions = {"plot": "RMSD vs time plot"}
            path = save_final_results(results, output_files, file_descriptions)
            with open(path, 'r') as f:
                data = json.load(f)
            self.assertIn('output_files', data)
            self.assertIn('file_descriptions', data)
        finally:
            ambertools_utils.OUTPUT_DIR = orig
            ambertools_utils._DIRS_CONFIGURED = orig_configured

    def test_save_final_results_numpy_types(self):
        """Test save_final_results handles numpy types."""
        import ambertools_utils
        orig = ambertools_utils.OUTPUT_DIR
        orig_configured = ambertools_utils._DIRS_CONFIGURED
        ambertools_utils.OUTPUT_DIR = self.output_dir
        ambertools_utils._DIRS_CONFIGURED = True
        try:
            results = {
                "energy": np.float64(-45678.1234),
                "n_atoms": np.int64(1234),
                "temps": np.array([300.0, 301.0, 299.5]),
                "converged": np.bool_(True),
            }
            path = save_final_results(results)
            with open(path, 'r') as f:
                data = json.load(f)
            self.assertIsInstance(data['summary']['energy'], float)
            self.assertIsInstance(data['summary']['n_atoms'], int)
            self.assertIsInstance(data['summary']['temps'], list)
            self.assertIsInstance(data['summary']['converged'], bool)
        finally:
            ambertools_utils.OUTPUT_DIR = orig
            ambertools_utils._DIRS_CONFIGURED = orig_configured

    def test_save_final_results_custom_status(self):
        """Test save_final_results with custom status."""
        import ambertools_utils
        orig = ambertools_utils.OUTPUT_DIR
        orig_configured = ambertools_utils._DIRS_CONFIGURED
        ambertools_utils.OUTPUT_DIR = self.output_dir
        ambertools_utils._DIRS_CONFIGURED = True
        try:
            path = save_final_results({"error": "convergence failed"}, status="failed")
            with open(path, 'r') as f:
                data = json.load(f)
            self.assertEqual(data['status'], 'failed')
        finally:
            ambertools_utils.OUTPUT_DIR = orig
            ambertools_utils._DIRS_CONFIGURED = orig_configured


class TestSystemPreparation(unittest.TestCase):
    """Test system preparation functions."""

    def test_write_tleap_script_protein(self):
        """Test tleap script generation for a basic protein."""
        script = write_tleap_script(
            pdb_file="protein.pdb",
            force_field="ff14SB",
            water_model="TIP3P",
            box_buffer=10.0,
        )
        self.assertIn("source leaprc.protein.ff14SB", script)
        self.assertIn("source leaprc.water.tip3p", script)
        self.assertIn("loadPdb protein.pdb", script)
        self.assertIn("solvateOct", script)
        self.assertIn("TIP3PBOX", script)
        self.assertIn("addIons mol Na+ 0", script)
        self.assertIn("saveAmberParm", script)
        self.assertIn("quit", script)

    def test_write_tleap_script_with_ligand(self):
        """Test tleap script generation for protein-ligand system."""
        script = write_tleap_script(
            pdb_file="complex.pdb",
            force_field="ff14SB",
            water_model="TIP3P",
            ligand_mol2="ligand.mol2",
            ligand_frcmod="ligand.frcmod",
            ligand_resname="LIG",
        )
        self.assertIn("source leaprc.gaff2", script)
        self.assertIn("loadAmberParams ligand.frcmod", script)
        self.assertIn("LIG = loadMol2 ligand.mol2", script)
        self.assertIn("source leaprc.protein.ff14SB", script)

    def test_write_tleap_script_dna(self):
        """Test tleap script generation for DNA."""
        script = write_tleap_script(
            pdb_file="dna.pdb",
            force_field="OL15",
            water_model="SPC/E",
        )
        self.assertIn("source leaprc.DNA.OL15", script)
        self.assertIn("source leaprc.water.spce", script)

    def test_write_tleap_script_rectangular_box(self):
        """Test tleap script with rectangular box."""
        script = write_tleap_script(
            pdb_file="protein.pdb",
            box_type="box",
        )
        self.assertIn("solvateBox", script)
        self.assertNotIn("solvateOct", script)

    def test_write_tleap_script_no_neutralize(self):
        """Test tleap script without neutralization."""
        script = write_tleap_script(
            pdb_file="protein.pdb",
            neutralize=False,
        )
        self.assertNotIn("addIons", script)

    def test_write_tleap_script_extra_commands(self):
        """Test tleap script with extra commands."""
        script = write_tleap_script(
            pdb_file="protein.pdb",
            extra_commands=["bond mol.123.SG mol.456.SG", "set mol.1 cap ACE"],
        )
        self.assertIn("bond mol.123.SG mol.456.SG", script)
        self.assertIn("set mol.1 cap ACE", script)

    def test_write_minimization_input(self):
        """Test minimization input file generation."""
        mdin = write_minimization_input(max_cycles=10000, steepest_descent=5000)
        self.assertIn("imin=1", mdin)
        self.assertIn("maxcyc=10000", mdin)
        self.assertIn("ncyc=5000", mdin)
        self.assertIn("ntb=1", mdin)

    def test_write_minimization_input_with_restraints(self):
        """Test minimization with restraints."""
        mdin = write_minimization_input(
            restraint_wt=10.0,
            restraint_mask="@CA,C,N,O",
        )
        self.assertIn("ntr=1", mdin)

    def test_write_minimization_input_no_restraints(self):
        """Test minimization without restraints."""
        mdin = write_minimization_input(restraint_wt=0.0)
        self.assertIn("ntr=0", mdin)

    def test_write_heating_input(self):
        """Test NVT heating input generation."""
        mdin = write_heating_input(target_temp=300.0, nsteps=25000, dt=0.002)
        self.assertIn("imin=0", mdin)
        self.assertIn("nstlim=25000", mdin)
        self.assertIn("dt=0.002", mdin)
        self.assertIn("temp0=300.0", mdin)
        self.assertIn("ntt=3", mdin)
        self.assertIn("ntb=1", mdin)
        self.assertIn("ntp=0", mdin)  # NVT: no pressure control
        self.assertIn("irest=0", mdin)  # New velocities

    def test_write_equilibration_input(self):
        """Test NPT equilibration input generation."""
        mdin = write_equilibration_input(target_temp=300.0, target_pressure=1.0, nsteps=50000)
        self.assertIn("imin=0", mdin)
        self.assertIn("nstlim=50000", mdin)
        self.assertIn("temp0=300.0", mdin)
        self.assertIn("ntp=1", mdin)  # NPT: pressure control
        self.assertIn("ntb=2", mdin)  # Constant pressure periodic
        self.assertIn("irest=1", mdin)  # Restart from previous
        self.assertIn("barostat=2", mdin)

    def test_write_production_input(self):
        """Test production MD input generation."""
        mdin = write_production_input(nsteps=500000, dt=0.002)
        self.assertIn("imin=0", mdin)
        self.assertIn("nstlim=500000", mdin)
        self.assertIn("dt=0.002", mdin)
        self.assertIn("ntp=1", mdin)
        self.assertIn("ntr=0", mdin)  # No restraints in production
        self.assertIn("iwrap=1", mdin)

    def test_write_production_input_custom(self):
        """Test production MD with custom parameters."""
        mdin = write_production_input(
            target_temp=310.0,
            nsteps=1000000,
            ntwx=10000,
            ntpr=1000,
            cutoff=12.0,
            iwrap=0,
        )
        self.assertIn("temp0=310.0", mdin)
        self.assertIn("nstlim=1000000", mdin)
        self.assertIn("ntwx=10000", mdin)
        self.assertIn("ntpr=1000", mdin)
        self.assertIn("cut=12.0", mdin)
        self.assertIn("iwrap=0", mdin)


class TestParseMdout(unittest.TestCase):
    """Test sander output parsing."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_parse_mdout_minimization(self):
        """Test parsing minimization output."""
        filepath = os.path.join(self.test_dir, "min.mdout")
        make_mdout_minimization(filepath)
        data = parse_mdout(filepath)
        self.assertTrue(data['is_minimization'])
        self.assertEqual(len(data['steps']), 3)
        self.assertAlmostEqual(data['etot'][0], -3.4567e4, places=0)
        self.assertAlmostEqual(data['etot'][2], -4.8901e4, places=0)

    def test_parse_mdout_dynamics(self):
        """Test parsing MD dynamics output."""
        filepath = os.path.join(self.test_dir, "md.mdout")
        make_mdout_dynamics(filepath)
        data = parse_mdout(filepath)
        self.assertFalse(data['is_minimization'])
        self.assertTrue(len(data['steps']) > 0)
        self.assertTrue(len(data['etot']) > 0)
        self.assertTrue(len(data['temp']) > 0)

    def test_parse_mdout_missing_file(self):
        """Test parsing non-existent file raises error."""
        with self.assertRaises(FileNotFoundError):
            parse_mdout(os.path.join(self.test_dir, "nonexistent.mdout"))

    def test_parse_mdout_empty_file(self):
        """Test parsing empty file returns empty arrays."""
        filepath = os.path.join(self.test_dir, "empty.mdout")
        with open(filepath, 'w') as f:
            f.write("")
        data = parse_mdout(filepath)
        self.assertEqual(len(data['etot']), 0)


class TestParseCpptraj(unittest.TestCase):
    """Test cpptraj output parsing."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_parse_cpptraj_rmsd(self):
        """Test parsing cpptraj RMSD output."""
        filepath = os.path.join(self.test_dir, "rmsd.dat")
        make_cpptraj_rmsd(filepath)
        data = parse_cpptraj_dat(filepath)
        self.assertIn('Frame', data)
        self.assertIn('rmsd_calc', data)
        self.assertEqual(len(data['rmsd_calc']), 10)
        self.assertAlmostEqual(data['rmsd_calc'][0], 0.0, places=3)
        self.assertAlmostEqual(data['rmsd_calc'][1], 1.234, places=3)

    def test_parse_cpptraj_rmsf(self):
        """Test parsing cpptraj RMSF output."""
        filepath = os.path.join(self.test_dir, "rmsf.dat")
        make_cpptraj_rmsf(filepath)
        data = parse_cpptraj_dat(filepath)
        self.assertIn('Atom', data)
        self.assertIn('rmsf_calc', data)
        self.assertEqual(len(data['rmsf_calc']), 10)

    def test_parse_cpptraj_rdf(self):
        """Test parsing cpptraj RDF output."""
        filepath = os.path.join(self.test_dir, "rdf.dat")
        make_cpptraj_rdf(filepath)
        data = parse_cpptraj_dat(filepath)
        self.assertIn('Bin', data)
        self.assertIn('rdf_calc', data)
        self.assertTrue(len(data['rdf_calc']) > 0)

    def test_parse_cpptraj_distance(self):
        """Test parsing cpptraj distance output."""
        filepath = os.path.join(self.test_dir, "distance.dat")
        make_cpptraj_distance(filepath)
        data = parse_cpptraj_dat(filepath)
        self.assertIn('Frame', data)
        self.assertIn('dist_calc', data)
        self.assertEqual(len(data['dist_calc']), 10)
        self.assertAlmostEqual(data['dist_calc'][0], 3.456, places=3)

    def test_parse_cpptraj_secondary_structure(self):
        """Test parsing cpptraj secondary structure output."""
        filepath = os.path.join(self.test_dir, "secstruct.dat")
        make_cpptraj_secstruct(filepath)
        data = parse_cpptraj_dat(filepath)
        self.assertIn('Frame', data)
        self.assertTrue(any('ss_' in k for k in data))

    def test_parse_cpptraj_missing_file(self):
        """Test parsing non-existent cpptraj file."""
        with self.assertRaises(FileNotFoundError):
            parse_cpptraj_dat(os.path.join(self.test_dir, "nonexistent.dat"))

    def test_parse_cpptraj_empty_file(self):
        """Test parsing empty cpptraj file."""
        filepath = os.path.join(self.test_dir, "empty.dat")
        with open(filepath, 'w') as f:
            f.write("")
        data = parse_cpptraj_dat(filepath)
        self.assertEqual(len(data), 0)

    def test_parse_cpptraj_comments_only(self):
        """Test parsing file with only comments."""
        filepath = os.path.join(self.test_dir, "comments.dat")
        with open(filepath, 'w') as f:
            f.write("#Frame rmsd\n# This is a comment\n")
        data = parse_cpptraj_dat(filepath)
        self.assertEqual(len(data), 0)


class TestParseHbond(unittest.TestCase):
    """Test hbond output parsing."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_parse_hbond_output(self):
        """Test parsing hbond average output."""
        filepath = os.path.join(self.test_dir, "hbonds_avg.dat")
        make_cpptraj_hbond_avg(filepath)
        data = parse_hbond_output(filepath)
        self.assertIn('hbonds', data)
        self.assertIn('n_hbonds', data)
        self.assertEqual(data['n_hbonds'], 3)
        self.assertTrue(len(data['hbonds']) > 0)

    def test_parse_hbond_missing_file(self):
        """Test parsing non-existent hbond file."""
        with self.assertRaises(FileNotFoundError):
            parse_hbond_output(os.path.join(self.test_dir, "nonexistent.dat"))


class TestParseTleapLog(unittest.TestCase):
    """Test tleap log parsing."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_parse_tleap_log(self):
        """Test parsing tleap log file."""
        filepath = os.path.join(self.test_dir, "leap.log")
        make_tleap_log(filepath)
        info = parse_tleap_log(filepath)
        self.assertEqual(info['n_atoms'], 1234)
        self.assertEqual(info['n_residues'], 80)
        self.assertTrue(len(info['warnings']) > 0)

    def test_parse_tleap_log_missing(self):
        """Test parsing non-existent tleap log."""
        info = parse_tleap_log(os.path.join(self.test_dir, "nonexistent.log"))
        self.assertEqual(info['n_atoms'], 0)
        self.assertEqual(len(info['warnings']), 0)


class TestAnalysis(unittest.TestCase):
    """Test analysis functions."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_analyze_energy(self):
        """Test energy analysis from MD output."""
        filepath = os.path.join(self.test_dir, "md.mdout")
        make_mdout_dynamics(filepath)
        result = analyze_energy(filepath)
        self.assertIn('mean_etot', result)
        self.assertIn('n_records', result)
        self.assertTrue(result['n_records'] > 0)

    def test_analyze_energy_minimization(self):
        """Test energy analysis from minimization output."""
        filepath = os.path.join(self.test_dir, "min.mdout")
        make_mdout_minimization(filepath)
        result = analyze_energy(filepath)
        self.assertTrue(result['is_minimization'])
        self.assertEqual(result['n_records'], 3)

    def test_block_average(self):
        """Test block averaging."""
        data = np.random.normal(300.0, 5.0, 1000)
        result = block_average(data, num_blocks=10)
        self.assertIn('mean', result)
        self.assertIn('std_err', result)
        self.assertIn('block_means', result)
        self.assertEqual(len(result['block_means']), 10)
        self.assertEqual(result['block_size'], 100)
        self.assertAlmostEqual(result['mean'], 300.0, delta=2.0)
        self.assertTrue(result['std_err'] > 0)

    def test_block_average_small_data(self):
        """Test block averaging with very small dataset."""
        data = np.array([1.0, 2.0, 3.0])
        result = block_average(data, num_blocks=10)
        self.assertIn('mean', result)
        self.assertAlmostEqual(result['mean'], 2.0, places=5)

    def test_block_average_single_value(self):
        """Test block averaging with single value."""
        data = np.array([42.0])
        result = block_average(data, num_blocks=5)
        self.assertAlmostEqual(result['mean'], 42.0, places=5)


class TestVisualization(unittest.TestCase):
    """Test visualization functions."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.output_dir = os.path.join(self.test_dir, "output")
        os.makedirs(self.output_dir)
        # Set up module state for output
        import ambertools_utils
        self._orig_output = ambertools_utils.OUTPUT_DIR
        self._orig_configured = ambertools_utils._DIRS_CONFIGURED
        ambertools_utils.OUTPUT_DIR = self.output_dir
        ambertools_utils._DIRS_CONFIGURED = True

    def tearDown(self):
        import ambertools_utils
        ambertools_utils.OUTPUT_DIR = self._orig_output
        ambertools_utils._DIRS_CONFIGURED = self._orig_configured
        shutil.rmtree(self.test_dir)

    def test_plot_energy(self):
        """Test energy plot creation."""
        filepath = os.path.join(self.test_dir, "md.mdout")
        make_mdout_dynamics(filepath)
        data = parse_mdout(filepath)
        output_file = "test_energy.png"
        result = plot_energy(data, output_file)
        self.assertTrue(os.path.exists(result))

    def test_plot_rmsd(self):
        """Test RMSD plot creation."""
        filepath = os.path.join(self.test_dir, "rmsd.dat")
        make_cpptraj_rmsd(filepath)
        data = parse_cpptraj_dat(filepath)
        if 'rmsd_calc' in data:
            data['rmsd'] = data.pop('rmsd_calc')
        # Column headers already have '#' stripped by parse_cpptraj_dat
        output_file = "test_rmsd.png"
        result = plot_rmsd(data, output_file)
        self.assertTrue(os.path.exists(result))

    def test_plot_rmsf(self):
        """Test RMSF plot creation."""
        filepath = os.path.join(self.test_dir, "rmsf.dat")
        make_cpptraj_rmsf(filepath)
        data = parse_cpptraj_dat(filepath)
        if 'rmsf_calc' in data:
            data['rmsf'] = data.pop('rmsf_calc')
        output_file = "test_rmsf.png"
        result = plot_rmsf(data, output_file)
        self.assertTrue(os.path.exists(result))

    def test_plot_hbonds(self):
        """Test hydrogen bond plot creation."""
        data = {
            '#Frame': np.arange(1, 101),
            'hb_total': np.random.randint(10, 30, 100).astype(float),
        }
        output_file = "test_hbonds.png"
        result = plot_hbonds(data, output_file)
        self.assertTrue(os.path.exists(result))

    def test_plot_rdf(self):
        """Test RDF plot creation."""
        filepath = os.path.join(self.test_dir, "rdf.dat")
        make_cpptraj_rdf(filepath)
        data = parse_cpptraj_dat(filepath)
        output_file = "test_rdf.png"
        result = plot_rdf(data, output_file)
        self.assertTrue(os.path.exists(result))

    def test_plot_secondary_structure(self):
        """Test secondary structure plot creation."""
        filepath = os.path.join(self.test_dir, "secstruct.dat")
        make_cpptraj_secstruct(filepath)
        data = parse_cpptraj_dat(filepath)
        output_file = "test_secstruct.png"
        result = plot_secondary_structure(data, output_file)
        self.assertTrue(os.path.exists(result))


class TestNumpyJSONEncoder(unittest.TestCase):
    """Test NumpyJSONEncoder."""

    def test_encode_float64(self):
        data = {"val": np.float64(3.14)}
        result = json.loads(json.dumps(data, cls=NumpyJSONEncoder))
        self.assertIsInstance(result['val'], float)

    def test_encode_int64(self):
        data = {"val": np.int64(42)}
        result = json.loads(json.dumps(data, cls=NumpyJSONEncoder))
        self.assertIsInstance(result['val'], int)

    def test_encode_ndarray(self):
        data = {"vals": np.array([1.0, 2.0, 3.0])}
        result = json.loads(json.dumps(data, cls=NumpyJSONEncoder))
        self.assertIsInstance(result['vals'], list)
        self.assertEqual(len(result['vals']), 3)

    def test_encode_bool(self):
        data = {"flag": np.bool_(True)}
        result = json.loads(json.dumps(data, cls=NumpyJSONEncoder))
        self.assertIsInstance(result['flag'], bool)

    def test_encode_regular_types(self):
        data = {"str": "hello", "int": 42, "float": 3.14}
        result = json.loads(json.dumps(data, cls=NumpyJSONEncoder))
        self.assertEqual(result, data)


class TestEdgeCases(unittest.TestCase):
    """Test edge cases and error handling."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_parse_mdout_partial_data(self):
        """Test parsing mdout with partial/incomplete data."""
        filepath = os.path.join(self.test_dir, "partial.mdout")
        with open(filepath, 'w') as f:
            f.write("""
   NSTEP =        0   TIME(PS) =       0.000  TEMP(K) =     0.00  PRESS =     0.0
 Etot   =    -34567.1234  EKtot   =         0.0000  EPtot      =    -34567.1234
Some garbage line
More garbage
""")
        data = parse_mdout(filepath)
        self.assertTrue(len(data['etot']) >= 1)

    def test_write_tleap_script_all_force_fields(self):
        """Verify all force fields in FF_LEAPRC_MAP produce valid scripts."""
        for ff_name, ff_leaprc in FF_LEAPRC_MAP.items():
            script = write_tleap_script(pdb_file="test.pdb", force_field=ff_name)
            self.assertIn(f"source {ff_leaprc}", script,
                          f"Force field {ff_name} not correctly mapped to {ff_leaprc}")

    def test_write_tleap_script_all_water_models(self):
        """Verify all water models produce valid scripts."""
        for wm_name, wm_leaprc in WATER_MODEL_MAP.items():
            script = write_tleap_script(pdb_file="test.pdb", water_model=wm_name)
            self.assertIn(f"source {wm_leaprc}", script,
                          f"Water model {wm_name} not correctly mapped to {wm_leaprc}")
            # Also check that box model is included
            expected_box = WATER_BOX_MAP[wm_name]
            self.assertIn(expected_box, script,
                          f"Water box {expected_box} not in script for {wm_name}")

    def test_block_average_empty_array(self):
        """Test block average with empty data."""
        data = np.array([])
        result = block_average(data, num_blocks=10)
        # Should not crash - returns nan or 0
        self.assertIn('mean', result)


if __name__ == '__main__':
    unittest.main()
