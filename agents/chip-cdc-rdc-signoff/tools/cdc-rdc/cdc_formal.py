#!/usr/bin/env python3
"""
cdc_formal.py -- formal proof of the SOURCE-DOMAIN obligations behind a
multi-bit clock-domain crossing, driven by SymbiYosys + yosys-smtbmc + z3.

WHY THIS EXISTS
===============
The structural screen in cdc_rdc_utils.py can see that N bits cross a domain
boundary and that each bit has a 2-flop synchronizer. It cannot see whether the
BITS ARE COHERENT, and coherency is the whole ballgame for a multi-bit crossing:
independently synchronized bits settle on different destination cycles, so the
receiver can assemble a word that never existed in the source domain. Structure
cannot answer that question because two designs with identical flop topology --
one gray-coded, one not -- are structurally the same design.

THE KEY OBSERVATION THAT MAKES THIS TRACTABLE
=============================================
The obligations that make a multi-bit crossing safe are properties OF THE SOURCE
DOMAIN, not of the crossing itself:

  * gray-coded      -> "at most one bit of the bus changes per source clock"
  * handshake-held  -> "the bus is stable while req is asserted and unacked"

Both are single-clock, single-domain statements. They need no multi-clock
modelling, no metastability injection, and no `(* gclk *)` global-clock frame --
just an immediate assertion in a clocked always block, which is the ONE formal
encoding open-source Yosys fully supports. That is why this is a real proof
rather than a research project, and it is also why the scope is bounded: see
"WHAT THIS DOES NOT PROVE" below.

WHAT THIS DOES NOT PROVE
========================
Proving the source obligation does NOT prove the crossing is safe end to end.
Not proved here, and NOT to be implied anywhere downstream:
  * metastability settling behaviour at the destination (needs multi-clock
    modelling with nondeterministic settling -- Phase 2);
  * reconvergence of separately synchronized signals in the destination domain;
  * glitches on combinational logic feeding a synchronizer input;
  * that the DECLARED scheme is the scheme the designer intended.
A proof of the source obligation plus a structural synchronizer check is
STRONGER evidence than either alone. It is not a commercial CDC signoff, and
must never be reported as one.

ENCODING NOTE (open-source toolchain reality)
=============================================
Open-source Yosys does not support `bind`, and does not parse clocked CONCURRENT
SVA (`assert property (@(posedge clk) ...)`) at any version -- that grammar is a
Verific feature. Properties are therefore INJECTED into a COPY of the source as
immediate assertions inside `always @(posedge clk)` blocks, guarded by `ifdef
FORMAL` so the original semantics are untouched when the macro is absent.

Editing source text is the fragile step in this file, so it is fail-closed at
three points, and every one of them yields NOT ASSESSABLE rather than a pass:
  1. the target module must be located unambiguously;
  2. every signal named in a property must exist in the elaborated netlist;
  3. the injected copy must elaborate to the SAME flop and cell counts as the
     original -- if injection perturbed the design, the proof would be about a
     different circuit, and a proof about a different circuit is worse than no
     proof because it looks like evidence.
"""

import json
import hashlib
import os
import re
import shutil
import signal
import subprocess

# `$onehot0` is deliberately NOT used: its availability varies across Yosys
# front-end paths, and a property that fails to PARSE is indistinguishable
# downstream from a property that passed. `x & (x-1)` is plain Verilog and is
# zero exactly when x has at most one bit set, which is the same predicate.
_AT_MOST_ONE_BIT = "(({d} ^ {p}) & (({d} ^ {p}) - 1)) == 0"
_SOLVERS = {"z3", "bitwuzla", "boolector", "yices", "cvc5"}
_MODES = {"bmc", "prove", "cover", "live"}


def _bounded_int(value, field, minimum, maximum):
    if isinstance(value, bool):
        raise ValueError(f"{field} must be an integer")
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field} must be an integer")
    if number < minimum or number > maximum:
        raise ValueError(f"{field} must be in [{minimum}, {maximum}]")
    return number


