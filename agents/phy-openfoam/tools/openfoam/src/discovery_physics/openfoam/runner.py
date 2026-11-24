"""Host-side orchestration primitives for CLIO. No model calls, no task/engine dependencies.

Every decision is recomputed from journal-pinned artifacts (see core/integrity.py);
``assessment.json``, ``ruling.json`` and ``report.md`` are human-readable copies only.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Any

from ..core import config, integrity
from ..core.checks import assess
from ..core.hashing import files_sha256, sha256_json, sha256_text
from ..core.integrity import IntegrityError
from ..core.lint import ContractRejected, inject_baseline, lint
from ..core.models import Assessment, CaseBundle, Confirmation, Evidence, Metric, Verdict
from ..core.policy import Proposal, rule
from ..core.slots import slot
from .catalog import BASELINE, known_metrics
from .estimate import estimate
from .monitors import instrument_control_dict, set_end_time
from .safety import require_safe

DEFAULT_IMAGE = config.DEFAULT_IMAGE
_RUN_ID = re.compile(r"^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}$")
REBUILD_ACTIONS = ("REFINE_MESH", "REDUCE_MAX_CO", "REBUILD_CASE")


def runs_root() -> Path:
    env = os.environ.get("DISCOVERY_PHYSICS_RUNS")
    base = Path(env) if env else config.home() / "runs"
    base.mkdir(parents=True, exist_ok=True)
    return base


def run_dir(run_id: str) -> Path:
    if not _RUN_ID.match(run_id):
        raise ValueError("invalid run id")
    path = runs_root() / run_id
    if not path.is_dir():
        raise FileNotFoundError(f"unknown run {run_id}")
    return path


def container_runtime() -> str:
    selected = os.environ.get("DISCOVERY_PHYSICS_RUNTIME") or config.load()["runtime"]
    if selected != "auto":
        if shutil.which(selected):
            return selected
        raise RuntimeError(f"Configured container runtime is unavailable: {selected}")
    for rt in ("podman", "docker"):
        if shutil.which(rt):
            return rt
    raise RuntimeError("Podman or Docker is required to execute OpenFOAM")


def image() -> str:
    return os.environ.get("DISCOVERY_PHYSICS_IMAGE") or config.load()["image"]


def in_container() -> bool:
    return os.environ.get("DISCOVERY_PHYSICS_IN_CONTAINER") == "1"


@lru_cache(maxsize=1)
def code_sha() -> str:
    """Digest of the deterministic decision code; a verdict is bound to the code that made it."""
    root = Path(__file__).resolve().parents[1]
    files = [*sorted((root / "core").glob("*.py")), *sorted((root / "openfoam").glob("*.py")), root / "worker.py"]
    return sha256_json({p.relative_to(root).as_posix(): sha256_text(p.read_text(encoding="utf-8"))
                        for p in files})


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=1, allow_nan=False, default=str), encoding="utf-8")


def _state(path: Path, state: str, **extra: Any) -> None:
    """Progress hint for status/monitoring. Not trusted for decisions."""
    _write(path / "state.json", {"state": state, "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                 "pid": os.getpid(), **extra})


def _new_id() -> str:
    return time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "-" + uuid.uuid4().hex[:8]


def _end_time(control: str) -> float:
    m = re.search(r"(?m)^\s*endTime\s+([^;\s]+)\s*;", control)
    if not m:
        raise ValueError("controlDict needs a numeric endTime")
    return float(m.group(1))


def _decompose_dict(ranks: int) -> str:
    return ("FoamFile\n{\n    format ascii;\n    class dictionary;\n    object decomposeParDict;\n}\n\n"
            f"numberOfSubdomains {ranks};\n\nmethod scotch;\n")


# --------------------------------------------------------------------------- freeze


def freeze(bundle_data: dict, *, study_member: bool = False) -> tuple[CaseBundle, dict]:
    """Validate, add baseline checks, lint, and estimate. Raises on any refusal; writes nothing."""
    bundle = CaseBundle.model_validate(bundle_data)
    contract = inject_baseline(bundle.contract, BASELINE)
    if contract.authority == "proposed":
        contract = contract.model_copy(update={"authority": "frozen"})
    bundle = bundle.model_copy(update={"contract": contract})
    require_safe(bundle.files)
    errors, warnings = lint(contract, known_metrics(bundle.diagnostics), study_member=study_member)
    known = known_metrics(bundle.diagnostics)
    for i, dv in enumerate(bundle.diagnostics.derived):
        # A derived operand may only reference metrics produced earlier (catalog or prior derived).
        earlier = {k for k in known if not k.startswith("derived.")} | \
            {f"derived.{x.name}" for x in bundle.diagnostics.derived[:i]}
        for ref in (dv.a, dv.b):
            if ref is not None and ref not in earlier:
                hint = f" (did you mean 'quantity.{ref}'?)" if f"quantity.{ref}" in known else ""
                errors.append(f"derived '{dv.name}': operand '{ref}' is not a produced metric{hint}")
        if dv.op in ("difference", "ratio") and dv.b is None:
            errors.append(f"derived '{dv.name}': '{dv.op}' needs operand b")
        if dv.op == "abs_rel_error_pct" and not dv.reference:
            errors.append(f"derived '{dv.name}': abs_rel_error_pct needs a nonzero reference")
    for rel, text in bundle.files.items():
        if text.count("/*") > text.count("*/"):
            errors.append(f"{rel}: unterminated /* comment (OpenFOAM will misparse the file)")
    files = dict(bundle.files)
    ranks = bundle.budget.mpi_ranks
    if ranks > 1 and "system/decomposeParDict" not in files:
        files["system/decomposeParDict"] = _decompose_dict(ranks)
    elif ranks > 1 and not re.search(rf"(?m)^\s*numberOfSubdomains\s+{ranks}\s*;", files["system/decomposeParDict"]):
        errors.append(f"system/decomposeParDict numberOfSubdomains must equal budget.mpi_ranks ({ranks})")
    est = estimate(files, [c.executable for c in bundle.mesh], ranks, bundle.budget.wall_seconds)
    if est["cells"] and est["cells"] > bundle.budget.max_cells:
        errors.append(f"blockMesh would create {est['cells']} cells, above budget.max_cells {bundle.budget.max_cells}")
    if est.get("wall_s") and est["wall_s"] > 3 * bundle.budget.wall_seconds:
        errors.append(f"estimated {est['wall_s']:.0f} s exceeds 3x budget.wall_seconds; coarsen or raise the budget")
    elif est.get("exceeds_budget"):
        warnings.append(f"estimated {est['wall_s']:.0f} s may exceed budget.wall_seconds")
    if errors:
        raise ContractRejected(errors)
    bundle = bundle.model_copy(update={"files": files})
    return bundle, {"warnings": warnings, "estimate": est}


def lint_bundle(bundle_data: dict, *, study_member: bool = False) -> dict:
    try:
        bundle, info = freeze(bundle_data, study_member=study_member)
    except ContractRejected as exc:
        return {"ok": False, "errors": exc.errors}
    return {"ok": True, "errors": [], **info, "contract_sha256": sha256_json(bundle.contract),
            "checks": len(bundle.contract.checks),
            "baseline_added": [c.id for c in bundle.contract.checks if c.id.startswith("baseline_")]}


def prepare(bundle_data: dict, parent_run_id: str | None = None, *, study: str | None = None) -> dict:
    """Validate, freeze, and stage a case. Nothing executes here."""
    bundle, info = freeze(bundle_data, study_member=study is not None)
    lineage: dict[str, Any] = {"root": None, "parent": None, "attempt": 1}
    if parent_run_id:
        st = verified(parent_run_id)
        ruling = st["ruling"]
        if not ruling or not ruling["approved"] or ruling["action"] not in REBUILD_ACTIONS:
            raise PermissionError("parent run has no approved rebuild/refinement/time-step action")
        if sha256_json(bundle.contract) != st["plan"]["contract_sha256"]:
            raise PermissionError("a correction must keep the frozen contract; start a new lineage instead")
        if st["children"]:
            raise PermissionError("the parent's approved action was already used")
        pplan = st["plan"]
        lineage = {"root": pplan["lineage"]["root"], "parent": parent_run_id, "attempt": pplan["lineage"]["attempt"] + 1}
    files = dict(bundle.files)
    files["system/controlDict"] = instrument_control_dict(files["system/controlDict"], bundle.diagnostics)
    run_id = _new_id()
    lineage["root"] = lineage["root"] or run_id
    path = runs_root() / run_id
    case = path / "input" / "case"
    for rel, text in files.items():
        dest = case / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8", newline="\n")
    from ..worker import frozen_sha256

    plan = {
        "run_id": run_id, "mode": "fresh", "attempt": lineage["attempt"], "lineage": lineage,
        "solver": bundle.solver, "mesh": [c.model_dump() for c in bundle.mesh],
        "diagnostics": bundle.diagnostics.model_dump(mode="json"),
        "budget": bundle.budget.model_dump(mode="json"), "end_time": _end_time(files["system/controlDict"]),
        "contract_sha256": sha256_json(bundle.contract), "frozen_sha256": frozen_sha256(case),
        "submitted_files_sha256": files_sha256(bundle.files),
        "reference_hashes": bundle.diagnostics.reference_hashes, "study": study,
    }
    _write(path / "bundle.json", bundle.model_dump(mode="json"))
    _write(path / "input" / "plan.json", plan)
    _write(path / "plan.json", plan)
    pending = [a.model_dump() for a in bundle.contract.assumptions if a.source == "needs_confirmation"]
    integrity.append(path, "prepared", contract_sha256=plan["contract_sha256"], frozen_sha256=plan["frozen_sha256"],
                     parent=parent_run_id, bundle_sha256=integrity.file_sha256(path / "bundle.json"),
                     plan_sha256=integrity.file_sha256(path / "plan.json"),
                     input_sha256=integrity.tree_sha256(path / "input"), code_sha256=code_sha(),
                     lint_warnings=info["warnings"], estimate=info["estimate"],
                     pending_assumptions=[a["parameter"] for a in pending], study=study)
    if parent_run_id:
        integrity.append(run_dir(parent_run_id), "child_prepared", child=run_id)
    _state(path, "prepared")
    return {"run_id": run_id, "contract_sha256": plan["contract_sha256"], "frozen_sha256": plan["frozen_sha256"],
            "end_time": plan["end_time"], "lineage": lineage, "assumptions_needing_confirmation": pending,
            "authority": bundle.contract.authority, "lint_warnings": info["warnings"], "estimate": info["estimate"],
            "baseline_checks_added": [c.id for c in bundle.contract.checks if c.id.startswith("baseline_")]}


def confirm(run_id: str, confirmations: list[dict]) -> dict:
    """Record the user's confirmation of needs_confirmation assumptions (before execute)."""
    path = run_dir(run_id)
    st = verified(run_id)
    if st["started"]:
        raise PermissionError("assumptions must be confirmed before execution")
    items = [Confirmation.model_validate(c) for c in confirmations]
    pending = set(st["pending"])
    unknown = [c.parameter for c in items if c.parameter not in pending]
    if unknown:
        raise ValueError(f"not awaiting confirmation: {unknown}")
    integrity.append(path, "assumptions_confirmed", confirmations=[c.model_dump() for c in items])
    return {"run_id": run_id, "still_pending": verified(run_id)["pending"]}


