"""Read-only, standard-library evidence reporting with lossless selected VCD data."""

import argparse
from bisect import bisect_right
from datetime import datetime, timezone
import hashlib
import html
import json
import math
import os
from pathlib import Path, PureWindowsPath
import re
import sys
from urllib.parse import quote
import uuid


ROOT = Path(__file__).resolve().parents[1]
MAX_TEXT = 8 * 1024 * 1024
SAFE_INTEGER = 2**53 - 1
DIGITAL_TYPES = {
    "wire", "reg", "integer", "time", "parameter", "supply0", "supply1",
    "tri", "triand", "trior", "trireg", "tri0", "tri1", "wand", "wor",
}


class EvidenceError(ValueError):
    pass


def esc(value):
    return html.escape(str(value), quote=True)


def display(value):
    return json.dumps(value, ensure_ascii=True) if not isinstance(value, str) else value


def script_json(value):
    text = json.dumps(value, ensure_ascii=True, separators=(",", ":"), allow_nan=False)
    return text.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")


def normalize_status(value):
    key = str(value).strip().upper()
    return {
        "PASS": "PASS", "PASSED": "PASS", "FAIL": "FAIL", "FAILED": "FAIL",
        "BLOCKED": "BLOCKED", "ERROR": "FAIL", "SKIPPED": "SKIPPED",
        "NOT_RUN": "NOT RUN", "NOT RUN": "NOT RUN",
    }.get(key, "UNKNOWN")


def badge(value):
    status = normalize_status(value)
    return f'<span class="badge {status.lower().replace(" ", "-")}">{esc(status)}</span>'


def confined(run, reference):
    if not isinstance(reference, str) or not reference.strip():
        raise EvidenceError(f"Invalid artifact reference: {reference!r}")
    parts = reference.replace("\\", "/").split("/")
    if (PureWindowsPath(reference).drive or reference.startswith(("/", "\\"))
            or any(p in {"", ".", ".."} or ":" in p for p in parts)):
        raise EvidenceError(f"Artifact must be run-relative: {reference!r}")
    path = run.joinpath(*parts).resolve()
    if not path.is_relative_to(run):
        raise EvidenceError(f"Artifact escapes the run directory: {reference!r}")
    return path


def read_text(path, limit=MAX_TEXT):
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise EvidenceError(f"{path.name}: exceeds {limit} byte limit; no partial content used")
    try:
        return raw.decode("utf-8-sig")
    except UnicodeError as exc:
        raise EvidenceError(f"{path.name}: invalid UTF-8: {exc}") from exc


def decode_json(text, label):
    try:
        return json.loads(text, parse_constant=invalid_constant)
    except json.JSONDecodeError as exc:
        raise EvidenceError(f"{label}: invalid JSON: {exc}") from exc


def object_json(text, label):
    data = decode_json(text, label)
    if not isinstance(data, dict):
        raise EvidenceError(f"{label}: expected a JSON object")
    return data


def invalid_constant(value):
    raise EvidenceError(f"Non-finite JSON value: {value}")


def zero_exits(value):
    if isinstance(value, dict):
        return bool(value) and all(zero_exits(v) for v in value.values())
    return type(value) is int and value == 0


def artifact_reference(artifacts, key, run, issues):
    matches = [value for label, value in artifacts.items()
               if re.sub(r"[\s-]+", "_", label.strip().lower()) == key]
    if not matches:
        return None
    try:
        if len({confined(run, value) for value in matches}) != 1:
            raise EvidenceError(f"Conflicting artifact aliases for {key}")
    except EvidenceError as exc:
        issues.append(str(exc))
        return None
    return matches[0]


def source_attribution(owner, key, label, issues):
    if key not in owner:
        return "not recorded"
    value = owner[key]
    if not isinstance(value, str) or not value.strip():
        issues.append(f"{label}: expected nonempty source-reported text")
    return display(value)


def recorded_time(value):
    if not isinstance(value, str):
        raise EvidenceError("missing native UTC timestamp")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise EvidenceError(f"invalid native timestamp {value!r}") from exc
    if result.utcoffset() is None:
        raise EvidenceError(f"native timestamp lacks timezone: {value!r}")
    return result