def normalize_config(config=None, depth=20):
    config = dict(config or {})
    modes = config.get("formal_modes", ["bmc", "prove", "cover"])
    if isinstance(modes, str):
        modes = [modes]
    modes = [str(mode).lower() for mode in modes]
    if not modes or len(modes) != len(set(modes)) or any(
            mode not in _MODES for mode in modes):
        raise ValueError("formal_modes must contain unique bmc, prove, or cover values")
    if not {"bmc", "prove", "cover"}.issubset(modes):
        raise ValueError(
            "formal_modes must include bmc, prove, and cover for signoff; live is additive")
    solver = str(config.get("formal_solver", "z3")).lower()
    if solver not in _SOLVERS:
        raise ValueError("formal_solver must be one of: " + ", ".join(sorted(_SOLVERS)))
    blackbox_types = config.get("_formal_blackbox_cell_types", [])
    if not isinstance(blackbox_types, list) or any(
            not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*", str(item))
            for item in blackbox_types):
        raise ValueError("_formal_blackbox_cell_types must contain safe module names")
    return {
        "modes": modes,
        "depth": _bounded_int(config.get("formal_depth", depth),
                              "formal_depth", 2, 100000),
        "timeout_s": _bounded_int(config.get("formal_timeout_s", 300),
                                  "formal_timeout_s", 1, 86400),
        "solver_timeout_s": _bounded_int(
            config.get("formal_solver_timeout_s", 120),
            "formal_solver_timeout_s", 1, 86400),
        "jobs": _bounded_int(config.get("formal_jobs", 1),
                             "formal_jobs", 1, 32),
        "seed": _bounded_int(config.get("formal_seed", 1),
                             "formal_seed", 0, 2147483647),
        "append": _bounded_int(config.get("formal_append_cycles", 2),
                               "formal_append_cycles", 0, 1000),
        "z3_memory_mb": _bounded_int(config.get("formal_z3_memory_mb", 4096),
                                     "formal_z3_memory_mb", 64, 1048576),
        "keep_going": config.get("formal_keep_going", True) is not False,
        "solver": solver,
        "blackbox_cell_types": sorted(set(map(str, blackbox_types))),
    }


def _module_span(text, module):
    """Locate `module <name> ... endmodule` and return (start, end_of_body).

    Returns None when the module cannot be located UNAMBIGUOUSLY. Nested/duplicate
    definitions return None rather than a guess: injecting into the wrong module
    would produce a proof about the wrong circuit.
    """
    pat = re.compile(r"\bmodule\s+" + re.escape(module) + r"\b")
    starts = list(pat.finditer(text))
    if len(starts) != 1:
        return None
    start = starts[0].start()
    ends = list(re.finditer(r"\bendmodule\b", text[start:]))
    if not ends:
        return None
    return (start, start + ends[0].start())


def build_properties(buses, protocols, clock_of_domain):
    """Turn bus records into (property_name, clock, verilog_expr, kind) tuples.

    Only buses with a DECLARED scheme get a property: the obligation being proved
    comes from the declaration. An undeclared multi-bit bus is not provable here
    and is already a gating structural violation, so it is returned as a skip
    with a reason rather than silently dropped -- a property that was never
    generated must not be mistaken for one that passed.
    """
    props, skipped = [], []
    for b in buses:
        if not b.get("multi_bit"):
            continue
        sig = b["signal"]
        decl = (protocols or {}).get(sig) or {}
        scheme = str(decl.get("scheme", "")).strip().lower()
        clk = decl.get("clock") or clock_of_domain.get(b["from_domain"])
        if not clk:
            skipped.append({"signal": sig, "reason": (
                "no source clock resolved for domain "
                f"{b['from_domain']}; cannot build a clocked property")})
            continue
        base = re.sub(r"[^A-Za-z0-9_]", "_", sig).strip("_") or "bus"
        if scheme == "gray":
            past = f"$past({sig})"
            props.append({
                "name": f"cdc_gray_{base}", "clock": clk, "signal": sig,
                "kind": "gray_at_most_one_bit_changes",
                "expr": _AT_MOST_ONE_BIT.format(d=sig, p=past),
                "cover_expr": f"{sig} != $past({sig})",
                "obligation": (
                    f"At most one bit of '{sig}' changes per '{clk}' cycle, so no "
                    f"mixture of old and new bits sampled by the destination is "
                    f"ever an invalid value."),
            })
        elif scheme == "handshake":
            req, ack = decl.get("req"), decl.get("ack")
            if not req:
                skipped.append({"signal": sig, "reason": (
                    "scheme 'handshake' declared without a 'req' signal; the "
                    "stability window is undefined")})
                continue
            window = f"{req} && !{ack}" if ack else f"{req}"
            props.append({
                "name": f"cdc_stable_{base}", "clock": clk, "signal": sig,
                "kind": "handshake_data_stable",
                "expr": f"!({window}) || $stable({sig})",
                "cover_expr": window,
                "obligation": (
                    f"'{sig}' is stable while the qualifier ({window}) is "
                    f"asserted, so the destination samples a settled word."),
            })
        else:
            skipped.append({"signal": sig, "reason": (
                f"scheme {scheme or 'undeclared'!r} has no formal encoding here; "
                f"it remains a structural finding")})
    return props, skipped