# --------------------------------------------------------------------------- verification


def verified(run_id: str) -> dict:
    """Recompute a run's state from its signed journal and pinned artifacts."""
    path = run_dir(run_id)
    records = integrity.verify_journal(path)
    prep = records[0]
    if prep["event"] not in ("prepared", "prepared_continuation"):
        raise IntegrityError("journal does not start with preparation")
    integrity.require_file(path / "bundle.json", prep.get("bundle_sha256"), "bundle.json")
    integrity.require_file(path / "plan.json", prep.get("plan_sha256"), "plan.json")
    bundle = CaseBundle.model_validate(_read(path / "bundle.json"))
    plan = _read(path / "plan.json")
    if sha256_json(bundle.contract) != plan["contract_sha256"]:
        raise IntegrityError("bundle contract does not match the plan")
    confirmed = {c["parameter"] for r in records if r["event"] == "assumptions_confirmed" for c in r["confirmations"]}
    pending = [p for p in prep.get("pending_assumptions", []) if p not in confirmed]
    attempts = [r["event"] for r in records if r["event"] in ("execution_started", "execution_refused")]
    st: dict[str, Any] = {
        "path": path, "records": records, "prepared": prep, "bundle": bundle, "plan": plan, "pending": pending,
        "started": bool(attempts) and attempts[-1] == "execution_started",
        "cancelled": integrity.last(records, "cancel_requested") is not None,
        "lost": integrity.last(records, "execution_lost") is not None,
        "children": [r["child"] for r in records if r["event"] == "child_prepared"],
        "assessed": None, "evidence": None, "assessment": None, "ruling": None, "final": None,
    }
    assessed = integrity.last(records, "assessed")
    if assessed:
        # A tool upgrade is fine as long as it re-derives the identical record; any change is an error.
        st["code_changed"] = assessed["code_sha256"] != code_sha()
        raw = None
        if assessed["raw_evidence_sha256"]:
            integrity.require_file(path / "output" / "evidence.json", assessed["raw_evidence_sha256"], "worker evidence")
            raw = _read(path / "output" / "evidence.json")
        evidence = _build_evidence(bundle, plan, raw, assessed["runtime_host"], assessed["worker_digest_ok"])
        assessment = assess(bundle.contract, evidence)
        if sha256_json(evidence) != assessed["evidence_sha256"] or \
                sha256_json(assessment) != assessed["assessment_sha256"]:
            raise IntegrityError("recomputed evidence/assessment differs from the journaled record"
                                 + (" (the tool version changed since assessment)" if st.get("code_changed") else ""))
        st.update(assessed=assessed, evidence=evidence, assessment=assessment)
    ruling = integrity.last(records, "ruling")
    st["ruling"] = ruling["record"] if ruling else None
    final = integrity.last(records, "finalized")
    st["final"] = final["record"] if final else None
    return st


