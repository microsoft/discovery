"""Unit tests for tamgen_utils.py

Tests are organised in tiers:
  1. Pure-Python / RDKit tests that run WITHOUT TamGen installed
  2. Integration tests that require the full TamGen Docker environment
     (marked with @requires_tamgen)
"""

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path

# ---------------------------------------------------------------------------
# Ensure tamgen_utils is importable even outside the Docker container
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

# We need to guard imports that rely on packages only present in the container
try:
    from rdkit import Chem
    HAS_RDKIT = True
except ImportError:
    HAS_RDKIT = False

try:
    import torch
    HAS_TORCH = True
except ImportError:
    HAS_TORCH = False


def requires_rdkit(fn):
    return unittest.skipUnless(HAS_RDKIT, "rdkit not installed")(fn)


def requires_tamgen(fn):
    """Skip if the TamGen repo is not available (i.e. not inside Docker)."""
    tamgen_root = os.environ.get("TAMGEN_ROOT", "/app/TamGen")
    return unittest.skipUnless(
        os.path.isdir(tamgen_root), "TamGen not installed"
    )(fn)


# ============================================================================
# Tier 1 – Pure-Python / RDKit tests
# ============================================================================

class TestQuickSetup(unittest.TestCase):
    """Tests for quick_setup / quick_finish / save_final_results."""

    def test_quick_setup_creates_dirs(self):
        import tamgen_utils as tu

        with tempfile.TemporaryDirectory() as tmp:
            inp = os.path.join(tmp, "in")
            out = os.path.join(tmp, "out")
            wrk = os.path.join(tmp, "wrk")
            info = tu.quick_setup(input_dir=inp, output_dir=out, work_dir=wrk)

            self.assertTrue(os.path.isdir(inp))
            self.assertTrue(os.path.isdir(out))
            self.assertTrue(os.path.isdir(wrk))
            self.assertIn("tamgen_installed", info)

    def test_save_final_results(self):
        import tamgen_utils as tu

        with tempfile.TemporaryDirectory() as tmp:
            tu.quick_setup(
                input_dir=os.path.join(tmp, "in"),
                output_dir=tmp,
                work_dir=os.path.join(tmp, "wrk"),
            )
            path = tu.save_final_results(
                {"molecules": 5},
                output_files=["a.csv"],
                file_descriptions={"a.csv": "results"},
            )
            self.assertTrue(os.path.isfile(path))
            data = json.loads(Path(path).read_text())
            self.assertEqual(data["status"], "success")
            self.assertEqual(data["results"]["molecules"], 5)


@requires_rdkit
class TestMolProperties(unittest.TestCase):
    """Test _compute_mol_properties with known molecules."""

    def test_aspirin(self):
        from tamgen_utils import _compute_mol_properties

        props = _compute_mol_properties("CC(=O)Oc1ccccc1C(=O)O")
        self.assertTrue(props["valid"])
        self.assertAlmostEqual(props["molecular_weight"], 180.16, delta=0.1)
        self.assertEqual(props["hbd"], 1)
        self.assertEqual(props["hba"], 4)
        self.assertTrue(props["lipinski_pass"])
        self.assertGreater(props["qed"], 0)

    def test_invalid_smiles(self):
        from tamgen_utils import _compute_mol_properties

        props = _compute_mol_properties("NOT_A_SMILES")
        self.assertFalse(props["valid"])

    def test_caffeine(self):
        from tamgen_utils import _compute_mol_properties

        props = _compute_mol_properties("Cn1c(=O)c2c(ncn2C)n(C)c1=O")
        self.assertTrue(props["valid"])
        self.assertAlmostEqual(props["molecular_weight"], 194.19, delta=0.2)
        self.assertTrue(props["lipinski_pass"])

    def test_heavy_molecule_lipinski_fail(self):
        """A molecule with MW > 500 should have at least 1 Lipinski violation."""
        from tamgen_utils import _compute_mol_properties

        # Cyclosporin A fragment (~600 MW)
        big_smi = "CC(C)CC1NC(=O)C(CC(C)C)N(C)C(=O)C(CC(C)C)N(C)C(=O)C(CC(C)C)NC(=O)C(C(C)C)N(C)C(=O)C(CC(C)C)NC1=O"
        props = _compute_mol_properties(big_smi)
        if props["valid"]:
            self.assertGreater(props["lipinski_violations"], 0)


