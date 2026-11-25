"""Read-only, bounded terminal heartbeats for an existing private run store.

No package imports, solver/runtime calls, keys, or writes to the observed store.
All status files and log tails are operational hints, never verified verdicts.
This process writes stdout; it cannot schedule messages into an inactive chat.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import threading
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

RUN_ID = re.compile(r"^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}$")
TIME = re.compile(r"^Time = ([0-9.eE+\-]+)(?:s)?\s*$", re.M)
STATES = {"prepared", "awaiting_confirmation", "queued", "running", "assessing",
          "done", "refused", "cancelled", "lost"}
VERDICTS = {"ACCEPT", "REJECT", "INCONCLUSIVE", "CORRECT_AND_RERUN"}
ACTIVE = {"queued", "running", "assessing"}
TAIL_BYTES = 65536


def _object(path: Path) -> dict | None:
    """An absent/partially saved file is unknown, not a terminal state."""
    try:
        if path.stat().st_size > 2 * 1024 * 1024:
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, UnicodeError, ValueError):
        return None


def _text(value: object, limit: int = 80) -> str:
    # Keep one physical line and prevent terminal controls from file/CLI labels.
    return " ".join("".join(c if c.isprintable() else " " for c in str(value)).split())[:limit]


def _number(value: object) -> float | None:
    return float(value) if type(value) in (float, int) and math.isfinite(value) else None


def _solver_progress(case: Path, target: float | None, now: float) -> str:
    try:
        logs = list(case.glob("log.foamRun*"))
        if not logs:
            return "solver log not yet available (meshing/startup may be in progress)"
        log = max(logs, key=lambda p: p.stat().st_mtime)
        info = log.stat()
        with log.open("rb") as stream:
            offset = max(0, info.st_size - TAIL_BYTES)
            stream.seek(offset)
            data = stream.read(TAIL_BYTES)
        # Ignore incomplete rows at either edge of a concurrently written tail.
        if offset:
            data = data.partition(b"\n")[2]
        if data and not data.endswith(b"\n"):
            data = data.rsplit(b"\n", 1)[0] if b"\n" in data else b""
        values = TIME.findall(data.decode("utf-8", errors="replace"))
        last = float(values[-1]) if values else None
        if last is not None and not math.isfinite(last):
            last = None
        schemes = case / "system/fvSchemes"
        steady = schemes.is_file() and schemes.stat().st_size < TAIL_BYTES and bool(
            re.search(r"\bdefault\s+steadyState\s*;", schemes.read_text(encoding="utf-8"))
        )
        unit = "iteration" if steady else "solver time"
        progress = f"{unit} {last:g}" if last is not None else "solver progress unavailable"
        if last is not None and target is not None:
            progress += f"/{target:g}"
        age = max(0, int(now - info.st_mtime))
        return f"{progress}; log age {age}s"
    except (OSError, UnicodeError, ValueError):
        return "solver progress unavailable (startup/write race or inaccessible output)"


def snapshot(runs_root: Path, *, now: float) -> dict:
    """Bounded file reads only; don't call status/verify or load a signing key."""
    paths = sorted(p for p in runs_root.iterdir() if RUN_ID.fullmatch(p.name) and p.is_dir())
    counts: Counter = Counter()
    active, waiting = [], []
    unavailable = 0
    for path in paths:
        plan = _object(path / "plan.json")
        if not plan or plan.get("run_id") != path.name:
            unavailable += 1
            continue
        final = _object(path / "final_decision.json")
        if (final and final.get("run_id") == path.name and final.get("final_verdict") in VERDICTS
                and type(final.get("live_acceptance")) is bool):
            counts[final["final_verdict"]] += 1
            continue
        state = _object(path / "state.json")
        if not state or state.get("state") not in STATES:
            unavailable += 1
            continue
        bundle = _object(path / "bundle.json") or {}
        label = _text(bundle.get("name") or path.name)
        phase = state["state"]
        if phase in ACTIVE:
            progress = _solver_progress(path / "output/case", _number(plan.get("end_time")), now)
            active.append(f"{label}: reported {phase}; {progress}")
        else:
            waiting.append(phase)
    total, finalized = len(paths), sum(counts.values())
    return {"total": total, "finalized": finalized, "final_hints": dict(counts), "active": active,
            "waiting": dict(Counter(waiting)), "unavailable": unavailable,
            "all_final_hints": total > 0 and finalized == total and unavailable == 0}