# --------------------------------------------------------------------------- execution


def execute(run_id: str, *, detach: bool = False) -> dict:
    path = run_dir(run_id)
    st = verified(run_id)
    integrity.require_file(path / "plan.json", st["prepared"]["plan_sha256"], "plan.json")
    if integrity.tree_sha256(path / "input") != st["prepared"]["input_sha256"]:
        raise IntegrityError("staged input changed after preparation")
    if st["started"] or st["assessed"]:
        raise RuntimeError("run already executed; propose an action to continue")
    if st["pending"]:
        raise PermissionError("assumptions need the user's confirmation before execution: "
                              f"{st['pending']} (ask the user, then `discovery-physics confirm`)")
    if detach:
        log = (path / "execute.log").open("w", encoding="utf-8")
        flags = (subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP) if os.name == "nt" else 0
        proc = subprocess.Popen([sys.executable, "-m", "discovery_physics.cli", "execute", run_id],
                                stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                creationflags=flags, start_new_session=os.name != "nt", close_fds=True)
        _state(path, "queued", pid=proc.pid, detached=True)
        return {"run_id": run_id, "state": "queued", "pid": proc.pid,
                "next": "poll `discovery-physics status <run_id>` until state is done"}
    cfg = config.load()
    _state(path, "queued")
    on_wait = lambda: integrity.append(path, "queued", capacity=cfg["max_concurrent_runs"])  # noqa: E731
    with slot(config.home() / "slots", cfg["max_concurrent_runs"], cfg["queue_timeout_s"], on_wait):
        if in_container():
            return _execute_local(path, st["plan"])
        return _execute_container(path, st["plan"], cfg)


