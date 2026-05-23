#!/usr/bin/env python3
"""Unit tests for janus_utils — run with pytest.

These tests exercise the WRAPPER logic (validation, PFAS filter, scoring helpers,
file I/O) without requiring janus-ga itself. Tests that need JANUS are skipped
gracefully if the package is not importable.
"""

from __future__ import annotations

import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(__file__))

import janus_utils as ju  # noqa: E402


# ============= chemistry helpers =============

class TestSmilesValidation:
    def test_valid_smiles_passes(self):
        assert ju.validate_smiles("CCO") is True
        assert ju.validate_smiles("c1ccccc1") is True
        assert ju.validate_smiles("CCC(=O)C(F)(F)C(F)(F)F") is True  # Novec 649

    def test_invalid_smiles_fails(self):
        assert ju.validate_smiles("not a smiles") is False
        assert ju.validate_smiles("C(=O)(=O)(=O)C") is False  # bad valence
        assert ju.validate_smiles("") is False

    def test_canonicalize_returns_canonical(self):
        # Two equivalent SMILES for ethanol should canonicalize identically.
        assert ju.canonicalize_smiles("OCC") == ju.canonicalize_smiles("CCO")

    def test_canonicalize_invalid_returns_none(self):
        assert ju.canonicalize_smiles("nope") is None

    def test_validate_list_dedupes_and_orders(self):
        out = ju.validate_smiles_list(["CCO", "OCC", "c1ccccc1", "garbage", "CCO"])
        assert len(out) == 2  # ethanol + benzene
        assert "garbage" not in out


# ============= PFAS filter =============

class TestPfasFilter:
    def test_novec649_is_pfas(self):
        # The reference molecule we want to REPLACE. It must trigger.
        assert ju.has_pfas_substructure("CCC(=O)C(F)(F)C(F)(F)F") is True

    def test_pfba_is_pfas(self):
        # Perfluorobutanoic acid — definitionally PFAS.
        assert ju.has_pfas_substructure("OC(=O)C(F)(F)C(F)(F)C(F)(F)F") is True

    def test_simple_alcohol_is_not_pfas(self):
        assert ju.has_pfas_substructure("CCO") is False

    def test_methylated_siloxane_is_not_pfas(self):
        # HMDSO — a candidate non-PFAS coolant chemistry.
        assert ju.has_pfas_substructure("C[Si](C)(C)O[Si](C)(C)C") is False

    def test_filter_rejects_pfas(self):
        flt = ju.make_pfas_filter()
        assert flt("CCO") is True              # keep
        assert flt("CCC(=O)C(F)(F)C(F)(F)F") is False  # reject Novec 649
        assert flt("nonsense_smiles") is False           # invalid -> reject

    def test_filter_with_custom_patterns(self):
        # Caller-supplied SMARTS — ensures we honor the override path.
        flt = ju.make_pfas_filter(smarts_patterns=("[Cl]",))
        assert flt("CCCl") is False  # reject anything with chlorine
        assert flt("CCO") is True

    def test_pfas_filter_is_picklable(self):
        # Regression test: the filter MUST be picklable so that sharded
        # run_janus() can ship it to multiprocessing workers.
        import pickle
        flt = ju.make_pfas_filter()
        blob = pickle.dumps(flt)
        restored = pickle.loads(blob)
        # Behaviour survives the round-trip.
        assert restored("CCO") is True
        assert restored("CCC(=O)C(F)(F)C(F)(F)F") is False
        # Also picklable with custom SMARTS.
        flt2 = ju.make_pfas_filter(smarts_patterns=("[Cl]",))
        restored2 = pickle.loads(pickle.dumps(flt2))
        assert restored2("CCCl") is False
        assert restored2("CCO") is True


class TestPostFilter:
    def test_post_filter_scored_drops_rejected(self):
        scored = [
            {"smiles": "CCO", "score": 0.9},
            {"smiles": "CCC(=O)C(F)(F)C(F)(F)F", "score": 0.95},  # PFAS
            {"smiles": "c1ccccc1", "score": 0.5},
        ]
        out = ju.post_filter_scored(scored, ju.make_pfas_filter())
        smis = [r["smiles"] for r in out]
        assert "CCO" in smis
        assert "c1ccccc1" in smis
        assert "CCC(=O)C(F)(F)C(F)(F)F" not in smis

    def test_post_filter_scored_swallows_filter_exceptions(self):
        def bad_filter(_smi):
            raise RuntimeError("boom")
        # Must not propagate; rejected items just get dropped.
        out = ju.post_filter_scored([{"smiles": "CCO", "score": 1.0}], bad_filter)
        assert out == []


# ============= scoring helpers =============

class TestScoring:
    def test_target_score_peaks_at_target(self):
        s_at = ju.score_property_target("CCO", lambda _s: 78.0, target=78.0)
        s_off = ju.score_property_target("CCO", lambda _s: 100.0, target=78.0, tolerance=10.0)
        assert s_at == pytest.approx(1.0)
        assert 0.0 < s_off < 1.0
        assert s_off < s_at

    def test_target_score_bad_descriptor_returns_zero(self):
        # Descriptor raises -> score must be 0.0, never propagate.
        def bad(_s):
            raise RuntimeError("explode")
        assert ju.score_property_target("CCO", bad, target=1.0) == 0.0

    def test_molecular_weight_known(self):
        # Ethanol MW = 46.07; allow generous tolerance.
        assert abs(ju.molecular_weight("CCO") - 46.07) < 0.5

    def test_molecular_weight_invalid_is_nan(self):
        import math
        assert math.isnan(ju.molecular_weight("not_a_mol"))


# ============= seed file I/O =============

