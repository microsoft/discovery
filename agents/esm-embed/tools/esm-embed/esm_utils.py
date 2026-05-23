"""esm_utils.py -- Discovery agent utilities for ESM-2 protein embeddings.

Public API (used by agent scripts):
    quick_setup(input_dir, output_dir, work_dir)         -> dict(paths, device)
    quick_finish()                                       -> None
    save_final_results(results, output_files=None, file_descriptions=None) -> str

    SUPPORTED_MODELS                                     -> dict[str, dict]
    resolve_model_name(short_name)                       -> str (HF id)
    load_esm2(model_name='esm2_t33_650M', device=None, dtype=None) -> (model, tokenizer, device)

    read_fasta(path)                                     -> list[(id, sequence)]
    read_sequences_json(path)                            -> list[(id, sequence)]
    load_sequences(input_dir='/input')                   -> list[(id, sequence)]
    sanitize_sequence(seq)                               -> str

    embed_sequences(model, tokenizer, sequences, device, batch_size=8,
                    max_length=1024, return_per_residue=False,
                    return_contacts=False, fp16=True, progress=True) -> dict
    save_embeddings(result, out_dir='/output', save_per_residue=True,
                    save_contacts=False)                 -> dict (manifest)
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import sys
import time
import traceback
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple

import numpy as np

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("esm_utils")


# ---------------------------------------------------------------------------
# Model registry
# ---------------------------------------------------------------------------

SUPPORTED_MODELS = {
    "esm2_t6_8M":    {"hf_id": "facebook/esm2_t6_8M_UR50D",    "layers": 6,  "dim": 320,  "params_m": 8},
    "esm2_t12_35M":  {"hf_id": "facebook/esm2_t12_35M_UR50D",  "layers": 12, "dim": 480,  "params_m": 35},
    "esm2_t30_150M": {"hf_id": "facebook/esm2_t30_150M_UR50D", "layers": 30, "dim": 640,  "params_m": 150},
    "esm2_t33_650M": {"hf_id": "facebook/esm2_t33_650M_UR50D", "layers": 33, "dim": 1280, "params_m": 650},
}
DEFAULT_MODEL = "esm2_t33_650M"

# Standard 20 amino acids; everything else mapped to X
_VALID_AA = set("ACDEFGHIKLMNPQRSTVWY")


def resolve_model_name(short_name: str) -> str:
    """Map a short alias (e.g. 'esm2_t33_650M') or a full HF id to the canonical HF id."""
    if not short_name:
        return SUPPORTED_MODELS[DEFAULT_MODEL]["hf_id"]
    if short_name in SUPPORTED_MODELS:
        return SUPPORTED_MODELS[short_name]["hf_id"]
    # Allow full HF ids directly
    for entry in SUPPORTED_MODELS.values():
        if entry["hf_id"] == short_name:
            return short_name
    raise ValueError(
        f"Unknown ESM-2 model '{short_name}'. "
        f"Supported: {list(SUPPORTED_MODELS.keys())}"
    )


# ---------------------------------------------------------------------------
# Setup / teardown (Discovery convention)
# ---------------------------------------------------------------------------

_PATHS = {"input": "/input", "output": "/output", "work": "/app/workdir"}


def quick_setup(input_dir: str = "/input",
                output_dir: str = "/output",
                work_dir: str = "/app/workdir") -> dict:
    """Create directories, log device info, return resolved paths + device string.

    Returns
    -------
    dict with keys: input, output, work, device, gpu_name, torch_version, transformers_version
    """
    for p in (input_dir, output_dir, work_dir):
        Path(p).mkdir(parents=True, exist_ok=True)
    _PATHS.update(input=input_dir, output=output_dir, work=work_dir)

    info = {
        "input": input_dir,
        "output": output_dir,
        "work": work_dir,
    }
    try:
        import torch
        info["torch_version"] = torch.__version__
        info["cuda_available"] = bool(torch.cuda.is_available())
        if info["cuda_available"]:
            info["device"] = "cuda"
            info["gpu_name"] = torch.cuda.get_device_name(0)
            info["gpu_count"] = torch.cuda.device_count()
            try:
                props = torch.cuda.get_device_properties(0)
                info["gpu_total_mem_gb"] = round(props.total_memory / 1024**3, 2)
            except Exception:
                pass
        else:
            info["device"] = "cpu"
    except Exception as exc:
        log.warning("Could not import torch during quick_setup: %s", exc)
        info["device"] = "cpu"

    try:
        import transformers
        info["transformers_version"] = transformers.__version__
    except Exception:
        info["transformers_version"] = "unknown"

    log.info("quick_setup: input=%s output=%s work=%s device=%s",
             input_dir, output_dir, work_dir, info.get("device"))
    if info.get("device") == "cuda":
        log.info("  GPU: %s (%.1f GB, count=%d)",
                 info.get("gpu_name", "?"),
                 info.get("gpu_total_mem_gb", 0.0),
                 info.get("gpu_count", 1))
    return info


def quick_finish() -> None:
    """Copy any files left in workdir to output_dir (no-op if already there)."""
    work = _PATHS.get("work", "/app/workdir")
    output = _PATHS.get("output", "/output")
    if not os.path.isdir(work) or not os.path.isdir(output):
        return
    for fn in os.listdir(work):
        src = os.path.join(work, fn)
        dst = os.path.join(output, fn)
        if os.path.isfile(src) and not os.path.exists(dst):
            try:
                shutil.copy2(src, dst)
            except Exception as exc:
                log.warning("quick_finish: failed to copy %s -> %s: %s", src, dst, exc)
    log.info("quick_finish: workdir flushed to %s", output)


def save_final_results(results: dict,
                       output_files: Optional[List[str]] = None,
                       file_descriptions: Optional[List[str]] = None) -> str:
    """Persist the agent's final result record as /output/final_results.json.

    Required at the end of every Discovery script.
    """
    output_dir = _PATHS.get("output", "/output")
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    payload = {
        "results": results,
        "output_files": output_files or [],
        "file_descriptions": file_descriptions or [],
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    out_path = os.path.join(output_dir, "final_results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, default=_json_default)
    log.info("save_final_results: wrote %s", out_path)
    return out_path


def _json_default(obj):
    """JSON encoder for numpy scalars / arrays."""
    import numpy as _np
    if isinstance(obj, (_np.integer,)):
        return int(obj)
    if isinstance(obj, (_np.floating,)):
        return float(obj)
    if isinstance(obj, (_np.ndarray,)):
        return obj.tolist()
    if isinstance(obj, (Path,)):
        return str(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


# ---------------------------------------------------------------------------
# Model loading
# ---------------------------------------------------------------------------

def load_esm2(model_name: str = DEFAULT_MODEL,
              device: Optional[str] = None,
              dtype: Optional[str] = None):
    """Load an ESM-2 model + tokenizer from the local HuggingFace cache.

    Parameters
    ----------
    model_name : str
        Either a short alias from SUPPORTED_MODELS (e.g. 'esm2_t33_650M')
        or a full HuggingFace id ('facebook/esm2_t33_650M_UR50D').
    device : 'cuda' | 'cpu' | None
        None -> auto (cuda if available, else cpu).
    dtype : 'float16' | 'float32' | 'bfloat16' | None
        None -> float16 on cuda, float32 on cpu.

    Returns
    -------
    (model, tokenizer, device_str)
    """
    import torch
    from transformers import AutoModel, AutoTokenizer

    hf_id = resolve_model_name(model_name)
    if device is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"
    if dtype is None:
        dtype_t = torch.float16 if device == "cuda" else torch.float32
    else:
        dtype_t = {"float16": torch.float16,
                   "bfloat16": torch.bfloat16,
                   "float32": torch.float32}[dtype]

    log.info("Loading ESM-2 model '%s' (%s) on %s [%s] ...",
             model_name, hf_id, device, dtype_t)
    t0 = time.time()
    tokenizer = AutoTokenizer.from_pretrained(hf_id)
    model = AutoModel.from_pretrained(hf_id, torch_dtype=dtype_t)
    model.eval()
    model.to(device)
    log.info("Model loaded in %.1fs (params=%.1fM)",
             time.time() - t0,
             sum(p.numel() for p in model.parameters()) / 1e6)
    return model, tokenizer, device


# ---------------------------------------------------------------------------
# Sequence I/O
# ---------------------------------------------------------------------------

def sanitize_sequence(seq: str) -> str:
    """Uppercase, strip whitespace, map non-standard residues to X."""
    s = "".join(seq.split()).upper()
    return "".join(ch if ch in _VALID_AA else "X" for ch in s)


def read_fasta(path: str) -> List[Tuple[str, str]]:
    """Parse a FASTA file. Falls back to a tiny pure-Python parser if
    Biopython is not present."""
    records: List[Tuple[str, str]] = []
    try:
        from Bio import SeqIO
        for rec in SeqIO.parse(path, "fasta"):
            records.append((str(rec.id), sanitize_sequence(str(rec.seq))))
        return records
    except ImportError:
        pass
    cur_id, cur_seq = None, []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip()
            if not line:
                continue
            if line.startswith(">"):
                if cur_id is not None:
                    records.append((cur_id, sanitize_sequence("".join(cur_seq))))
                cur_id = line[1:].split()[0]
                cur_seq = []
            else:
                cur_seq.append(line)
        if cur_id is not None:
            records.append((cur_id, sanitize_sequence("".join(cur_seq))))
    return records


def read_sequences_json(path: str) -> List[Tuple[str, str]]:
    """Parse a JSON list of {id, sequence} objects."""
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, list):
        raise ValueError(f"{path}: expected a JSON list of objects")
    out: List[Tuple[str, str]] = []
    for i, item in enumerate(data):
        if isinstance(item, dict):
            sid = str(item.get("id") or item.get("name") or f"seq_{i}")
            seq = item.get("sequence") or item.get("seq") or ""
        else:
            sid, seq = f"seq_{i}", str(item)
        out.append((sid, sanitize_sequence(seq)))
    return out


def load_sequences(input_dir: str = "/input") -> List[Tuple[str, str]]:
    """Auto-detect FASTA or JSON in input_dir and return (id, sequence) pairs.

    Search order: sequences.fasta, sequences.fa, *.fasta, *.fa, sequences.json.
    """
    p = Path(input_dir)
    candidates = ["sequences.fasta", "sequences.fa"]
    for c in candidates:
        f = p / c
        if f.is_file():
            log.info("Reading sequences from %s", f)
            return read_fasta(str(f))
    for ext in ("*.fasta", "*.fa"):
        for f in p.glob(ext):
            log.info("Reading sequences from %s", f)
            return read_fasta(str(f))
    for c in ("sequences.json", "input.json"):
        f = p / c
        if f.is_file():
            log.info("Reading sequences from %s", f)
            return read_sequences_json(str(f))
    raise FileNotFoundError(
        f"No sequences.fasta / *.fasta / sequences.json found in {input_dir}"
    )


# ---------------------------------------------------------------------------
# Embedding
# ---------------------------------------------------------------------------

def _bucket_by_length(items: List[Tuple[str, str]]) -> List[Tuple[str, str]]:
    """Sort by sequence length so each batch has minimal padding."""
    return sorted(items, key=lambda kv: len(kv[1]))


def embed_sequences(model,
                    tokenizer,
                    sequences: Sequence[Tuple[str, str]],
                    device: str,
                    batch_size: int = 8,
                    max_length: int = 1024,
                    return_per_residue: bool = False,
                    return_contacts: bool = False,
                    fp16: bool = True,
                    progress: bool = True) -> dict:
    """Compute mean-pooled (and optionally per-residue / contact) embeddings.

    Parameters
    ----------
    sequences : list of (id, sequence)
    batch_size : int
        Number of sequences per forward pass. Auto-bucketed by length.
    max_length : int
        Sequences longer than this are truncated (ESM-2 was trained at 1024).
    return_per_residue : bool
        If True, retain per-residue embeddings (after stripping CLS/EOS/pad tokens).
    return_contacts : bool
        If True, also compute predict_contacts() via the contact head.
    fp16 : bool
        Use autocast on CUDA. Ignored on CPU.

    Returns
    -------
    dict with keys:
        ids                    : list[str]
        sequences              : list[str]
        lengths                : np.ndarray[int32]    -- length after truncation
        mean_embeddings        : np.ndarray[float32] (N, D)
        per_residue_embeddings : list[np.ndarray]    (only if return_per_residue)
        contacts               : list[np.ndarray]    (only if return_contacts)
        embed_dim              : int
        model_id               : str
        timing                 : dict
    """
    import torch

    if not sequences:
        raise ValueError("No sequences provided to embed_sequences")

    # Bucket by length but remember original order so outputs align with input.
    indexed = list(enumerate(sequences))
    bucketed = sorted(indexed, key=lambda x: len(x[1][1]))

    n = len(sequences)
    out_mean: List[Optional[np.ndarray]] = [None] * n
    out_per_res: List[Optional[np.ndarray]] = [None] * n
    out_contacts: List[Optional[np.ndarray]] = [None] * n
    out_lengths: List[int] = [0] * n

    # Decide autocast policy
    use_autocast = bool(fp16) and (device == "cuda")
    autocast_ctx = torch.cuda.amp.autocast if use_autocast else _nullcontext

    t0 = time.time()
    with torch.inference_mode():
        for start in range(0, n, batch_size):
            chunk = bucketed[start:start + batch_size]
            orig_idx = [c[0] for c in chunk]
            ids = [c[1][0] for c in chunk]
            seqs = [c[1][1] for c in chunk]

            enc = tokenizer(
                seqs,
                add_special_tokens=True,
                padding=True,
                truncation=True,
                max_length=max_length + 2,  # +CLS +EOS
                return_tensors="pt",
            )
            input_ids = enc["input_ids"].to(device)
            attn = enc["attention_mask"].to(device)

            with autocast_ctx():
                outputs = model(
                    input_ids=input_ids,
                    attention_mask=attn,
                    output_attentions=return_contacts,
                    output_hidden_states=False,
                )
            last_hidden = outputs.last_hidden_state  # (B, L, D)

            # Mask out CLS (pos 0), EOS (last real token per sequence), and PAD.
            # ESM-2 puts EOS at the position of the first 0 in attention_mask - 1.
            attn_b = attn.bool()
            real_mask = attn_b.clone()
            # zero out CLS
            real_mask[:, 0] = False
            # zero out EOS = last True position per row
            for r in range(real_mask.shape[0]):
                last_true = int(attn_b[r].sum().item()) - 1
                if last_true >= 0:
                    real_mask[r, last_true] = False

            real_mask_f = real_mask.unsqueeze(-1).to(last_hidden.dtype)
            summed = (last_hidden * real_mask_f).sum(dim=1)
            counts = real_mask_f.sum(dim=1).clamp(min=1.0)
            mean_emb = (summed / counts).to(torch.float32).cpu().numpy()  # (B, D)

            per_residue_arrays: List[Optional[np.ndarray]] = [None] * len(chunk)
            if return_per_residue:
                hidden_cpu = last_hidden.to(torch.float32).cpu().numpy()
                rm_cpu = real_mask.cpu().numpy()
                for j in range(len(chunk)):
                    keep = rm_cpu[j]
                    per_residue_arrays[j] = hidden_cpu[j, keep, :]

            contact_arrays: List[Optional[np.ndarray]] = [None] * len(chunk)
            if return_contacts:
                # transformers ESM-2 exposes predict_contacts via the model
                try:
                    contacts = model.predict_contacts(input_ids, attn)  # (B, L', L')
                    c_cpu = contacts.to(torch.float32).cpu().numpy()
                    rm_cpu = real_mask.cpu().numpy()
                    for j in range(len(chunk)):
                        keep = rm_cpu[j]
                        # predict_contacts returns L' = L - 2 (no CLS/EOS) already
                        L_eff = int(keep.sum())
                        contact_arrays[j] = c_cpu[j, :L_eff, :L_eff]
                except Exception as exc:
                    log.warning("predict_contacts failed (%s); skipping contacts", exc)

            for j, oi in enumerate(orig_idx):
                out_mean[oi] = mean_emb[j]
                out_lengths[oi] = int(real_mask[j].sum().item())
                if return_per_residue:
                    out_per_res[oi] = per_residue_arrays[j]
                if return_contacts:
                    out_contacts[oi] = contact_arrays[j]

            if progress:
                done = min(start + batch_size, n)
                log.info("  embedded %d / %d sequences (batch_max_len=%d)",
                         done, n, int(attn.shape[1]))

    elapsed = time.time() - t0
    embed_dim = int(out_mean[0].shape[-1]) if out_mean[0] is not None else 0

    result = {
        "ids": [s[0] for s in sequences],
        "sequences": [s[1] for s in sequences],
        "lengths": np.array(out_lengths, dtype=np.int32),
        "mean_embeddings": np.stack(out_mean, axis=0).astype(np.float32),
        "embed_dim": embed_dim,
        "model_id": getattr(model.config, "name_or_path", None) or "esm2",
        "timing": {
            "elapsed_sec": round(elapsed, 3),
            "sec_per_seq": round(elapsed / max(n, 1), 4),
            "n": n,
        },
    }
    if return_per_residue:
        result["per_residue_embeddings"] = out_per_res
    if return_contacts:
        result["contacts"] = out_contacts

    log.info("embed_sequences: %d seqs in %.2fs (%.3fs/seq), dim=%d",
             n, elapsed, elapsed / max(n, 1), embed_dim)
    return result


class _nullcontext:
    """Tiny no-op context manager (Python 3.7+ has contextlib.nullcontext but we want callable())."""
    def __init__(self, *a, **kw): pass
    def __enter__(self): return self
    def __exit__(self, *a): return False


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def save_embeddings(result: dict,
                    out_dir: str = "/output",
                    save_per_residue: bool = True,
                    save_contacts: bool = False) -> dict:
    """Write embeddings + manifest to disk.

    Always writes:
        {out_dir}/embeddings.npz       -- ids, mean_embeddings, lengths
        {out_dir}/manifest.json        -- run metadata

    Optionally writes:
        {out_dir}/per_residue/<id>.npy
        {out_dir}/contacts/<id>.npy
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    npz_path = out / "embeddings.npz"
    np.savez_compressed(
        npz_path,
        ids=np.array(result["ids"], dtype=object),
        mean_embeddings=result["mean_embeddings"],
        lengths=result["lengths"],
    )
    log.info("Wrote %s (shape=%s)", npz_path, result["mean_embeddings"].shape)

    per_res_dir = None
    if save_per_residue and "per_residue_embeddings" in result:
        per_res_dir = out / "per_residue"
        per_res_dir.mkdir(exist_ok=True)
        for sid, arr in zip(result["ids"], result["per_residue_embeddings"]):
            if arr is None:
                continue
            np.save(per_res_dir / f"{_safe_filename(sid)}.npy", arr)
        log.info("Wrote per-residue embeddings to %s/", per_res_dir)

    contacts_dir = None
    if save_contacts and "contacts" in result:
        contacts_dir = out / "contacts"
        contacts_dir.mkdir(exist_ok=True)
        for sid, arr in zip(result["ids"], result["contacts"]):
            if arr is None:
                continue
            np.save(contacts_dir / f"{_safe_filename(sid)}.npy", arr)
        log.info("Wrote contact maps to %s/", contacts_dir)

    manifest = {
        "model_id": result.get("model_id"),
        "embed_dim": result.get("embed_dim"),
        "n_sequences": len(result["ids"]),
        "lengths": {
            "min": int(result["lengths"].min()) if len(result["lengths"]) else 0,
            "max": int(result["lengths"].max()) if len(result["lengths"]) else 0,
            "mean": float(result["lengths"].mean()) if len(result["lengths"]) else 0.0,
        },
        "ids": list(result["ids"]),
        "timing": result.get("timing", {}),
        "files": {
            "embeddings_npz": str(npz_path),
            "per_residue_dir": str(per_res_dir) if per_res_dir else None,
            "contacts_dir": str(contacts_dir) if contacts_dir else None,
        },
    }
    manifest_path = out / "manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, default=_json_default)
    log.info("Wrote %s", manifest_path)
    return manifest


def _safe_filename(name: str) -> str:
    """Make a string safe to use as a filename."""
    return "".join(c if c.isalnum() or c in "._-" else "_" for c in str(name))[:120]