def _container_argv(rt: str, path: Path, out: Path, budget: dict, limited: bool) -> list[str]:
    argv = [rt, "run", "--rm", "--name", f"dp-{path.name}", "--network", "none", "--read-only",
            "--tmpfs", "/tmp:rw,size=1g", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "-e", "HOME=/tmp"]
    if limited:
        argv += ["--pids-limit", "4096", "--cpus", str(budget["cpus"]), "--memory", f"{budget['memory_mb']}m"]
    # No --userns=keep-id: on rootless Podman it re-owns the whole multi-GB image on first use.
    return argv + ["-v", f"{path / 'input'}:/input:ro", "-v", f"{out}:/output:rw", image(),
                   "python", "-m", "discovery_physics.worker", "/input", "/output"]


def _execute_container(path: Path, plan: dict, cfg: dict) -> dict:
    out = path / "output"
    budget = plan["budget"]
    rt = container_runtime()
    out.mkdir(exist_ok=False)
    integrity.append(path, "execution_started", image=image(), runtime=rt, executor="container")
    _state(path, "running", container=f"dp-{path.name}")
    t0 = time.monotonic()
    timeout = budget["wall_seconds"] + 600
    proc = subprocess.run(_container_argv(rt, path, out, budget, True), capture_output=True, text=True,
                          timeout=timeout, check=False)
    limits = "enforced (cpus, memory, pids)"
    if proc.returncode and re.search(r"memory\.max|cpu\.max|pids|cgroup", proc.stderr) and not any(out.iterdir()):
        if not cfg["allow_unenforced_limits"]:
            out.rmdir()
            integrity.append(path, "execution_refused", reason="resource limits cannot be enforced",
                             stderr=proc.stderr[-300:])
            _state(path, "refused")
            raise RuntimeError(
                "This host cannot enforce CPU/memory/pid limits (cgroup controllers not delegated). "
                "Refusing to run unbounded. An operator may opt in with allow_unenforced_limits in "
                f"{config.config_path()} or DISCOVERY_PHYSICS_ALLOW_UNENFORCED_LIMITS=1; the agent must not.")
        limits = "UNENFORCED by operator opt-in (cgroups unavailable); wall-clock budget only"
        integrity.append(path, "resource_limits_unenforced", opt_in_source=str(config.config_path()),
                         stderr=proc.stderr[-300:])
        proc = subprocess.run(_container_argv(rt, path, out, budget, False), capture_output=True, text=True,
                              timeout=timeout, check=False)
    wall = time.monotonic() - t0
    (path / "container.log").write_text(proc.stdout[-200000:] + "\n--- stderr ---\n" + proc.stderr[-200000:],
                                        encoding="utf-8")
    digest = subprocess.run([rt, "image", "inspect", image(), "--format", "{{.Id}}"],
                            capture_output=True, text=True, check=False).stdout.strip()
    return _assess_run(path, plan, proc.returncode, wall, digest, limits)