@requires_rdkit
class TestValidateMolecules(unittest.TestCase):

    def test_mixed_validity(self):
        from tamgen_utils import validate_molecules, quick_setup
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            quick_setup(
                os.path.join(tmp, "in"),
                os.path.join(tmp, "out"),
                os.path.join(tmp, "wrk"),
            )
        results = validate_molecules(["CCO", "INVALID", "c1ccccc1"])
        self.assertEqual(len(results), 3)
        self.assertTrue(results[0]["valid"])    # ethanol
        self.assertFalse(results[1]["valid"])   # invalid
        self.assertTrue(results[2]["valid"])    # benzene


@requires_rdkit
class TestComputeDiversity(unittest.TestCase):

    def test_identical_molecules(self):
        from tamgen_utils import compute_diversity

        result = compute_diversity(["CCO", "CCO", "CCO"])
        # Identical molecules → diversity = 0
        self.assertAlmostEqual(result["mean_diversity"], 0.0, places=3)

    def test_diverse_molecules(self):
        from tamgen_utils import compute_diversity

        smiles = [
            "c1ccccc1",      # benzene
            "CC(=O)O",       # acetic acid
            "C1CCCCC1",      # cyclohexane
            "c1ccncc1",      # pyridine
        ]
        result = compute_diversity(smiles)
        self.assertGreater(result["mean_diversity"], 0.3)
        self.assertEqual(result["n_valid"], 4)


@requires_rdkit
class TestSummarizeGeneration(unittest.TestCase):

    def test_summary(self):
        from tamgen_utils import summarize_generation

        mols = [
            {"smiles": "CCO", "valid": True, "molecular_weight": 46.07,
             "logp": -0.31, "qed": 0.4, "tpsa": 20.23, "heavy_atoms": 3,
             "lipinski_pass": True},
            {"smiles": "c1ccccc1", "valid": True, "molecular_weight": 78.11,
             "logp": 1.56, "qed": 0.44, "tpsa": 0.0, "heavy_atoms": 6,
             "lipinski_pass": True},
        ]
        summary = summarize_generation(mols)
        self.assertEqual(summary["valid_molecules"], 2)
        self.assertAlmostEqual(summary["validity_rate"], 1.0)
        self.assertEqual(summary["lipinski_pass_rate"], 1.0)


@requires_rdkit
class TestFilterMolecules(unittest.TestCase):

    def test_filter_by_mw(self):
        from tamgen_utils import filter_molecules, quick_setup
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            quick_setup(
                os.path.join(tmp, "in"),
                os.path.join(tmp, "out"),
                os.path.join(tmp, "wrk"),
            )
        mols = [
            {"smiles": "CCO", "valid": True, "molecular_weight": 46.07},
            {"smiles": "c1ccccc1", "valid": True, "molecular_weight": 78.11},
        ]
        filtered = filter_molecules(mols, mw_range=(50, 100))
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["smiles"], "c1ccccc1")


@requires_rdkit
class TestParseRawOutput(unittest.TestCase):

    def test_parse_hypothesis_lines(self):
        from tamgen_utils import _parse_raw_output

        raw = (
            "S-0\tsome source\n"
            "T-0\tsome target\n"
            "H-0\t-2.5\tC C O\n"
            "H-0\t-1.8\tC C N\n"
            "H-0\t-3.0\tINVALID_SMILES\n"
            "H-1\t-2.0\tc 1 c c c c c 1\n"
        )
        mols = _parse_raw_output(raw)
        # Should have at least ethanol (CCO), methylamine (CCN), benzene
        valid_smiles = {m["smiles"] for m in mols}
        self.assertIn("CCO", valid_smiles)
        self.assertIn("CCN", valid_smiles)


