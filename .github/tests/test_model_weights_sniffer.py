"""Unit tests for model_weights_sniffer.

These tests construct minimal valid and invalid fixtures on disk so that
they run without any ML dependencies installed (other than the optional
``onnx`` package, whose code path is exercised only when available).

Run with: python -m pytest .github/tests/test_model_weights_sniffer.py
"""

from __future__ import annotations

import io
import json
import pickle
import struct
import zipfile
from pathlib import Path

import pytest

from model_weights_sniffer import (
    HDF5_MAGIC,
    NPY_MAGIC,
    ZIP_MAGIC,
    sniff,
    sniff_hdf5,
    sniff_npz,
    sniff_onnx,
    sniff_pytorch_zip,
    sniff_safetensors,
)


# ── safetensors ──────────────────────────────────────────────────────────────

def _write_safetensors(path: Path, header_obj: dict, payload: bytes = b"") -> None:
    raw = json.dumps(header_obj).encode("utf-8")
    path.write_bytes(struct.pack("<Q", len(raw)) + raw + payload)


def test_safetensors_valid(tmp_path: Path) -> None:
    p = tmp_path / "weights.safetensors"
    _write_safetensors(p, {
        "weight_0": {"dtype": "F32", "shape": [2, 2], "data_offsets": [0, 16]},
        "__metadata__": {"format": "pt"},
    }, payload=b"\x00" * 16)
    ok, detail = sniff_safetensors(p)
    assert ok, detail


def test_safetensors_truncated(tmp_path: Path) -> None:
    p = tmp_path / "weights.safetensors"
    p.write_bytes(b"\x00\x00\x00")  # < 8 byte prefix
    ok, _ = sniff_safetensors(p)
    assert not ok


def test_safetensors_bad_json(tmp_path: Path) -> None:
    p = tmp_path / "weights.safetensors"
    raw = b"not json"
    p.write_bytes(struct.pack("<Q", len(raw)) + raw)
    ok, _ = sniff_safetensors(p)
    assert not ok


def test_safetensors_missing_required_fields(tmp_path: Path) -> None:
    p = tmp_path / "weights.safetensors"
    _write_safetensors(p, {"weight_0": {"dtype": "F32"}})  # no shape, no offsets
    ok, _ = sniff_safetensors(p)
    assert not ok


def test_safetensors_implausible_header_length(tmp_path: Path) -> None:
    p = tmp_path / "weights.safetensors"
    p.write_bytes(struct.pack("<Q", 10**12))  # 1 TB header — clearly bogus
    ok, _ = sniff_safetensors(p)
    assert not ok


def test_safetensors_shape_must_be_list_of_ints(tmp_path: Path) -> None:
    p = tmp_path / "weights.safetensors"
    _write_safetensors(p, {
        "weight_0": {"dtype": "F32", "shape": [2, "two"], "data_offsets": [0, 16]},
    }, payload=b"\x00" * 16)
    ok, detail = sniff_safetensors(p)
    assert not ok
    assert "shape" in detail.lower()


def test_safetensors_shape_negative_dimension(tmp_path: Path) -> None:
    p = tmp_path / "weights.safetensors"
    _write_safetensors(p, {
        "weight_0": {"dtype": "F32", "shape": [-1, 4], "data_offsets": [0, 16]},
    }, payload=b"\x00" * 16)
    ok, detail = sniff_safetensors(p)
    assert not ok
    assert "shape" in detail.lower() or "negative" in detail.lower()


def test_safetensors_data_offsets_wrong_arity(tmp_path: Path) -> None:
    p = tmp_path / "weights.safetensors"
    _write_safetensors(p, {
        "weight_0": {"dtype": "F32", "shape": [2, 2], "data_offsets": [0, 16, 32]},
    }, payload=b"\x00" * 32)
    ok, detail = sniff_safetensors(p)
    assert not ok
    assert "data_offsets" in detail


def test_safetensors_data_offsets_start_after_end(tmp_path: Path) -> None:
    p = tmp_path / "weights.safetensors"
    _write_safetensors(p, {
        "weight_0": {"dtype": "F32", "shape": [2, 2], "data_offsets": [16, 0]},
    }, payload=b"\x00" * 16)
    ok, detail = sniff_safetensors(p)
    assert not ok
    assert "data_offsets" in detail or "start" in detail.lower()