def _execute_local(path: Path, plan: dict) -> dict:
    """In-container execution (cloud action). The platform container enforces resources."""
    out = path / "output"
    out.mkdir(exist_ok=False)
    integrity.append(path, "execution_started", image=os.environ.get("DISCOVERY_PHYSICS_IMAGE_REF", "in-container"),
                     runtime="in-container", executor="local")
    _state(path, "running")
    t0 = time.monotonic()
    try:
        proc = subprocess.run([sys.executable, "-m", "discovery_physics.worker", str(path / "input"), str(out)],
                              capture_output=True, text=True, timeout=plan["budget"]["wall_seconds"] + 600,
                              check=False)
        rc, log = proc.returncode, proc.stdout[-200000:] + "\n--- stderr ---\n" + proc.stderr[-200000:]
    except subprocess.TimeoutExpired:
        rc, log = -9, "worker exceeded wall budget"
    (path / "container.log").write_text(log, encoding="utf-8")
    return _assess_run(path, plan, rc, time.monotonic() - t0,
                       os.environ.get("DISCOVERY_PHYSICS_IMAGE_REF", "in-container"),
                       "platform-enforced (cloud container job)")


def _dir_mb(path: Path) -> float:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file()) / 1e6


def _build_evidence(bundle: CaseBundle, plan: dict, raw: dict | None, host: dict, digest_ok: bool) -> Evidence:
    """Deterministic: worker evidence + journaled host runtime -> evidence record."""
    errors: list[str] = []
    if raw is None:
        errors.append(f"worker produced no evidence (container exit {host['container_exit']})")
        raw = {"metrics": {}, "errors": [], "runtime": {}}
    elif not digest_ok:
        errors.append("evidence digest mismatch")
        raw = {**raw, "metrics": {}}
    if host["output_mb"] > plan["budget"]["max_output_mb"]:
        errors.append(f"output {host['output_mb']:.0f} MB exceeds budget")
    metrics = {k: Metric.model_validate(v) for k, v in raw["metrics"].items()}
    from ..core.derived import compute

    metrics.update(compute(bundle.diagnostics.derived, metrics))
    return Evidence(
        run_id=plan["run_id"], origin="native", solver_invoked="solver.exit_code" in metrics
        and metrics["solver.exit_code"].value not in (None, -1),
        contract_sha256=plan["contract_sha256"], case_sha256=plan["frozen_sha256"], metrics=metrics,
        errors=[*raw.get("errors", []), *errors], runtime={**raw.get("runtime", {}), **host},
    )


def _assess_run(path: Path, plan: dict, container_rc: int, wall: float, digest: str, limits: str) -> dict:
    _state(path, "assessing")
    out = path / "output"
    bundle = CaseBundle.model_validate(_read(path / "bundle.json"))
    worker_evidence_path = out / "evidence.json"
    host_evidence_path = path / "evidence.json"
    raw, raw_sha, digest_ok = None, None, False
    if worker_evidence_path.exists():
        raw_sha = integrity.file_sha256(worker_evidence_path)
        raw = _read(worker_evidence_path)
        sig = out / "evidence.sha256"
        digest_ok = sig.exists() and sig.read_text(encoding="utf-8").strip() == sha256_json(raw)
    host = {"container_exit": container_rc, "wall_s": round(wall, 2), "image": image(), "image_id": digest,
            "output_mb": round(_dir_mb(out), 1) if out.exists() else 0.0, "resource_limits": limits,
            "mpi_ranks": plan["budget"].get("mpi_ranks", 1)}
    evidence = _build_evidence(bundle, plan, raw, host, digest_ok)
    assessment = assess(bundle.contract, evidence)
    # Keep output/evidence.json byte-identical to the worker packet pinned below.
    # This separate run-root copy is host-enriched and is never the raw input.
    _write(host_evidence_path, evidence.model_dump(mode="json"))
    _write(path / "assessment.json", assessment.model_dump(mode="json"))
    from ..core.report import render

    (path / "report.md").write_text(render(bundle, plan, evidence, assessment), encoding="utf-8")
    integrity.append(path, "assessed", verdict=assessment.verdict.value, live_acceptance=assessment.live_acceptance,
                     evidence_sha256=sha256_json(evidence), assessment_sha256=sha256_json(assessment),
                     raw_evidence_sha256=raw_sha, worker_digest_ok=digest_ok, runtime_host=host,
                     output_case_sha256=integrity.tree_sha256(out / "case") if (out / "case").exists() else None,
                     code_sha256=code_sha())
    _state(path, "done", verdict=assessment.verdict.value)
    return summary(plan["run_id"])