def render_injection(props):
    """Render the `ifdef FORMAL` block asserting each property.

    `$past` is undefined on the first cycle, so every property is qualified by a
    local past-valid flag. Without it the proof would report a counterexample at
    time 0 for a perfectly correct design -- a false failure, which erodes trust
    in the check faster than no check at all.
    """
    if not props:
        return ""
    lines = ["", "`ifdef FORMAL", "`default_nettype none",
             "  // ---- injected by chip-cdc-rdc formal CDC screen ----",
             "  // Source-domain coherency obligations. Removed with the macro."]
    clocks = sorted({p["clock"] for p in props})
    history_by_clock = {
        clock: max(int(p.get("history", 1)) for p in props
                   if p["clock"] == clock)
        for clock in clocks}
    for i, clk in enumerate(clocks):
        event = "$global_clock" if clk == "$global_clock" else f"posedge {clk}"
        history = history_by_clock[clk]
        lines.append(f"  reg [{history - 1}:0] _cdcf_past_valid_{i} = 0;")
        if history == 1:
            shift = "1'b1"
        else:
            shift = f"{{_cdcf_past_valid_{i}[{history - 2}:0], 1'b1}}"
        lines.append(f"  always @({event}) _cdcf_past_valid_{i} <= {shift};")
    for p in props:
        i = clocks.index(p["clock"])
        event = ("$global_clock" if p["clock"] == "$global_clock"
                 else f"posedge {p['clock']}")
        guard = f"_cdcf_past_valid_{i}[{int(p.get('history', 1)) - 1}]"
        role = p.get("role", "assert")
        statement = "assume" if role == "assume" else "assert"
        lines += [
            f"  // {p['obligation']}",
            f"  always @({event})",
            f"    if ({guard})",
            f"      {p['name']}: {statement} ({p['expr']});",
            f"  always @({event})",
            f"    if ({guard})",
            f"      {p['name']}_reachable: cover ({p['cover_expr']});",
        ]
        if p.get("live_expr"):
            trigger = p.get("live_trigger") or "1'b1"
            lines += [
                f"  always @({event})",
                f"    if ({guard} && ({trigger}))",
                f"      {p['name']}_eventual: assert property "
                f"(s_eventually ({p['live_expr']}));",
                f"  always @({event})",
                f"    if ({guard})",
                f"      {p['name']}_fair: assume property "
                f"(s_eventually ({p['fair_expr']}));",
                f"  always @({event})",
                f"    if ({guard})",
                f"      {p['name']}_fair_reachable: cover ({p['fair_expr']});",
            ]
    lines += ["`default_nettype wire", "`endif", ""]
    return "\n".join(lines)


def inject(text, module, block):
    """Insert *block* just before the module's `endmodule`. None if not locatable."""
    span = _module_span(text, module)
    if span is None:
        return None
    _, body_end = span
    return text[:body_end] + block + text[body_end:]


