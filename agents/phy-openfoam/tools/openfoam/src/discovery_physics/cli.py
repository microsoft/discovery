"""`discovery-physics` CLI: the only interface to the deterministic tools (JSON in, JSON out)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .openfoam import runner


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="discovery-physics")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("capabilities")
    sc = sub.add_parser("schema")
    sc.add_argument("which", nargs="?", default="bundle", choices=["bundle", "study", "proposal", "confirmation"])
    ex = sub.add_parser("example", help="write a worked bundle to adapt")
    ex.add_argument("kind", choices=["forward_step", "nozzle"])
    ex.add_argument("out", type=Path)
    t = sub.add_parser("tutorial")
    t.add_argument("path")
    li = sub.add_parser("lint", help="validate + lint a bundle without staging it")
    li.add_argument("bundle", type=Path)
    p = sub.add_parser("prepare")
    p.add_argument("bundle", type=Path)
    p.add_argument("--parent")
    ex2 = sub.add_parser("execute")
    ex2.add_argument("run_id")
    ex2.add_argument("--detach", action="store_true", help="run in the background; poll with status")
    for name in ("status", "finalize", "reassess", "cancel", "recover", "verify"):
        sub.add_parser(name).add_argument("run_id")
    pr = sub.add_parser("propose")
    pr.add_argument("run_id")
    pr.add_argument("proposal", type=Path, help="JSON proposal file")
    cf = sub.add_parser("confirm", help="record the USER's confirmation of needs_confirmation assumptions")
    cf.add_argument("run_id")
    cf.add_argument("confirmations", type=Path, help="JSON list of confirmations")
    g = sub.add_parser("geometry", help="convert STEP/IGES/BREP/STL to ASCII STL")
    g.add_argument("source", type=Path)
    g.add_argument("dest", type=Path)
    g.add_argument("--mesh-size", type=float)
    sp = sub.add_parser("study-prepare")
    sp.add_argument("spec", type=Path)
    for name in ("study-status", "study-assess"):
        sub.add_parser(name).add_argument("study_id")
    ds = sub.add_parser("design-sample", help="Latin-hypercube points within bounds")
    ds.add_argument("spec", type=Path, help='{"bounds": {"x": [lo, hi]}, "n": 8, "seed": 0}')
    xp = sub.add_parser("export")
    xp.add_argument("run_id")
    xp.add_argument("dest", type=Path)
    xp.add_argument("--include-fields", action="store_true")
    cp = sub.add_parser("compact", help="free solver field data of old finalized runs (records kept)")
    cp.add_argument("--older-than-days", type=float, default=30)
    cp.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    try:
        out = _dispatch(a)
        code = 0
    except Exception as exc:  # refusals are data for the agent, not stack traces
        out = {"error": type(exc).__name__, "detail": str(exc)}
        errors = getattr(exc, "errors", None)
        if errors:
            out["errors"] = errors
        code = 2
    print(json.dumps(out, indent=1, default=str))
    return code


def _dispatch(a: argparse.Namespace):
    if a.cmd == "capabilities":
        return runner.capabilities()
    if a.cmd == "schema":
        from .core.models import CaseBundle, Confirmation
        from .core.policy import Proposal
        from .openfoam.study import Study

        return {"bundle": CaseBundle, "study": Study, "proposal": Proposal,
                "confirmation": Confirmation}[a.which].model_json_schema()
    if a.cmd == "example":
        from .benchmarks import cases

        if a.kind == "forward_step":
            b = cases.forward_step_bundle(runner.tutorial("shockFluid/forwardStep")["files"])
        else:
            b = cases.nozzle_bundle()
        a.out.write_text(json.dumps(b, indent=1), encoding="utf-8")
        return {"written": str(a.out)}
    if a.cmd == "tutorial":
        return runner.tutorial(a.path)
    if a.cmd == "lint":
        return runner.lint_bundle(_json(a.bundle))
    if a.cmd == "prepare":
        return runner.prepare(_json(a.bundle), a.parent)
    if a.cmd == "execute":
        return runner.execute(a.run_id, detach=a.detach)
    if a.cmd == "propose":
        return runner.propose(a.run_id, _json(a.proposal))
    if a.cmd == "confirm":
        data = _json(a.confirmations)
        return runner.confirm(a.run_id, data if isinstance(data, list) else [data])
    if a.cmd == "geometry":
        return runner.geometry(a.source, a.dest, mesh_size=a.mesh_size)
    if a.cmd.startswith("study-"):
        from .openfoam import study

        if a.cmd == "study-prepare":
            return study.prepare(study.load_spec(a.spec))
        return study.status(a.study_id) if a.cmd == "study-status" else study.assess(a.study_id)
    if a.cmd == "design-sample":
        from .core.design import latin_hypercube

        spec = _json(a.spec)
        return {"points": latin_hypercube({k: tuple(v) for k, v in spec["bounds"].items()}, int(spec["n"]),
                                          int(spec.get("seed", 0)))}
    if a.cmd in ("export", "compact"):
        from .openfoam import retention

        if a.cmd == "export":
            return retention.export(a.run_id, a.dest, include_fields=a.include_fields)
        return retention.compact(a.older_than_days, apply=a.apply)
    return getattr(runner, {"status": "summary", "finalize": "finalize", "reassess": "reassess",
                            "cancel": "cancel", "recover": "recover", "verify": "verify"}[a.cmd])(a.run_id)


if __name__ == "__main__":
    raise SystemExit(main())