def reassess(run_id: str) -> dict:
    """Re-derive an executed run from its pinned worker evidence (no solver); e.g. after a tool upgrade."""
    path = run_dir(run_id)
    records = integrity.verify_journal(path)
    assessed = integrity.last(records, "assessed")
    if not assessed:
        raise FileNotFoundError("run has no assessment to re-derive")
    if integrity.last(records, "ruling", "finalized"):
        raise PermissionError("run already has a ruling; its verdict is final")
    if assessed["raw_evidence_sha256"]:
        integrity.require_file(path / "output" / "evidence.json", assessed["raw_evidence_sha256"], "worker evidence")
    h = assessed["runtime_host"]
    return _assess_run(path, _read(path / "plan.json"), h["container_exit"], h["wall_s"], h["image_id"],
                       h["resource_limits"])


def cancel(run_id: str) -> dict:
    path = run_dir(run_id)
    st = verified(run_id)
    if st["assessed"]:
        raise RuntimeError("run already finished")
    integrity.append(path, "cancel_requested")
    stopped = False
    if not in_container():
        proc = subprocess.run([container_runtime(), "stop", "-t", "10", f"dp-{run_id}"], capture_output=True,
                              text=True, check=False)
        stopped = proc.returncode == 0
    return {"run_id": run_id, "cancel_requested": True, "container_stopped": stopped,
            "note": "the run will be assessed from whatever it produced and finalized INCONCLUSIVE"}


def _pid_alive(pid: int) -> bool:
    if os.name == "nt":
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True,
                             check=False).stdout
        return str(pid) in out
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def recover(run_id: str) -> dict:
    """Resolve a run whose executing process died (host reboot, crash)."""
    path = run_dir(run_id)
    st = verified(run_id)
    if st["assessed"] or not st["started"]:
        return {"run_id": run_id, "recovered": False, "reason": "run is not in an interrupted state"}
    hint = _read(path / "state.json") if (path / "state.json").exists() else {}
    if hint.get("pid") and _pid_alive(int(hint["pid"])) and hint.get("state") in ("running", "queued", "assessing"):
        return {"run_id": run_id, "recovered": False, "reason": f"executor process {hint['pid']} is still alive"}
    if not in_container():
        subprocess.run([container_runtime(), "rm", "-f", f"dp-{run_id}"], capture_output=True, check=False)
    integrity.append(path, "execution_lost", hint=hint.get("state"))
    return _assess_run(path, st["plan"], -2, 0.0, "", "unknown (executor lost; recovered)")


# --------------------------------------------------------------------------- reporting and decisions


def summary(run_id: str) -> dict:
    path = run_dir(run_id)
    st = verified(run_id)
    hint = _read(path / "state.json") if (path / "state.json").exists() else {}
    if not st["assessed"]:
        progress = None
        case = path / "output" / "case"
        if case.exists():
            times = [float(p.name) for p in case.iterdir() if p.is_dir() and re.fullmatch(r"[0-9.eE+-]+", p.name)]
            progress = {"latest_saved_time": max(times) if times else None, "end_time": st["plan"]["end_time"]}
        return {"run_id": run_id, "state": hint.get("state", "prepared") if st["started"] or hint.get("detached")
                else ("awaiting_confirmation" if st["pending"] else "prepared"),
                "pending_assumptions": st["pending"], "progress": progress,
                "lint_warnings": st["prepared"].get("lint_warnings", []),
                "estimate": st["prepared"].get("estimate")}
    a: Assessment = st["assessment"]
    ev: Evidence = st["evidence"]
    return {
        "run_id": run_id, "state": "done", "verdict": a.verdict.value, "live_acceptance": a.live_acceptance,
        "passed": sum(c.state == "PASS" for c in a.checks), "total_checks": len(a.checks),
        "not_passing": [c.model_dump() for c in a.checks if c.state != "PASS"], "unresolved": a.unresolved,
        "metrics": {k: (m.value, m.unit) for k, m in ev.metrics.items() if m.status == "measured"},
        "runtime": ev.runtime, "report": str(path / "report.md"), "ruling": st["ruling"], "final": st["final"],
        "integrity": "verified (signed journal, pinned evidence, recomputed verdict)",
        "lint_warnings": st["prepared"].get("lint_warnings", []),
    }