def test_safetensors_data_offsets_overflow_payload(tmp_path: Path) -> None:
    p = tmp_path / "weights.safetensors"
    _write_safetensors(p, {
        "weight_0": {"dtype": "F32", "shape": [4, 4], "data_offsets": [0, 64]},
    }, payload=b"\x00" * 8)  # only 8 bytes available, header claims 64
    ok, detail = sniff_safetensors(p)
    assert not ok
    assert "exceeds" in detail.lower() or "data_offsets" in detail


def test_safetensors_dtype_must_be_string(tmp_path: Path) -> None:
    p = tmp_path / "weights.safetensors"
    _write_safetensors(p, {
        "weight_0": {"dtype": 32, "shape": [2, 2], "data_offsets": [0, 16]},
    }, payload=b"\x00" * 16)
    ok, _ = sniff_safetensors(p)
    assert not ok


def test_safetensors_metadata_must_be_object(tmp_path: Path) -> None:
    p = tmp_path / "weights.safetensors"
    _write_safetensors(p, {
        "weight_0": {"dtype": "F32", "shape": [2, 2], "data_offsets": [0, 16]},
        "__metadata__": "not an object",
    }, payload=b"\x00" * 16)
    ok, _ = sniff_safetensors(p)
    assert not ok


# ── HDF5 ─────────────────────────────────────────────────────────────────────

def test_hdf5_valid_signature(tmp_path: Path) -> None:
    p = tmp_path / "stock.h5"
    p.write_bytes(HDF5_MAGIC + b"\x00" * 32)
    ok, _ = sniff_hdf5(p)
    assert ok


def test_hdf5_wrong_signature(tmp_path: Path) -> None:
    p = tmp_path / "stock.h5"
    p.write_bytes(b"NOTHDF5" + b"\x00" * 32)
    ok, _ = sniff_hdf5(p)
    assert not ok


# ── PyTorch ZIP ──────────────────────────────────────────────────────────────