def write_sby(path, files, top, depth, mode="bmc", engine="smtbmc z3",
              timeout_s=None, append=0, multiclock=False,
              blackbox_cell_types=None):
    """Emit a .sby driving a BMC of the injected properties.

    `read_verilog -sv -formal` defines the FORMAL macro, which is what activates
    the injected block.
    """
    reads = "\n".join(f"read_verilog -sv -formal {os.path.basename(f)}"
                      for f in files)
    blackbox_cell_types = list(blackbox_cell_types or [])
    if blackbox_cell_types:
        delete_selection = " ".join(
            "t:" + cell_type for cell_type in blackbox_cell_types)
        prep = (
            f"hierarchy -top {top}\n"
            "proc\n"
            "flatten\n"
            f"delete {delete_selection}\n"
            "setundef -undriven -anyseq\n"
            f"prep -top {top} -run coarse"
        )
    else:
        prep = f"prep -top {top}"
    cfg = (
        "[options]\n"
        f"mode {mode}\n"
        + (f"depth {int(depth)}\n" if mode != "live" else "")
        + (f"timeout {int(timeout_s)}\n" if timeout_s else "")
        + (f"append {int(append)}\n" if append and mode != "live" else "")
        + ("multiclock on\n" if multiclock else "")
        + "\n"
        "[engines]\n"
        f"{engine}\n\n"
        "[script]\n"
        f"{reads}\n"
        f"{prep}\n\n"
        "[files]\n"
        + "\n".join(files) + "\n"
    )
    open(path, "w").write(cfg)
    return cfg


_FAIL_RE = re.compile(r"Assert failed in \S+: (\S+)")
_UNREACHED_RE = re.compile(r"Unreached cover statement at \S+: (\S+)")


def parse_sby(stdout, stderr):
    """Extract (status, failing_property_names) from an sby run.

    Anything that is not an explicit PASS is treated as NOT a pass. An
    unrecognised sby status must never fall through to success -- that is the
    single most damaging way a formal check can lie.
    """
    txt = (stdout or "") + "\n" + (stderr or "")
    failing = sorted(set(_FAIL_RE.findall(txt) + _UNREACHED_RE.findall(txt)))
    if re.search(r"DONE \(PASS", txt):
        return "pass", failing
    if re.search(r"DONE \(FAIL", txt):
        return "fail", failing or ["<unnamed>"]
    if re.search(r"DONE \(UNKNOWN", txt):
        return "unknown", failing
    if re.search(r"DONE \(TIMEOUT", txt):
        return "timeout", failing
    if re.search(r"DONE \(CANCELLED", txt):
        return "cancelled", failing
    if re.search(r"DONE \(ERROR", txt):
        return "error", failing
    return "error", failing


def parse_property_statuses(text):
    statuses = {}
    for line in (text or "").splitlines():
        marker = "jsonl: "
        if marker not in line:
            continue
        try:
            record = json.loads(line.split(marker, 1)[1])
        except (ValueError, TypeError):
            continue
        name = record.get("name")
        status = record.get("status")
        if not name or not status:
            continue
        short_name = str(name).rsplit(".", 1)[-1]
        statuses[short_name] = {
            key: record[key] for key in
            ("status", "kind", "depth", "trace", "location", "engine")
            if key in record}
    return statuses


def _artifact_refs(root, output_dir):
    references = []
    for directory, _, files in os.walk(root):
        for name in files:
            if (name.endswith((".vcd", ".yw", "_tb.v", ".smtc", ".smt2",
                               ".aig", ".aiw", ".aim", ".ywa", ".log",
                               ".xml")) or name == "logfile.txt"):
                references.append(os.path.relpath(
                    os.path.join(directory, name), output_dir))
    return sorted(references)


def _artifact_hashes(references, output_dir):
    hashes = {}
    for reference in references:
        path = os.path.join(output_dir, reference)
        digest = hashlib.sha256()
        with open(path, "rb") as stream:
            for chunk in iter(lambda: stream.read(65536), b""):
                digest.update(chunk)
        hashes[reference] = digest.hexdigest()
    return hashes


def _formal_cell_names(job_dir, cell_type):
    path = os.path.join(job_dir, "model", "design_prep.il")
    try:
        text = open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        return set()
    return set(re.findall(
        r"^\s*cell\s+\$" + re.escape(cell_type) + r"\s+\\([^\s]+)",
        text, re.M))


