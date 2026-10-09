"""Regression tests for helper wiring; dynamics tests use the real toolkit."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import alchemi_utils as u


class OutputContractTests(unittest.TestCase):
    def setUp(self):
        self.cwd = os.getcwd()
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.work, self.out = self.root / "work", self.root / "out"
        with patch.object(u, "log_gpu_info", return_value={}):
            u.quick_setup(str(self.root / "input"), str(self.out), str(self.work))

    def tearDown(self):
        os.chdir(self.cwd)
        self.tmp.cleanup()

    def test_npz_python_text_declared_and_reverified(self):
        files = {}
        for suffix in ("npz", "py", "txt", "unusual"):
            p = self.work / ("evidence." + suffix)
            p.write_bytes(b"first")
            files[suffix] = str(p)
        mapped = u.save_final_results({"nonfinite": float("inf")}, files)
        self.assertTrue(all(Path(p).parent == self.out.resolve() for p in mapped.values()))
        (self.work / "evidence.txt").write_bytes(b"updated-after-save")
        u.quick_finish()
        result = json.loads((self.out / "final_results.json").read_text())
        self.assertEqual(result["summary"]["nonfinite"]["encoding"], "+inf")
        manifest = json.loads((self.out / "artifact_manifest.json").read_text())
        for entry in manifest["artifacts"]:
            self.assertEqual(entry["sha256"], hashlib.sha256(Path(entry["path"]).read_bytes()).hexdigest())
        self.assertEqual((self.out / "evidence.txt").read_bytes(), b"updated-after-save")

    def test_missing_evidence_fails_not_completed(self):
        with self.assertRaises(FileNotFoundError):
            u.save_final_results({}, {"missing": "absent.npz"})
        result = json.loads((self.out / "final_results.json").read_text())
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["output_files"], {})
        with self.assertRaises(FileNotFoundError):
            u.quick_finish()

    def test_empty_failure_can_clear_invalid_declarations(self):
        with self.assertRaises(FileNotFoundError):
            u.save_final_results({}, {"missing": "absent.txt"})
        u.save_final_results({"error": "handled"}, output_files={}, status="failed")
        u.quick_finish()
        self.assertEqual(json.loads((self.out / "final_results.json").read_text())["status"], "failed")

    def test_legacy_finish_does_not_overwrite_final_report(self):
        (self.work / "final_results.json").write_text('{"status":"stale"}')
        (self.work / "artifact_manifest.json").write_text('{}')
        (self.work / "sample.npz").write_bytes(b"sample")
        u.quick_finish()
        self.assertTrue((self.out / "sample.npz").exists())
        self.assertFalse((self.out / "final_results.json").exists())


@unittest.skipUnless(importlib.util.find_spec("nvalchemi") and importlib.util.find_spec("ase"),
                     "toolkit and ASE needed (run inside image)")
class IdentityTests(unittest.TestCase):
    def setUp(self):
        import torch
        self.device = "cuda" if os.getenv("ALCHEMI_TEST_GPU") == "1" else "cpu"
        if self.device == "cuda" and not torch.cuda.is_available():
            self.fail("GPU integration explicitly requested, but unavailable")

    def test_nonperiodic_roundtrip_preserves_ids_masses_velocities(self):
        from ase import Atoms
        import numpy as np
        a = Atoms("H2", positions=[[0, 0, 0], [1, 0, 0]], masses=[2, 3])
        a.info.update(system_id=73, input_index=8)
        b = u.atoms_to_batch([a], device=self.device)
        b.velocities.fill_(0.25)
        restored = u.batch_to_atoms(b)[0]
        self.assertEqual(restored.info["system_id"], 73)
        self.assertEqual(restored.info["input_index"], 8)
        np.testing.assert_array_equal(restored.get_masses(), [2, 3])
        np.testing.assert_array_equal(restored.arrays["alchemi_velocities"], np.full((2, 3), 0.25))
        self.assertFalse(restored.pbc.any())

    def test_identity_survives_reorder_and_partial_selection(self):
        from ase import Atoms
        import torch
        items = [Atoms("Ar" * n, positions=[[i * 20, 0, 0] for i in range(n)]) for n in [7, 3, 5]]
        for i, a in enumerate(items):
            a.info.update(system_id=100+i, input_index=i)
        b = u.atoms_to_batch(items, device=self.device)
        selected = b.index_select(torch.tensor([2, 0], device=self.device))
        result = u.batch_to_atoms(selected)
        self.assertEqual([a.info["input_index"] for a in result], [2, 0])
        self.assertEqual([a.info["system_id"] for a in result], [102, 100])
        u._restore_screen_identity(result, items)
        self.assertEqual([a.info["source_system_id"] for a in result], [102, 100])

    def test_screen_mixed_sizes_matches_input_not_admission(self):
        from ase import Atoms
        sizes = [7, 3, 6, 2, 5, 4]
        items = [Atoms("Ar" * n, positions=[[j * 20, 0, 0] for j in range(n)]) for n in sizes]
        for i, a in enumerate(items):
            a.info["sample_label"] = "input-" + str(i)
        model = u.load_model("lj", device=self.device)
        result = u.screen(items, model, fmax=0.001, max_steps=10,
                          max_batch_size=3, max_atoms=12, device=self.device)
        self.assertEqual(len(result), len(items))
        self.assertEqual(sorted(a.info["input_index"] for a in result), list(range(6)))
        for a in result:
            i = a.info["input_index"]
            self.assertEqual(len(a), sizes[i])
            self.assertEqual(a.info["sample_label"], "input-" + str(i))
        self.assertTrue(any(a.info["input_index"] != a.info["system_id"] for a in result))

    def test_screen_partial_returns_explicit_input_identity(self):
        from ase import Atoms
        items = [Atoms("Ar2", positions=[[0, 0, 0], [3.6, 0, 0]]),
                 Atoms("Ar", positions=[[0, 0, 0]])]
        model = u.load_model("lj", device=self.device)
        result = u.screen(items, model, fmax=1e-8, max_steps=1,
                          max_batch_size=2, device=self.device)
        self.assertEqual([a.info["input_index"] for a in result], [1])

    def test_invalid_duplicate_or_missing_identity_rejected(self):
        from ase import Atoms
        a = Atoms("Ar")
        with self.assertRaises(RuntimeError):
            u._restore_screen_identity([a], [a])
        a.info.update(system_id=1, input_index=0)
        with self.assertRaises(RuntimeError):
            u._restore_screen_identity([a.copy(), a.copy()], [a])
        self.assertEqual(u.screen([], None), [])
        with self.assertRaises(ValueError):
            u.screen([a, a], None, sink_capacity=1)

    def test_single_point_matches_analytic_lennard_jones(self):
        from ase import Atoms
        eps, sigma = u.MODEL_DEFAULTS["lj"]["epsilon"], u.MODEL_DEFAULTS["lj"]["sigma"]
        model = u.load_model("lj", device=self.device)
        cases = [(sigma, 0.0, 24 * eps / sigma), (2 ** (1 / 6) * sigma, -eps, 0.0)]
        for r, energy, force in cases:
            b = u.atoms_to_batch([Atoms("Ar2", positions=[[0, 0, 0], [r, 0, 0]])], device=self.device)
            out = u.single_point(b, model)
            self.assertEqual(tuple(out["energy"].shape), (1, 1))
            self.assertEqual(out["energy"].device.type, self.device)
            self.assertAlmostEqual(float(out["energy"][0, 0]), energy, delta=1e-6)
            # Repulsive at sigma: atom 0 is pushed toward -x.
            self.assertAlmostEqual(float(out["forces"][0, 0]), -force, delta=1e-5)
            self.assertAlmostEqual(float(out["forces"].sum()), 0.0, delta=1e-6)
            self.assertAlmostEqual(float(b.energy[0, 0]), energy, delta=1e-6)

    def test_write_structures_accepts_single_atoms_list_and_batch(self):
        from ase import Atoms
        from ase.io import read
        import tempfile
        a = Atoms("H2O", positions=[[0, 0, 0], [0.757, 0, 0.587], [-0.757, 0, 0.587]], pbc=False)
        with tempfile.TemporaryDirectory() as tmp:
            for name, value in (("single", a), ("list", [a, a]),
                                ("batch", u.atoms_to_batch([a], device=self.device))):
                path = u.write_structures(value, os.path.join(tmp, name + ".extxyz"))
                written = read(path, index=":")
                self.assertEqual(len(written), 2 if name == "list" else 1, name)
                self.assertEqual(written[0].get_chemical_formula(), "H2O", name)

    def test_step_recorder_rows_match_independent_kinetic_energy(self):
        from ase import Atoms
        import torch
        from alchemi_validators import independent_kinetic_energy
        model = u.load_model("lj", device=self.device)
        items = [Atoms("Ar2", positions=[[0, 0, 0], [3.9, 0, 0]]),
                 Atoms("Ar3", positions=[[0, 0, 0], [3.8, 0, 0], [0, 3.8, 0]])]
        b = u.atoms_to_batch(items, device=self.device)
        g = torch.Generator().manual_seed(0)
        b.velocities.copy_(0.01 * torch.randn(tuple(b.velocities.shape), generator=g).to(self.device))
        recorder = u.step_recorder()
        out = u.run_md(b, model, ensemble="nve", dt=1.0, n_steps=4, hooks=[recorder])
        self.assertEqual([(r["step"], r["graph"]) for r in recorder.rows],
                         [(s, i) for s in range(1, 5) for i in range(2)])
        last = [r for r in recorder.rows if r["step"] == 4]
        reference = independent_kinetic_energy(out.velocities.cpu().numpy(), out.atomic_masses.cpu().numpy(),
                                               out.batch_idx.cpu().numpy(), 2)
        kb = 8.617333262145e-5
        for i, (row, atoms) in enumerate(zip(last, (2, 3))):
            self.assertAlmostEqual(row["kinetic_energy_eV"], float(reference[i]), delta=1e-7)
            self.assertAlmostEqual(row["temperature_K"], 2 * float(reference[i]) / (3 * atoms * kb),
                                   delta=1e-3)
            self.assertAlmostEqual(row["energy_eV"], float(out.energy.reshape(-1)[i]), delta=1e-7)
        with self.assertRaises(ValueError):
            u.step_recorder(0)


MANIFEST = Path("/app/release-manifest.json")


@unittest.skipUnless(MANIFEST.is_file(), "release manifest only exists inside the built image")
class ReleaseManifestTests(unittest.TestCase):
    def test_every_cached_checkpoint_is_named_and_documented_names_exist(self):
        checkpoints = json.loads(MANIFEST.read_text())["checkpoints"]
        for path, entry in checkpoints.items():
            self.assertTrue(entry.get("loader") and entry.get("name"), path)
            self.assertTrue(Path(path).is_file(), path)
        named = {(e["loader"], e["name"]): p for p, e in checkpoints.items()}
        self.assertEqual(named, {
            ("mace", "small-0b"): "/opt/cache/mace/mace_agnesi_smallmodel",
            ("mace", "medium-0b2"): "/opt/cache/mace/macemediumdensityagnesistressmodel",
            ("aimnet2", "aimnet2"): "/root/.cache/aimnet/aimnet2_wb97m_d3_0.pt",
        })


if __name__ == "__main__":
    unittest.main()