def _make_torch_zip(path: Path, archive_name: str = "archive",
                    pickle_obj: object | None = None) -> None:
    """Minimal mimic of torch.save(obj, path) zip layout."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
        payload = pickle.dumps(pickle_obj if pickle_obj is not None else {"state": 1})
        z.writestr(f"{archive_name}/data.pkl", payload)
        z.writestr(f"{archive_name}/version", "3\n")
    path.write_bytes(buf.getvalue())


def test_pytorch_zip_valid(tmp_path: Path) -> None:
    p = tmp_path / "model.pt"
    _make_torch_zip(p)
    ok, detail = sniff_pytorch_zip(p)
    assert ok, detail


def test_pytorch_zip_legacy_pickle_rejected(tmp_path: Path) -> None:
    """Legacy pickle-only torch files have no ZIP magic and must be rejected."""
    p = tmp_path / "legacy.pt"
    p.write_bytes(pickle.dumps({"state": 1}))
    ok, detail = sniff_pytorch_zip(p)
    assert not ok
    assert "PK" in detail or "magic" in detail.lower()


def test_pytorch_zip_missing_data_pkl(tmp_path: Path) -> None:
    p = tmp_path / "model.pt"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
        z.writestr("archive/version", "3\n")
    p.write_bytes(buf.getvalue())
    ok, _ = sniff_pytorch_zip(p)
    assert not ok


def test_pytorch_zip_corrupt(tmp_path: Path) -> None:
    p = tmp_path / "model.pt"
    p.write_bytes(ZIP_MAGIC + b"corrupt body")
    ok, _ = sniff_pytorch_zip(p)
    assert not ok


# ── ONNX ─────────────────────────────────────────────────────────────────────

def _onnx_installed() -> bool:
    try:
        import onnx  # noqa: F401
        return True
    except ImportError:
        return False


def test_onnx_invalid_first_byte(tmp_path: Path) -> None:
    p = tmp_path / "model.onnx"
    p.write_bytes(b"\xff\xff\xff")  # field 31, wire type 7 — not a ModelProto field
    ok, _ = sniff_onnx(p)
    assert not ok


@pytest.mark.skipif(not _onnx_installed(),
                    reason="onnx.checker path requires the onnx package")
def test_onnx_real_checker_accepts_valid_model(tmp_path: Path) -> None:
    """When onnx is installed, sniff_onnx must accept a structurally valid model."""
    import onnx
    from onnx import TensorProto, helper

    x = helper.make_tensor_value_info("x", TensorProto.FLOAT, [1])
    y = helper.make_tensor_value_info("y", TensorProto.FLOAT, [1])
    node = helper.make_node("Identity", ["x"], ["y"])
    graph = helper.make_graph([node], "g", [x], [y])
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)])
    model.ir_version = 7
    p = tmp_path / "model.onnx"
    onnx.save(model, str(p))
    ok, detail = sniff_onnx(p)
    assert ok, detail


def test_onnx_fails_closed_when_onnx_missing(tmp_path: Path, monkeypatch) -> None:
    """If the onnx package is unavailable, even a syntactically plausible file is rejected.

    Soft-passing on missing dependencies in a security gate silently weakens
    enforcement (POL-009 reviewer feedback). This test simulates the
    no-onnx environment by hiding the import.
    """
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "onnx" or name.startswith("onnx."):
            raise ImportError("simulated: onnx not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    p = tmp_path / "model.onnx"
    p.write_bytes(b"\x3a\x00")  # would have passed the legacy fallback sniff
    ok, detail = sniff_onnx(p)
    assert not ok
    assert "onnx" in detail.lower() and "not installed" in detail.lower()


@pytest.mark.skipif(not _onnx_installed(),
                    reason="strict-checker test requires the onnx package")
def test_onnx_rejects_non_onnx_protobuf_with_valid_first_tag(tmp_path: Path) -> None:
    """A protobuf payload that begins with a valid ModelProto field tag but
    is NOT a real ModelProto must still be rejected.

    Reviewer #6 asked whether the first-byte sniff was meant to be a strong
    anti-spoofing check. The answer (after the fail-closed change) is no —
    acceptance is decided by ``onnx.checker``. This test pins that behaviour
    by writing a minimal, parseable protobuf payload using a different
    schema (a ``DescriptorProto`` containing a ``name`` field). It begins
    with byte 0x0a (field 1, wire type 2 — valid for ModelProto.ir_version
    by accident) but is NOT a valid ONNX model.
    """
    # Wire format: 0x0a = field 1, wire type 2 (length-delimited);
    # then varint length 0x07; then 7 bytes of UTF-8 "spoofed".
    # In real ModelProto, field 1 is ir_version (int64, wire type 0), so
    # parsing it as a length-delimited string would fail in onnx.checker.
    payload = b"\x0a\x07spoofed"
    p = tmp_path / "spoofed.onnx"
    p.write_bytes(payload)
    ok, detail = sniff_onnx(p)
    assert not ok, (
        f"sniff_onnx accepted a non-ONNX protobuf based on first-tag heuristic "
        f"alone: detail={detail!r}"
    )


def test_onnx_empty(tmp_path: Path) -> None:
    p = tmp_path / "model.onnx"
    p.write_bytes(b"")
    ok, _ = sniff_onnx(p)
    assert not ok


# ── NPZ ──────────────────────────────────────────────────────────────────────

def _make_npy_bytes(descr: str, shape: tuple = (1,), payload: bytes = b"\x00") -> bytes:
    """Build a minimal valid .npy v1 byte string with the given dtype descr."""
    header_dict = "{'descr': '" + descr + "', 'fortran_order': False, 'shape': " + str(shape) + ", }"
    # Pad header so total prefix length is a multiple of 64 per NPY spec.
    prefix_len = 6 + 2 + 2 + len(header_dict) + 1  # magic+ver+hlen+header+\n
    pad = (-prefix_len) % 64
    header_dict_padded = header_dict + (" " * pad) + "\n"
    hlen = len(header_dict_padded)
    return NPY_MAGIC + b"\x01\x00" + struct.pack("<H", hlen) + header_dict_padded.encode("latin-1") + payload


def _make_npz(path: Path, entries: dict[str, bytes]) -> None:
    """Build a .npz file (ZIP of .npy entries)."""
    import io
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
        for name, npy in entries.items():
            z.writestr(name if name.endswith(".npy") else name + ".npy", npy)
    path.write_bytes(buf.getvalue())


def test_npz_valid_numeric(tmp_path: Path) -> None:
    p = tmp_path / "fingerprints.npz"
    _make_npz(p, {
        "arr_0": _make_npy_bytes("<f4", shape=(4,), payload=b"\x00" * 16),
        "arr_1": _make_npy_bytes("<i8", shape=(2,), payload=b"\x00" * 16),
    })
    ok, detail = sniff_npz(p)
    assert ok, detail


def test_npz_object_dtype_rejected(tmp_path: Path) -> None:
    """Object dtype requires allow_pickle=True — must be blocked."""
    p = tmp_path / "evil.npz"
    _make_npz(p, {
        "arr_0": _make_npy_bytes("|O", shape=(1,), payload=b"\x80\x04N."),
    })
    ok, detail = sniff_npz(p)
    assert not ok
    assert "object" in detail.lower() or "|O" in detail


def test_npz_not_a_zip(tmp_path: Path) -> None:
    p = tmp_path / "notzip.npz"
    p.write_bytes(b"NOTAZIP" + b"\x00" * 32)
    ok, _ = sniff_npz(p)
    assert not ok


def test_npz_empty_archive(tmp_path: Path) -> None:
    p = tmp_path / "empty.npz"
    import io
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
        z.writestr("readme.txt", "no .npy here")
    p.write_bytes(buf.getvalue())
    ok, _ = sniff_npz(p)
    assert not ok


def test_npz_corrupt_zip(tmp_path: Path) -> None:
    p = tmp_path / "corrupt.npz"
    p.write_bytes(ZIP_MAGIC + b"corrupt body")
    ok, _ = sniff_npz(p)
    assert not ok


def test_npz_entry_missing_npy_magic(tmp_path: Path) -> None:
    """A .npy file inside the ZIP that doesn't start with \\x93NUMPY."""
    p = tmp_path / "broken.npz"
    import io
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
        z.writestr("arr_0.npy", b"NOTNUMPY" + b"\x00" * 32)
    p.write_bytes(buf.getvalue())
    ok, _ = sniff_npz(p)
    assert not ok