def propose(run_id: str, proposal_data: dict) -> dict:
    """Rule on a model proposal. Approved CONTINUE_RUN stages a restart child run."""
    path = run_dir(run_id)
    st = verified(run_id)
    if st["ruling"] or st["final"]:
        raise RuntimeError("this run already has a ruling; act on its child or start a new lineage")
    if not st["assessed"]:
        raise RuntimeError("run has not been executed and assessed")
    proposal = Proposal.model_validate(proposal_data)
    plan, bundle, a, ev = st["plan"], st["bundle"], st["assessment"], st["evidence"].metrics
    if st["cancelled"] or st["lost"]:
        a = a.model_copy(update={"verdict": Verdict.INCONCLUSIVE})
    final_time = ev["solver.final_time"].value if "solver.final_time" in ev else None
    cells = ev["mesh.cells"].value if "mesh.cells" in ev else None
    d = bundle.diagnostics
    ruling = rule(a, proposal, attempts_used=plan["attempt"], max_attempts=bundle.budget.max_attempts,
                  final_time=final_time, max_end_time=bundle.budget.max_end_time or d.target_time,
                  cells=cells, max_cells=bundle.budget.max_cells, dimensions=d.dimensions or 3,
                  known_evidence=set(ev))
    record = {"action": proposal.action, "proposal": proposal.model_dump(mode="json"), **ruling.model_dump(mode="json")}
    integrity.append(path, "ruling", record=record)
    _write(path / "ruling.json", record)
    result = {"run_id": run_id, **record}
    if ruling.approved and proposal.action == "CONTINUE_RUN":
        result["child_run_id"] = _stage_continuation(path, st, proposal.end_time)
    return result


def _stage_continuation(path: Path, st: dict, end_time: float) -> str:
    plan, bundle = st["plan"], st["bundle"]
    if integrity.tree_sha256(path / "output" / "case") != st["assessed"]["output_case_sha256"]:
        raise IntegrityError("solver output changed after assessment; cannot continue from it")
    child_id = _new_id()
    child = runs_root() / child_id
    shutil.copytree(path / "output" / "case", child / "input" / "case")
    control = child / "input" / "case" / "system" / "controlDict"
    control.write_text(set_end_time(control.read_text(encoding="utf-8"), end_time, restart=True), encoding="utf-8")
    child_plan = {**plan, "run_id": child_id, "mode": "continue", "attempt": plan["attempt"] + 1,
                  "end_time": end_time,
                  "lineage": {**plan["lineage"], "parent": plan["run_id"], "attempt": plan["attempt"] + 1}}
    _write(child / "bundle.json", bundle.model_dump(mode="json"))
    _write(child / "input" / "plan.json", child_plan)
    _write(child / "plan.json", child_plan)
    integrity.append(child, "prepared_continuation", parent=plan["run_id"], end_time=end_time,
                     contract_sha256=plan["contract_sha256"],
                     bundle_sha256=integrity.file_sha256(child / "bundle.json"),
                     plan_sha256=integrity.file_sha256(child / "plan.json"),
                     input_sha256=integrity.tree_sha256(child / "input"), code_sha256=code_sha(),
                     lint_warnings=st["prepared"].get("lint_warnings", []), pending_assumptions=[])
    integrity.append(path, "child_prepared", child=child_id)
    _state(child, "prepared")
    return child_id


def finalize(run_id: str) -> dict:
    """Terminal decision for a lineage: deterministic verdict combined with the action ruling."""
    path = run_dir(run_id)
    st = verified(run_id)
    if st["final"]:
        return st["final"]
    if not st["assessed"]:
        raise RuntimeError("run has not been executed and assessed")
    a: Assessment = st["assessment"]
    ruling = st["ruling"]
    if st["cancelled"] or st["lost"]:
        final = Verdict.INCONCLUSIVE
    elif ruling and ruling.get("terminal_verdict"):
        final = Verdict(ruling["terminal_verdict"])
    elif ruling and not ruling["approved"]:
        final = Verdict.INCONCLUSIVE
    else:
        final = Verdict.INCONCLUSIVE if a.verdict == Verdict.CORRECT_AND_RERUN else a.verdict
    live = final == Verdict.ACCEPT and a.live_acceptance
    record = {"run_id": run_id, "final_verdict": final.value, "live_acceptance": live,
              "scientific_verdict": a.verdict.value, "ruling": ruling,
              "cancelled": st["cancelled"], "executor_lost": st["lost"]}
    integrity.append(path, "finalized", record=record)
    _write(path / "final_decision.json", record)
    return record