def _tool_version(command):
    try:
        process = subprocess.run(command, capture_output=True, text=True,
                                 timeout=30)
        return (process.stdout or process.stderr).strip().splitlines()[0]
    except Exception:  # noqa: BLE001
        return "unknown"


def _run_sby(command, cwd, timeout_s):
    process = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        cwd=cwd, start_new_session=True)
    try:
        return (*process.communicate(timeout=timeout_s), process.returncode, False)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        stdout, stderr = process.communicate()
        return stdout, stderr, process.returncode, True


def _engine_line(config):
    options = ["smtbmc"]
    if config["keep_going"]:
        options.append("--keep-going")
    options.append("--seed=%d" % config["seed"])
    options.append(config["solver"])
    if config["solver"] == "z3":
        options.append("-memory:%d" % config["z3_memory_mb"])
    options.extend(("--", "--timeout", str(config["solver_timeout_s"])))
    return " ".join(options)


def run(work_dir, files, top, module, buses, protocols, clock_of_domain,
    depth=20, elaborate_check=None, config=None, output_dir="/output",
    properties=None, skipped_properties=None, extra_injection="",
    multiclock=False, label="cdc_formal", auxiliary_properties=None,
    auxiliary_extra_injection=None):
    """Full formal pass. Returns a dict; NEVER raises.

    `elaborate_check(files, top) -> (flop_count, cell_count)` is injected by the
    caller so this module does not import the Yosys driver. When supplied, the
    injected copy is re-elaborated and compared with the original: any structural
    difference aborts as not_assessable, because a proof about a design the
    injection accidentally changed is a proof about the wrong circuit.
    """
    try:
        formal_config = normalize_config(config, depth)
    except ValueError as exc:
        return {"attempted": False, "status": "not_assessable",
                "properties": [], "skipped": [], "note": str(exc)}
    if properties is None:
        props, skipped = build_properties(buses, protocols, clock_of_domain)
    else:
        props = list(properties)
        skipped = list(skipped_properties or [])
    auxiliary_properties = dict(auxiliary_properties or {})
    auxiliary_extra_injection = dict(auxiliary_extra_injection or {})
    all_props = props + [
        prop for module_props in auxiliary_properties.values()
        for prop in module_props
    ]
    out = {"attempted": bool(all_props), "properties": all_props, "skipped": skipped,
           "depth": formal_config["depth"],
           "engine": _engine_line(formal_config), "status": "not_attempted",
           "failing_properties": [], "tasks": {}, "note": "",
           "configuration": formal_config,
           "tool_versions": {
               "sby": _tool_version(["sby", "--version"]),
               "yosys-smtbmc": _tool_version(["yosys-smtbmc", "-h"]),
               "solver": _tool_version([formal_config["solver"], "--version"]),
           }}
    if not all_props:
        out["note"] = ("No formally checkable obligation: no multi-bit crossing "
                       "carried a declared gray/handshake scheme. This is NOT a "
                       "clean formal result -- nothing was proved.")
        return out
    if "live" in formal_config["modes"] and not any(
            prop.get("live_expr") for prop in all_props):
        out["status"] = "not_assessable"
        out["skipped"].append({
            "reason": "live mode requested without an eventual response and fairness contract"})
        out["note"] = "liveness requires explicit eventual-response and fairness declarations"
        return out

    try:
        # Find WHICH file defines the module. Assuming files[0] would make the
        # screen unusable on any multi-file design whose top is not listed first
        # -- and it would fail as "not locatable", which reads like a parsing
        # problem rather than a wrong-file problem. Ambiguity (the module appears
        # to be defined in more than one file) is an abort, not a choice.
        texts = {}
        owners = []
        for f in files:
            try:
                t = open(f, encoding="utf-8", errors="replace").read()
            except Exception:
                continue
            texts[f] = t
            if _module_span(t, module) is not None:
                owners.append(f)
        if len(owners) != 1:
            out["status"] = "not_assessable"
            out["note"] = (
                f"could not locate a unique 'module {module} ... endmodule' "
                f"across {len(files)} source file(s) (matched {len(owners)}); "
                f"properties were NOT injected and nothing was proved")
            return out
        src = owners[0]
        text = texts[src]
        block = extra_injection + render_injection(props)
        injected = inject(text, module, block)
        if injected is None:
            out["status"] = "not_assessable"
            out["note"] = (
                f"could not locate a unique 'module {module} ... endmodule' in "
                f"{os.path.basename(src)}; properties were NOT injected and "
                f"nothing was proved")
            return out

        for aux_module, module_props in auxiliary_properties.items():
            aux_owners = [
                path for path, source_text in texts.items()
                if _module_span(source_text, aux_module) is not None
            ]
            if len(aux_owners) != 1:
                out["status"] = "not_assessable"
                out["note"] = (
                    f"could not locate unique auxiliary module {aux_module}")
                return out
            aux_owner = aux_owners[0]
            aux_injected = inject(
                texts[aux_owner], aux_module,
                auxiliary_extra_injection.get(aux_module, "")
                + render_injection(module_props))
            if aux_injected is None:
                out["status"] = "not_assessable"
                out["note"] = (
                    f"could not inject auxiliary module {aux_module}")
                return out
            texts[aux_owner] = aux_injected

        fdir = os.path.join(output_dir, "formal")
        if os.path.isdir(fdir):
            shutil.rmtree(fdir)
        os.makedirs(fdir, exist_ok=True)
        inj_path = os.path.join(fdir, os.path.basename(src))
        open(inj_path, "w").write(injected)
        all_files = []
        for f in files:
            if f == src:
                if f in texts and auxiliary_properties:
                    injected = inject(texts[f], module, block)
                    open(inj_path, "w").write(injected)
                all_files.append(inj_path)
                continue
            dst = os.path.join(fdir, os.path.basename(f))
            open(dst, "w").write(texts.get(f, ""))
            all_files.append(dst)
        out["injected_into"] = os.path.basename(src)

        if elaborate_check is not None:
            try:
                before = elaborate_check(files, top)
                after = elaborate_check(all_files, top)
                if before != after:
                    out["status"] = "not_assessable"
                    out["note"] = (
                        f"injection changed the elaborated design "
                        f"(flops/cells {before} -> {after}); the proof would not "
                        f"be about the design under test, so it was abandoned")
                    return out
                out["injection_neutral"] = True
                out["elaboration_signature"] = list(before)
            except Exception as e:  # noqa: BLE001
                out["status"] = "not_assessable"
                out["note"] = f"could not verify injection neutrality: {e}"
                return out

        engine = _engine_line(formal_config)
        statuses = []
        all_failing = set()
        for mode in formal_config["modes"]:
            mode_engine = "aiger suprove" if mode == "live" else engine
            sby_path = os.path.join(fdir, f"{label}_{mode}.sby")
            write_sby(
                sby_path, all_files, top, formal_config["depth"], mode=mode,
                engine=mode_engine, timeout_s=formal_config["timeout_s"],
                append=formal_config["append"] if mode == "bmc" else 0,
                multiclock=multiclock,
                blackbox_cell_types=formal_config["blackbox_cell_types"])
            job_dir = os.path.join(fdir, mode)
            stdout, stderr, returncode, timed_out = _run_sby(
                ["sby", "--live", "jsonl", "-j", str(formal_config["jobs"]),
                 "-f", "-d", job_dir, sby_path], fdir,
                formal_config["timeout_s"] + 30)
            log_path = os.path.join(fdir, f"sby_{mode}.log")
            open(log_path, "w").write(stdout + "\n" + stderr)
            status, failing = (("timeout", []) if timed_out
                               else parse_sby(stdout, stderr))
            statuses.append(status)
            all_failing.update(failing)
            artifacts = _artifact_refs(job_dir, output_dir)
            property_statuses = parse_property_statuses(stdout)
            for record in property_statuses.values():
                trace = record.get("trace")
                if trace and os.path.isabs(trace):
                    record["trace"] = os.path.relpath(trace, output_dir)
            if mode == "live" and status == "pass":
                for name in _formal_cell_names(job_dir, "live"):
                    property_statuses[name] = {
                        "status": "PASS", "kind": "LIVE",
                        "engine": "aggregate_pass_plus_model_inventory"}
                for name in _formal_cell_names(job_dir, "fair"):
                    property_statuses[name] = {
                        "status": "ASSUMED", "kind": "FAIR",
                        "engine": "model_inventory"}
            elif mode == "live" and status == "fail":
                live_names = _formal_cell_names(job_dir, "live")
                for name in live_names:
                    property_statuses[name] = {
                        "status": "FAIL", "kind": "LIVE",
                        "engine": "aggregate_fail_plus_model_inventory"}
                if live_names:
                    failing = sorted(live_names)
                    all_failing.discard("<unnamed>")
                    all_failing.update(live_names)
            out["tasks"][mode] = {
                "status": status, "returncode": returncode,
                "log": f"formal/sby_{mode}.log",
                "workdir": f"formal/{mode}",
                "failing_properties": failing,
                "properties": property_statuses,
                "artifacts": artifacts,
                "artifact_sha256": _artifact_hashes(artifacts, output_dir),
            }
            out["multiclock"] = bool(multiclock)
        expected_asserts = {
            prop["name"] for prop in all_props
            if prop.get("role", "assert") == "assert"}
        assumed_properties = {
            prop["name"] for prop in all_props if prop.get("role") == "assume"}
        expected_covers = {prop["name"] + "_reachable" for prop in all_props}
        expected_covers.update(
            prop["name"] + "_fair_reachable" for prop in all_props
            if prop.get("live_expr"))
        for mode, task in out["tasks"].items():
            observed = task["properties"]
            required = (expected_covers if mode == "cover" else
                        ({prop["name"] + "_eventual" for prop in all_props
                          if prop.get("live_expr")} if mode == "live" else
                         expected_asserts))
            allowed = set(required)
            if mode in ("bmc", "prove"):
                allowed.update(assumed_properties)
            if mode == "live":
                allowed.update(prop["name"] + "_fair" for prop in all_props
                               if prop.get("live_expr"))
            task["expected_properties"] = sorted(required)
            task["missing_properties"] = sorted(required - set(observed))
            task["unexpected_properties"] = sorted(set(observed) - allowed)
            task["expected_work_count"] = len(required)
            task["observed_work_count"] = len(required & set(observed))
            if not required:
                task["status"] = "semantically_absent"
                task["note"] = (
                    f"no {mode} obligation is declared by the domain map")
            elif task["missing_properties"] or task["unexpected_properties"]:
                task["status"] = "not_assessable"
        applicable = [
            task["status"] for task in out["tasks"].values()
            if task["expected_work_count"] > 0]
        if skipped or not applicable:
            out["status"] = "not_assessable"
        elif all(status == "pass" for status in applicable):
            out["status"] = "pass"
        elif "fail" in applicable:
            out["status"] = "fail"
        else:
            out["status"] = next(
                status for status in applicable if status != "pass")
        out["work_counts"] = {
            mode: task["observed_work_count"]
            for mode, task in out["tasks"].items()}
        out["positive_work_count"] = sum(out["work_counts"].values())
        out["failing_properties"] = sorted(all_failing)
        out["log"] = "formal/sby_bmc.log"
        if out["status"] == "pass":
            out["note"] = (
                "All requested formal tasks passed: "
                + ", ".join(formal_config["modes"])
                + ". This proves only the encoded digital obligations and says "
                  "nothing about physical metastability.")
        elif out["status"] == "fail":
            out["note"] = (
                f"FORMAL FAILURE: {', '.join(sorted(all_failing)) or 'required cover unreached'}. "
                f"The declared coherency "
                f"scheme does not hold in the source domain, so the destination "
                f"can sample a word that never existed. This is a real defect.")
        else:
            out["note"] = (f"formal run did not reach a definite result "
                           f"({out['status']}); nothing was proved")
    except Exception as e:  # noqa: BLE001
        out["status"] = "not_assessable"
        out["note"] = f"formal screen failed to run: {e}"
    return out