def check_execution(stage, cde, read, run, consumed, summary, issues):
    """Validate explicit links to existing host evidence, never synthesize an audit."""
    label = str(stage.get("stage", "unnamed"))
    evidence = mapping(stage.get("execution_evidence"), f"{label} execution_evidence", issues)
    if not evidence:
        issues.append(f"{label}: no execution evidence in place of attempt audit")
        return None
    invocation = read(evidence.get("invocation"), "json_value")
    arguments = invocation.get("arguments") if isinstance(invocation, dict) else invocation
    if (not isinstance(arguments, list) or not arguments
            or any(not isinstance(arg, str) or not arg.strip() for arg in arguments)):
        issues.append(f"{label}: invocation must contain a nonempty string argument list")
    else:
        images = [arg.rsplit("/", 1)[-1].split(":", 1)[0].split("@", 1)[0] for arg in arguments]
        tool = cde.get("tool") if cde else None
        if (not isinstance(tool, str) or tool not in images or "run" not in arguments
                or arguments.index("run") >= images.index(tool)):
            issues.append(f"{label}: invocation does not identify a container run of the native CDE tool")
    exit_record = read(evidence.get("exit"), "json_value")
    exit_code = exit_record.get("exit_code") if isinstance(exit_record, dict) else exit_record
    if type(exit_code) is not int or exit_code != 0:
        issues.append(f"{label}: host exit must be recorded integer zero, got {exit_code!r}")
    native = cde or {}
    signoff = mapping(native.get("signoff_evidence", {}), f"{label} signoff_evidence", issues)
    provenance = mapping(native.get("provenance", {}), f"{label} provenance", issues)
    if not zero_exits(signoff.get("native_exit_codes")):
        issues.append(f"{label}: missing, malformed or nonzero native_exit_codes")
    rtl_ref = evidence.get("rtl")
    rtl = read(rtl_ref, "text")
    if rtl is None:
        return None
    path = confined(run, rtl_ref)
    digest = consumed[str(path.relative_to(run)).replace("\\", "/")]
    hashes = []
    for source, owner, key in (
            ("provenance.input_hashes", provenance, "input_hashes"),
            ("signoff_evidence.source_hashes", signoff, "source_hashes"),
            ("signoff_evidence.source_hashes_before", signoff, "source_hashes_before"),
            ("signoff_evidence.source_hashes_after", signoff, "source_hashes_after")):
        if key not in owner:
            continue
        values = mapping(owner[key], f"{label} {source}", issues)
        entries = [v for k, v in values.items() if PureWindowsPath(k).name == path.name]
        if len(entries) != 1 or not isinstance(entries[0], dict):
            issues.append(f"{label}: {source} must identify exactly one RTL hash for {path.name}")
            continue
        entry = entries[0]
        hashes.append((source, entry.get("sha256")))
        if "bytes" in entry and (type(entry["bytes"]) is not int or entry["bytes"] != path.stat().st_size):
            issues.append(f"{label}: {source} RTL byte count mismatch")
    before, after = signoff.get("rtl_sha256_before"), signoff.get("rtl_sha256_after")
    if "rtl_sha256_before" in signoff or "rtl_sha256_after" in signoff:
        hashes.extend([("rtl_sha256_before", before), ("rtl_sha256_after", after)])
    if not hashes:
        issues.append(f"{label}: no native RTL SHA256 evidence")
    for source, value in hashes:
        if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", value) or value.lower() != digest:
            issues.append(f"{label}: {source} RTL SHA256 mismatch or missing hash")
    if "sources_unchanged" in signoff and signoff["sources_unchanged"] is not True:
        issues.append(f"{label}: native sources_unchanged is not true")
    if "rtl_sha256" in summary and summary["rtl_sha256"] != digest:
        issues.append(f"{label}: summary RTL SHA256 mismatch")
    return digest


def parse_vcd(text, requested=None, max_changes=1_000_000):
    """Parse digital VCD strictly; never return a partial trace on failure."""
    tokens = re.findall(r"\S+", text)
    scope, signals, widths, changes = [], [], {}, {}
    timescale, definitions, dumping = None, False, False
    timestamp = last_time = records = i = 0

    def command_body(index):
        end = index
        while end < len(tokens) and tokens[end] != "$end":
            end += 1
        if end == len(tokens):
            raise EvidenceError(f"VCD: unterminated directive near token {index}")
        return tokens[index:end], end + 1

    while i < len(tokens):
        token = tokens[i]
        i += 1
        if not definitions:
            if not token.startswith("$"):
                raise EvidenceError(f"VCD: expected declaration, got {token!r}")
            body, i = command_body(i)
            if token in {"$date", "$version", "$comment"}:
                continue
            if token == "$timescale":
                value = "".join(body)
                if timescale is not None or not re.fullmatch(r"(1|10|100)(s|ms|us|ns|ps|fs)", value):
                    raise EvidenceError(f"VCD: invalid/duplicate timescale {value!r}")
                timescale = value
            elif token == "$scope":
                if len(body) != 2:
                    raise EvidenceError("VCD: malformed scope")
                scope.append(body[1])
            elif token == "$upscope":
                if body or not scope:
                    raise EvidenceError("VCD: unbalanced scope")
                scope.pop()
            elif token == "$var":
                if len(body) < 4 or len(body) > 5 or body[0] not in DIGITAL_TYPES:
                    raise EvidenceError(f"VCD: unsupported/malformed variable: {' '.join(body)}")
                kind, size, code, name = body[:4]
                if not re.fullmatch("[0-9]+", size) or not 1 <= int(size) <= 65536:
                    raise EvidenceError(f"VCD: invalid width {size!r}")
                width = int(size)
                if len(body) == 5 and not re.fullmatch(r"\[-?\d+(?::-?\d+)?\]", body[4]):
                    raise EvidenceError("VCD: unsupported variable range")
                if code in widths and widths[code] != width:
                    raise EvidenceError("VCD: alias width mismatch")
                full_name = ".".join([*scope, name])
                if any(s["name"] == full_name for s in signals):
                    raise EvidenceError(f"VCD: duplicate signal name {full_name}")
                widths[code] = width
                changes.setdefault(code, [])
                signals.append({"name": full_name, "id": code, "width": width,
                                "kind": kind, "range": body[4] if len(body) == 5 else ""})
            elif token == "$enddefinitions":
                if body or scope or not signals or timescale is None:
                    raise EvidenceError("VCD: incomplete definitions, scopes or timescale")
                definitions = True
            else:
                raise EvidenceError(f"VCD: unsupported definition {token}")
            continue
        if token.startswith("#"):
            if dumping or not re.fullmatch(r"#[0-9]+", token):
                raise EvidenceError(f"VCD: invalid timestamp {token!r}")
            timestamp = int(token[1:])
            if timestamp < last_time or timestamp > SAFE_INTEGER:
                raise EvidenceError("VCD: decreasing timestamp or timestamp exceeds exact JS integer range")
            last_time = timestamp
            continue
        if token == "$comment":
            _, i = command_body(i)
            continue
        if token in {"$dumpvars", "$dumpall", "$dumpon", "$dumpoff"}:
            if dumping:
                raise EvidenceError("VCD: nested dump directive")
            dumping = True
            continue
        if token == "$end" and dumping:
            dumping = False
            continue
        if token.startswith(("b", "B")):
            if i >= len(tokens):
                raise EvidenceError("VCD: vector missing identifier")
            bits, code = token[1:].lower(), tokens[i]
            i += 1
            if not re.fullmatch("[01xz]+", bits):
                raise EvidenceError(f"VCD: invalid vector {token!r}")
        elif token[0] in "01xXzZ" and len(token) > 1:
            bits, code = token[0].lower(), token[1:]
            if widths.get(code) != 1:
                raise EvidenceError(f"VCD: scalar change for undeclared/non-scalar identifier {code!r}")
        else:
            raise EvidenceError(f"VCD: unsupported/malformed value record {token!r}")
        if code not in widths or len(bits) > widths[code]:
            raise EvidenceError(f"VCD: undeclared identifier or oversized vector {code!r}")
        padding = bits[0] if bits[0] in "xz" else "0"
        bits = bits.rjust(widths[code], padding)
        changes[code].append([timestamp, bits])
        records += 1
        if records > max_changes:
            raise EvidenceError(f"VCD: exceeds {max_changes} value records; no transitions discarded silently")
    if not definitions or dumping or records == 0:
        raise EvidenceError("VCD: missing definitions, unterminated dump or empty value data")
    if requested:
        names = {s["name"]: s for s in signals}
        if len(set(requested)) != len(requested) or len(requested) > 12:
            raise EvidenceError("VCD: select 1 to 12 distinct exact scoped signal names")
        missing = [name for name in requested if name not in names]
        if missing:
            raise EvidenceError(f"VCD: requested signals not found: {missing}")
        selected = [names[name] for name in requested]
    else:
        selected = []
        for leaves in (("clk", "clock"), ("rst_n", "reset_n", "reset", "rst"),
                       ("clear", "clr"), ("enable", "en"), ("count",), ("overflow",)):
            candidates = [s for s in signals if s["name"].split(".")[-1] in leaves]
            if candidates:
                selected.append(min(candidates, key=lambda s: (s["name"].count("."), s["name"])))
        selected = selected or signals[:6]
    selected_ids = {s["id"] for s in selected}
    result = {
        "timescale": timescale, "end": last_time, "declarations": signals,
        "signals": selected, "changes": {k: v for k, v in changes.items() if k in selected_ids},
        "total_records": records,
        "selected_records": sum(len(changes[k]) for k in selected_ids),
        "selection": "explicit exact names" if requested else "automatic leaf-name subset",
    }
    if result["selected_records"] == 0:
        raise EvidenceError("VCD: selected signals have no value records")
    result["windows"] = representative_windows(result)
    return result