def format_line(data: dict, *, label: str, now: float, stale_seconds: float) -> str:
    stamp = datetime.fromtimestamp(now, timezone.utc).strftime("%H:%M:%SZ")
    parts = [f"[{stamp}] {_text(label)}", f"finalized {data['finalized']}/{data['total']}"]
    if data["final_hints"]:
        parts.append(", ".join(f"{key} {count}" for key, count in sorted(data["final_hints"].items())))
    if data["active"]:
        parts.extend(data["active"][:2])
        if len(data["active"]) > 2:
            parts.append(f"+{len(data['active']) - 2} other reported active runs")
        ages = [int(x) for line in data["active"] for x in re.findall(r"log age (\d+)s", line)]
        if ages and max(ages) >= stale_seconds:
            parts.append("no recent solver output; liveness uncertain, not proven hung")
    elif data["all_final_hints"]:
        parts.append("run finalization hints complete; study/design decision requires verification")
    else:
        parts.append("no active run confirmed by status files")
    if data["unavailable"] or not data["total"]:
        parts.append(f"progress unavailable for {data['unavailable'] or 'all'} runs")
    parts.append("hints only; not verified acceptance or process-liveness evidence")
    return " | ".join(parts)


def watch(runs_root: Path, *, interval: float = 60.0, max_seconds: float = 18000.0,
          label: str = "phy-openfoam", once: bool = False,
          clock: Callable[[], float] = time.monotonic,
          now: Callable[[], float] = time.time,
          wait: Callable[[float], object] | None = None,
          emit: Callable[[str], None] | None = None) -> int:
    if not math.isfinite(interval) or interval < 60 or not math.isfinite(max_seconds) or max_seconds <= 0:
        raise ValueError("heartbeat interval must be at least 60 seconds; monitor duration must be positive")
    if wait is None:
        wait = threading.Event().wait
    if emit is None:
        emit = lambda line: print(line, flush=True)
    deadline = clock() + max_seconds
    while True:
        wall = now()
        try:
            data = snapshot(runs_root, now=wall)
            emit(format_line(data, label=label, now=wall, stale_seconds=2 * interval))
            if once or data["all_final_hints"]:
                return 0
        except OSError:
            emit(f"{_text(label)} | progress unavailable: run store inaccessible | observation only")
            if once:
                return 1
        remaining = deadline - clock()
        if remaining <= 0:
            break
        # Only the passive observer waits; it neither supervises nor controls a solve.
        wait(min(interval, remaining))
        if clock() >= deadline:
            break
    emit(f"{_text(label)} | monitor duration reached; observer stopped, campaign untouched")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-root", required=True, type=Path, help="Existing private run-store directory")
    parser.add_argument("--label", default="phy-openfoam")
    parser.add_argument("--interval", type=float, default=60.0, help="Seconds between flushed stdout lines (minimum 60)")
    parser.add_argument("--max-seconds", type=float, default=18000.0, help="Observer-only duration cap; does not change run budgets")
    parser.add_argument("--once", action="store_true", help="Print one snapshot without waiting")
    args = parser.parse_args(argv)
    if not args.runs_root.is_dir():
        parser.error("--runs-root must be an existing directory; nothing was created")
    try:
        return watch(args.runs_root, interval=args.interval, max_seconds=args.max_seconds,
                     label=args.label, once=args.once)
    except ValueError as exc:
        parser.error(str(exc))
    except KeyboardInterrupt:
        print("Observer stopped; campaign untouched", flush=True)
        return 130


if __name__ == "__main__":
    sys.exit(main())