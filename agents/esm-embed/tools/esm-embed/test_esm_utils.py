"""Unit tests for esm_utils. These cover IO + utility helpers and skip the
expensive model-loading tests when transformers/torch are unavailable.

Run:    python -m pytest tools/test_esm_utils.py -v
"""

import json
import os
import sys
from pathlib import Path

import numpy as np
import pytest

# Make the utils importable regardless of cwd
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import esm_utils as eu  # noqa: E402


# ---------------------------------------------------------------------------
# Pure-Python helpers
# ---------------------------------------------------------------------------

def test_supported_models_registry():
    assert eu.DEFAULT_MODEL in eu.SUPPORTED_MODELS
    for name, meta in eu.SUPPORTED_MODELS.items():
        assert meta["hf_id"].startswith("facebook/esm2_")
        assert meta["dim"] > 0
        assert meta["layers"] > 0


def test_resolve_model_name_short_and_full():
    assert eu.resolve_model_name("esm2_t33_650M") == "facebook/esm2_t33_650M_UR50D"
    assert eu.resolve_model_name("facebook/esm2_t6_8M_UR50D") == "facebook/esm2_t6_8M_UR50D"
    assert eu.resolve_model_name("") == eu.SUPPORTED_MODELS[eu.DEFAULT_MODEL]["hf_id"]


def test_resolve_model_name_invalid_raises():
    with pytest.raises(ValueError):
        eu.resolve_model_name("not-a-real-model")


def test_sanitize_sequence_uppercases_and_maps_unknown():
    s = eu.sanitize_sequence("  m k t  Bxz  *  \nA  ")
    # Only standard amino acids preserved; rest -> X. Whitespace stripped.
    assert set(s).issubset(set("ACDEFGHIKLMNPQRSTVWYX"))
    # 'M', 'K', 'T', 'A' are valid; B, Z, *, space replaced -> X (or removed if whitespace)
    assert s.startswith("MKT")
    assert s.endswith("A")


def test_safe_filename():
    assert eu._safe_filename("sp|P12345|HUMAN") == "sp_P12345_HUMAN"
    assert eu._safe_filename("a" * 200).__len__() == 120


def test_json_default_handles_numpy():
    arr = np.array([1, 2, 3])
    blob = json.dumps({"x": np.float32(1.5), "y": np.int64(7), "z": arr},
                      default=eu._json_default)
    parsed = json.loads(blob)
    assert parsed["x"] == 1.5
    assert parsed["y"] == 7
    assert parsed["z"] == [1, 2, 3]


# ---------------------------------------------------------------------------
# IO helpers
# ---------------------------------------------------------------------------

def test_read_fasta(tmp_path):
    f = tmp_path / "seqs.fasta"
    f.write_text(">a desc\nMKT\nVLG\n>b\nA\n", encoding="utf-8")
    recs = eu.read_fasta(str(f))
    assert recs == [("a", "MKTVLG"), ("b", "A")]


def test_read_sequences_json(tmp_path):
    f = tmp_path / "seqs.json"
    f.write_text(json.dumps([
        {"id": "p1", "sequence": "MKT"},
        {"name": "p2", "seq": "ALA"},
        "RAW",
    ]), encoding="utf-8")
    recs = eu.read_sequences_json(str(f))
    assert [r[0] for r in recs] == ["p1", "p2", "seq_2"]
    assert [r[1] for r in recs] == ["MKT", "ALA", "RAW"]


def test_load_sequences_finds_fasta(tmp_path):
    (tmp_path / "sequences.fasta").write_text(">x\nMKT\n", encoding="utf-8")
    recs = eu.load_sequences(str(tmp_path))
    assert recs == [("x", "MKT")]


def test_load_sequences_falls_back_to_json(tmp_path):
    (tmp_path / "sequences.json").write_text(
        json.dumps([{"id": "x", "sequence": "MKT"}]),
        encoding="utf-8",
    )
    recs = eu.load_sequences(str(tmp_path))
    assert recs == [("x", "MKT")]


def test_load_sequences_missing_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        eu.load_sequences(str(tmp_path))


# ---------------------------------------------------------------------------
# quick_setup / save_final_results
# ---------------------------------------------------------------------------

def test_quick_setup_returns_paths(tmp_path):
    info = eu.quick_setup(
        input_dir=str(tmp_path / "in"),
        output_dir=str(tmp_path / "out"),
        work_dir=str(tmp_path / "work"),
    )
    assert os.path.isdir(info["input"])
    assert os.path.isdir(info["output"])
    assert info["device"] in ("cuda", "cpu")


def test_save_final_results_writes_json(tmp_path):
    eu.quick_setup(input_dir=str(tmp_path / "in"),
                   output_dir=str(tmp_path / "out"),
                   work_dir=str(tmp_path / "work"))
    p = eu.save_final_results({"foo": 1}, output_files=["embeddings.npz"],
                              file_descriptions=["mean embeddings"])
    data = json.loads(Path(p).read_text())
    assert data["results"]["foo"] == 1
    assert "embeddings.npz" in data["output_files"]


# ---------------------------------------------------------------------------
# save_embeddings (no model needed)
# ---------------------------------------------------------------------------

def test_save_embeddings_writes_npz_and_manifest(tmp_path):
    eu.quick_setup(input_dir=str(tmp_path / "in"),
                   output_dir=str(tmp_path / "out"),
                   work_dir=str(tmp_path / "work"))
    result = {
        "ids": ["a", "b"],
        "sequences": ["MKT", "AAA"],
        "lengths": np.array([3, 3], dtype=np.int32),
        "mean_embeddings": np.random.rand(2, 320).astype(np.float32),
        "per_residue_embeddings": [np.random.rand(3, 320).astype(np.float32),
                                    np.random.rand(3, 320).astype(np.float32)],
        "embed_dim": 320,
        "model_id": "facebook/esm2_t6_8M_UR50D",
        "timing": {"elapsed_sec": 0.1, "n": 2},
    }
    manifest = eu.save_embeddings(result, out_dir=str(tmp_path / "out"),
                                  save_per_residue=True)
    assert (tmp_path / "out" / "embeddings.npz").is_file()
    assert (tmp_path / "out" / "manifest.json").is_file()
    assert (tmp_path / "out" / "per_residue" / "a.npy").is_file()
    assert manifest["n_sequences"] == 2
    assert manifest["embed_dim"] == 320

    # Verify NPZ is round-trippable
    z = np.load(tmp_path / "out" / "embeddings.npz", allow_pickle=True)
    assert z["mean_embeddings"].shape == (2, 320)
    assert list(z["ids"]) == ["a", "b"]


# ---------------------------------------------------------------------------
# End-to-end model test (only when transformers + a tiny model are available)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    "ESM_UTILS_RUN_MODEL_TEST" not in os.environ,
    reason="Set ESM_UTILS_RUN_MODEL_TEST=1 to run the slow model-loading test",
)
def test_embed_sequences_end_to_end():
    import torch  # noqa: F401
    model, tok, device = eu.load_esm2("esm2_t6_8M", device="cpu", dtype="float32")
    seqs = [("a", "MKTVLG"), ("b", "AAAA")]
    res = eu.embed_sequences(model, tok, seqs, device=device,
                             batch_size=2, return_per_residue=True,
                             fp16=False, progress=False)
    assert res["mean_embeddings"].shape == (2, eu.SUPPORTED_MODELS["esm2_t6_8M"]["dim"])
    assert res["lengths"].tolist() == [6, 4]
    assert len(res["per_residue_embeddings"]) == 2
    assert res["per_residue_embeddings"][0].shape[0] == 6
