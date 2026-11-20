#!/usr/bin/env python3
"""Real KLayout XOR and independent KLayout/Magic DEF streamout."""
import datetime
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import time

TOOL = "streamout-xor"
OUTPUT = "/output"
WORK = "/workdir"


def quick_setup(output_dir="/output", work_dir="/workdir"):
    global OUTPUT, WORK
    OUTPUT = os.environ.get("CHIP_OUTPUT_DIR", output_dir)
    WORK = os.environ.get("CHIP_WORK_DIR", work_dir)
    os.makedirs(OUTPUT, exist_ok=True)
    os.makedirs(WORK, exist_ok=True)
    for name in ("results", "reports", "logs"):
        os.makedirs(os.path.join(OUTPUT, name), exist_ok=True)


def _version(executable, argument="-v"):
    path = shutil.which(executable)
    if not path:
        return "unavailable"
    try:
        proc = subprocess.run([path, argument], text=True, capture_output=True, timeout=20)
        lines = (proc.stdout + proc.stderr).strip().splitlines()
        return lines[0] if lines else executable
    except Exception:
        return executable


def _sha(path):
    try:
        digest = hashlib.sha256()
        with open(path, "rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return {"sha256": digest.hexdigest(), "bytes": os.path.getsize(path)}
    except OSError:
        return None


def _walk(value, found):
    if isinstance(value, str) and os.path.isfile(value):
        found[os.path.abspath(value)] = _sha(value)
    elif isinstance(value, dict):
        for item in value.values():
            _walk(item, found)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _walk(item, found)


def _cde(objective, status, binding=None, inputs=None, results=None,
         validation=None, provenance=None, error=None):
    data = {
        "tool": TOOL,
        "status": status,
        "objective": objective,
        "tools_used": [{"name": "KLayout", "version": _version("klayout")},
                       {"name": "Magic", "version": _version("magic", "--version")}],
        "pdk_binding": binding or "none",
        "assumptions": [],
        "inputs_ref": inputs or {},
        "vplan": "not_applicable",
        "results": results or {},
        "qor_metrics": {"difference_count": (results or {}).get("difference_count"),
                        "difference_area_um2": (results or {}).get("difference_area_um2")},
        "signoff_evidence": results or {},
        "margin": {"method": "exact_geometric_xor", "allowed_difference_area_um2": 0.0},
        "validation": validation or {"verdict": "fail"},
        "provenance": provenance or {},
    }
    if error:
        data["signoff_evidence"]["failure_reason"] = error
    return data


def failure_envelope(objective, error, params=None, trace=None):
    result = _cde(objective, "failed", (params or {}).get("pdk_binding"), params or {},
                  validation={"verdict": "fail", "note": error}, error=error)
    result["error"] = str(error)
    if trace:
        result["provenance"]["traceback"] = trace
    return result


def _resolve(params, policy, name, default=None, aliases=()):
    for key in (name,) + tuple(aliases):
        if key in params:
            source = "caller_override" if name in policy and params[key] != policy[name] else "caller"
            return params[key], source
    if name in policy:
        return policy[name], "pdk_policy"
    return default, "tool_default"


def _as_list(value):
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _require_files(values, label):
    values = _as_list(values)
    if not values:
        return "missing required " + label
    missing = [str(path) for path in values if not os.path.exists(str(path))]
    return (label + " not found: " + ", ".join(missing)) if missing else None


def _run(command, tag):
    open(os.path.join(OUTPUT, "logs", tag + "_command.txt"), "w", encoding="utf-8").write(
        " ".join(shlex.quote(str(x)) for x in command) + "\n")
    proc = subprocess.run(command, text=True, capture_output=True, cwd=WORK)
    text = proc.stdout + "\n" + proc.stderr
    open(os.path.join(OUTPUT, "logs", tag + ".log"), "w", encoding="utf-8").write(text)
    return proc, text


def _klayout_script(body, tag):
    script = os.path.join(WORK, tag + ".py")
    open(script, "w", encoding="utf-8").write(body)
    shutil.copy2(script, os.path.join(OUTPUT, "logs", tag + ".py"))
    return _run(["klayout", "-b", "-r", script], tag)


def _xor(layout_a, layout_b, top=None, output_format="gds", tag="xor",
         geometry_diagnostics=False):
    if not shutil.which("klayout"):
        return None, "klayout not found on PATH"
    for path in (layout_a, layout_b):
        if not path or not os.path.exists(str(path)):
            return None, "layout input not found: " + str(path)
    extension = ".oas" if str(output_format).lower() in ("oas", "oasis") else ".gds"
    diff_path = os.path.join(OUTPUT, "results", tag + "_differences" + extension)
    report_path = os.path.join(OUTPUT, "reports", tag + "_report.json")
    body = '''import json, pya
la = pya.Layout(); lb = pya.Layout()
la.read(%s); lb.read(%s)
want = %s
with_geometry = %s
def choose(ly):
    if want:
        cell = ly.cell(want)
        if cell is None: raise RuntimeError("top cell not found: " + want)
        return cell
    tops = ly.top_cells()
    if len(tops) != 1: raise RuntimeError("layout must have one top cell or explicit top")
    return tops[0]
ca = choose(la); cb = choose(lb)
if abs(la.dbu - lb.dbu) > 1e-12:
    raise RuntimeError("layout DBU mismatch: %%s versus %%s" %% (la.dbu, lb.dbu))
out = pya.Layout(); out.dbu = la.dbu; co = out.create_cell("XOR_DIFFERENCES")
infos = {}
indexes = [{}, {}]
for number, ly in enumerate((la, lb)):
    for index in ly.layer_indexes():
        info = ly.get_info(index)
        key = (info.layer, info.datatype, info.name if info.layer < 0 else "")
        infos[key] = info
        indexes[number][key] = index
count = 0; area_dbu2 = 0
input_polygons = [0, 0]
per_layer = {}
for key in sorted(infos):
    info = infos[key]
    ia = indexes[0].get(key)
    ib = indexes[1].get(key)
    ra = pya.Region(ca.begin_shapes_rec(ia)) if ia is not None else pya.Region()
    rb = pya.Region(cb.begin_shapes_rec(ib)) if ib is not None else pya.Region()
    input_polygons[0] += ra.count()
    input_polygons[1] += rb.count()
    delta = ra ^ rb
    entry = {"a_polygons": int(ra.count()), "b_polygons": int(rb.count()),
             "xor_polygons": int(delta.count()),
             "xor_area_um2": float(delta.area()) * la.dbu * la.dbu,
             "only_in": ("a" if ra.count() and not rb.count() else
                         "b" if rb.count() and not ra.count() else None)}
    layer_name = ("%%d/%%d" %% key[:2]) if key[0] >= 0 else "name:" + key[2]
    if with_geometry:
        def boxes(region):
            values = []
            for polygon in region.each():
                if len(values) == 64:
                    break
                box = polygon.bbox()
                values.append([float(v) * la.dbu for v in
                               (box.left, box.bottom, box.right, box.top)])
            return {"boxes_um": values, "truncated": region.count() > len(values)}
        entry["geometry_diagnostic"] = {
            "a": boxes(ra), "b": boxes(rb), "xor": boxes(delta),
            "basis": "actual native polygon bounding boxes, maximum64 per region"}
    per_layer[layer_name] = entry
    if not delta.is_empty():
        oi = out.layer(info)
        co.shapes(oi).insert(delta)
        count += delta.count()
        area_dbu2 += delta.area()
if not any(input_polygons):
    raise RuntimeError("no polygon geometry was compared in either input; empty comparison cannot pass")
out.write(%s)
report = {"layout_a_top": ca.name, "layout_b_top": cb.name,
          "difference_count": int(count),
          "difference_area_um2": float(area_dbu2) * la.dbu * la.dbu,
          "dbu_um": la.dbu, "layers_compared": len(infos),
          "input_polygons_a": int(input_polygons[0]),
          "input_polygons_b": int(input_polygons[1]),
          "layers_with_differences": sorted(k for k, v in per_layer.items() if v["xor_polygons"]),
          "layers_only_in_a": sorted(k for k, v in per_layer.items() if v["only_in"] == "a"),
          "layers_only_in_b": sorted(k for k, v in per_layer.items() if v["only_in"] == "b"),
          "per_layer": per_layer,
          "difference_layout": %s}
open(%s, "w").write(json.dumps(report, indent=2))
''' % (json.dumps(str(layout_a)), json.dumps(str(layout_b)), json.dumps(top),
       repr(bool(geometry_diagnostics)),
       json.dumps(diff_path), json.dumps(os.path.relpath(diff_path, OUTPUT).replace(os.sep, "/")),
       json.dumps(report_path))
    proc, text = _klayout_script(body, tag)
    if proc.returncode != 0 or not os.path.exists(report_path) or not os.path.exists(diff_path):
        return None, "KLayout XOR failed; see logs/" + tag + ".log: " + text[-600:]
    try:
        return json.load(open(report_path, encoding="utf-8")), None
    except (OSError, ValueError) as exc:
        return None, "invalid KLayout XOR report: " + str(exc)


def _xor_scenario(params):
    started = time.time()
    binding = params.get("pdk_binding")
    if not isinstance(binding, dict) or not binding:
        return failure_envelope("Geometric layout XOR", "missing required pdk_binding", params)
    policy = ((binding.get("tool_policy") or {}).get("streamout_xor") or {})
    output_format, format_source = _resolve(params, policy, "output_format", "gds")
    top, top_source = _resolve(params, policy, "top", None)
    a = params.get("layout_a") or params.get("reference_layout")
    b = params.get("layout_b") or params.get("candidate_layout")
    for label, path in (("layout_a", a), ("layout_b", b)):
        error = _require_files(path, label)
        if error:
            return failure_envelope("Geometric layout XOR", error, params)
    report, error = _xor(a, b, top, output_format)
    if error:
        return failure_envelope("Geometric layout XOR", error, params)
    clean = report["difference_count"] == 0 and report["difference_area_um2"] == 0.0
    status = "completed" if clean else "failed"
    verdict = "pass" if clean else "fail"
    provenance = {"runtime_s": round(time.time() - started, 3),
                  "settings_source": {"output_format": format_source, "top": top_source},
                  "effective_settings": {"output_format": output_format, "top": top}}
    return _cde("Geometric layout XOR", status, binding,
                {"layout_a": a, "layout_b": b}, report,
                {"verdict": verdict, "note": "layouts are geometrically identical" if clean else "layout XOR contains differences"},
                provenance, None if clean else "layout XOR contains differences")


# --- PDK FILL-layer resolution (vendored VERBATIM from chip-gds-assembly) -------
# These tools are separate containers and share code BY COPY, not by import.
# Keep this block byte-identical to the chip-gds-assembly original apart from
# the work-dir constant: both tools must resolve the node's fill layers the
# SAME way, because those layer/datatype numbers are PDK-DECLARED and are not
# derivable from the drawing layers.
def _pdk_fill_layers(magic_tech):
    """Return {map_layer_name: (gds_layer, gds_datatype)} for the node's FILL layers.

    Read from the PDK's Magic techfile, which declares them explicitly:

        layer MET1FILL m1fill
            ...
            calma 36 28

    These numbers are NOT derivable from the drawing layers. sky130 routes on
    66,67,68,69,70,71,72 but fills on 28,36,41,34,51,59 -- unordered, and not
    offset from the drawing layer by any constant. Anything that computes a fill
    layer instead of reading it is guessing, so this parses the PDK or returns {}.
    """
    try:
        lines = open(magic_tech, encoding="utf-8", errors="replace").read().splitlines()
    except Exception:
        return {}
    out = {}
    for i, ln in enumerate(lines):
        m = re.match(r"^\s*layer\s+([A-Za-z0-9_]*FILL)\s", ln)
        if not m:
            continue
        # `calma <layer> <datatype>` belongs to the nearest following stanza.
        for nxt in lines[i + 1:i + 8]:
            if re.match(r"^\s*layer\s", nxt):
                break
            c = re.match(r"^\s*calma\s+(\d+)\s+(\d+)", nxt)
            if c:
                name = m.group(1).lower()[:-4]        # MET1FILL -> met1
                out.setdefault(name, (c.group(1), c.group(2)))
                break
    return out


def _map_has_fill_purpose(map_path):
    """True if the layer map declares a FILL/OPCFILL purpose on any layer.

    Interrogates the map that will actually be handed to KLayout, so the caller
    can fail closed on the map's CONTENT rather than on its provenance.
    """
    if not map_path or not os.path.exists(str(map_path)):
        return False
    try:
        for ln in open(str(map_path), encoding="utf-8", errors="replace"):
            s = ln.strip()
            if not s or s.startswith("#"):
                continue
            parts = s.split()
            if len(parts) < 4 or not (parts[-1].isdigit() and parts[-2].isdigit()):
                continue
            if {p.strip().upper() for p in parts[1].split(",")} & {"FILL", "OPCFILL"}:
                return True
    except Exception:
        return False
    return False


def _augment_map_with_fill(map_path, magic_tech=None):
    """Return (augmented_map_path, rows_added, reason) adding the node's FILL purpose.

    KLayout's LEF/DEF reader emits DEF FILLS on a `<layer>.FILL` purpose. Vendor
    maps commonly omit that purpose (sky130A.map carries NET/SPNET/PIN/VIA/LEFPIN/
    LEFOBS/LABEL and no FILL), and the reader then prints

        No mapping for layer 'met2', purpose 'FILL' - layer is ignored

    and DROPS the fill -- a warning, not an error, so streamout still reports
    success while the design silently loses every fill shape it just inserted.

    THE FILL LAYERS ARE READ FROM THE PDK, NOT COMPUTED. An earlier version of
    this routine pointed the FILL purpose at each layer's own routing row (the
    row carrying NET) on the reasoning that fill must sit on the drawing layer to
    count toward density. That was WRONG, and measurably so: fill is floating
    metal by construction, so putting it on the drawing layer made the signoff
    deck's floating-metal rule fire once per fill shape --

        m2.x 3, m3.x 239, m4.x 504, m5.x 117   == 863, exactly the fill count
        ("floating met3, must interact with via3 or via4")

    taking DRC from 0 to 971. sky130 declares dedicated *FILL layers precisely so
    density rules can see fill while connectivity rules do not. Deriving the
    numbers, however plausible the derivation, produced a design that could not
    sign off; reading them from the techfile is the only correct source.

    The vendor map is never modified; an augmented copy is written to the work
    dir. Returns (None, [], reason) when nothing needed adding or the fill layers
    could not be resolved, so the caller fails closed rather than shipping a GDS
    whose fill was invented or dropped.
    """
    try:
        lines = open(map_path, encoding="utf-8", errors="replace").read().splitlines()
    except Exception:
        return None, [], "layer map unreadable"
    pdk_fill = _pdk_fill_layers(magic_tech) if magic_tech else {}
    if not pdk_fill:
        return None, [], ("no FILL layers declared in the PDK Magic techfile "
                          f"({magic_tech or 'not provided'})")
    present, has_fill = set(), set()
    for ln in lines:
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        parts = s.split()
        if len(parts) < 4 or not (parts[-1].isdigit() and parts[-2].isdigit()):
            continue
        pset = {p.strip().upper() for p in parts[1].split(",")}
        present.add(parts[0])
        if "FILL" in pset or "OPCFILL" in pset:
            has_fill.add(parts[0])
    # Only map layers the bound map already knows about; never invent a layer.
    todo = sorted(n for n in present if n in pdk_fill and n not in has_fill)
    if not todo:
        return None, [], "layer map already carries a FILL purpose"
    out = list(lines)
    out += ["",
            "# --- appended by chip-streamout-xor: FILL purpose ---",
            "# layer/datatype read from the PDK Magic techfile (layer <X>FILL ->",
            "# calma <n> <dt>). Fill is FLOATING metal: it belongs on the node's",
            "# dedicated fill layer, NOT on the drawing layer, or the floating-",
            "# metal rule (mN.x) fires once per fill shape."]
    added = []
    for name in todo:
        num, dt = pdk_fill[name]
        out.append("%-8s%-25s%-4s%s" % (name, "FILL,OPCFILL", num, dt))
        added.append("%s->%s/%s" % (name, num, dt))
    dest = os.path.join(WORK, "lefdef_with_fill.map")
    try:
        with open(dest, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(out) + "\n")
    except Exception as exc:
        return None, [], f"could not write augmented map: {exc}"
    return dest, added, ""


def _magic_grid_refinement(tech_lef, magic_tech):
    from decimal import Decimal
    from fractions import Fraction
    try:
        with open(tech_lef, encoding="utf-8") as stream:
            lef = stream.read()
        with open(magic_tech, encoding="utf-8") as stream:
            tech = stream.read()
    except (OSError, TypeError):
        return None
    grid = re.search(r"MANUFACTURINGGRID\s+([0-9.]+)\s*;", lef)
    scale = re.search(r"scalefactor\s+([0-9.]+)\s+nanometers", tech)
    if not grid or not scale:
        return None
    grid_um = Decimal(grid.group(1))
    lambda_um = Decimal(scale.group(1)) / Decimal(1000)
    if grid_um <= 0 or lambda_um <= grid_um:
        return None
    ratio = Fraction(grid_um / lambda_um)
    return {"scalegrid": [ratio.numerator, ratio.denominator],
            "manufacturing_grid_um": str(grid_um), "magic_lambda_um": str(lambda_um),
            "tech_lef_sha256": hashlib.sha256(lef.encode()).hexdigest(),
            "magic_tech_sha256": hashlib.sha256(tech.encode()).hexdigest()}


def _magic_port_pairs(magic_tech):
    try:
        with open(magic_tech, encoding="utf-8") as stream:
            text = stream.read()
    except (OSError, TypeError):
        return {}
    match = re.search(r"(?ms)^cifoutput\s*\n(.*?)^end\s*$", text)
    if not match:
        return {}
    records, record, style_seen = [], None, False
    for line in match.group(1).splitlines():
        parts = line.split("#", 1)[0].split()
        if not parts:
            continue
        if parts[0] == "style":
            if style_seen:
                break
            style_seen = True
        elif parts[0] == "layer":
            record = {"expression": "".join(parts[2:])}
            records.append(record)
        elif record is not None and parts[0] == "labels" and parts[-1] == "port":
            record["port_expression"] = "".join(parts[1:-1])
        elif record is not None and parts[0] == "calma" and len(parts) == 3:
            record["target"] = (int(parts[1]), int(parts[2]))
    drawings = {r["expression"]: r["target"] for r in records
                if r.get("expression") and r.get("target") and not r.get("port_expression")}
    return {drawings[r["port_expression"]]: r["target"] for r in records
            if r.get("port_expression") in drawings and r.get("target")}


def _align_default_port_map(tech_file, magic_tech):
    import xml.etree.ElementTree as ET
    pairs = _magic_port_pairs(magic_tech)
    if not pairs or not tech_file:
        return tech_file, []
    tree = ET.parse(tech_file)
    node = tree.find("./reader-options/lefdef/layer-map")
    if node is None or not node.text:
        return tech_file, []
    pattern = r"'([^']+?)\s*:\s*(\d+)/(\d+)'"
    entries = {m.group(1).strip(): (int(m.group(2)), int(m.group(3)))
               for m in re.finditer(pattern, node.text)}
    roles = []
    changes = {}
    for name, target in entries.items():
        if not name.endswith(".PIN"):
            continue
        layer = name[:-4]
        drawing = entries.get(layer)
        port = pairs.get(drawing)
        if drawing is None or port is None or target != drawing or port == drawing:
            continue
        roles.append({"layer": layer, "drawing": list(drawing), "port": list(port)})
        changes[name] = port
        if entries.get(layer + ".LABEL") == drawing:
            changes[layer + ".LABEL"] = port
    if not roles:
        return tech_file, []
    node.text = re.sub(pattern, lambda m: "'%s : %d/%d'" % (
        m.group(1).strip(), *changes.get(m.group(1).strip(),
                                      (int(m.group(2)), int(m.group(3))))), node.text)
    base = tree.find("./base-path")
    if base is not None and base.text and not os.path.isabs(base.text):
        base.text = os.path.abspath(os.path.join(os.path.dirname(tech_file), base.text))
    dest = os.path.join(WORK, "port_aligned.lyt")
    tree.write(dest, encoding="utf-8", xml_declaration=True)
    return dest, roles


def _companion_lefdef_map(tech_file):
    if not tech_file:
        return None
    import xml.etree.ElementTree as ET
    tree = ET.parse(tech_file)
    node = tree.find("./reader-options/lefdef/layer-map")
    if node is not None and node.text and re.search(r"\d+/\d+", node.text):
        return None
    candidate = os.path.splitext(tech_file)[0] + ".map"
    return candidate if os.path.isfile(candidate) else None


def _map_port_roles(map_file):
    drawings, ports = {}, {}
    with open(map_file, encoding="utf-8") as stream:
        for line in stream:
            parts = line.split("#", 1)[0].split()
            if len(parts) != 4 or not all(p.isdigit() for p in parts[-2:]):
                continue
            name, purposes = parts[:2]
            target = [int(p) for p in parts[-2:]]
            if set(purposes.split(",")) & {"NET", "SPNET"}:
                drawings[name] = target
            if "PIN" in purposes.split(","):
                ports[name] = target
    return [{"layer": name, "drawing": target, "port": ports[name]}
            for name, target in drawings.items()
            if name in ports and ports[name] != target]


def _klayout_streamout(def_file, top, tech_lef, cell_lef, cell_gds, tech_file,
                       lefdef_map=None, magic_tech=None, obligations=None):
    """KLayout DEF->GDS streamout. `obligations` (single-engine mode) enforces the
    PDK binding's consumer_obligations: read_all_layers OFF, an explicit layer map
    that must be non-empty, an exact dbu, LEFs replaced by the supplied set (a
    .lyt-relative LEF entry is not resolvable in the container), a single top
    cell, and a post-read ASSERTION that every output layer is a map target or a
    cell-GDS layer. The settings actually applied are written to
    reports/klayout_streamout_settings.json."""
    out = os.path.join(OUTPUT, "results", top + "_klayout.gds")
    settings_path = os.path.join(OUTPUT, "reports", "klayout_streamout_settings.json")
    # DEF FILLS need an explicit FILL purpose in the LEF/DEF layer map or KLayout
    # either DROPS them or INVENTS a layer for them. MEASURED on this tool before
    # the fix, on a DEF carrying `FILLS 863 ;`:
    #     KLayout leg -> 863 shapes on 8/28, 10/28, 12/28, 14/28  (INVENTED --
    #                    sky130 fills on 28/36/41/34/51/59, none of these)
    #     Magic leg   -> 0 fill shapes
    # so the two independent streamouts disagreed by construction and the XOR
    # reported a difference that was an artifact of the reader, not the design.
    # The augmented map is a WORK-DIR COPY; the vendor map is never modified.
    if not lefdef_map:
        try:
            lefdef_map = _companion_lefdef_map(tech_file)
        except (OSError, ValueError) as exc:
            return None, "Could not resolve PDK companion layer map: " + str(exc)
    fill_map, fill_added, fill_reason = None, [], ""
    if lefdef_map:
        fill_map, fill_added, fill_reason = _augment_map_with_fill(
            lefdef_map, magic_tech)
    effective_map = fill_map or lefdef_map
    port_roles = _map_port_roles(effective_map) if effective_map else []
    if not effective_map:
        try:
            tech_file, port_roles = _align_default_port_map(tech_file, magic_tech)
        except (OSError, ValueError) as exc:
            return None, "Could not align declared Magic port purposes: " + str(exc)
    body = '''import json, re, pya
LEFS = %s
GDS = %s
DEF_FILE = %s
OUT_GDS = %s
TOP_NAME = %s
LYT = %s
LEFDEF_MAP = %s
OBLIG = %s
SETTINGS = %s
PORT_ROLES = %s
applied = {"obligations": OBLIG, "port_purpose_alignment": PORT_ROLES}
ly = pya.Layout()
opt2 = pya.LoadLayoutOptions()
if LYT:
    try:
        tech = pya.Technology()
        tech.load(LYT)
        opt2 = tech.load_layout_options
        print("streamout: applied .lyt layer-map from", LYT)
    except Exception as e:
        print("streamout: .lyt technology load failed, bare LEF/DEF fallback:", e)
try:
    cfg = opt2.lefdef_config
    if LEFDEF_MAP:
        cfg.map_file = LEFDEF_MAP
        print("streamout: applied LEF/DEF layer map", LEFDEF_MAP)
    # KLayout API quirk: cfg.lef_files returns a FRESH COPY on every access, so
    # `cfg.lef_files.append(x)` mutates a throwaway and the LEFs are NEVER loaded.
    # It fails SILENTLY -- the only symptom is "Macro not found in LEF file:
    # <cell> - creating dummy macro" for every cell, so the streamout is built
    # from EMPTY placeholders and carries none of the real cell geometry.
    # MEASURED here before the fix: the KLayout leg produced 4985 shapes against
    # Magic's 13065, and the XOR reported 21748 differences -- a difference
    # manufactured ENTIRELY by this tool's own broken LEF registration, not by any
    # real disagreement between the two engines. That is the worst possible state
    # for an XOR gate: it exists to catch a single-engine mistake and instead
    # reports a large, permanent, self-inflicted one, so it can never close.
    # chip-gds-assembly already documents and fixes the identical trap.
    # Assign the whole list at once so it actually takes effect.
    existing = list(cfg.lef_files)
    if OBLIG:
        applied["lyt_lef_files_replaced"] = existing
        cfg.lef_files = list(LEFS)
    else:
        cfg.lef_files = existing + [l for l in LEFS if l not in existing]
    if GDS:
        cfg.macro_resolution_mode = 2
        cfg.macro_layout_files = GDS
        print("streamout: macro_resolution_mode=2, macros resolved from", GDS)
    if OBLIG:
        cfg.read_all_layers = False
        if OBLIG.get("dbu"):
            cfg.dbu = float(OBLIG["dbu"])
        print("streamout: obligations applied: read_all_layers=False dbu=%%s" %% cfg.dbu)
    opt2.lefdef_config = cfg
except Exception as e:
    print("streamout: lef config failed:", e)
    if OBLIG:
        raise RuntimeError("could not apply consumer_obligations: %%s" %% e)
if OBLIG:
    cfg = opt2.lefdef_config
    try:
        map_text = cfg.layer_map.to_string()
    except Exception:
        map_text = ""
    targets = set()
    for m in re.finditer(r":\\s*(\\d+)/(\\d+)", map_text or ""):
        targets.add((int(m.group(1)), int(m.group(2))))
    if cfg.map_file:
        for ln in open(cfg.map_file, errors="replace"):
            p = ln.split()
            if len(p) >= 4 and not ln.lstrip().startswith("#") and p[-1].isdigit() and p[-2].isdigit():
                targets.add((int(p[-2]), int(p[-1])))
    if not targets:
        raise RuntimeError("no LEF/DEF layer map in effect (neither the .lyt lefdef "
                           "layer-map nor a lefdef_map declares any target); with "
                           "read_all_layers=False every shape would be dropped")
    gds_layers = set()
    for g in GDS:
        gl = pya.Layout(); gl.read(g)
        for li in gl.layer_indexes():
            inf = gl.get_info(li); gds_layers.add((inf.layer, inf.datatype))
    applied.update({"read_all_layers": cfg.read_all_layers, "config_dbu": cfg.dbu,
                    "lef_files": list(cfg.lef_files), "map_file": cfg.map_file or None,
                    "map_targets": sorted("%%d/%%d" %% t for t in targets),
                    "cell_gds_layers": sorted("%%d/%%d" %% t for t in gds_layers)})
ly.read(DEF_FILE, opt2)
tc = ly.cell(TOP_NAME) if TOP_NAME else None
if tc is not None:
    # Magic emits terminal rectangles as both drawing metal and port purpose.
    # Preserve both from actual DEF pin geometry, without editing library cells.
    for role in PORT_ROLES:
        pin = ly.find_layer(*role["port"])
        drawing = ly.layer(pya.LayerInfo(*role["drawing"]))
        shapes = list(tc.shapes(pin).each()) if pin is not None else []
        count = 0
        for shape in shapes:
            if not shape.is_text():
                tc.shapes(drawing).insert(shape)
                count += 1
        role["actual_top_pin_shapes_copied_to_drawing"] = count
    keep = set(tc.called_cells()); keep.add(tc.cell_index())
    drop = [c.cell_index() for c in ly.each_cell() if c.cell_index() not in keep]
    if drop:
        ly.delete_cells(drop)
        print("streamout: pruned", len(drop), "cells; single top", TOP_NAME)
if ly.cell(TOP_NAME) is None: raise RuntimeError("top cell absent after DEF import")
if OBLIG:
    tc = ly.cell(TOP_NAME)
    layers = {}
    for li in ly.layer_indexes():
        inf = ly.get_info(li)
        n = pya.Region(tc.begin_shapes_rec(li)).count()
        layers["%%d/%%d" %% (inf.layer, inf.datatype)] = int(n)
    unexpected = sorted(k for k in layers if layers[k] and
                        tuple(int(x) for x in k.split("/")) not in targets | gds_layers)
    applied.update({"layout_dbu": ly.dbu,
                    "top_cells": [c.name for c in ly.top_cells()],
                    "layer_shape_counts": layers,
                    "shapes_on_map_targets": sum(v for k, v in layers.items()
                        if tuple(int(x) for x in k.split("/")) in targets),
                    "unexpected_layers": unexpected})
open(SETTINGS, "w").write(json.dumps(applied, indent=2))
ly.write(OUT_GDS)
''' % (json.dumps([tech_lef] + cell_lef), json.dumps(cell_gds),
       json.dumps(def_file), json.dumps(out), json.dumps(top),
       json.dumps(tech_file) if tech_file else "None",
       json.dumps(effective_map) if effective_map else "None",
       repr(obligations) if obligations else "None",
       json.dumps(settings_path), repr(port_roles))
    if obligations and os.path.exists(settings_path):
        os.remove(settings_path)
    proc, text = _klayout_script(body, "klayout_streamout")
    if proc.returncode != 0 or not os.path.exists(out):
        return None, "KLayout streamout failed; see logs/klayout_streamout.log: " + text[-600:]
    if obligations:
        error = _check_streamout_obligations(settings_path, obligations, top, text)
        if error:
            return None, error
    # FAIL CLOSED on a DEF that carries fill the effective map cannot express.
    # Keyed on the map's CONTENT, never on its provenance: a guard that trusts an
    # explicitly-supplied map exempts the exact worst case (binding the stock
    # vendor map, which has no FILL purpose).
    if _def_has_fills(def_file) and not _map_has_fill_purpose(effective_map):
        return None, (
            "DEF carries FILLS but the effective LEF/DEF layer map declares no "
            "FILL purpose, so KLayout would silently DROP or INVENT every fill "
            "shape and the XOR would compare layouts that differ by construction"
            + (" (" + fill_reason + ")" if fill_reason else "")
            + ". Supply `lefdef_map` (+ `magic_tech` so the node's fill layers "
              "can be read from the PDK techfile).")
    return out, None


def _check_streamout_obligations(settings_path, obligations, top, log_text):
    """Python-side ASSERTION that the consumer_obligations took effect."""
    try:
        applied = json.load(open(settings_path, encoding="utf-8"))
    except (OSError, ValueError):
        return ("KLayout streamout wrote no settings report, so the consumer "
                "obligations (layer map, read_all_layers=False, dbu, single top "
                "cell) cannot be shown to have taken effect")
    problems = []
    if applied.get("read_all_layers") is not False:
        problems.append("read_all_layers is %r, not False" % applied.get("read_all_layers"))
    want_dbu = obligations.get("dbu")
    if want_dbu and abs(float(applied.get("layout_dbu") or 0) - float(want_dbu)) > 1e-12:
        problems.append("layout dbu %s != required %s" % (applied.get("layout_dbu"), want_dbu))
    if applied.get("top_cells") != [top]:
        problems.append("top cells %s (single top cell %r required)" % (applied.get("top_cells"), top))
    if not applied.get("shapes_on_map_targets"):
        problems.append("0 shapes landed on any layer-map target (the map did not take effect)")
    if applied.get("unexpected_layers"):
        problems.append("shapes on layers that are neither layer-map targets nor cell-GDS "
                        "layers (auto-assigned): %s" % ", ".join(applied["unexpected_layers"]))
    dropped = {}
    for m in re.finditer(r"No mapping for layer '([^']*)'(?:, purpose '([^']*)')?", log_text or ""):
        key = m.group(1) + ("." + m.group(2) if m.group(2) else "")
        dropped[key] = dropped.get(key, 0) + 1
    applied["dropped_unmapped_layer_purposes"] = dropped
    with open(settings_path, "w", encoding="utf-8") as stream:
        json.dump(applied, stream, indent=2)
    if problems:
        return ("KLayout streamout did not satisfy the PDK consumer_obligations: "
                + "; ".join(problems) + ". See reports/klayout_streamout_settings.json.")
    return None


def _def_has_fills(def_file):
    """True if the DEF declares a non-empty FILLS section."""
    try:
        with open(def_file, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                m = re.match(r"^\s*FILLS\s+(\d+)\s*;", line)
                if m:
                    return int(m.group(1)) > 0
    except OSError:
        return False
    return False


def _tcl(value):
    return "{" + str(value).replace("}", "\\}") + "}"


def _magic_streamout(def_file, top, tech_lef, cell_lef, cell_gds, magicrc, magic_tech,
                     preserve_cell_gds=True):
    if not shutil.which("magic"):
        return None, "magic not found on PATH"
    if magic_tech and os.path.isfile(magic_tech):
        with open(magic_tech, encoding="utf-8", errors="replace") as stream:
            requirement = re.search(r"(?m)^\s*requires\s+magic-(\d+\.\d+\.\d+)\b",
                                    stream.read())
        if requirement:
            actual = _version("magic", "--version")
            measured = re.search(r"\b(\d+\.\d+\.\d+)\b", actual)
            required_version = tuple(map(int, requirement.group(1).split(".")))
            if not measured or tuple(map(int, measured.group(1).split("."))) < required_version:
                return None, ("Bound Magic technology requires magic-" + requirement.group(1)
                              + "; installed engine version is " + actual
                              + ". Engine capability is unavailable; PDK data presence is not compatibility.")
    suffix = "" if preserve_cell_gds else "_editable_control"
    tag = "magic_streamout" + suffix
    out = os.path.join(OUTPUT, "results", top + "_magic" + suffix + ".gds")
    lines = ["drc off", "crashbackups stop"]
    refinement = _magic_grid_refinement(tech_lef, magic_tech) if not magicrc else None
    if refinement:
        # LEF widths otherwise round on the coarse startup lambda before GDS
        # import refines the grid. Refine first using the bound manufacturing grid.
        lines.append("scalegrid %d %d" % tuple(refinement["scalegrid"]))
        with open(os.path.join(OUTPUT, "reports", tag + "_precision.json"),
                  "w", encoding="utf-8") as stream:
            json.dump(refinement, stream, indent=2)
    for lef in [tech_lef] + cell_lef:
        lines.append("lef read " + _tcl(lef))
    # Editable GDS import/export regenerates masks through cifinput/cifoutput.
    # Immutable library cells must retain their supplied GDS geometry instead.
    lines.append("gds readonly " + ("true" if preserve_cell_gds else "false"))
    for gds in cell_gds:
        lines.append("gds read " + _tcl(gds))
    lines += ["def read " + _tcl(def_file), "load " + _tcl(top),
              "select top cell", "expand", "gds write " + _tcl(out), "quit -noprompt"]
    script = os.path.join(WORK, tag + ".tcl")
    open(script, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    shutil.copy2(script, os.path.join(OUTPUT, "logs", tag + ".tcl"))
    command = ["magic", "-dnull", "-noconsole"]
    if magicrc:
        command += ["-rcfile", str(magicrc)]
    elif magic_tech:
        command += ["-T", str(magic_tech)]
    command.append(script)
    proc, text = _run(command, tag)
    valid_header = False
    if os.path.isfile(out):
        with open(out, "rb") as stream:
            header = stream.read(6)
        valid_header = len(header) == 6 and header[:4] == b"\x00\x06\x00\x02"
    if proc.returncode != 0 or not valid_header:
        return None, "Magic streamout failed; see logs/" + tag + ".log: " + text[-600:]
    return out, None


_SINGLE_ENGINE_LABEL = ("single-engine reproducibility (KLayout vs reference); engine "
                        "independence NOT established because Magic tech is "
                        "unavailable for %s")
_MAGIC_OFF_STATES = ("unavailable", "not_available", "requires_provisioning",
                     "not_applicable", "absent", "missing")


def _magic_capability_unavailable(binding):
    """Reason string when the binding DECLARES Magic unusable, else None."""
    caps = binding.get("capabilities") or {}
    for key in ("streamout_xor", "streamout", "magic"):
        cap = caps.get(key)
        if not isinstance(cap, dict):
            continue
        magic = cap.get("magic", cap if key == "magic" else None)
        state = (magic.get("state") if isinstance(magic, dict) else magic)
        if magic is False or str(state).lower() in _MAGIC_OFF_STATES:
            return ("pdk_binding.capabilities.%s declares Magic unavailable (%s)"
                    % (key, (magic.get("reason") if isinstance(magic, dict) else None)
                       or cap.get("reason") or state))
    return None


def _obligation_dbu(binding):
    text = str((((binding.get("capabilities") or {}).get("drc") or {})
                .get("consumer_obligations") or {}).get("dbu") or "")
    m = re.search(r"\b(0\.\d*[1-9])\b", text)
    return float(m.group(1)) if m else None


def _single_engine(params, binding, policy, values, decisions, reference, why, pdk, started):
    """KLayout DEF->GDS streamout of `def` XORed per layer against a supplied
    reference GDS. Only ONE engine is exercised, so this demonstrates
    reproducibility of the reference, never engine independence: the verdict is
    capped at pass_with_caveats."""
    objective = "Single-engine streamout XOR (KLayout vs reference)"
    label = _SINGLE_ENGINE_LABEL % pdk
    if not shutil.which("klayout"):
        return failure_envelope(objective, "klayout not found on PATH; the single-engine "
                                "mode needs a real KLayout streamout and XOR (%s)" % label, params)
    error = _require_files(reference, "reference_layout")
    if error:
        return failure_envelope(objective, error, params)
    obligations_src = (((binding.get("capabilities") or {}).get("drc") or {})
                       .get("consumer_obligations") or {})
    dbu, dbu_source = _resolve(params, policy, "dbu", _obligation_dbu(binding))
    if dbu_source == "tool_default":
        dbu_source = "pdk_binding.capabilities.drc.consumer_obligations.dbu" if dbu else "lyt"
    obligations = {"read_all_layers": False, "dbu": float(dbu) if dbu else None,
                   "single_top_cell": True, "layer_map_required": True}
    cell_lef, cell_gds = _as_list(values["cell_lef"]), _as_list(values["cell_gds"])
    kgds, error = _klayout_streamout(values["def_file"], values["top"], values["tech_lef"],
                                     cell_lef, cell_gds, values["klayout_tech"],
                                     values.get("lefdef_map"), values.get("magic_tech"),
                                     obligations=obligations)
    if error:
        return failure_envelope(objective, error + " [" + label + "]", params)
    settings_path = os.path.join(OUTPUT, "reports", "klayout_streamout_settings.json")
    try:
        applied = json.load(open(settings_path, encoding="utf-8"))
    except (OSError, ValueError):
        applied = {}
    report, error = _xor(reference, kgds, values["top"], values["output_format"], "single_engine_xor")
    if error:
        return failure_envelope(objective, error + " [" + label + "]", params)
    caveats = [label + ": " + why,
               "the XOR shows only that a KLayout streamout of the DEF reproduces the "
               "supplied reference; if the reference was itself produced by KLayout, a "
               "shared reader defect would cancel out and go undetected"]
    if applied.get("lyt_lef_files_replaced"):
        caveats.append("LEF list from the .lyt (%s) replaced by the supplied tech/cell LEFs"
                       % ", ".join(applied["lyt_lef_files_replaced"]))
    if applied.get("dropped_unmapped_layer_purposes"):
        caveats.append("LEF/DEF layer/purposes with no map entry were dropped "
                       "(read_all_layers=False): %s" % ", ".join(
                           sorted(applied["dropped_unmapped_layer_purposes"])))
    if report.get("layers_only_in_a"):
        caveats.append("layers present only in the reference: %s" % ", ".join(report["layers_only_in_a"]))
    if report.get("layers_only_in_b"):
        caveats.append("layers present only in the KLayout streamout: %s" % ", ".join(report["layers_only_in_b"]))
    report.update({"mode": "single_engine_reproducibility", "mode_label": label,
                   "engine_independence_established": False,
                   "magic_unavailable_reason": why,
                   "reference_layout": reference,
                   "klayout_streamout": os.path.relpath(kgds, OUTPUT).replace(os.sep, "/"),
                   "streamout_settings": "reports/klayout_streamout_settings.json",
                   "consumer_obligations_applied": obligations,
                   "consumer_obligations_source": ("pdk_binding.capabilities.drc.consumer_obligations"
                                                   if obligations_src else "tool_default"),
                   "require_real_klayout_xor": bool(params.get("require_real_klayout_xor")),
                   "caveats": caveats})
    clean = report["difference_count"] == 0 and report["difference_area_um2"] == 0.0
    status, verdict = ("completed", "pass_with_caveats") if clean else ("failed", "fail")
    note = (label + ("; KLayout streamout reproduces the reference exactly"
                     if clean else "; KLayout streamout differs from the reference on %s"
                     % ", ".join(report.get("layers_with_differences") or [])))
    decisions = dict(decisions, dbu=dbu_source)
    provenance = {"runtime_s": round(time.time() - started, 3),
                  "settings_source": decisions,
                  "effective_settings": dict({k: v for k, v in values.items()
                                              if k not in ("magicrc", "magic_tech")}, dbu=dbu),
                  "policy_overrides": [k for k, source in decisions.items() if source == "caller_override"]}
    result = _cde(objective, status, binding,
                  {"def_file": values["def_file"], "tech_lef": values["tech_lef"],
                   "cell_lef": cell_lef, "cell_gds": cell_gds,
                   "klayout_tech": values["klayout_tech"], "reference_layout": reference},
                  report, {"verdict": verdict, "note": note, "mode": label,
                           "verdict_cap": "pass_with_caveats"},
                  provenance, None if clean else "KLayout streamout differs from the reference layout")
    result["tools_used"] = [t for t in result["tools_used"] if t["name"] == "KLayout"]
    result["assumptions"] = [label, "reference_layout is a GDS of the same DEF at the same dbu"]
    if not clean:
        result["error"] = note
    return result


def _dual(params):
    started = time.time()
    binding = params.get("pdk_binding")
    if not isinstance(binding, dict) or not binding:
        return failure_envelope("Independent dual streamout XOR", "missing required pdk_binding", params)
    policy = ((binding.get("tool_policy") or {}).get("streamout_xor") or {})
    decisions = {}
    values = {}
    specifications = (
        ("def_file", None, ("def",)), ("top", None, ()),
        ("tech_lef", binding.get("tech_lef"), ()),
        ("cell_lef", binding.get("cell_lef"), ()),
        ("cell_gds", binding.get("cell_gds"), ()),
        ("klayout_tech", binding.get("klayout_tech"), ("tech_file",)),
        ("magicrc", binding.get("magicrc"), ("magic_rcfile",)),
        ("magic_tech", binding.get("magic_tech"), ()),
        ("magic_gds_map", binding.get("magic_gds_map"), ("gds_map",)),
        ("lefdef_map", binding.get("lefdef_map"), ("layer_map", "map_file")),
        ("output_format", "gds", ()),
    )
    for name, default, aliases in specifications:
        values[name], decisions[name] = _resolve(params, policy, name, default, aliases)
    for name in ("def_file", "tech_lef", "cell_lef", "cell_gds", "klayout_tech"):
        error = _require_files(values[name], name)
        if error:
            return failure_envelope("Independent dual streamout XOR", error, params)
    if not values["top"]:
        return failure_envelope("Independent dual streamout XOR", "missing required top", params)
    magic_ref = values["magicrc"] or values["magic_tech"]
    magic_off = _magic_capability_unavailable(binding)
    if not magic_ref or magic_off:
        pdk = binding.get("pdk") or "this PDK"
        why = (magic_off if magic_off else
               "no Magic technology reference: magicrc/magic_tech are absent from both "
               "the params and pdk_binding (binding magicrc=%r, magic_tech=%r)"
               % (binding.get("magicrc"), binding.get("magic_tech")))
        reference = params.get("reference_layout") or params.get("reference_gds")
        if reference:
            return _single_engine(params, binding, policy, values, decisions,
                                  reference, why, pdk, started)
        return failure_envelope(
            "Independent dual streamout XOR",
            "missing Magic technology reference (magicrc or magic_tech) for %s: %s. "
            "The Magic streamout leg cannot run, and no `reference_layout` was "
            "supplied for the single-engine KLayout-vs-reference mode, so no XOR "
            "was performed. Supply `magicrc`/`magic_tech` for an independent dual "
            "streamout, or `reference_layout` (an independently produced GDS of the "
            "same DEF) for a single-engine reproducibility check." % (pdk, why), params)
    error = _require_files(magic_ref, "Magic technology reference")
    if error:
        return failure_envelope("Independent dual streamout XOR", error, params)
    if values["magic_gds_map"]:
        error = _require_files(values["magic_gds_map"], "Magic GDS mapping")
        if error:
            return failure_envelope("Independent dual streamout XOR", error, params)
    if not shutil.which("klayout") or not shutil.which("magic"):
        return failure_envelope("Independent dual streamout XOR", "both klayout and magic engines are required", params)
    cell_lef, cell_gds = _as_list(values["cell_lef"]), _as_list(values["cell_gds"])
    kgds, error = _klayout_streamout(values["def_file"], values["top"], values["tech_lef"],
                                     cell_lef, cell_gds, values["klayout_tech"],
                                     values.get("lefdef_map"), values.get("magic_tech"))
    if error:
        return failure_envelope("Independent dual streamout XOR", error, params)
    mgds, error = _magic_streamout(values["def_file"], values["top"], values["tech_lef"],
                                   cell_lef, cell_gds, values["magicrc"], values["magic_tech"])
    if error:
        return failure_envelope("Independent dual streamout XOR", error, params)
    report, error = _xor(kgds, mgds, values["top"], values["output_format"], "dual_streamout_xor",
                         geometry_diagnostics=bool(params.get("diagnostic_geometry")))
    if error:
        return failure_envelope("Independent dual streamout XOR", error, params)
    report.update({"klayout_streamout": os.path.relpath(kgds, OUTPUT).replace(os.sep, "/"),
                   "magic_streamout": os.path.relpath(mgds, OUTPUT).replace(os.sep, "/"),
                   "magic_cell_geometry_policy": "gds readonly true: preserve supplied library GDS; independently import DEF placement/routing"})
    if params.get("diagnose_editable_magic"):
        editable, diagnostic_error = _magic_streamout(
            values["def_file"], values["top"], values["tech_lef"], cell_lef,
            cell_gds, values["magicrc"], values["magic_tech"],
            preserve_cell_gds=False)
        diagnostic = {"scope": "same inputs and engines, changing only Magic library GDS readonly policy",
                      "editable_control_error": diagnostic_error}
        if not diagnostic_error:
            control, control_error = _xor(
                kgds, editable, values["top"], values["output_format"],
                "editable_magic_control")
            diagnostic.update({"editable_full_layout": control, "editable_control_error": control_error})
            cell = params.get("diagnostic_cell")
            if cell:
                for label, layout in (("editable_cell", editable), ("preserved_cell", mgds)):
                    cell_report, cell_error = _xor(
                        kgds, layout, cell, values["output_format"], label)
                    diagnostic[label] = {"cell": cell, "report": cell_report, "error": cell_error}
        report["magic_geometry_diagnostic"] = diagnostic
    clean = report["difference_count"] == 0 and report["difference_area_um2"] == 0.0
    status, verdict = ("completed", "pass") if clean else ("failed", "fail")
    provenance = {"runtime_s": round(time.time() - started, 3),
                  "settings_source": decisions,
                  "effective_settings": {k: v for k, v in values.items() if k not in ("magicrc", "magic_tech")},
                  "policy_overrides": [k for k, source in decisions.items() if source == "caller_override"]}
    return _cde("Independent Magic/KLayout DEF streamout XOR", status, binding,
                {"def_file": values["def_file"], "tech_lef": values["tech_lef"],
                 "cell_lef": cell_lef, "cell_gds": cell_gds,
                 "klayout_tech": values["klayout_tech"], "magic_technology": magic_ref},
                report, {"verdict": verdict,
                         "note": "independent streamouts are geometrically identical" if clean else "independent streamouts differ"},
                provenance, None if clean else "independent streamouts differ")


def save_final_results(result):
    inputs = {}
    _walk(result.get("inputs_ref"), inputs)
    result.setdefault("provenance", {})["input_hashes"] = inputs
    result["provenance"]["finished_utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    summary = ["# Streamout XOR summary", "",
               "- Status: **" + result.get("status", "unknown") + "**",
               "- Verdict: **" + str(result.get("validation", {}).get("verdict", "unknown")) + "**"]
    results = result.get("results", {})
    if results.get("difference_count") is not None:
        summary += ["- Difference polygons: **" + str(results["difference_count"]) + "**",
                    "- Difference area: **" + str(results.get("difference_area_um2")) + " $\\mu\\text{m}^2$"]
    failure_reason = result.get("signoff_evidence", {}).get("failure_reason")
    if failure_reason:
        summary += ["", "> " + str(failure_reason)]
    text = "\n".join(summary) + "\n"
    open(os.path.join(OUTPUT, "SUMMARY.md"), "w", encoding="utf-8").write(text)
    open(os.path.join(OUTPUT, "reports", "REPORT.md"), "w", encoding="utf-8").write(text)
    with open(os.path.join(OUTPUT, "common_design_envelope.json"), "w", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2)
    outputs = {}
    for root, _, files in os.walk(OUTPUT):
        for name in files:
            path = os.path.join(root, name)
            if name != "common_design_envelope.json":
                outputs[os.path.relpath(path, OUTPUT).replace(os.sep, "/")] = _sha(path)
    result["provenance"]["output_hashes"] = outputs
    with open(os.path.join(OUTPUT, "common_design_envelope.json"), "w", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2)


SCENARIOS = ("xor_gds", "dual_streamout_xor")


def resolve_scenario(params):
    """(scenario, source_key). Accepts `scenario`, then `mode`, then
    `tool.scenario` (nested {"tool": {"scenario": ...}} or a flat dotted key)."""
    if not isinstance(params, dict):
        return None, None
    if params.get("scenario"):
        return params["scenario"], "scenario"
    if params.get("mode"):
        return params["mode"], "mode"
    tool = params.get("tool")
    if isinstance(tool, dict) and tool.get("scenario"):
        return tool["scenario"], "tool.scenario"
    if params.get("tool.scenario"):
        return params["tool.scenario"], "tool.scenario"
    return None, None


def dispatch(params):
    scenario, source = resolve_scenario(params)
    if scenario and source != "scenario":
        params = dict(params, scenario=scenario)
    if scenario == "xor_gds":
        result = _xor_scenario(params)
    elif scenario == "dual_streamout_xor":
        result = _dual(params)
    elif not scenario:
        detail = (params or {}).get("_parse_error") if isinstance(params, dict) else None
        result = failure_envelope(
            "Layout streamout XOR",
            "no scenario supplied (looked for keys: scenario, mode, tool.scenario)%s; "
            "supported scenarios: %s" % ((" -- " + str(detail)) if detail else "",
                                         ", ".join(SCENARIOS)), params)
        result["validation"]["supported_scenarios"] = list(SCENARIOS)
    else:
        result = failure_envelope("Layout streamout XOR",
                                  "unknown scenario {!r}; supported: {}".format(
                                      scenario, ", ".join(SCENARIOS)), params)
        result["validation"]["supported_scenarios"] = list(SCENARIOS)
    if source and source != "scenario" and isinstance(result, dict):
        result.setdefault("provenance", {})["scenario_alias"] = source
    return result


# --- shared CDE stack (migrate_shared_envelope.py) -------------------------
# _SHARED_ENVELOPE_WRAPPED_V1 template=78fcd5727179
# This tool builds its envelope by hand rather than through the shared
# `_finalize_envelope`. The wrapper below closes that gap WITHOUT rewriting the
# hand-rolled construction: it runs once, at dispatch exit, after every
# post-construction mutation (`error`, `signoff_evidence.engine_error`,
# `provenance.traceback`) has already been applied. Stamping at the envelope
# helper instead would snapshot a dict that is then edited underneath it.
#
# Everything here is setdefault-based and non-fatal: the tool's own richer
# values always win, and envelope bookkeeping must never fail a design run.
_CDE_REQUIRED_FIELDS = ('tool', 'status', 'objective', 'tools_used', 'pdk_binding', 'assumptions', 'inputs_ref', 'vplan', 'results', 'qor_metrics', 'signoff_evidence', 'margin', 'validation', 'provenance')

# NOTE: single braces. This template is expanded with str.replace(), NOT
# str.format(), so doubled braces would emit literally -- and `{{...}}` is a SET
# containing a dict, which imports cleanly past py_compile and then dies with
# "unhashable type: 'dict'" at module load. That failure mode was hit here once.
_EMPTY_DEFAULTS = {
    "tools_used": [], "assumptions": [], "qor_metrics": {},
    "signoff_evidence": {}, "inputs_ref": {}, "margin": {},
    "vplan": "shared_artifact", "pdk_binding": "none",
}


def _finalize_envelope(results):
    """Typed-empty defaults + provenance + progress + runtime. Never raises."""
    if not isinstance(results, dict):
        return results
    try:
        _defaulted = []
        for _k, _dv in _EMPTY_DEFAULTS.items():
            if _k not in results:
                results[_k] = list(_dv) if isinstance(_dv, list) else \
                    (dict(_dv) if isinstance(_dv, dict) else _dv)
                _defaulted.append(_k)
        _missing = [k for k in _CDE_REQUIRED_FIELDS if k not in results]
        _warns = results.get("envelope_warnings")
        if not isinstance(_warns, list):
            _warns = []
        if _defaulted:
            _warns.append("CDE auto-defaulted empty required field(s): "
                          + ", ".join(sorted(_defaulted)))
        if _missing:
            _warns.append("CDE missing required field(s): " + ", ".join(_missing))
        if _warns:
            results["envelope_warnings"] = _warns
    except Exception as _e:
        print("[" + str(TOOL) + "] CDE self-check skipped: " + str(_e), flush=True)
    try:
        import datetime as _dt
        _prov = results.get("provenance")
        if not isinstance(_prov, dict):
            _prov = {} if _prov in (None, "") else {"note": str(_prov)}
        _prov.setdefault(
            "finished_utc",
            _dt.datetime.now(_dt.timezone.utc).isoformat())
        # Always record the input-hash key even when empty, so the audit chain
        # is an explicit empty rather than a silent gap. These tools already
        # hash their own inputs on the success paths; setdefault preserves that.
        _prov.setdefault("input_hashes", {})
        results["provenance"] = _prov
    except Exception as _e:
        print("[" + str(TOOL) + "] provenance stamp skipped: " + str(_e), flush=True)

    # --- runtime + peak-memory capture (migrate_runtime_capture.py) --------
    # _CDE_RUNTIME_CAPTURED_V1
    # Cost hints (slot-minutes) and `peak_ram_hint` were expert GUESSES: an audit
    # of 130 real CDEs found only 3 recording any runtime and none recording
    # memory, so every effort budget was calibrated against nothing. This records
    # what the run actually cost.
    #
    # Peak RSS of CHILDREN is the number that matters -- the heavy memory lives
    # in the yosys/openroad/eqy subprocesses, not in this wrapper. Repeated
    # exit-137 OOM kills in this campaign (LEC combine ~23GB; routing 2.18GB
    # against a then-2GB VM) were each diagnosed only forensically, after the
    # kill. Recording the peak on EVERY run makes the next one predictable.
    # Bookkeeping must never fail a design run, so nothing here is fatal.
    try:
        import datetime as _dt
        import time as _time
        _rt = {}
        _start_age = None
        try:
            # Process age on Linux, from the kernel's own accounting.
            #
            # NOT /proc/self mtime -- that looks like process start time but the
            # kernel refreshes it, so it reads ~0s for any run (verified in a
            # real container: a 2s sleep measured 0.006s). Use field 22 of
            # /proc/self/stat (`starttime`, in clock ticks since boot) against
            # /proc/uptime instead. comm (field 2) may itself contain spaces and
            # parentheses, so split after the LAST ')' -- index 19 of that tail
            # is field 22.
            with open("/proc/self/stat", "rb") as _f:
                _tail = _f.read().decode("utf-8", "replace").rsplit(")", 1)[1]
            _ticks = float(_tail.split()[19])
            _hz = float(os.sysconf("SC_CLK_TCK")) or 100.0
            with open("/proc/uptime", "rb") as _f:
                _up = float(_f.read().split()[0])
            _start_age = max(0.0, _up - (_ticks / _hz))
        except Exception:
            _start_age = None
        if _start_age is not None:
            _rt["started_utc"] = _dt.datetime.utcfromtimestamp(
                _time.time() - _start_age).isoformat() + "Z"
            _rt["elapsed_seconds"] = round(_start_age, 3)
            # the effort cost model is denominated in slot-minutes
            _rt["slot_minutes"] = round(_start_age / 60.0, 4)
            _rt["measurement"] = "proc_self_stat_starttime"
        else:
            # Honest absence beats a fabricated zero: a 0.0 here would silently
            # price a real run as free and understate campaign burn.
            _rt["measurement"] = "unavailable"
        try:
            import resource as _res
            # ru_maxrss is KILOBYTES on Linux (bytes on macOS -- containers here
            # are Linux). RUSAGE_CHILDREN covers children that have been waited
            # for, which is exactly how every EDA engine here is invoked
            # (subprocess.run / check_output).
            _self_kb = _res.getrusage(_res.RUSAGE_SELF).ru_maxrss
            _kid_kb = _res.getrusage(_res.RUSAGE_CHILDREN).ru_maxrss
            _rt["peak_rss_mb_self"] = round(_self_kb / 1024.0, 1)
            _rt["peak_rss_mb_children"] = round(_kid_kb / 1024.0, 1)
            _rt["peak_rss_mb"] = round(max(_self_kb, _kid_kb) / 1024.0, 1)
        except Exception:
            pass
        _prov = results.get("provenance")
        if isinstance(_prov, dict):
            _prov.setdefault("runtime", _rt)
    except Exception as _e:
        print("[" + str(TOOL) + "] runtime capture skipped: " + str(_e),
              flush=True)
    # --- end runtime + peak-memory capture ---------------------------------
    # --- normalized progress contract (migrate_cde_progress.py) -------------
    # Emits the stable `progress` block (residual / verdict_normalized /
    # alignment) that effort budgets, stall detection and QoR analytics read.
    # Freeform `results` keys are NOT stable across attempts, so this mapping is
    # what makes any metric-driven decision possible. Never fatal.
    try:
        import cde_progress as _cde_progress   # _CDE_PROGRESS_STAMPED_V1
        _cde_progress.stamp_progress(results, results.get("stage") or TOOL)
    except Exception as _e:
        print("[" + str(TOOL) + "] progress stamp skipped: " + str(_e), flush=True)
    # --- end normalized progress contract ----------------------------------

    return results
# --- end shared CDE stack --------------------------------------------------


# --- dispatch finalization (migrate_shared_envelope.py) --------------------
_dispatch_unfinalized = dispatch


def dispatch(params):          # noqa: F811  (intentional wrap)
    """Run the tool, then stamp the shared envelope contract on the result."""
    return _finalize_envelope(_dispatch_unfinalized(params))
# --- end dispatch finalization ---------------------------------------------


# --- attempt capture (BEGIN) -- vendored by catalog/migrate_attempt_capture.py
# Records WHAT THE STAGE WAS ASKED TO DO alongside what it measured, so that an
# attempt chain (stage.1 -> stage.N) can be mined for which knob actually moved the
# residual. Without it a CDE says the residual fell from 102 to 9 but not why, and
# the causal knowledge is lost the moment the run ends.
#
# Hooked as wrappers rather than edits to dispatch()/save_final_results() so this
# migration never has to understand tool-specific code.
_ATTEMPT_CAPTURE = {}

#: Substrings that mark a value as secret. Envelopes are committed to git, so a
#: credential that reaches one is durable and public. Narrow on purpose: a broad
#: "key" match would redact legitimate EDA parameters (`clock_key`, `map_key`).
_CAPTURE_SECRET_HINTS = ("password", "passwd", "secret", "token", "api_key",
                         "apikey", "credential", "private_key", "auth")

_CAPTURE_MAX_STR = 512
_CAPTURE_MAX_SEQ = 64
_CAPTURE_MAX_DEPTH = 6


def _capture_digest(obj):
    import hashlib
    import json as _json
    try:
        blob = _json.dumps(obj, sort_keys=True, default=str)
    except Exception:  # noqa: BLE001
        blob = repr(obj)
    return hashlib.sha256(blob.encode("utf-8", "replace")).hexdigest()


def _capture_head(value, limit=120):
    """Truncate an excerpt on a LINE boundary so it never ends mid-token.

    A raw byte slice cuts wherever the count lands, and 120 bytes into this
    campaign's RTL lands inside `campaigns/.../spec.3/reports/bsum16.md`, leaving
    `campaigns/.../spec.3/repor`. The publication citation scanner reads any
    path-shaped string as a citation, so the excerpt turns a real reference into a
    dangling one and blocks the whole publication transaction -- a provenance
    failure manufactured entirely by the truncation.
    """
    if len(value) <= limit:
        return value
    window = value[:limit]
    cut = window.rfind("\n")
    if cut <= 0:
        cut = max(window.rfind(" "), window.rfind("\t"))
    if cut <= 0:
        # One unbroken token wider than the window: nothing to cut back to.
        return window
    return window[:cut]


def _capture_normalize(value, depth=0):
    """Bound the size of a captured value without losing change-detection.

    Elision keeps a sha256 of the ELIDED PART, so a parameter that changed between
    two attempts still shows a different hash even when its content is too big to
    store. Silently dropping it would make the delta look empty -- i.e. would
    report "nothing changed" for a run that changed something.
    """
    if depth > _CAPTURE_MAX_DEPTH:
        return {"_elided": "depth", "sha256": _capture_digest(value)}
    if value is None or isinstance(value, bool) or isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        if len(value) > _CAPTURE_MAX_STR:
            return {"_elided": "str", "chars": len(value),
                    "sha256": _capture_digest(value),
                    "head": _capture_head(value)}
        return value
    if isinstance(value, dict):
        out = {}
        for key in list(value)[:_CAPTURE_MAX_SEQ]:
            low = str(key).lower()
            if any(hint in low for hint in _CAPTURE_SECRET_HINTS):
                out[key] = {"_redacted": "secret-like key"}
                continue
            out[key] = _capture_normalize(value[key], depth + 1)
        if len(value) > _CAPTURE_MAX_SEQ:
            out["_elided"] = {"keys": len(value), "sha256": _capture_digest(value)}
        return out
    if isinstance(value, (list, tuple)):
        if len(value) > _CAPTURE_MAX_SEQ:
            return {"_elided": "list", "len": len(value),
                    "sha256": _capture_digest(value),
                    "head": [_capture_normalize(v, depth + 1) for v in value[:8]]}
        return [_capture_normalize(v, depth + 1) for v in value]
    return {"_elided": type(value).__name__, "sha256": _capture_digest(value)}


def _capture_params(params):
    import datetime
    if not isinstance(params, dict):
        return
    intent = params.get("attempt_intent")
    _ATTEMPT_CAPTURE.clear()
    _ATTEMPT_CAPTURE.update({
        "schema": "attempt-capture/1",
        # Hash the RAW params, before elision -- see _capture_normalize.
        "parameters_sha256": _capture_digest(params),
        "parameters": _capture_normalize(params),
        "intent": intent or None,
        "intent_missing": not bool(intent),
        "captured_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    })


try:
    _dispatch_undecorated = dispatch

    def dispatch(params):  # noqa: F811
        _capture_params(params)
        return _dispatch_undecorated(params)
except NameError:  # pragma: no cover - a tool without dispatch()
    pass


try:
    _save_final_results_undecorated = save_final_results

    def save_final_results(results):  # noqa: F811
        if isinstance(results, dict):
            # Fall back to the fail-closed path's own copy: run.py sets
            # `input_parameters` when it fails BEFORE dispatch, which is exactly
            # when _ATTEMPT_CAPTURE would otherwise be empty.
            if not _ATTEMPT_CAPTURE and isinstance(
                    results.get("input_parameters"), dict):
                _capture_params(results["input_parameters"])
            if _ATTEMPT_CAPTURE:
                results.setdefault("attempt_capture", dict(_ATTEMPT_CAPTURE))
        return _save_final_results_undecorated(results)
except NameError:  # pragma: no cover - a tool without save_final_results()
    pass
# --- attempt capture (END) ---


# --- magic PDK_ROOT env (BEGIN) -- vendored by catalog/migrate_magic_env.py
# sky130A.magicrc (and the open_pdks family generally) resolves its techfile via
# $PDK_ROOT and falls back to the ORIGINAL BUILD MACHINE's absolute path when
# that variable is unset. A tool that does not set PDK_ROOT therefore runs Magic
# with NO TECHNOLOGY LOADED -- and Magic does not fail: it reads no geometry,
# extracts an empty cell, reports zero violations and EXITS 0. That is a silent
# false clean on a mandatory tapeout gate, which is the worst value these tools
# can emit. Setting PDK_ROOT is what makes the vendor magicrc work unmodified.
def _magic_pdk_root(techfile=None, rcfile=None, params=None):
    """Derive a PDK_ROOT that makes the vendor magicrc resolve, or None.

    Precedence: explicit caller param > already-set environment > derived from
    the techfile/rcfile path. Never guesses: a derived root is returned only
    when the expected <root>/<variant>/libs.tech/magic directory really exists,
    so a wrong layout yields None (and the caller fails closed) rather than a
    plausible-but-wrong path.
    """
    if params:
        explicit = params.get("pdk_root") or (
            (params.get("pdk_binding") or {}).get("pdk_root")
            if isinstance(params.get("pdk_binding"), dict) else None)
        if explicit and os.path.isdir(str(explicit)):
            return str(explicit)
    env_root = os.environ.get("PDK_ROOT")
    if env_root and os.path.isdir(env_root):
        return env_root
    for path in (techfile, rcfile):
        if not path:
            continue
        p = os.path.abspath(str(path))
        # <root>/<variant>/libs.tech/magic/<file>  ->  climb four levels.
        magic_dir = os.path.dirname(p)
        libs_tech = os.path.dirname(magic_dir)
        variant = os.path.dirname(libs_tech)
        root = os.path.dirname(variant)
        if (os.path.basename(magic_dir) == "magic"
                and os.path.basename(libs_tech) == "libs.tech"
                and os.path.isdir(os.path.join(variant, "libs.tech", "magic"))
                and os.path.isdir(root)):
            return root
    return None


def _magic_env(techfile=None, rcfile=None, params=None, extra=None):
    """Environment for a Magic subprocess, with PDK_ROOT resolved."""
    env = dict(os.environ)
    env.setdefault("MAGTYPE", "mag")
    root = _magic_pdk_root(techfile, rcfile, params)
    if root:
        env["PDK_ROOT"] = root
    if extra:
        env.update({str(k): str(v) for k, v in extra.items()})
    return env
# --- magic PDK_ROOT env (END) ---
