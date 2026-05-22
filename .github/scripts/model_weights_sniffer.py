"""Header validators for the model-weight binary formats allowed by POL-009.

Each validator reads at most a few KB from the file. They never deserialise
tensors and they never execute pickle code. The goal is to confirm that the
extension matches the actual content (anti-spoofing) and to surface obvious
corruption before the file lands in main.

Allowed formats (kept deliberately small — see docs/authoring-guide.md):

    .safetensors   HuggingFace SafeTensors          (length-prefixed JSON header)
    .onnx          ONNX (protobuf ModelProto)        (protobuf field-tag sniff)
    .pt / .pth     PyTorch state-dict (ZIP+pickle)   (PK\\x03\\x04 + data.pkl)
    .ckpt          PyTorch Lightning / generic torch (same as .pt)
    .h5 / .hdf5    HDF5 / Keras                      (HDF5 superblock signature)
    .npz           NumPy compressed archive          (ZIP of .npy, no object dtype)

Pickle-bearing formats (.pt/.pth/.ckpt) MUST also be passed through the
``picklescan`` package by the caller (see validate_pr.py POL-009).

NPZ has its own pickle hazard: a .npy entry with object dtype (``|O``)
requires ``allow_pickle=True`` to load, which deserialises arbitrary
pickle hidden inside the ZIP. The NPZ sniffer therefore rejects any
entry whose dtype descriptor uses object types.
"""

from __future__ import annotations

import ast
import json
import struct
import zipfile
from pathlib import Path

# ── Magic numbers ───────────────────────────────────────────

HDF5_MAGIC = b"\x89HDF\r\n\x1a\n"
ZIP_MAGIC = b"PK\x03\x04"
NPY_MAGIC = b"\x93NUMPY"

# Per the safetensors specification the header is a JSON object whose UTF-8
# byte length is given by a little-endian uint64 prefix. The spec recommends
# capping the header at a few hundred MB; we cap at 100 MB which is well above
# any real model and well below "obviously wrong".
SAFETENSORS_MAX_HEADER = 100 * 1024 * 1024

# Top-level field numbers defined in onnx/onnx.proto3 ModelProto.
# Wire types 0 (varint) and 2 (length-delimited) are the only ones used here.
ONNX_TOP_LEVEL_FIELDS = {1, 2, 3, 4, 5, 6, 7, 8, 14, 20, 25}


# ── Sniffers ─────────────────────────────────────────────────────────────────

def sniff_safetensors(path: Path) -> tuple[bool, str]:
    """Validate a .safetensors file by parsing its JSON header only."""
    with path.open("rb") as f:
        raw = f.read(8)
        if len(raw) < 8:
            return False, "file shorter than safetensors 8-byte header length prefix"
        (n,) = struct.unpack("<Q", raw)
        if not (8 <= n <= SAFETENSORS_MAX_HEADER):
            return False, f"implausible safetensors header length {n}"
        header = f.read(n)
        if len(header) < n:
            return False, "safetensors header truncated"
        # The total file size must accommodate header + payload referenced by
        # the largest data_offsets value. We capture it for the offset check.
        f.seek(0, 2)
        file_size = f.tell()
    try:
        meta = json.loads(header)
    except json.JSONDecodeError as e:
        return False, f"safetensors header is not valid JSON: {e}"
    if not isinstance(meta, dict) or not meta:
        return False, "safetensors header JSON must be a non-empty object"
    required = {"dtype", "shape", "data_offsets"}
    payload_size = file_size - 8 - n
    for k, v in meta.items():
        if k == "__metadata__":
            if not isinstance(v, dict):
                return False, "safetensors __metadata__ must be a JSON object"
            continue
        if not isinstance(v, dict) or not required <= set(v.keys()):
            return False, f"safetensors entry '{k}' missing required tensor fields"
        # dtype must be a non-empty string (we don't enforce the exact set;
        # the spec evolves and an unknown dtype would simply fail to load).
        if not isinstance(v["dtype"], str) or not v["dtype"]:
            return False, f"safetensors entry '{k}' has non-string dtype"
        # shape must be a list of non-negative integers.
        shape = v["shape"]
        if not isinstance(shape, list):
            return False, f"safetensors entry '{k}' shape must be a list"
        for d in shape:
            if not isinstance(d, int) or isinstance(d, bool) or d < 0:
                return False, (
                    f"safetensors entry '{k}' shape contains non-integer or "
                    f"negative dimension: {d!r}"
                )
        # data_offsets must be a 2-element list of non-negative integers
        # with start <= end and end within the payload region.
        offsets = v["data_offsets"]
        if (not isinstance(offsets, list) or len(offsets) != 2
                or not all(isinstance(x, int) and not isinstance(x, bool) and x >= 0
                           for x in offsets)):
            return False, (
                f"safetensors entry '{k}' data_offsets must be a 2-element "
                f"list of non-negative integers; got {offsets!r}"
            )
        start, end = offsets
        if start > end:
            return False, (
                f"safetensors entry '{k}' has data_offsets start > end "
                f"({start} > {end})"
            )
        if end > payload_size:
            return False, (
                f"safetensors entry '{k}' data_offsets end {end} exceeds "
                f"payload size {payload_size}"
            )
    return True, "ok"


