"""Run-store retention: export a run as an archive, compact old runs (records are never deleted)."""

from __future__ import annotations

import shutil
import time
import zipfile
from pathlib import Path

from ..core import integrity
from . import runner


def export(run_id: str, dest: Path, *, include_fields: bool = False) -> dict:
    path = runner.run_dir(run_id)
    check = runner.verify(run_id)
    dest.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(path.rglob("*")):
            rel = p.relative_to(path)
            if not p.is_file():
                continue
            heavy = rel.parts[:2] == ("output", "case") and not (len(rel.parts) == 3 and rel.parts[2].startswith("log."))
            if heavy and not include_fields:
                continue
            z.write(p, (Path(run_id) / rel).as_posix())
            count += 1
    return {"run_id": run_id, "archive": str(dest), "files": count, "integrity": check,
            "fields_included": include_fields}


def compact(older_than_days: float, *, apply: bool = False) -> dict:
    """Remove solver field data of finalized runs older than N days; keep journal, evidence, report, logs."""
    cutoff = time.time() - older_than_days * 86400
    plan, freed = [], 0
    for path in sorted(runner.runs_root().iterdir()):
        case = path / "output" / "case"
        if not case.is_dir() or path.stat().st_mtime > cutoff:
            continue
        try:
            records = integrity.verify_journal(path)
        except integrity.IntegrityError:
            continue
        if not integrity.last(records, "finalized") or integrity.last(records, "compacted"):
            continue
        heavy = [p for p in case.iterdir() if not p.name.startswith("log.")]
        size = sum(f.stat().st_size for p in heavy for f in ([p] if p.is_file() else p.rglob("*")) if f.is_file())
        plan.append({"run_id": path.name, "mb": round(size / 1e6, 1)})
        freed += size
        if apply:
            for p in heavy:
                shutil.rmtree(p) if p.is_dir() else p.unlink()
            integrity.append(path, "compacted", removed_mb=round(size / 1e6, 1))
    return {"applied": apply, "runs": plan, "total_mb": round(freed / 1e6, 1),
            "note": "journals, evidence, reports, and logs are kept; compacted runs cannot be continued"}