def representative_windows(trace):
    signals = {s["name"].split(".")[-1]: s for s in trace["signals"]}
    clk = signals.get("clk", signals.get("clock"))
    clock_records = trace["changes"][clk["id"]] if clk else []
    gaps = [b[0] - a[0] for a, b in zip(clock_records, clock_records[1:]) if b[0] > a[0]]
    step = sorted(gaps)[len(gaps) // 2] if gaps else max(1, trace["end"] // 200)
    span = min(max(1, step * 24), trace["end"])
    windows = [{"label": "Initial interval", "start": 0, "end": span}]
    states, found = {}, set()
    events = {}
    for signal in trace["signals"]:
        for t, value in trace["changes"][signal["id"]]:
            events.setdefault(t, []).append((signal, value))
    previous_count = None
    for t, entries in sorted(events.items()):
        for signal, value in entries:
            states[signal["name"].split(".")[-1]] = value
        reset_leaf = next((name for name in ("rst_n", "reset_n", "reset", "rst") if name in signals), None)
        reset_on = states.get(reset_leaf) == ("0" if reset_leaf and reset_leaf.endswith("_n") else "1")
        clear = states.get("clear", states.get("clr")) == "1"
        enable = states.get("enable", states.get("en")) == "1"
        count = states.get("count")
        numeric = int(count, 2) if count and re.fullmatch("[01]+", count) else None
        labels = []
        if reset_on:
            labels.append("Reset asserted (name-based polarity)")
        if reset_on and clear and enable:
            labels.append("Reset + clear + enable (priority stimulus)")
        if not reset_on and clear and enable:
            labels.append("Clear + enable (priority stimulus)")
        if numeric is not None and previous_count is not None and numeric == previous_count + 1:
            labels.append("Observed count increase")
        if count and set(count) == {"1"} and states.get("overflow") == "1":
            labels.append("All-ones count + overflow (saturation candidate)")
        previous_count = numeric
        for label in labels:
            if label not in found:
                start = max(0, min(t - span // 3, trace["end"] - span))
                windows.append({"label": label, "start": start, "end": start + span})
                found.add(label)
    return windows


def mapping(value, label, issues):
    if not isinstance(value, dict):
        issues.append(f"{label}: expected an object, got {display(value)}")
        return {}
    return value


def objects(value, label, issues):
    if not isinstance(value, list) or any(not isinstance(v, dict) for v in value):
        issues.append(f"{label}: expected a list of objects")
        return []
    return value


def invocation_flow(dispatch, label, issues):
    """Draw recorded dispatches, not an inferred history of native stage results."""
    entries = objects(dispatch.get("dispatch_order"), f"{label} dispatch_order", issues)
    if not entries:
        return ('<p class="notice">No invocation sequence recorded. '
                'Agent retries, reasons and outcomes cannot be inferred from native stages.</p>')
    nodes, counts = [], {}
    for index, entry in enumerate(entries, 1):
        context = f"{label} dispatch_order[{index - 1}]"
        agent = source_attribution(entry, "agent" if "agent" in entry else "agent_type",
                                   f"{context} agent", issues)
        reason = source_attribution(entry, "reason", f"{context} reason", issues)
        outcome = source_attribution(entry, "outcome", f"{context} outcome", issues)
        status_key = "status" if "status" in entry else "reported_status"
        status = normalize_status(source_attribution(entry, status_key,
                                                    f"{context} status", issues))
        if agent != "not recorded":
            counts[agent] = counts.get(agent, 0) + 1
        nodes.append(
            f'<li class="invocation-node {status.lower().replace(" ", "-")}">'
            f'<div class="invocation-heading"><span class="invocation-number">{index}</span>'
            f'<h3>{esc(agent)}</h3>{badge(status)}</div>'
            f'<p><b>Why:</b> {esc(reason)}</p><p><b>Outcome:</b> {esc(outcome)}</p></li>')
    scope = source_attribution(dispatch, "scope", f"{label} scope", issues)
    totals = "; ".join(f"{agent}: {count}" for agent, count in counts.items())
    return (
        f'<p><b>{len(entries)} recorded invocations</b>'
        f'{esc(" | " + totals) if totals else ""}</p>'
        f'<p class="source">Recorded scope: {esc(scope)}. List order is dispatch order, '
        'not inferred timestamps or duration. Only supplied entries are counted; missing history '
        'is not reconstructed. Parent-recorded attribution is not an activation audit or native signoff.</p>'
        '<ol class="invocation-flow" aria-label="Recorded agent invocations in dispatch order">'
        + "".join(nodes) + '</ol>')


def number(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and abs(value) <= SAFE_INTEGER and math.isfinite(value))


def bars(items, unit):
    if not items:
        return '<p class="muted">No measured numeric data recorded.</p>'
    maximum = max((value for _, value, _ in items), default=0) or 1
    rows = []
    for label, value, basis in items:
        rows.append(f'<div class="bar-row" title="{esc(basis)}"><span>{esc(label)}</span>'
                    f'<div class="bar-track"><i style="width:{max(0, value / maximum * 100):.5f}%"></i></div>'
                    f'<b>{esc(value)} {esc(unit)}</b><small>{esc(basis)}</small></div>')
    return "".join(rows)


def value_table(values, source):
    return ('<table><thead><tr><th>Field</th><th>Recorded value</th></tr></thead><tbody>'
            + "".join(f'<tr><td>{esc(k)}</td><td><code>{esc(display(v))}</code></td></tr>'
                      for k, v in values.items())
            + f'</tbody></table><p class="source">{esc(source)}</p>')


def static_wave(trace):
    """Initial SVG also works with JavaScript disabled."""
    start, end = trace["windows"][0]["start"], trace["windows"][0]["end"]
    width, left, lane = 1100, 170, 52
    height = 50 + lane * len(trace["signals"])
    scale = (width - left - 15) / max(1, end - start)
    parts = [f'<svg id="wave-svg" role="img" aria-label="Actual VCD digital timing diagram" '
             f'viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg">']
    for tick in range(6):
        t = start + (end - start) * tick // 5
        x = left + (t - start) * scale
        parts.append(f'<path class="grid" d="M{x} 28V{height}"/>'
                     f'<text x="{x}" y="18">{t}</text>')
    for index, signal in enumerate(trace["signals"]):
        y = 52 + lane * index
        parts.append(f'<text x="8" y="{y + 6}">{esc(signal["name"])}</text>')
        records = trace["changes"][signal["id"]]
        pos = bisect_right([r[0] for r in records], start)
        value = records[pos - 1][1] if pos else "unrecorded"
        cursor = start
        segments = []
        for t, new in records[pos:]:
            if t > end:
                break
            segments.append((cursor, t, value))
            cursor, value = t, new
        segments.append((cursor, end, value))
        for a, b, value in segments:
            x1, x2 = left + (a - start) * scale, left + (b - start) * scale
            unknown = not re.fullmatch("[01]+", value)
            color = "#f4af59" if unknown else "#5ce0c3"
            title = esc(f'{signal["name"]}: {value}; [{a}, {b}] ticks x {trace["timescale"]}')
            if signal["width"] == 1 and not unknown:
                level = y - 10 if value == "1" else y + 10
                parts.append(f'<path stroke="{color}" d="M{x1} {level}H{x2}">'
                             f'<title>{title}</title></path>')
            else:
                label = value if unknown else f"0x{int(value, 2):X}"
                inset = min(3, max(0, (x2 - x1) / 2))
                parts.append(f'<path stroke="{color}" d="M{x1} {y}l{inset} -11H{x2 - inset}'
                             f'L{x2} {y}l{-inset} 11H{x1 + inset}Z">'
                             f'<title>{title}</title></path>')
                if x2 - x1 > 40:
                    parts.append(f'<text x="{x1 + 5}" y="{y + 4}">{esc(label)}</text>')
        collisions = {}
        previous = records[pos - 1][1] if pos else None
        for t, new in records[bisect_right([r[0] for r in records], start - 1):]:
            if t > end:
                break
            x = left + (t - start) * scale
            pixel = int(x)
            collisions[pixel] = collisions.get(pixel, 0) + 1
            if signal["width"] == 1 and previous in {"0", "1"} and new in {"0", "1"} and previous != new and t > start:
                parts.append(f'<path stroke="#5ce0c3" d="M{x} {y - 10}V{y + 10}">'
                             f'<title>{esc(signal["name"])} recorded edge at {t} ticks</title></path>')
            previous = new
        for pixel, count in collisions.items():
            if count > 1:
                parts.append(f'<path class="density" d="M{pixel} {y - 17}V{y + 17}">'
                             f'<title>{count} records share this pixel; zoom or inspect native VCD</title></path>')
    return "".join(parts) + "</svg>"


def render(run, output, vcd_reference=None, signals=None, max_vcd_bytes=32 * 1024 * 1024,
           max_changes=1_000_000):
    run, output = Path(run).resolve(), Path(output).resolve()
    if not run.is_dir():
        raise EvidenceError(f"Run directory does not exist: {run}")
    if output.exists():
        raise EvidenceError(f"Refusing to overwrite: {output}")
    issues, consumed, links = [], {}, {}

    def reference(path):
        return str(path.relative_to(run)).replace("\\", "/")

    def read(reference_value, kind="json", limit=MAX_TEXT):
        try:
            path = confined(run, reference_value)
            raw = read_text(path, limit)
            data = (object_json(raw, path.name) if kind == "json" else
                    decode_json(raw, path.name) if kind == "json_value" else raw)
            consumed[reference(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
            links[reference(path)] = path
            return data
        except (OSError, EvidenceError) as exc:
            issues.append(f"{reference_value}: {exc}")
            return None

    def link(path, label=None):
        href = quote(os.path.relpath(path, output.parent).replace("\\", "/"), safe="/.")
        return f'<a href="{esc(href)}">{esc(label or reference(path))}</a>'

    summary = read("results.json") or {}
    narrative = read("results.md", "text")
    stages = objects(summary.get("stages"), "results.json stages", issues)
    artifacts = mapping(summary.get("artifacts"), "results.json artifacts", issues)
    coverage = mapping(summary.get("coverage", {}), "results.json coverage", issues)
    workflow = source_attribution(summary, "workflow_status", "results.json workflow_status", issues)
    for label, value in artifacts.items():
        try:
            path = confined(run, value)
            if not path.is_file():
                raise EvidenceError("missing artifact")
            links[reference(path)] = path
        except (OSError, EvidenceError) as exc:
            issues.append(f"Artifact {label}: {exc}")

    attribution = ""
    invocation_diagram = (
        '<p class="notice">No readable dispatch record supplied. Agent invocation order, retries, '
        'reasons and outcomes are not recorded; native stage results are shown separately below.</p>')
    dispatch_name = artifact_reference(artifacts, "dispatch_record", run, issues)
    if dispatch_name:
        dispatch = read(dispatch_name)
        if dispatch is not None:
            invocation_diagram = invocation_flow(dispatch, dispatch_name, issues)
            attribution = (
                '<details><summary>Agent dispatch outcomes (parent-recorded; not an activation audit)</summary>'
                '<p>Dispatch outcomes do not establish who executed native tools. '
                'Blocked dispatches remain distinct from the native fallback results above.</p>'
                f'<pre>{esc(json.dumps(dispatch, indent=2))}</pre></details>')

    audits = []
    for path in sorted(run.glob("attempt-*/smoke-test.json")):
        audit = read(reference(path))
        if audit is not None:
            audits.append((reference(path), audit))
    if not audits and not any("execution_evidence" in stage for stage in stages):
        issues.append("No readable attempt-*/smoke-test.json audit; attempts/activation unverified")

    cdes = {}
    for path in sorted(run.glob("attempt-*/*/output/common_design_envelope.json")):
        cdes[reference(path)] = read(reference(path))
    for stage in stages:
        if not stage.get("cde"):
            issues.append(f"{stage.get('stage', 'unnamed')}: no native CDE reference")
        elif isinstance(stage["cde"], str) and stage["cde"] not in cdes:
            cdes[stage["cde"]] = read(stage["cde"])
        elif not isinstance(stage["cde"], str):
            issues.append("Stage CDE reference must be a string")

    native_cards, runtimes = [], []
    cde_statuses = {}
    for name, cde in cdes.items():
        if cde is None:
            continue
        validation = mapping(cde.get("validation", {}), f"{name} validation", issues)
        progress = mapping(cde.get("progress", {}), f"{name} progress", issues)
        signoff = mapping(cde.get("signoff_evidence", {}), f"{name} signoff_evidence", issues)
        results = mapping(cde.get("results", {}), f"{name} results", issues)
        provenance = mapping(cde.get("provenance", {}), f"{name} provenance", issues)
        runtime = mapping(provenance.get("runtime", {}), f"{name} runtime", issues)
        verdicts = [v for v in (cde.get("verdict"), validation.get("verdict"),
                               progress.get("verdict_normalized"), signoff.get("verdict"))
                    if v is not None]
        if normalize_status(cde.get("status")) in {"FAIL", "BLOCKED", "SKIPPED", "NOT RUN"}:
            verdicts.append(cde["status"])
        normalized = [normalize_status(v) for v in verdicts]
        status = next((s for s in ("FAIL", "BLOCKED", "UNKNOWN", "SKIPPED", "NOT RUN")
                       if s in normalized), "PASS" if normalized else "UNKNOWN")
        if len(set(normalized)) > 1:
            issues.append(f"{name}: contradictory native verdict fields {verdicts}")
        cde_statuses[name] = status
        if status != "PASS":
            issues.append(f"{name}: native verdict {status}; raw lifecycle {cde.get('status')!r}")
        if status == "PASS" and (progress.get("gate_closed") is False
                                 or validation.get("stage_closure_eligible") is False):
            issues.append(f"{name}: PASS contradicts explicit native closure ineligibility")
        if "native_exit_codes" in signoff and not zero_exits(signoff["native_exit_codes"]):
            issues.append(f"{name}: missing, malformed or nonzero native_exit_codes")
        if "sources_unchanged" in signoff and signoff["sources_unchanged"] is not True:
            issues.append(f"{name}: native sources_unchanged is not true")
        if not results:
            issues.append(f"{name}: no native result metrics recorded")
        measured = {}
        for key, entry in results.items():
            if not isinstance(entry, dict) or "value" not in entry:
                issues.append(f"{name}: malformed metric {key}")
                continue
            measured[key] = entry
            if status == "PASS" and entry.get("class") == "gating":
                value, closes = entry["value"], str(entry.get("closes_at", "")).strip()
                if (value is None or (closes == "== true" and value is not True)
                        or (closes == "== 0" and (not number(value) or value != 0))
                        or (closes == "> 0" and (not number(value) or value <= 0))):
                    issues.append(f"{name}: PASS contradicts gating {key}={display(value)}")
        elapsed = runtime.get("elapsed_seconds")
        if elapsed is not None:
            if number(elapsed) and elapsed >= 0:
                runtimes.append((name.split("/")[0] + " / " + str(cde.get("stage", "?")),
                                 elapsed, f"{name}: provenance.runtime.elapsed_seconds"))
            else:
                issues.append(f"{name}: invalid elapsed_seconds {elapsed!r}")
        native_cards.append(f'<details><summary>{esc(name)} {badge(status)}</summary>'
                            f'<p>Raw lifecycle: <code>{esc(cde.get("status", "not recorded"))}</code>. '
                            f'Finished: {esc(provenance.get("finished_utc", "not recorded"))}.</p>'
                            + value_table(measured, f"{name}: results (value, unit, basis and class)")
                            + f'<pre>{esc(json.dumps(cde, indent=2))}</pre></details>')

    stage_rows, stage_statuses = [], []
    for stage in stages:
        reported = normalize_status(stage.get("status"))
        stage_statuses.append(reported)
        cde_name = stage.get("cde")
        actual = cde_statuses.get(cde_name, "UNKNOWN") if isinstance(cde_name, str) else "UNKNOWN"
        if reported != "PASS" or actual != reported:
            issues.append(f"{stage.get('stage')}: summary {reported}, native {actual}")
        cde = cdes.get(cde_name) if isinstance(cde_name, str) else None
        if cde:
            for key, metric in cde.get("results", {}).items() if isinstance(cde.get("results"), dict) else []:
                if isinstance(metric, dict) and "value" in metric and key in stage:
                    if type(stage[key]) is not type(metric.get("value")) or stage[key] != metric["value"]:
                        issues.append(f"{stage.get('stage')}: summary/native metric mismatch: {key}")
        if "exit_code" in stage and (type(stage["exit_code"]) is not int or stage["exit_code"] != 0):
            issues.append(f"{stage.get('stage')}: nonzero exit_code={stage['exit_code']}")
        fields = {k: v for k, v in stage.items() if k not in {"stage", "status", "cde"}}
        executor = source_attribution(stage, "executor", f"{stage.get('stage')} executor", issues)
        native_link = link(confined(run, cde_name), "Native envelope") if isinstance(cde_name, str) and cde_name in cde_statuses else "Missing"
        stage_rows.append(f'<tr><td><b>{esc(stage.get("stage", "unnamed"))}</b><br>'
                          f'<small>{esc(stage.get("operation", "not recorded"))}</small>'
                          f'<small>Executor (source-reported): {esc(executor)}</small></td>'
                          f'<td>{badge(reported)}<small>Summary</small></td>'
                          f'<td>{badge(actual)}<small>{native_link}</small></td>'
                          f'<td><details><summary>Recorded metrics / provenance</summary>'
                          f'{value_table(fields, "results.json: stages")}</details></td></tr>')

    attempt_cards = []
    activation = []
    previous_finish, ordered_digest = None, None
    execution_count = 0
    if summary.get("execution_mode") == "ordered":
        for field in ("stage", "cde"):
            values = [stage.get(field) for stage in stages]
            if any(not isinstance(value, str) or not value.strip() for value in values) or len(set(
                    value for value in values if isinstance(value, str))) != len(values):
                issues.append(f"Ordered execution requires distinct nonempty {field} references")
    for stage in stages:
        cde_name = stage.get("cde")
        cde = cdes.get(cde_name) if isinstance(cde_name, str) else None
        if "execution_evidence" in stage or not audits or summary.get("execution_mode") == "ordered":
            digest = check_execution(stage, cde, read, run, consumed, summary, issues)
            if isinstance(stage.get("execution_evidence"), dict) and stage["execution_evidence"]:
                execution_count += 1
            attempt_cards.append(
                f'<details><summary>{esc(stage.get("stage", "unnamed"))}: execution evidence references</summary>'
                + value_table(stage.get("execution_evidence", {}) if isinstance(stage.get("execution_evidence"), dict) else {},
                              "results.json references; invocation/exit/native RTL hashes checked; not an agent activation audit")
                + '</details>')
            if summary.get("execution_mode") == "ordered":
                if ordered_digest is not None and digest != ordered_digest:
                    issues.append(f"{stage.get('stage')}: ordered stages do not use identical RTL")
                ordered_digest = digest
        if summary.get("execution_mode") == "ordered":
            provenance = cde.get("provenance", {}) if cde else {}
            provenance = provenance if isinstance(provenance, dict) else {}
            runtime = provenance.get("runtime", {})
            runtime = runtime if isinstance(runtime, dict) else {}
            try:
                start = recorded_time(runtime.get("started_utc"))
                finish = recorded_time(provenance.get("finished_utc"))
                if finish < start or (previous_finish is not None and start < previous_finish):
                    raise EvidenceError("native stage timestamps contradict ordered execution")
                previous_finish = finish
            except EvidenceError as exc:
                issues.append(f"{stage.get('stage')}: {exc}")
    for name, audit in audits:
        activation.append(f'{name}: {display(audit.get("agent_activation", "unverified"))}')
        audit_stages = objects(audit.get("stages"), f"{name} stages", issues)
        for stage in audit_stages:
            status = normalize_status(stage.get("status"))
            if status != "PASS" or ("exit_code" in stage and
                                     (type(stage["exit_code"]) is not int or stage["exit_code"] != 0)):
                issues.append(f"{name}: {stage.get('stage')} attempt {stage.get('attempt')} "
                              f"status={status}, exit={stage.get('exit_code', 'not recorded')}")
        if normalize_status(audit.get("status")) != "PASS":
            issues.append(f"{name}: audit overall status={normalize_status(audit.get('status'))}")
        attempt_cards.append(f'<details><summary>{esc(name)} {badge(audit.get("status"))}</summary>'
                             f'<p>Host audit start: {esc(audit.get("started_utc", "not recorded"))}. '
                             'duration_s below is host wall time, not circuit timing.</p>'
                             + value_table({f'{s.get("stage", "?")} / attempt {s.get("attempt", "?")}': {
                                 k: s[k] for k in ("status", "exit_code", "duration_s", "measured") if k in s
                             } for s in audit_stages}, name)
                             + f'<pre>{esc(json.dumps(audit, indent=2))}</pre></details>')
    if not stages:
        issues.append("No native summary stages recorded")
    reported_overall = normalize_status(summary.get("status"))
    if reported_overall == "UNKNOWN":
        issues.append("Overall reported verdict is unknown or absent")
    if reported_overall == "PASS" and any(s != "PASS" for s in stage_statuses):
        issues.append("Overall PASS contradicts non-PASS stage status")
    unexecuted = summary.get("unexecuted_stages", [])
    if unexecuted:
        issues.append(f"Unexecuted stages: {display(unexecuted)}")

    trace = None
    vcd_name = vcd_reference or artifact_reference(artifacts, "waveform", run, issues)
    if not vcd_name:
        candidates = sorted(run.glob("attempt-*/*/output/results/*.vcd"))
        if len(candidates) == 1:
            vcd_name = reference(candidates[0])
        else:
            issues.append("No unambiguous VCD selected; supply --vcd with a run-relative path")
    if vcd_name:
        raw_vcd = read(vcd_name, "text", max_vcd_bytes)
        if raw_vcd is not None:
            try:
                trace = parse_vcd(raw_vcd, signals, max_changes)
                trace["source"] = vcd_name
                if trace["end"] == 0:
                    trace = None
                    raise EvidenceError("VCD has tick-zero values only; no positive-duration timing interval")
            except EvidenceError as exc:
                trace = None
                issues.append(f"{vcd_name}: {exc}")

    log_name = artifact_reference(artifacts, "simulation_log", run, issues)
    log = read(log_name, "text") if log_name else None
    if log is None:
        issues.append("Simulation log unavailable; final marker/comparisons not independently cross-checked")
    else:
        verification = []
        for stage in stages:
            cde_name = stage.get("cde")
            cde = cdes.get(cde_name) if isinstance(cde_name, str) else None
            metrics = cde.get("results", {}) if cde else {}
            metrics = metrics if isinstance(metrics, dict) else {}
            if "sim_passed" in stage or "sim_passed" in metrics:
                verification.append((stage, metrics))
        if len(verification) != 1:
            issues.append("Simulation log requires exactly one identifiable native simulation stage")
        if re.search(r"\b(?:TEST FAILED|FATAL|ERROR)\b", log, re.I):
            issues.append("Simulation log contains failure diagnostics despite summary PASS")
        lines = [line.strip() for line in log.splitlines()]
        if "TEST PASSED" not in lines:
            issues.append("Simulation log missing exact TEST PASSED marker")
        for field, regex in (("comparisons", r"\bCOMPARISONS=(\d+)\b"),
                             ("mismatches", r"\bMISMATCHES=(\d+)\b")):
            matches = list(re.finditer(regex, log))
            values = [int(match[1]) for match in matches]
            markers = list(re.finditer(r"(?m)^[ \t]*TEST PASSED[ \t]*\r?$", log))
            if matches and markers and markers[-1].start() < matches[-1].start():
                issues.append(f"Simulation log final TEST PASSED precedes final {field}")
            if not values or (field == "comparisons" and values[-1] <= 0) or (field == "mismatches" and any(values)):
                issues.append(f"Simulation log missing or unsuccessful {field}")
            expected = [(f"coverage.{field}", coverage[field])] if field in coverage else []
            for stage, metrics in verification:
                if field in stage:
                    expected.append((f"stage {field}", stage[field]))
                if field in metrics and isinstance(metrics[field], dict):
                    expected.append((f"native {field}", metrics[field].get("value")))
            if not expected:
                issues.append(f"Simulation log has no recorded summary/native {field} to cross-check")
            for source, value in expected:
                if type(value) is not int or not values or value != values[-1]:
                    issues.append(f"Simulation log disagrees with/misses summary/native {source}")
        for stage, metrics in verification:
            sim_passed = metrics.get("sim_passed")
            if not isinstance(sim_passed, dict) or sim_passed.get("value") is not True:
                issues.append("Native simulation sim_passed is not true")
            marker = stage.get("final_marker")
            if marker is not None and (not isinstance(marker, str) or marker not in lines):
                issues.append("Simulation log missing exact reported final marker")

    coverage_items = [(key, value, f"results.json: coverage.{key}")
                      for key, value in coverage.items() if number(value) and value >= 0]
    for key, value in coverage.items():
        if isinstance(value, (int, float)) and not isinstance(value, bool) and (not number(value) or value < 0):
            issues.append(f"coverage.{key}: invalid or out-of-range chart counter {value!r}; raw value retained")
    limitations = summary.get("limitations", [])
    if not isinstance(limitations, list):
        issues.append("results.json limitations: expected a list")
        limitations = [limitations]
    limitations = [*limitations,
                   "Reported evidence is not a new signoff. No rerun or specialist activation was performed.",
                   "Recorded elapsed seconds are tool/process duration, not circuit timing.",
                   "Waveform windows show observed patterns, not independently measured functional coverage.",
                   "Representative reset polarity is inferred from signal names (_n = active low); priority is not proven by a plot.",
                   "Relative source links require the original run to remain in place. Imported narrative is shown verbatim as text."]
    if trace:
        wave_body = (f'<p><b>{esc(trace["timescale"])} per tick</b> &middot; '
                     f'0 &ndash; {trace["end"]:,} ticks &middot; '
                     f'{trace["selected_records"]:,} selected value records / '
                     f'{trace["total_records"]:,} total. {link(confined(run, vcd_name), "Native VCD")}</p>'
                     f'<p class="muted">Selection: {esc(trace["selection"])}; '
                     f'{len(trace["signals"])} of {len(trace["declarations"])} declarations. '
                     'All selected records retained; no downsampling. Other declarations/aliases are listed in embedded data.</p>'
                     '<div id="wave-controls" hidden><label>Window <select id="presets"></select></label>'
                     '<label>Start tick <input id="start" type="number" min="0" step="1"></label>'
                     '<label>End tick <input id="end" type="number" min="1" step="1"></label>'
                     '<button id="apply">Apply</button><button id="zoom-in">Zoom +</button>'
                     '<button id="zoom-out">Zoom -</button><button id="pan-left">Earlier</button>'
                     '<button id="pan-right">Later</button><button id="full">Full trace</button>'
                     '<label>Position <input id="position" type="range" min="0" max="1000" value="0"></label></div>'
                     '<p id="wave-note" role="status">Initial interval shown. Enable JavaScript for zoom/pan. '
                     'Dense or same-time transitions may overlap; inspect the native VCD for exact ordering.</p>'
                     f'<div class="wave">{static_wave(trace)}</div>'
                     '<p class="muted">Bus labels: hexadecimal for known bits; binary X/Z otherwise. '
                     'Orange = unknown, high impedance, or unresolved transition density. Hover for raw bits and exact tick intervals.</p>'
                     '<noscript><p>JavaScript is disabled: static initial waveform only; native VCD contains the complete trace.</p></noscript>')
    else:
        wave_body = ('<div class="notice">Waveform unavailable: missing, empty, unsupported or malformed VCD. '
                     'No synthetic waveform substituted. See evidence issues below.</div>')

    review = "ISSUES PRESENT" if issues else "CONSISTENT EVIDENCE"
    issue_html = "".join(f"<li>{esc(item)}</li>" for item in dict.fromkeys(issues))
    fragments = {
        "TITLE": esc(summary.get("run_id", run.name)),
        "REPORTED": badge(reported_overall),
        "REVIEW": esc(review),
        "REVIEW_CLASS": "fail" if issues else "pass",
        "ACTIVATION": esc("; ".join(activation) or "unverified; recorded tool execution is not agent activation"),
        "EXECUTION": esc(summary.get("execution_mode", "not recorded")),
        "WORKFLOW": esc(workflow),
        "ATTRIBUTION": attribution,
        "INVOCATIONS": invocation_diagram,
        "ATTEMPTS": esc(f'Initial: {display(summary.get("initial_attempts", "not recorded"))}; '
                        f'corrective: {display(summary.get("corrective_attempts", "not recorded"))}; '
                        f'audits found: {len(audits)}; explicit stage execution records: {execution_count}'),
        "STAGES": "".join(stage_rows) or '<tr><td colspan="4">No stages recorded; UNKNOWN.</td></tr>',
        "TIMING": bars(runtimes, "s"),
        "COVERAGE": bars(coverage_items, "count") + value_table(coverage, "results.json: coverage; counters may overlap, no percentage denominator"),
        "WAVE": wave_body,
        "NARRATIVE": esc(narrative if narrative is not None else "results.md unavailable"),
        "LOG": esc(log if log is not None else "Simulation log unavailable"),
        "NATIVE": "".join(native_cards) or "<p>No readable native envelopes.</p>",
        "AUDITS": "".join(attempt_cards) or "<p>No readable attempt audits.</p>",
        "ISSUES": f"<ul>{issue_html}</ul>" if issues else "<p>No evidence inconsistencies detected by the supported checks. This is not engineering acceptance.</p>",
        "LIMITATIONS": "".join(f"<li>{esc(display(item))}</li>" for item in limitations),
        "ARTIFACTS": "".join(f"<li>{link(path)}</li>" for _, path in sorted(links.items())),
        "SUMMARY": esc(json.dumps(summary, indent=2)),
        "HASHES": value_table(consumed, "SHA256 of files read by this renderer; not a certification of supplied source hashes"),
        "DATA": script_json(trace),
    }
    template = (ROOT / "templates" / "report.html").read_text(encoding="utf-8")
    result = re.sub(r"@@([A-Z_]+)@@", lambda m: fragments[m[1]], template)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(result)
    return {"output": str(output), "reported_status": reported_overall, "evidence_issues": issues,
            "waveform_records": trace["selected_records"] if trace else 0,
            "waveform_windows": trace["windows"] if trace else [],
            "activation": "chip-report-gen runtime discovery/activation unverified"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--output", type=Path, help="new HTML filename; never overwritten")
    parser.add_argument("--vcd", help="run-relative VCD path")
    parser.add_argument("--signals", help="comma-separated exact scoped names, at most 12")
    parser.add_argument("--max-vcd-bytes", type=int, default=32 * 1024 * 1024)
    parser.add_argument("--max-changes", type=int, default=1_000_000)
    args = parser.parse_args(argv)
    if args.max_vcd_bytes < 1 or args.max_changes < 1:
        parser.error("resource limits must be positive")
    output = args.output
    if output is None:
        run = args.run_dir.resolve()
        if run.parent.name != "results":
            parser.error("--output is required outside the project results convention")
        unique = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
        output = run.parent / f"chip-report-gen-{unique}" / "report.html"
    try:
        result = render(args.run_dir, output, args.vcd,
                        args.signals.split(",") if args.signals else None,
                        args.max_vcd_bytes, args.max_changes)
    except (OSError, EvidenceError) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 2 if result["evidence_issues"] else 0


if __name__ == "__main__":
    sys.exit(main())