def sniff_hdf5(path: Path) -> tuple[bool, str]:
    """HDF5 files start with the 8-byte superblock signature."""
    with path.open("rb") as f:
        head = f.read(8)
    if head == HDF5_MAGIC:
        return True, "ok"
    return False, "missing HDF5 superblock signature \\x89HDF\\r\\n\\x1a\\n"


def sniff_pytorch_zip(path: Path) -> tuple[bool, str]:
    """For .pt / .pth / .ckpt — modern torch.save uses a ZIP container.

    Legacy pickle-only torch files (torch < 1.6 or
    ``_use_new_zipfile_serialization=False``) are rejected: they have no
    header to sniff, picklescan cannot bound their attack surface, and they
    have been the source of every notable PyTorch RCE to date.
    """
    with path.open("rb") as f:
        head = f.read(4)
    if head != ZIP_MAGIC:
        return False, (
            "not a torch ZIP archive (missing PK\\x03\\x04 magic). "
            "Re-save with torch.save(obj, path) using torch >= 1.6 "
            "(zip serialization is the default). Legacy pickle-only "
            "checkpoints are blocked for security."
        )
    try:
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            if not any(n == "data.pkl" or n.endswith("/data.pkl") for n in names):
                return False, "torch ZIP does not contain a data.pkl entry"
    except zipfile.BadZipFile as e:
        return False, f"corrupt torch ZIP: {e}"
    return True, "ok"


def sniff_onnx(path: Path) -> tuple[bool, str]:
    """Validate ONNX with onnx.checker. Fails closed if onnx is unavailable.

    A protobuf field-tag pre-check is *only* used to reject obviously
    non-protobuf inputs faster; it never decides acceptance on its own.
    Acceptance always requires a successful ``onnx.checker.check_model``.
    If the ``onnx`` package is missing, the file is rejected: in a security
    gate, soft-passing on missing dependencies silently weakens enforcement
    (POL-009 is a hard policy, not a best-effort hint).
    """
    with path.open("rb") as f:
        first = f.read(1)
    if not first:
        return False, "empty .onnx file"
    tag = first[0]
    field_no, wire_type = tag >> 3, tag & 0x07
    if wire_type not in (0, 2) or field_no not in ONNX_TOP_LEVEL_FIELDS:
        return False, f"first byte 0x{tag:02x} is not a valid ModelProto field tag"

    try:
        import onnx  # type: ignore
    except ImportError:
        return False, (
            "onnx package is not installed; POL-009 requires onnx.checker for "
            "full ModelProto validation. Install `onnx` in the validator "
            "environment (the CI workflow does this)."
        )
    try:
        model = onnx.load(str(path), load_external_data=False)
        onnx.checker.check_model(model)
    except Exception as e:
        return False, f"onnx.checker rejected the file: {e}"
    return True, "ok"


