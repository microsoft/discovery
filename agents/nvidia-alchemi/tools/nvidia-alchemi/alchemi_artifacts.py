"""Strict JSON and verified artifact export; standard library only.

Callers must not concurrently mutate sources or destinations. Export is atomic
per file, not per batch; directory replacement uses a rollback backup. Reports
are returned only on complete success and are never persisted by the exporter.
"""

import hashlib
import json
import math
import os
from pathlib import Path, PureWindowsPath
import shutil
import stat
import tempfile
from enum import Enum

__all__ = ["to_jsonable", "write_json_atomic", "export_artifacts"]
_RESERVED = {"final_results.json", "artifact_manifest.json"}


def to_jsonable(value):
    """Convert supported values without importing NumPy/Torch or stringifying objects.

    Scalar keys use JSON spelling (Path/Enum keys use their converted values).
    Colliding keys, cycles, non-scalar keys and non-CPU tensors raise. Array-like
    objects expose tolist(), scalar-like objects item(), tensors detach()/device.
    """
    active = set()

    def convert(obj):
        if isinstance(obj, Enum):
            return convert(obj.value)
        if obj is None or isinstance(obj, (str, bool, int)):
            return obj
        if isinstance(obj, float):
            return float(obj) if math.isfinite(obj) else {
                "value": None, "finite": False,
                "encoding": "nan" if math.isnan(obj) else "+inf" if obj > 0 else "-inf"}
        if isinstance(obj, Path):
            return str(obj)
        if id(obj) in active:
            raise ValueError("Cyclic JSON value")
        active.add(id(obj))
        try:
            if isinstance(obj, dict):
                result = {}
                for key, item in obj.items():
                    key = convert(key)
                    if not (key is None or isinstance(key, (str, bool, int, float))):
                        raise TypeError("JSON keys must convert to finite scalars")
                    key = key if isinstance(key, str) else json.dumps(key, allow_nan=False)
                    if key in result:
                        raise ValueError(f"JSON key collision: {key!r}")
                    result[key] = convert(item)
                return result
            if isinstance(obj, (list, tuple)):
                return [convert(item) for item in obj]
            if callable(getattr(obj, "detach", None)) and hasattr(obj, "device"):
                if str(getattr(obj.device, "type", obj.device)) != "cpu":
                    raise TypeError("Only CPU tensors can be serialized")
                return convert(obj.detach().tolist())
            for method in ("tolist", "item"):
                if callable(getattr(obj, method, None)):
                    converted = getattr(obj, method)()
                    if type(converted) is type(obj):
                        raise TypeError("Array/scalar conversion made no progress")
                    return convert(converted)
            raise TypeError(f"Unsupported JSON type: {type(obj).__name__}")
        finally:
            active.remove(id(obj))

    return convert(value)


def _no_links(path):
    for node in (*reversed(path.parents), path):
        try:
            info = node.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError(f"Symlink/reparse point forbidden: {node}")


def _absolute(value, base=None):
    if not isinstance(value, (str, Path)):
        raise TypeError("Paths must be str or pathlib.Path")
    text, path = str(value), Path(value)
    if not text or "\0" in text or ".." in text.replace("\\", "/").split("/"):
        raise ValueError(f"Invalid/traversing path: {value!r}")
    if not path.is_absolute():
        windows = PureWindowsPath(text)
        if windows.drive or windows.root:
            raise ValueError(f"Ambiguous relative path: {value!r}")
        path = (base or Path.cwd()) / path
    path = path.absolute()
    _no_links(path)
    return path.resolve()  # Canonicalize aliases only after rejecting links.


