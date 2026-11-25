"""Build an offline HTML presentation from existing CFD evidence; never solve or rule.

No third-party packages are needed. Native status/verify commands supply verdicts;
this helper only reads cases/figures and writes a NEW directory outside run stores.
Separate analysis is explicitly not a native verdict or independently verified claim.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import html
import json
import math
import os
import re
import shutil
import struct
import subprocess
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from types import ModuleType

_policy_file = Path(__file__).resolve().with_name("project_results.py")
if not _policy_file.is_file():
    raise FileNotFoundError("The complete phy-openfoam skill must include scripts/project_results.py")
results_policy = ModuleType("phy_openfoam_report_results_policy")
results_policy.__file__ = str(_policy_file)
exec(compile(_policy_file.read_text(encoding="utf-8"), str(_policy_file), "exec"), results_policy.__dict__)

RUN_ID = re.compile(r"^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}$")
STUDY_ID = re.compile(r"^S[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}$")
NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
VECTOR = re.compile(r"\(\s*(" + NUMBER + r")\s+(" + NUMBER + r")\s+(" + NUMBER + r")\s*\)")
MAX_JSON = 8 * 1024 * 1024
MAX_IMAGE = 8 * 1024 * 1024
MAX_IMAGES = 8
MAX_IMAGE_TOTAL = 32 * 1024 * 1024


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def formatted(value: object) -> str:
    if isinstance(value, float):
        return f"{value:.6g}" if math.isfinite(value) else "unavailable"
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, allow_nan=False)
    return str(value)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path, limit: int = MAX_JSON) -> dict:
    if path.stat().st_size > limit:
        raise ValueError(f"JSON input exceeds the bounded read limit: {path.name}")
    result = json.loads(path.read_text(encoding="utf-8-sig"),
                        parse_constant=lambda value: (_ for _ in ()).throw(ValueError(f"Non-finite JSON {value}")))
    if not isinstance(result, dict):
        raise ValueError(f"Expected a JSON object: {path.name}")
    return result


def inside(base: Path, relative: str) -> Path:
    candidate = PurePosixPath(relative)
    if "\\" in relative or candidate.is_absolute() or ".." in candidate.parts or ":" in relative:
        raise ValueError("Asset path must be a contained relative path")
    path = (base / relative).resolve()
    if not path.is_relative_to(base.resolve()):
        raise ValueError("Asset resolves outside its source directory")
    return path


def resolve_cli(explicit: str | None) -> str:
    selected = explicit or os.environ.get("DISCOVERY_PHYSICS_CLI")
    if selected:
        resolved = shutil.which(selected)
        if not resolved:
            raise FileNotFoundError("The explicitly selected physics CLI is unavailable")
        return resolved
    found = shutil.which("discovery-physics")
    if found:
        return found
    home = Path(os.environ.get("DISCOVERY_PHYSICS_HOME") or
                str(Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".local/share"))) / "DiscoveryPhysics"))
    candidate = home / "venv" / ("Scripts/discovery-physics.exe" if os.name == "nt" else "bin/discovery-physics")
    if not candidate.is_file():
        raise FileNotFoundError("Physics CLI unavailable; create a blocked report instead of installing or substituting a runtime")
    return str(candidate)


def native(cli: str, root: Path, operation: str, identifier: str) -> dict:
    # This allowlist is intentionally observation-only, even for failed reports.
    if operation not in {"status", "verify", "study-status"}:
        raise ValueError("Report generation only permits read-only native inspection")
    pattern = STUDY_ID if operation == "study-status" else RUN_ID
    if not pattern.fullmatch(identifier):
        raise ValueError("Invalid native record identifier")
    env = os.environ.copy()
    env["DISCOVERY_PHYSICS_RUNS"] = str(root)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    process = subprocess.run([cli, operation, identifier], env=env, capture_output=True,
                             text=True, encoding="utf-8", timeout=600, check=False)
    if process.returncode:
        raise RuntimeError(f"Native {operation} inspection failed; no execution or recovery was attempted")
    if len(process.stdout.encode("utf-8")) > MAX_JSON:
        raise ValueError("Native inspection response exceeds the report limit")
    result = json.loads(process.stdout)
    if not isinstance(result, dict) or result.get("error"):
        raise ValueError("Native inspection did not return a usable record")
    return result


def final_label(item: dict) -> str:
    if item.get("verification", {}).get("ok") is not True:
        return "UNVERIFIED"
    status = item.get("status", {})
    final = status.get("final") or {}
    verdict = final.get("final_verdict")
    if verdict == "ACCEPT":
        if final.get("live_acceptance") is True and status.get("live_acceptance") is True and status.get("verdict") == "ACCEPT":
            return "ACCEPT"
        return "UNVERIFIED"
    return verdict if verdict in {"REJECT", "INCONCLUSIVE", "CORRECT_AND_RERUN"} else "NOT FINAL"


def png_asset(path: Path, caption: str, source: str) -> dict:
    if path.stat().st_size > MAX_IMAGE:
        raise ValueError("Illustrative image exceeds 8 MiB")
    data = path.read_bytes()
    if len(data) < 33 or not data.startswith(b"\x89PNG\r\n\x1a\n") or data[12:16] != b"IHDR":
        raise ValueError("Only raster PNG images are embedded; active SVG/HTML is not accepted")
    width, height = struct.unpack(">II", data[16:24])
    if not (0 < width <= 20000 and 0 < height <= 20000 and width * height <= 50000000):
        raise ValueError("Illustrative image dimensions exceed the report limit")
    return {"caption": caption, "source": source, "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data), "width": width, "height": height,
            "uri": "data:image/png;base64," + base64.b64encode(data).decode("ascii")}


def geometry_svg(bundle: dict) -> str | None:
    """Draw literal input mesh-block geometry, explicitly NOT a flow solution."""
    text = bundle.get("files", {}).get("system/blockMeshDict", "")
    text = re.sub(r"/\*.*?\*/|//[^\n]*", "", text, flags=re.S)
    block = re.search(r"\bvertices\s*\((.*?)\)\s*;", text, re.S)
    if not block or "$" in block[1] or "#" in text:
        return None
    points = [tuple(map(float, match)) for match in VECTOR.findall(block[1])]
    if not 4 <= len(points) <= 8192 or any(not math.isfinite(x) for p in points for x in p):
        return None
    spans = [max(p[i] for p in points) - min(p[i] for p in points) for i in range(3)]
    axes = sorted(range(3), key=lambda i: spans[i], reverse=True)[:2]
    if min(spans[i] for i in axes) <= 0:
        return None
    xy = [(p[axes[0]], p[axes[1]]) for p in points]
    arcs = {}
    for match in re.finditer(r"\barc\s+(\d+)\s+(\d+)\s*" + VECTOR.pattern, text):
        a, b = int(match[1]), int(match[2])
        if max(a, b) >= len(points):
            return None
        mid = tuple(map(float, match.groups()[2:]))
        arcs[tuple(sorted((a, b)))] = (xy[a], (mid[axes[0]], mid[axes[1]]), xy[b])
    xlo, xhi = min(p[0] for p in xy), max(p[0] for p in xy)
    ylo, yhi = min(p[1] for p in xy), max(p[1] for p in xy)
    # Give curved bodies a useful detail view; far-field extents remain labeled.
    if arcs:
        curve = [p for arc in arcs.values() for p in arc]
        cx = (min(p[0] for p in curve) + max(p[0] for p in curve)) / 2
        cy = (min(p[1] for p in curve) + max(p[1] for p in curve)) / 2
        radius = max(max(p[0] for p in curve) - min(p[0] for p in curve),
                     max(p[1] for p in curve) - min(p[1] for p in curve)) * 0.85
        view = (cx - radius, cx + radius, cy - radius, cy + radius)
    else:
        view = (xlo, xhi, ylo, yhi)

    def project(p):
        return (70 + 760 * (p[0] - view[0]) / (view[1] - view[0]),
                300 - 230 * (p[1] - view[2]) / (view[3] - view[2]))

    edges = set()
    for match in re.finditer(r"\bhex\s*\(([\d\s]+)\)", text):
        ids = [int(x) for x in match[1].split()]
        if len(ids) != 8 or max(ids) >= len(points):
            return None
        for i, j in [(0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6), (6, 7), (7, 4)]:
            edges.add(tuple(sorted((ids[i], ids[j]))))
    drawing = []
    for a, b in sorted(edges):
        segment = [xy[a], xy[b]]
        arc = arcs.get((a, b))
        if arc:
            (x1, y1), (xm, ym), (x2, y2) = arc
            det = 2 * (x1 * (ym - y2) + xm * (y2 - y1) + x2 * (y1 - ym))
            if abs(det) < 1e-30:
                continue
            s1, sm, s2 = x1*x1 + y1*y1, xm*xm + ym*ym, x2*x2 + y2*y2
            cx = (s1*(ym-y2) + sm*(y2-y1) + s2*(y1-ym)) / det
            cy = (s1*(x2-xm) + sm*(x1-x2) + s2*(xm-x1)) / det
            start, mid, end = [math.atan2(y-cy, x-cx) for x, y in arc]
            delta = (end - start) % (2 * math.pi)
            if (mid - start) % (2 * math.pi) > delta:
                delta -= 2 * math.pi
            radius = math.hypot(x1-cx, y1-cy)
            segment = [(cx + radius * math.cos(start + delta*k/32),
                        cy + radius * math.sin(start + delta*k/32)) for k in range(33)]
        projected = [project(p) for p in segment]
        coords = " ".join(f"{x:.2f},{y:.2f}" for x, y in projected)
        drawing.append(f'<polyline points="{coords}" fill="none" stroke="{"#38bdf8" if arc else "#526d8e"}" stroke-width="{"3" if arc else "1.5"}"/>')
    if not drawing:
        return None
    bounds = f"Input coordinates: {xlo:.4g} to {xhi:.4g}; {ylo:.4g} to {yhi:.4g}. Geometry schematic; aspect adjusted."
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 370" role="img" aria-label="Input geometry schematic, not simulated flow">'
            '<rect width="900" height="370" rx="18" fill="#0e213b"/>'
            '<defs><clipPath id="geometry-clip"><rect x="55" y="60" width="790" height="255"/></clipPath></defs>'
            '<text x="38" y="37" fill="#e2e8f0" font-family="sans-serif" font-size="18">Input mesh-block geometry · not a flow solution</text>'
            '<g clip-path="url(#geometry-clip)">' + "".join(drawing) + '</g>'
            f'<text x="38" y="345" fill="#b9c9de" font-family="sans-serif" font-size="13">{esc(bounds)}</text></svg>')


def collect(cli: str, root: Path, run_ids: list[str], study_ids: list[str]) -> dict:
    studies, identifiers = [], list(run_ids)
    for sid in study_ids:
        current = native(cli, root, "study-status", sid)
        identifiers += [m["leaf_run"] for m in current["members"].values()]
        path = inside(root.parent / "studies", sid)
        spec = read_json(path / "study.json")
        journal = path / "journal.jsonl"
        if journal.stat().st_size > MAX_JSON:
            raise ValueError("Study journal exceeds the report read limit")
        records = [json.loads(row) for row in journal.read_text(encoding="utf-8").splitlines() if row.strip()]
        previous = [r["record"] for r in records if r.get("event") == "study_assessed"]
        assessment = previous[-1] if previous else None
        if assessment and any(assessment.get("members", {}).get(n, {}).get("leaf_run") != m["leaf_run"]
                              for n, m in current["members"].items()):
            assessment = None  # Do not present an older lineage's result as current.
        studies.append({"study_id": sid, "title": spec.get("title", sid),
                        "status": current, "assessment": assessment})
    runs, image_total = [], 0
    for rid in dict.fromkeys(identifiers):
        verification = native(cli, root, "verify", rid)
        status = native(cli, root, "status", rid) if verification.get("ok") is True else {}
        item = {"run_id": rid, "verification": {k: v for k, v in verification.items() if k != "key_id"},
                "status": status, "contract": {}, "geometry": None, "images": [], "image_notes": []}
        path = inside(root, rid)
        if verification.get("ok") is True:
            bundle = read_json(path / "bundle.json")
            item["contract"] = bundle.get("contract", {})
            item["geometry"] = geometry_svg(bundle)
            for name in status.get("runtime", {}).get("figures", [])[:MAX_IMAGES]:
                try:
                    source = inside(path / "output/figures", name)
                    if image_total + source.stat().st_size > MAX_IMAGE_TOTAL:
                        raise ValueError("Combined report image size limit reached")
                    caption = name.replace("_", " ").removesuffix(".png")
                    if name.startswith("field_") and name.endswith(".png"):
                        field_name = name[6:-4]
                        field = next((f for f in bundle.get("diagnostics", {}).get("fields", [])
                                      if f.get("name") == field_name), {})
                        unit = field.get("unit", "units unavailable")
                        stamp = status.get("metrics", {}).get("solver.final_time", [None])[0]
                        axis = "steady iteration" if item["contract"].get("regime") == "steady" else "solver time"
                        caption = f"{field_name}{' magnitude' if field.get('components') == 3 else ''} [{unit}] · {axis} {formatted(stamp) if stamp is not None else 'unavailable'}"
                    asset = png_asset(source, caption,
                                      f"{rid}/output/figures/{name}")
                    image_total += asset["bytes"]
                    item["images"].append(asset)
                except (OSError, ValueError):
                    item["image_notes"].append(f"Illustrative figure unavailable or refused: {Path(name).name}")
        item["label"] = final_label(item)
        runs.append(item)
    return {"runs": runs, "studies": studies}


def table(headings: list[str], rows: list[list[object]]) -> str:
    return ('<div class="table-scroll"><table><thead><tr>'
            + "".join(f"<th scope=\"col\">{esc(h)}</th>" for h in headings)
            + '</tr></thead><tbody>' + "".join("<tr>" + "".join(f"<td>{esc(formatted(v))}</td>" for v in row) + "</tr>" for row in rows)
            + '</tbody></table></div>')


def tone(label: str) -> str:
    return "bad" if label in {"REJECT", "FAIL"} else "good" if label in {"ACCEPT", "PASS"} else "warn"


def render(data: dict, title: str, blocked: str | None = None, bundle: dict | None = None) -> str:
    runs, studies, analysis = data["runs"], data["studies"], data.get("analysis")
    labels = [r["label"] for r in runs]
    external = analysis.get("content", {}).get("baseline_gate_state") if analysis else None
    if blocked:
        heading, summary = "BLOCKED · NOT RUN", blocked
    elif external:
        heading = f"BASELINE ANALYSIS: {external}"
        summary = (f"{sum(x == 'ACCEPT' for x in labels)} of {len(runs)} native run contracts were accepted. "
                   f"The separate baseline analysis records {external}. Numerical health or a passing grid study does not override the baseline/reference result.")
    elif len(runs) == 1:
        heading = labels[0]
        summary = f"Native run {runs[0]['run_id']} is {labels[0]}. Acceptance, when present, covers only its frozen objectives and checks."
    else:
        heading = "FINALIZED MEASUREMENTS" if labels and all(x == "ACCEPT" for x in labels) else "REVIEW REQUIRED"
        summary = (f"{sum(x == 'ACCEPT' for x in labels)} of {len(runs)} native run contracts were accepted. "
                   "There is no inferred campaign acceptance, physical validation or winning design; inspect the registered study criteria and limitations.")
    if external in {"PASS", "ACCEPT"}:
        summary += " The separate analysis is a recorded derivative, not an independently verified native verdict."
        conflicts = [label for label in labels if label != "ACCEPT"]
        if conflicts:
            heading = f"NATIVE RESULT: {conflicts[0]} · SEPARATE ANALYSIS: {external}"
            summary += " The separate analysis does not override the non-accepted or unverified native result."
    hero_images = []
    # Study-status member order is alphabetical, not a resolution ranking.
    # Prefer the highest-resolution selected case, not whichever happened last.
    def resolution(run):
        value = run["status"].get("metrics", {}).get("mesh.cells", [0])[0]
        return value if type(value) in (int, float) else 0

    for run in sorted(runs, key=resolution, reverse=True):
        fields = [i for i in run["images"] if "/field_" in i["source"]]
        if fields:
            hero_images = [(run["run_id"], i) for i in fields[:2]]
            break
    gallery = "".join(
        f'<figure><img src="{i["uri"]}" alt="{esc(i["caption"])}; native field visualization for {esc(rid)}">'
        f'<figcaption>Native field visualization · {esc(i["caption"])}<br><span>{esc(rid)} · illustrative, not acceptance evidence</span></figcaption></figure>'
        for rid, i in hero_images)
    geometry = next((r["geometry"] for r in reversed(runs) if r["geometry"]), None)
    if not geometry and bundle:
        geometry = geometry_svg(bundle)
    if not gallery:
        gallery = ('<figure class="schematic">' + geometry + '<figcaption>Input schematic only. No native solution image is available.</figcaption></figure>') if geometry else (
            '<div class="empty-visual"><span>NO SOLUTION IMAGE</span><h3>No native field image is available</h3>'
            '<p>No flow visualization has been invented. The result is blocked, incomplete, unverified, or its optional images were unavailable.</p></div>')
    counted = [r for r in runs if isinstance(r["status"].get("passed"), int)
               and isinstance(r["status"].get("total_checks"), int)]
    check_count = (f"{sum(r['status']['passed'] for r in counted)} / {sum(r['status']['total_checks'] for r in counted)}"
                   if len(counted) == len(runs) and runs else "Not run" if blocked else "Unavailable")
    walls = [r["status"].get("runtime", {}).get("wall_s") for r in runs]
    wall_label = (f"{sum(walls) / 60:.1f} min" if runs and all(type(w) in (int, float) and math.isfinite(w) for w in walls)
                  else "Not run" if blocked else "Unavailable")
    cards = [("Native runs", str(len(runs))), ("Registered checks passed", check_count),
             ("Displayed-run wall time", wall_label), ("Scope", "Frozen contracts only")]
    findings = []
    if analysis:
        recorded = analysis["content"]
        for key, label, unit in [
            ("fine_cd", "Fine-grid drag coefficient", ""),
            ("native_fine_gci_pct", "Fine-grid GCI", " percent"),
            ("domain_shift_pct", "Expanded-domain shift", " percent"),
            ("uncertainty_inclusive_reference_discrepancy_pct", "Reference discrepancy including assessed uncertainty", " percent"),
        ]:
            if key in recorded and type(recorded[key]) in (int, float):
                findings.append(f"{label}: {formatted(recorded[key])}{unit}.")
    elif len(runs) == 1:
        for name, pair in runs[0]["status"].get("metrics", {}).items():
            if name.startswith(("quantity.", "derived.")) and len(findings) < 4:
                findings.append(f"{name}: {formatted(pair[0])} [{pair[1]}].")
    findings_html = ('<ul class="key-findings">' + "".join(f"<li>{esc(item)}</li>" for item in findings) + '</ul>') if findings else ""
    sections = []
    for run in runs:
        status, contract = run["status"], run["contract"]
        metrics = status.get("metrics", {})
        objectives = "".join(f'<li><strong>{esc(o["description"])}</strong><br><span class="muted">Claim: {esc(o.get("claim", "unspecified"))}</span></li>'
                             for o in contract.get("objectives", []))
        not_passing = status.get("not_passing", [])
        failures = table(["Check", "State", "Measured", "Threshold", "Units"], [
            [c["id"], c["state"], c.get("value"), c.get("threshold"), c.get("unit", "1")] for c in not_passing]) if not_passing else '<p>No failing/unknown checks are returned by this native snapshot.</p>'
        metric_rows = [[name, pair[0], pair[1]] for name, pair in metrics.items()
                       if name.startswith(("quantity.", "derived.", "mesh.cells", "solver.final_time", "solver.residual_", "stationarity.", "conservation.final_net_flux_rel"))]
        assumptions = [[a["parameter"], a["value"], a.get("unit", "1"), a["source"]] for a in contract.get("assumptions", [])]
        limitations = "".join(f"<li>{esc(v)}</li>" for v in contract.get("limitations", []))
        notes = "".join(f"<li>{esc(v)}</li>" for v in [*status.get("unresolved", []), *run["image_notes"]])
        diagnostics = "".join(f'<figure><img loading="lazy" src="{i["uri"]}" alt="{esc(i["caption"])}"><figcaption>{esc(i["caption"])} · illustrative native output</figcaption></figure>'
                              for i in run["images"] if "/field_" not in i["source"])
        provenance = {"run_id": run["run_id"], "integrity": run["verification"],
                      "contract_sha256": data.get("contracts", {}).get(run["run_id"]),
                      "image_id": status.get("runtime", {}).get("image_id"),
                      "OpenFOAM_build": status.get("runtime", {}).get("openfoam_build"),
                      "resource_limits": status.get("runtime", {}).get("resource_limits"),
                      "wall_s": status.get("runtime", {}).get("wall_s")}
        sections.append(f'<section class="panel"><div class="section-heading"><h2>{esc(contract.get("title", run["run_id"]))}</h2>'
                        f'<span class="badge {tone(run["label"])}">{esc(run["label"])}</span></div>'
                        f'<p class="mono">{esc(run["run_id"])}</p><h3>What this contract supports</h3><ul>{objectives}</ul>'
                        f'<h3>Failing or unknown checks</h3>{failures}<ul>{notes}</ul>'
                        f'<h3>Engineering quantities & numerical diagnostics</h3>{table(["Metric", "Value", "Units"], metric_rows)}'
                        f'<details><summary>Assumptions, reference and limitations</summary>{table(["Parameter", "Value", "Units", "Source"], assumptions)}'
                        f'<p>{esc(contract.get("reference", "No reference comparison claimed."))}</p><ul>{limitations}</ul></details>'
                        f'<details><summary>Convergence and monitor images</summary><div class="diagnostics">{diagnostics or "No native diagnostic images available."}</div></details>'
                        f'<details><summary>Native provenance and resource use</summary><pre>{esc(json.dumps(provenance, indent=2))}</pre>'
                        '<p>Wall time above covers the displayed leaf run, not automatically its entire restart lineage or human effort.</p></details></section>')
    study_sections = "".join(
        f'<section class="panel"><h2>{esc(s["title"])}</h2><p>Native study verdict: <strong>{esc((s["assessment"] or {}).get("verdict", "NOT ASSESSED"))}</strong>. '
        'This applies only to its frozen cross-run criteria, not all engineering objectives.</p>'
        f'<pre>{esc(json.dumps(s["assessment"] or s["status"], indent=2))}</pre></section>' for s in studies)
    separate = ""
    if analysis:
        separate = ('<section class="panel"><h2>Separate baseline / campaign analysis</h2>'
                    '<p class="notice">Recorded derivative supplied for presentation; not a new native criterion and not independently verified by this helper. '
                    'Its failures and uncertainties cannot be replaced by accepted measurement contracts.</p>'
                    f'<pre>{esc(json.dumps(analysis["content"], indent=2))}</pre><p class="mono">Source SHA-256: {esc(analysis["sha256"])}</p></section>')
    geometry_panel = ('<section class="panel"><h2>Geometry context</h2><div class="geometry">' + geometry
                      + '</div><p class="muted">Input mesh-block schematic, not reconstructed flow; axes/aspect may be adjusted for readability.</p></section>') if geometry and hero_images else ""
    css = """
    :root{color-scheme:light;--ink:#15263e;--muted:#52647a;--blue:#126ab3;--line:#dce5ef}
    *{box-sizing:border-box}body{margin:0;background:#eef3f8;color:var(--ink);font:16px/1.6 'Segoe UI',system-ui,sans-serif}
    header{background:#10233e;color:#eef6ff;padding:22px max(5vw,24px)}header strong{letter-spacing:.13em;font-size:14px}header span{float:right;color:#adc9e8;font-size:13px}
    main{max-width:1240px;margin:32px auto;padding:0 24px}h1{font-size:clamp(28px,4vw,44px);line-height:1.16;letter-spacing:-.03em;margin:12px 0 18px}h2{font-size:23px;margin:0 0 12px}h3{font-size:17px;margin-top:24px}
    .panel,.hero{background:#fff;border:1px solid var(--line);border-radius:20px;padding:30px;margin:24px 0;box-shadow:0 10px 32px #16324f08}
    .hero{border-top:5px solid var(--blue)}.eyebrow{text-transform:uppercase;letter-spacing:.15em;font-size:12px;font-weight:700;color:var(--blue)}
    .lead{max-width:1000px;color:#425870;font-size:18px}.badge{display:inline-block;padding:6px 12px;border-radius:999px;font-size:12px;font-weight:800;letter-spacing:.05em;white-space:nowrap}
    .bad{background:#ffebe9;color:#9c2626}.good{background:#dcf7ed;color:#146344}.warn{background:#fff1cf;color:#835600}
    .cards{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:24px 0}.card{padding:18px;border:1px solid var(--line);border-radius:12px;background:#f8fbff}.card span{font-size:12px;color:var(--muted);display:block}.card strong{font-size:20px}
    .gallery{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}.gallery figure:only-child{grid-column:1/-1}figure{margin:0;border:1px solid var(--line);border-radius:14px;overflow:hidden;background:#fff}img{display:block;width:100%;height:auto}figcaption{padding:14px 18px;font-size:13px;font-weight:650;background:#f6f9fd}figcaption span{font-weight:400;color:var(--muted);font-size:11px}
    .notice{border-left:4px solid #eead41;background:#fff8e9;padding:14px 18px;font-size:14px}.section-heading{display:flex;align-items:flex-start;justify-content:space-between;gap:16px}.section-heading h2{max-width:900px}
    .table-scroll{overflow:auto}table{width:100%;border-collapse:collapse;font-size:13px}th{text-align:left;color:#48617b;background:#f1f6fc}th,td{padding:11px 14px;border-bottom:1px solid #e3ebf4;vertical-align:top}td{overflow-wrap:anywhere}tbody tr:nth-child(even){background:#fafcfe}
    pre{background:#f4f7fb;padding:18px;border-radius:12px;white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px}.mono{font-family:ui-monospace,monospace;font-size:12px;overflow-wrap:anywhere}.muted{color:var(--muted)}
    details{border-top:1px solid var(--line);padding:16px 0;margin-top:12px}summary{cursor:pointer;color:var(--blue);font-weight:650}.diagnostics{display:grid;gap:18px;max-width:820px;margin:18px auto}.geometry{max-width:900px;margin:auto}.geometry svg,.schematic svg{width:100%;height:auto;display:block}
    .empty-visual{grid-column:1/-1;background:#10233e;border-radius:14px;color:#e3efff;padding:42px}.empty-visual span{color:#7acbff;font-size:12px;letter-spacing:.15em}.empty-visual p{color:#bad0e9}
    footer{color:var(--muted);font-size:12px;padding:20px 0 40px}a{color:var(--blue)}li{margin:8px 0}
    @media(max-width:720px){main{padding:0 12px}.panel,.hero{padding:20px}.cards{grid-template-columns:repeat(2,1fr)}.gallery{grid-template-columns:1fr}header span{float:none;display:block}.section-heading{display:block}}
    @media print{body{background:white}header{background:white;color:#15263e}.panel,.hero{box-shadow:none;break-inside:avoid}details{display:block}details>*{display:block!important}summary{list-style:none}main{max-width:none;padding:0}.gallery{grid-template-columns:1fr 1fr}footer{padding-bottom:0}}
    """
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src data:; style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'; object-src \'none\'">'
            f'<title>{esc(title)}</title><style>{css}</style></head><body><header><strong>PHY-OPENFOAM / ENGINEERING REPORT</strong>'
            f'<span>{esc(data["created_utc"])} · offline evidence presentation</span></header><main>'
            f'<section id="executive-summary" class="hero"><div class="eyebrow">Executive summary</div><h1>{esc(title)}</h1>'
            f'<span class="badge {tone("REJECT" if "REJECT" in labels else "UNVERIFIED" if "UNVERIFIED" in labels else external or heading)}">{esc(heading)}</span><p class="lead">{esc(summary)}</p>'
            + findings_html + '<div class="cards">' + "".join(f'<div class="card"><span>{esc(label)}</span><strong>{esc(value)}</strong></div>' for label, value in cards)
            + f'</div><div class="gallery">{gallery}</div><p class="notice">Images illustrate available inputs or native outputs; they never decide acceptance. '
            'A healthy solve is not automatically mesh independent, domain independent, experimentally validated or a superior design.</p></section>'
            + separate + study_sections + geometry_panel + "".join(sections)
            + '<footer>Generated read-only from existing records. No solver, continuation, reassessment or acceptance-policy mutation was performed. '
            'The companion evidence snapshot and content hashes accompany this HTML. Local HMAC verification is same-user tamper evidence, not independent authorization or public authentication.</footer></main></body></html>')


def generate(*, project: Path, results: Path, out: Path | None = None, root: Path | None,
             cli: str | None, run_ids: list[str],
             study_ids: list[str], title: str, blocked: str | None = None,
             analysis: Path | None = None, bundle: Path | None = None) -> dict:
    project = results_policy.project_root(project)
    results = results_policy.validate_container(project, results)
    out = results_policy.validate_destination(project, results, out or results, allow_root=True)
    if out.exists() and out != results:
        raise FileExistsError("Report destination must be new; existing reports are never overwritten")
    if out.relative_to(results).parts[:1] and out.relative_to(results).parts[0].casefold() in {"runs", "studies"}:
        raise ValueError("Report output must be outside native run and study stores")
    if any((parent / "journal.jsonl").is_file() for parent in (out, *out.parents)):
        raise ValueError("Report output must not be inside any signed native record")
    names = ("report.html", "evidence-snapshot.json", "report-receipt.json")
    for name in names:
        results_policy.validate_destination(project, results, out / name, new=True)
    if root:
        root = root.resolve()
        if out.is_relative_to(root) or out.is_relative_to((root.parent / "studies").resolve()):
            raise ValueError("Report output must be outside signed run and study stores")
    if not blocked and not (run_ids or study_ids):
        raise ValueError("Select existing runs/studies or supply an explicit blocked reason")
    if (run_ids or study_ids) and (not root or not root.is_dir()):
        raise ValueError("An existing explicit runs root is required")
    data = collect(resolve_cli(cli), root, run_ids, study_ids) if run_ids or study_ids else {"runs": [], "studies": []}
    data["created_utc"] = datetime.now(timezone.utc).isoformat()
    data["analysis"] = {"content": read_json(analysis), "sha256": sha(analysis)} if analysis else None
    data["contracts"] = {}
    for item in data["runs"]:
        if item["verification"].get("ok") is True:
            data["contracts"][item["run_id"]] = read_json(inside(root, item["run_id"]) / "plan.json").get("contract_sha256")
    input_bundle = read_json(bundle) if bundle else None
    data["project_results"] = {"project_root": str(project), "results_root": str(results),
                               "source_runs_root": str(root) if root else None,
                               "results_manifest_sha256": sha(results / results_policy.MARKER)}
    document = render(data, title, blocked, input_bundle)
    snapshot = json.loads(json.dumps(data))
    for item in snapshot["runs"]:
        item.pop("geometry", None)
        for asset in item["images"]:
            asset.pop("uri", None)
    if out != results:
        out.parent.mkdir(parents=True, exist_ok=True)
        results_policy.validate_destination(project, results, out, new=True)
        out.mkdir(exist_ok=False)
    # Reserve every new presentation file before writing any report bytes.
    # Existing signed records and previous presentation files are never replaced.
    handles = []
    try:
        for name in names:
            results_policy.validate_destination(project, results, out / name, new=True)
            handles.append((out / name).open("x", encoding="utf-8", newline="\n"))
        handles[0].write(document)
        handles[0].close()
        handles[1].write(json.dumps(snapshot, indent=2, allow_nan=False))
        handles[1].close()
        receipt = {"created_utc": data["created_utc"], "presentation_only": True, "solver_executed": False,
                   "report_sha256": sha(out / "report.html"), "snapshot_sha256": sha(out / "evidence-snapshot.json"),
                   "renderer_sha256": sha(Path(__file__)), "path_policy_sha256": sha(_policy_file),
                   "project_results": data["project_results"], "run_ids": [r["run_id"] for r in data["runs"]],
                   "blocked_reason": blocked, "separate_analysis_native_verified": False}
        handles[2].write(json.dumps(receipt, indent=2))
    finally:
        for stream in handles:
            stream.close()
    return {"report": str(out / "report.html"), "receipt": str(out / "report-receipt.json"),
            "presentation_only": True, "solver_executed": False}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    selected = parser.add_mutually_exclusive_group(required=True)
    selected.add_argument("--results-dir", type=Path, help="Existing marked project-root results-<slug> folder")
    selected.add_argument("--slug", help="Create a new project-root results folder for this report")
    parser.add_argument("--runs-root", type=Path)
    parser.add_argument("--run", action="append", default=[])
    parser.add_argument("--study", action="append", default=[])
    parser.add_argument("--cli")
    parser.add_argument("--out", type=Path, help="Optional fresh subdirectory within the selected results folder")
    parser.add_argument("--title", default="CFD investigation · evidence and outcome")
    parser.add_argument("--analysis", type=Path, help="Existing separate-analysis JSON; displayed as a non-native derivative")
    parser.add_argument("--blocked-reason")
    parser.add_argument("--bundle", type=Path, help="Optional input schematic for a blocked report; never executed")
    args = parser.parse_args(argv)
    try:
        project = results_policy.project_root(args.project_root)
        if args.slug:
            if args.out is not None:
                raise ValueError("Initialize first when selecting a custom report subdirectory")
            result_dir = Path(results_policy.initialize(project, args.slug)["results_root"])
        else:
            result_dir = results_policy.validate_container(project, args.results_dir)
        result = generate(project=project, results=result_dir, out=args.out,
                          root=args.runs_root, cli=args.cli, run_ids=args.run,
                          study_ids=args.study, title=args.title, blocked=args.blocked_reason,
                          analysis=args.analysis, bundle=args.bundle)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print(json.dumps({"error": type(exc).__name__, "detail": str(exc)}))
        return 2
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())