# ============================================================================
# Tier 2 – Data preparation (subprocess, needs TamGen repo)
# ============================================================================

class TestDataPrepSubprocess(unittest.TestCase):
    """Test that data-preparation functions build correct subprocess commands."""

    @patch("tamgen_utils.subprocess.run")
    def test_prepare_pdb_id_command(self, mock_run):
        import tamgen_utils as tu

        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        with tempfile.TemporaryDirectory() as tmp:
            tu._config["data_dir"] = tmp
            result = tu.prepare_pocket_from_pdb_id("1iep", data_dir=tmp)

            self.assertEqual(result["subset_name"], "gen_1iep")
            self.assertTrue(mock_run.called)
            cmd = mock_run.call_args[0][0]
            self.assertIn("prepare_pdb_ids.py", cmd[1])

    @patch("tamgen_utils.subprocess.run")
    def test_prepare_center_command(self, mock_run):
        import tamgen_utils as tu

        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        with tempfile.TemporaryDirectory() as tmp:
            tu._config["data_dir"] = tmp
            result = tu.prepare_pocket_from_center(
                "1iep", 10.0, 20.0, 30.0, data_dir=tmp
            )
            self.assertEqual(result["subset_name"], "gen_1iep")
            cmd = mock_run.call_args[0][0]
            self.assertIn("prepare_pdb_ids_center.py", cmd[1])

    @patch("tamgen_utils.subprocess.run")
    def test_prepare_scaffold_command(self, mock_run):
        import tamgen_utils as tu

        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        with tempfile.TemporaryDirectory() as tmp:
            tu._config["data_dir"] = tmp
            result = tu.prepare_pocket_with_scaffold(
                "1iep", 10.0, 20.0, 30.0, "c1ccccc1", data_dir=tmp
            )
            self.assertEqual(result["subset_name"], "gen_1iep")
            cmd = mock_run.call_args[0][0]
            self.assertIn("prepare_pdb_ids_center_scaffold.py", cmd[1])

    @patch("tamgen_utils.subprocess.run")
    def test_data_prep_raises_on_failure(self, mock_run):
        import tamgen_utils as tu

        mock_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="Error: PDB not found"
        )
        with tempfile.TemporaryDirectory() as tmp:
            tu._config["data_dir"] = tmp
            with self.assertRaises(RuntimeError):
                tu.prepare_pocket_from_pdb_id("XXXX", data_dir=tmp)


# ============================================================================
# Tier 3 – Full integration (needs Docker container with GPU)
# ============================================================================

@requires_tamgen
class TestIntegrationGeneration(unittest.TestCase):
    """End-to-end test inside the TamGen Docker container."""

    def test_generate_from_pdb(self):
        """Generate molecules for PDB 8fln (used in TamGen demo)."""
        from tamgen_utils import (
            quick_setup,
            prepare_pocket_from_pdb_id,
            generate_molecules,
            summarize_generation,
            quick_finish,
        )

        with tempfile.TemporaryDirectory() as tmp:
            info = quick_setup(
                input_dir=os.path.join(tmp, "in"),
                output_dir=os.path.join(tmp, "out"),
                work_dir=os.path.join(tmp, "wrk"),
            )
            if not info.get("cuda_available"):
                self.skipTest("No GPU available")

            pocket = prepare_pocket_from_pdb_id("8fln")
            molecules = generate_molecules(
                pocket["data_dir"],
                pocket["subset_name"],
                num_molecules=5,
                beam_size=5,
                max_seeds=5,
            )
            self.assertGreater(len(molecules), 0)

            summary = summarize_generation(molecules)
            self.assertGreater(summary["valid_molecules"], 0)

            quick_finish()


if __name__ == "__main__":
    unittest.main()