def _npy_header_dtype_descr(header: str) -> str:
    """Extract the value of the 'descr' key from a .npy header string.

    The header is a Python literal dict (NumPy spec, NEP 1). We use
    ``ast.literal_eval`` so we never execute code from the file.
    Returns the descr value as a string for downstream substring matching;
    returns the raw header on parse failure so the caller can still reject
    suspicious content.
    """
    try:
        d = ast.literal_eval(header)
    except (ValueError, SyntaxError):
        return header
    if not isinstance(d, dict):
        return header
    descr = d.get("descr", "")
    return repr(descr)


def sniff_npz(path: Path) -> tuple[bool, str]:
    """Validate a .npz archive: ZIP-of-.npy with no object-dtype entries.

    NumPy's object dtype (``|O``) requires ``allow_pickle=True`` to load,
    which deserialises pickle hidden inside the ZIP. Any such entry is
    rejected outright. Plain numeric / string dtypes are safe.
    """
    with path.open("rb") as f:
        if f.read(4) != ZIP_MAGIC:
            return False, "not a ZIP archive (NPZ files start with PK\\x03\\x04)"
    try:
        with zipfile.ZipFile(path) as z:
            entries = [n for n in z.namelist() if n.endswith(".npy")]
            if not entries:
                return False, "NPZ archive contains no .npy entries"
            for name in entries:
                with z.open(name) as f:
                    if f.read(6) != NPY_MAGIC:
                        return False, f"entry '{name}' missing \\x93NUMPY signature"
                    ver = f.read(2)
                    if len(ver) < 2:
                        return False, f"entry '{name}' truncated NPY version field"
                    major = ver[0]
                    if major == 1:
                        hlen_bytes = f.read(2)
                        if len(hlen_bytes) < 2:
                            return False, f"entry '{name}' truncated NPY header length"
                        hlen = struct.unpack("<H", hlen_bytes)[0]
                    elif major in (2, 3):
                        hlen_bytes = f.read(4)
                        if len(hlen_bytes) < 4:
                            return False, f"entry '{name}' truncated NPY header length"
                        hlen = struct.unpack("<I", hlen_bytes)[0]
                    else:
                        return False, f"entry '{name}' uses unsupported NPY major version {major}"
                    if hlen > 1024 * 1024:
                        return False, f"entry '{name}' has implausible NPY header length {hlen}"
                    header = f.read(hlen).decode("latin-1")
                descr = _npy_header_dtype_descr(header)
                # Object dtype is the only pickle-bearing case. NumPy spells
                # it as '|O', '|O8', or with structured fields containing 'O'.
                if "'|O" in descr or '"|O' in descr or "'O'" in descr:
                    return False, (
                        f"entry '{name}' uses NumPy object dtype ({descr.strip()}). "
                        f"Object arrays require allow_pickle=True to load and are "
                        f"not permitted (POL-009). Re-export with a numeric dtype."
                    )
    except zipfile.BadZipFile as e:
        return False, f"corrupt NPZ: {e}"
    return True, "ok"


# ── Public API ───────────────────────────────────────────────────────────────

SNIFFERS = {
    ".safetensors": sniff_safetensors,
    ".h5":          sniff_hdf5,
    ".hdf5":        sniff_hdf5,
    ".pt":          sniff_pytorch_zip,
    ".pth":         sniff_pytorch_zip,
    ".ckpt":        sniff_pytorch_zip,
    ".onnx":        sniff_onnx,
    ".npz":         sniff_npz,
}

MODEL_WEIGHT_EXTENSIONS = frozenset(SNIFFERS)


def sniff(path: Path) -> tuple[bool, str]:
    """Dispatch to the format-specific sniffer based on extension."""
    ext = path.suffix.lower()
    sniffer = SNIFFERS.get(ext)
    if sniffer is None:
        return False, f"extension '{ext}' is not in the model-weights allow-list"
    if not path.is_file():
        return False, "path is not a regular file"
    return sniffer(path)
