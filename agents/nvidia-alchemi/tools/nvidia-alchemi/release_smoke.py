"""Release smoke test: real toolkit IDs, reviewed validators, verified artifacts.

Default run requires GPU. --cpu is only for build/local testing, never a hidden
fallback. The output deliberately includes NPZ/Python/text and nested Zarr data.
"""
import argparse
import hashlib
import json
import logging
from pathlib import Path
import shutil
import unittest

import numpy as np
import torch
from ase import Atoms
import alchemi_utils as u
from alchemi_artifacts import write_json_atomic, to_jsonable
from alchemi_validators import compare_numeric, independent_kinetic_energy, independent_energy_drift, audit_hook_events


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cpu", action="store_true")
    parser.add_argument("--output", default="/output")
    parser.add_argument("--work", default="/workdir")
    args = parser.parse_args()
    device = "cpu" if args.cpu else "cuda"
    if device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("Release GPU smoke requires CUDA; CPU fallback forbidden")
    # Run regression tests BEFORE setup; some tests deliberately change globals.
    import os
    os.environ["ALCHEMI_TEST_GPU"] = "0" if args.cpu else "1"
    suite = unittest.defaultTestLoader.discover(str(Path(__file__).parent / "tests"))
    test_result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not test_result.wasSuccessful() or test_result.skipped:
        raise RuntimeError("Release regressions failed or skipped")

    release = json.loads(Path("/app/release-manifest.json").read_text())["release"]
    if os.environ.get("ALCHEMI_AGENT_RELEASE") != release:
        raise RuntimeError("Image release variable disagrees with release manifest")

    u.quick_setup(output_dir=args.output, work_dir=args.work)
    work = Path(u.WORK_DIR)
    handler = logging.FileHandler(work / "smoke.log")
    logging.getLogger().addHandler(handler)
    outputs = {}
    try:
        sizes = [7, 3, 6, 2, 5, 4]
        inputs = [Atoms("Ar" * n, positions=[[20*j, 0, 0] for j in range(n)]) for n in sizes]
        for i,a in enumerate(inputs):
            a.info["sample_label"] = f"sample-{i}"
        model = u.load_model("lj", device=device)
        screened = u.screen(inputs, model, fmax=0.001, max_steps=10,
                            max_batch_size=3, max_atoms=12, device=device)
        ids = [{"input_index":a.info["input_index"], "system_id":a.info["system_id"],
                "sample_label":a.info["sample_label"], "atoms":len(a)} for a in screened]
        assert sorted(x["input_index"] for x in ids) == list(range(6))
        assert all(x["atoms"] == sizes[x["input_index"]] for x in ids)
        assert any(x["input_index"] != x["system_id"] for x in ids)

        # Independently computed reference, with actual tensor evidence saved.
        velocity = np.arange(18, dtype=np.float32).reshape(6,3) / 20
        masses = np.array([1,2,3,4,5,6], dtype=np.float32)
        groups = np.array([0,0,0,1,1,1], dtype=np.int32)
        from nvalchemi.dynamics.hooks._utils import kinetic_energy_per_graph
        observed = kinetic_energy_per_graph(torch.tensor(velocity,device=device),
            torch.tensor(masses,device=device),torch.tensor(groups,device=device),2).detach().cpu().numpy().reshape(-1)
        reference = independent_kinetic_energy(velocity,masses,groups,2)
        check = compare_numeric(observed, reference, observed_source="toolkit.runtime.kinetic_energy",
                                reference_source="numpy.direct.float64",atol=1e-5,rtol=1e-5)
        assert check["status"] == "pass"
        assert independent_energy_drift(np.array([1.]),None,np.array([6]),0) is None
        assert compare_numeric(None,reference,observed_source="missing",reference_source="numpy",atol=0,rtol=0)["status"] == "unverified"
        assert audit_hook_events([],[])["status"] == "unverified"
        np.savez(work / "reference_arrays.npz", velocities=velocity,masses=masses,groups=groups,
                 observed=observed,reference=reference)
        write_json_atomic(work / "identity_and_checks.json", {"identities":ids,"kinetic_energy":check})
        (work / "api_notes.txt").write_text("Release smoke: declared text artifacts are exported and hashed.\n")
        shutil.copy2(__file__,work / "executed_smoke.py")
        batch = u.atoms_to_batch([inputs[0]],device=device)
        sink = u.zarr_sink("nested/trajectory.zarr",capacity=3)
        sink.write(batch)
        del sink
        for name in ("release-manifest.json", "requirements.lock.txt", "agent-instructions.txt"):
            shutil.copy2(Path("/app") / name, work / name)
        outputs = {"arrays":"reference_arrays.npz", "script":"executed_smoke.py",
                   "notes":"api_notes.txt", "checks":"identity_and_checks.json",
                   "trajectory":"nested/trajectory.zarr", "log":"smoke.log",
                   "release":"release-manifest.json", "packages":"requirements.lock.txt",
                   "instructions":"agent-instructions.txt"}
        logging.info("All smoke assertions completed successfully")
        summary = {"release":release,"helper_version":u.HELPER_VERSION,"device":device,
                   "gpu":torch.cuda.get_device_name(0) if device=="cuda" else None,
                   "tests_run":test_result.testsRun,"tests_skipped":len(test_result.skipped),
                   "checks":{"identity":"pass","independent_energy":"pass"},
                   "expected_nonfinite_diagnostics":[float("inf"),float("-inf"),float("nan")],
                   "helper_sha256":hashlib.sha256(Path(u.__file__).read_bytes()).hexdigest()}
        u.save_final_results(summary, outputs)
    except Exception as exc:
        u.save_final_results({"error":str(exc)},output_files={},status="failed")
        raise
    finally:
        logging.getLogger().removeHandler(handler)
        handler.close()
        u.quick_finish()
    print("RELEASE_SMOKE_PASS", json.dumps(to_jsonable(summary),allow_nan=False))


if __name__ == "__main__":
    main()