class TestSeedIO:
    def test_write_start_population_dedupes(self, tmp_path):
        path = tmp_path / "seeds.txt"
        out = ju.write_start_population(["CCO", "OCC", "c1ccccc1"], str(path))
        lines = [ln for ln in open(out).read().splitlines() if ln.strip()]
        assert len(lines) == 2  # dedup happened
        assert "OCC" not in lines or "CCO" not in lines  # only canonical kept

    def test_write_start_population_empty_raises(self, tmp_path):
        with pytest.raises(ValueError):
            ju.write_start_population(["bad", "junk", ""], str(tmp_path / "seeds.txt"))


# ============= setup / teardown =============

class TestLifecycle:
    def test_quick_setup_creates_dirs(self, tmp_path):
        ju.quick_setup(
            input_dir=str(tmp_path / "in"),
            output_dir=str(tmp_path / "out"),
            work_dir=str(tmp_path / "work"),
        )
        assert (tmp_path / "out").exists()
        assert (tmp_path / "work").exists()
        assert ju.OUTPUT_DIR == str(tmp_path / "out")

    def test_save_final_results_writes_json(self, tmp_path):
        ju.OUTPUT_DIR = str(tmp_path)
        path = ju.save_final_results({"hello": "world"})
        import json
        data = json.loads(open(path).read())
        assert data["status"] == "completed"
        assert data["summary"]["hello"] == "world"


# ============= optional: smoke-test JANUS itself =============

@pytest.mark.skipif(
    pytest.importorskip("janus", reason="janus-ga not installed in this env") is None,
    reason="janus-ga not installed",
)
@pytest.mark.skipif(
    sys.platform.startswith("win"),
    reason="janus-ga 1.0.3 hardcodes POSIX './'+absolute path; runs inside Linux container only",
)
class TestJanusSmoke:
    """Tiny end-to-end exercise — only runs if janus-ga is importable AND on Linux."""

    def test_run_janus_minimal(self, tmp_path):
        try:
            import janus  # noqa: F401
        except ImportError:
            pytest.skip("janus-ga not installed")

        out = ju.run_janus(
            seed_smiles=["CCO", "CCCO", "CCCCO"],
            fitness_function=lambda s: ju.score_property_target(
                s, ju.molecular_weight, target=60.0, tolerance=10.0,
            ),
            work_dir=str(tmp_path / "janus_work"),
            generations=2,
            generation_size=10,
            use_classifier=False,
            use_fragments=False,
            shards=1,
            cpus_per_shard=2,
        )
        assert out["seed_count"] == 3
        assert out["best"] is not None
        assert out["best"]["score"] >= 0.0
        # FilterGuard stats must be present on every run.
        assert "filter_guard_stats" in out


# ============= signature / template guards =============

class TestPublicApi:
    """Static guards that protect the agent.yaml-required template path."""

    def test_run_janus_signature_has_shards_and_cpus_per_shard(self):
        # The agent template uses these kwargs; protect them from rename.
        import inspect
        sig = inspect.signature(ju.run_janus)
        params = sig.parameters
        for kw in ("seed_smiles", "fitness_function", "custom_filter",
                   "allowed_elements", "generations", "generation_size",
                   "shards", "cpus_per_shard"):
            assert kw in params, f"run_janus is missing required kwarg '{kw}'"
        # Regression guard: 'num_workers' was removed from the public API
        # in favour of 'shards' / 'cpus_per_shard'. If it ever comes back
        # by accident, the agent.yaml template / docs must be re-aligned.
        assert "num_workers" not in params, (
            "run_janus() exposes 'num_workers' again; agent.yaml template "
            "and SCALE GUIDE must be updated to match."
        )

    def test_required_template_kwargs_match_signature(self):
        # Statically validate the kwargs used in agent.yaml's REQUIRED SCRIPT
        # TEMPLATE block against the current run_janus signature. This catches
        # the class of regression where docs and code drift apart.
        #
        # We parse agent.yaml directly (not a hard-coded constant) so future
        # template edits are automatically covered.
        import inspect
        import re
        agent_yaml = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..", "..", "agent.yaml")
        )
        if not os.path.exists(agent_yaml):
            pytest.skip(f"agent.yaml not found at {agent_yaml}")

        text = open(agent_yaml, encoding="utf-8").read()

        # Locate the REQUIRED SCRIPT TEMPLATE fenced code block.
        m = re.search(
            r"# REQUIRED SCRIPT TEMPLATE\s*```python\s*(.*?)```",
            text,
            flags=re.DOTALL,
        )
        assert m, "Could not locate '# REQUIRED SCRIPT TEMPLATE' python block in agent.yaml"
        template_src = m.group(1)

        # Find the run_janus(...) call and extract its kwargs.
        call = re.search(r"run_janus\s*\((.*?)\)", template_src, flags=re.DOTALL)
        assert call, "agent.yaml template does not call run_janus(...)"
        # Identifier= matches: kwargs only (positional args won't have '=').
        kwargs_used = set(re.findall(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*=", call.group(1)))
        assert kwargs_used, "Could not parse any kwargs from run_janus(...) in template"

        sig = inspect.signature(ju.run_janus)
        params = set(sig.parameters)
        unknown = kwargs_used - params
        assert not unknown, (
            f"agent.yaml template uses kwargs that run_janus does not accept: "
            f"{sorted(unknown)}. Either rename them in the template or add them "
            f"to the run_janus signature."
        )

    def test_make_pfas_filter_returns_picklable_callable(self):
        import pickle
        flt = ju.make_pfas_filter()
        # Must be callable with the JANUS contract.
        assert callable(flt)
        assert flt("CCO") is True
        # Must be picklable so multi-shard runs work.
        pickle.loads(pickle.dumps(flt))


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