def write_json_atomic(path, value):
    """Validate before touching the final file, stage, replace, and strictly reopen.

    Returns None. Serialization/prevalidation errors preserve an existing final.
    """
    clean = to_jsonable(value)
    text = json.dumps(clean, allow_nan=False, ensure_ascii=True, indent=2) + "\n"
    path = _absolute(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    def verify(candidate):
        def reject(token):
            raise ValueError(f"Nonstandard JSON constant: {token}")
        with candidate.open(encoding="utf-8") as stream:
            content = stream.read()
        if content != text or json.loads(content, parse_constant=reject) != clean:
            raise OSError(f"JSON verification failed: {candidate}")

    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n",
                                         dir=path.parent, prefix=".json-", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        verify(temporary)
        _no_links(path)
        os.replace(temporary, path)
        verify(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _portable(parts):
    for name in parts:
        stem = name.split(".")[0].upper()
        if (name.endswith((".", " ")) or any(ord(c) < 32 or c in '<>:"\\|?*' for c in name)
                or stem in {"CON", "PRN", "AUX", "NUL"}
                or stem in {f"{p}{i}" for p in ("COM", "LPT") for i in range(1, 10)}):
            raise ValueError(f"Nonportable artifact name: {name!r}")


def _snapshot(path):
    _no_links(path)
    files, directories = [], []

    def visit(node, relative):
        _no_links(node)
        mode = node.stat().st_mode
        if stat.S_ISREG(mode):
            digest, size = hashlib.sha256(), 0
            with node.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
                    size += len(block)
            files.append(dict(relative_path=relative, size=size, sha256=digest.hexdigest()))
        elif stat.S_ISDIR(mode):
            directories.append(relative)
            names = set()
            for child in sorted(node.iterdir()):
                _portable((child.name,))
                if child.name.casefold() in names:
                    raise ValueError(f"Case-insensitive collision in {node}")
                names.add(child.name.casefold())
                visit(child, child.relative_to(path).as_posix())
        else:
            raise ValueError(f"Not a regular file/directory: {node}")

    visit(path, "." if path.is_dir() else path.name)
    files.sort(key=lambda entry: entry["relative_path"])
    kind = "directory" if directories else "file"
    canonical = json.dumps(files, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest() if directories else files[0]["sha256"]
    return dict(kind=kind, total_bytes=sum(f["size"] for f in files), sha256=digest,
                files=files), sorted(directories)


def _destination(path, output, kind):
    _no_links(path)
    parent = output
    for name in path.relative_to(output).parts:
        if parent.exists():
            for child in parent.iterdir():
                if child.name.casefold() == name.casefold() and child.name != name:
                    raise ValueError(f"Case-insensitive destination collision: {child}")
        parent = parent / name
    if path.exists():
        snapshot = _snapshot(path)
        if snapshot[0]["kind"] != kind:
            raise ValueError(f"File/directory destination conflict: {path}")


def _verify(path, expected):
    if _snapshot(path) != expected:
        raise OSError(f"Artifact integrity verification failed: {path}")


def _publish(source, destination, output, expected):
    temporary = Path(tempfile.mkdtemp(prefix=".alchemi-", dir=output))
    staged, backup = temporary / "candidate" / destination.name, temporary / "backup"
    preserve_backup, published = False, False
    try:
        staged.parent.mkdir()
        if expected[0]["kind"] == "directory":
            shutil.copytree(source, staged, copy_function=shutil.copy2)
        else:
            shutil.copy2(source, staged)
        _verify(staged, expected)
        _destination(destination, output, expected[0]["kind"])
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.is_dir():
            os.replace(destination, backup)
        try:
            os.replace(staged, destination)
            published = True
            _verify(destination, expected)
        except BaseException:
            if backup.exists():
                preserve_backup = True  # Retain recovery data if rollback itself fails.
                if published:
                    shutil.rmtree(destination)
                os.replace(backup, destination)
                preserve_backup = False
            raise
    finally:
        if not preserve_backup:
            shutil.rmtree(temporary)


def export_artifacts(output_files, work_dir, output_dir):
    """Return (label -> absolute output string, schema_version=1 manifest).

    Relative sources are rooted at work_dir; its nested layout is preserved.
    External absolute sources use basenames; sources inside output pass through.
    Equal source aliases share one copy but each gets a manifest entry. Manifest
    files are relative to the artifact directory (a file uses its basename).
    Directory SHA256 hashes the UTF-8 JSON files list, sorted by relative_path,
    with sort_keys=True, separators=(',', ':'), ensure_ascii=True. Empty
    directories are copied/verified but intentionally excluded from that digest.
    """
    if not isinstance(output_files, dict) or not all(isinstance(k, str) for k in output_files):
        raise TypeError("output_files must be a dict with string labels")
    work, output = _absolute(work_dir), _absolute(output_dir)
    if not work.is_dir():
        raise NotADirectoryError(work)
    if output.exists() and not output.is_dir():
        raise NotADirectoryError(output)
    plans, labels, claims = {}, {}, {}
    for label, value in output_files.items():
        source = _absolute(value, work)
        labels[label] = source
        if source in plans:
            continue
        if source.is_dir() and (source == work or output.is_relative_to(source)):
            raise ValueError(f"Directory includes work/output root: {source}")
        relative = (source.relative_to(output) if source.is_relative_to(output) else
                    source.relative_to(work) if source.is_relative_to(work) else Path(source.name))
        _portable(relative.parts)
        if not relative.parts or relative.parts[0].casefold() in _RESERVED:
            raise ValueError(f"Reserved output path: {relative}")
        expected = _snapshot(source)  # Missing declarations fail before any publication.
        destination = output / relative
        for previous, (target, _) in plans.items():
            if (source.is_relative_to(previous) or previous.is_relative_to(source)
                    or destination.is_relative_to(target) or target.is_relative_to(destination)):
                raise ValueError(f"Overlapping source/destination declarations: {source}, {previous}")
        for i in range(1, len(relative.parts) + 1):
            parts = relative.parts[:i]
            key = tuple(p.casefold() for p in parts)
            claim = (parts, expected[0]["kind"] if i == len(relative.parts) else "directory")
            if key in claims and claims[key] != claim:
                raise ValueError(f"Case/type destination collision: {relative}")
            claims[key] = claim
        _destination(destination, output, expected[0]["kind"])
        plans[source] = destination, expected
    output.mkdir(parents=True, exist_ok=True)
    for source, (destination, expected) in plans.items():
        if source != destination:
            _publish(source, destination, output, expected)
    for destination, expected in plans.values():
        _verify(destination, expected)
    mapped, entries = {}, []
    for label, source in labels.items():
        destination, (metadata, _) = plans[source]
        mapped[label] = str(destination)
        entries.append(dict(metadata, label=label, relative_path=destination.relative_to(output).as_posix(),
                            path=str(destination), verified=True))
    return mapped, {"schema_version": 1, "artifacts": entries}