def verify(run_id: str) -> dict:
    """Explicit integrity audit of one run (journal, signatures, pinned artifacts, recomputation)."""
    try:
        st = verified(run_id)
    except IntegrityError as exc:
        return {"run_id": run_id, "ok": False, "error": str(exc)}
    return {"run_id": run_id, "ok": True, "records": len(st["records"]), "key_id": integrity.key_id(),
            "verdict": st["assessment"].verdict.value if st["assessment"] else None,
            "final": st["final"]["final_verdict"] if st["final"] else None}


# --------------------------------------------------------------------------- inspection


def foam(args: list[str], timeout: int = 120, mounts: list[tuple[Path, str, str]] | None = None) -> str:
    """Run a command in the image (no network, read-only root)."""
    if in_container():
        proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
    else:
        rt = container_runtime()
        vols = [x for src, dst, mode in (mounts or []) for x in ("-v", f"{src}:{dst}:{mode}")]
        proc = subprocess.run([rt, "run", "--rm", "--network", "none", "--read-only", "--tmpfs", "/tmp",
                               "--cap-drop", "ALL", "-e", "HOME=/tmp", *vols, image(), *args],
                              capture_output=True, text=True, timeout=timeout, check=False)
    if proc.returncode:
        raise RuntimeError(proc.stderr[-2000:] or proc.stdout[-2000:])
    return proc.stdout


def capabilities() -> dict:
    text = foam(["bash", "-c", "ls /opt/openfoam14/applications/modules; echo '#'; "
                 "cd /opt/openfoam14/tutorials && find . -name controlDict -path '*/system/*' | "
                 "sed 's#/system/controlDict##; s#^./##' | sort"])
    modules, tutorials = text.split("#", 1)
    return {"distribution": "OpenFOAM Foundation 14", "solver_modules": modules.split(),
            "tutorials": tutorials.split(), "mesh_commands": [
                "blockMesh", "checkMesh", "snappyHexMesh", "surfaceFeatures", "setFields", "renumberMesh"],
            "quantity_function_objects": ["forces", "forceCoeffs", "probes", "surfaceFieldValue",
                                          "volFieldValue", "yPlus"],
            "geometry_import": "STEP/IGES/BREP/STL -> ASCII STL via `discovery-physics geometry`",
            "parallel": "budget.mpi_ranks > 1 runs decomposePar + mpirun + reconstructPar",
            "note": "Cases are free-form; no prompt family is required. Unsupported physics is reported."}


def tutorial(relative: str) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9_./-]+", relative) or ".." in relative:
        raise ValueError("invalid tutorial path")
    text = foam(["python", "-c", (
        "import json,pathlib,sys;r=pathlib.Path('/opt/openfoam14/tutorials')/sys.argv[1];"
        "print(json.dumps({p.relative_to(r).as_posix():p.read_text(errors='replace') for p in r.rglob('*') "
        "if p.is_file() and p.stat().st_size<400000}))"), relative])
    return {"tutorial": relative, "files": json.loads(text),
            "licence": "OpenFOAM Foundation tutorial, GPL-3.0; adapt within the user's case."}


def geometry(source: Path, dest: Path, *, mesh_size: float | None = None) -> dict:
    """Convert CAD (STEP/IGES/BREP) or STL to ASCII STL inside the isolated image (gmsh/OpenCASCADE)."""
    source = source.resolve()
    if source.suffix.lower() not in (".step", ".stp", ".iges", ".igs", ".brep", ".stl"):
        raise ValueError("geometry must be STEP, IGES, BREP, or STL")
    if source.stat().st_size > 200 * 1024 * 1024:
        raise ValueError("geometry file exceeds 200 MB")
    work = runs_root().parent / "geometry" / uuid.uuid4().hex[:12]
    work.mkdir(parents=True)
    shutil.copyfile(source, work / ("in" + source.suffix.lower()))
    args = ["python", "-m", "discovery_physics.geometry", f"/work/in{source.suffix.lower()}", "/work/out.stl"]
    if mesh_size:
        args += ["--mesh-size", str(float(mesh_size))]
    if in_container():
        args = [a.replace("/work", str(work)) for a in args]
    report = json.loads(foam(args, timeout=1800, mounts=[(work, "/work", "rw")]))
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(work / "out.stl", dest)
    shutil.rmtree(work, ignore_errors=True)
    return {**report, "stl": str(dest), "bundle_path_hint": f"constant/geometry/{dest.name}"}