# ── Top-level sniff() dispatcher ─────────────────────────────────────────────

def test_sniff_dispatches_by_extension(tmp_path: Path) -> None:
    p = tmp_path / "stock.hdf5"
    p.write_bytes(HDF5_MAGIC + b"\x00" * 8)
    ok, _ = sniff(p)
    assert ok


def test_sniff_rejects_unknown_extension(tmp_path: Path) -> None:
    p = tmp_path / "weights.bin"
    p.write_bytes(b"anything")
    ok, _ = sniff(p)
    assert not ok


def test_sniff_extension_spoof_jpeg_as_safetensors(tmp_path: Path) -> None:
    """A JPEG renamed .safetensors must fail header validation."""
    p = tmp_path / "evil.safetensors"
    p.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 64)  # JPEG SOI + APP0
    ok, _ = sniff(p)
    assert not ok


def test_sniff_missing_file(tmp_path: Path) -> None:
    p = tmp_path / "nope.safetensors"
    ok, _ = sniff(p)
    assert not ok


# ── Smoke test that the public surface advertises exactly the 5 formats ─────

def test_allow_list_is_exactly_five_formats() -> None:
    from model_weights_sniffer import MODEL_WEIGHT_EXTENSIONS

    # Six formats, eight extensions: the original five (.pt/.pth/.ckpt collapse
    # to PyTorch, .h5/.hdf5 collapse to HDF5) plus NumPy NPZ.
    assert MODEL_WEIGHT_EXTENSIONS == {
        ".safetensors", ".onnx",
        ".pt", ".pth", ".ckpt",
        ".h5", ".hdf5",
        ".npz",
    }


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
