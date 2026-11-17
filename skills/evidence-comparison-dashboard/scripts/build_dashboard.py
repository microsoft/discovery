#!/usr/bin/env python3
"""Build and verify a self-contained evidence comparison dashboard.

Standard library only; no network access. Every record must carry an http(s)
source link, missing values are shown as "not reported" and never guessed, and
`verify` re-reads the generated HTML and compares it with a fresh build of the input, using
settings (missing tokens, columns) given by the caller rather than read from the page.

    build_dashboard.py build INPUT.json --out dashboard.html [--columns a,b] [--missing-token NA]
    build_dashboard.py verify INPUT.json dashboard.html [--columns a,b] [--missing-token NA]
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import html
import json
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

VERSION = "1.0.0"
NOT_REPORTED = "not reported"
NOT_RECORDED = "not recorded"
MAX_SELECT_VALUES = 12

STYLE = """
body{font-family:system-ui,sans-serif;margin:1.5rem;color:#1b1b1b}
h1{font-size:1.4rem;margin:0 0 .25rem}
.meta,.note{color:#505050;font-size:.85rem;margin:.25rem 0}
.controls{display:flex;flex-wrap:wrap;gap:.75rem;align-items:end;margin:1rem 0}
.controls label{display:flex;flex-direction:column;font-size:.8rem;gap:.15rem}
table{border-collapse:collapse;width:100%;font-size:.9rem}
th,td{border:1px solid #c8c8c8;padding:.35rem .5rem;text-align:left;vertical-align:top}
thead th{background:#f0f0f0}
td.missing{color:#7a3b00;background:#fff4e5;font-style:italic}
a{color:#0b5cad}
.coverage{margin-top:1.5rem;max-width:34rem}
""".strip()

SCRIPT = """
(function(){
var rows=[].slice.call(document.querySelectorAll('tbody tr[data-id]'));
var q=document.getElementById('q');
var complete=document.getElementById('complete');
var count=document.getElementById('count');
var selects=[].slice.call(document.querySelectorAll('select[data-field]'));
function apply(){
var needle=q.value.toLowerCase();var shown=0;
rows.forEach(function(row){
var ok=true;
if(needle&&row.textContent.toLowerCase().indexOf(needle)<0){ok=false;}
if(ok&&complete.checked&&row.querySelector('td[data-missing="true"]')){ok=false;}
selects.forEach(function(sel){
if(!ok||sel.value==='all'){return;}
var cell=null;
for(var i=0;i<row.cells.length;i++){if(row.cells[i].dataset.field===sel.dataset.field){cell=row.cells[i];}}
if(!cell){ok=false;return;}
var missing=cell.dataset.missing==='true';
if(sel.value==='missing'){ok=missing;}else{ok=!missing&&sel.value==='v:'+cell.textContent;}
});
row.hidden=!ok;
if(ok){shown++;}
});
count.textContent='Showing '+shown+' of '+rows.length+' records';
}
q.addEventListener('input',apply);
complete.addEventListener('change',apply);
selects.forEach(function(sel){sel.addEventListener('change',apply);});
apply();
})();
""".strip()


class InputError(Exception):
    def __init__(self, problems):
        super().__init__("; ".join(problems))
        self.problems = problems


def _reject_constant(name):
    raise ValueError(f"{name} is not allowed; use null for unknown values")


def _no_duplicate_keys(pairs):
    seen = {}
    for key, value in pairs:
        if key in seen:
            raise ValueError(f"duplicate JSON key {key!r}")
        seen[key] = value
    return seen


def load_json(path):
    raw = Path(path).read_bytes()
    try:
        data = json.loads(
            raw.decode("utf-8"),
            parse_constant=_reject_constant,
            object_pairs_hook=_no_duplicate_keys,
        )
    except (UnicodeDecodeError, ValueError) as exc:
        raise InputError([f"input is not valid UTF-8 JSON: {exc}"])
    return data, hashlib.sha256(raw).hexdigest()


def cell_text(value, missing_tokens):
    """Return the text shown for a value, or None when the value is missing."""
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped or stripped.casefold() in missing_tokens:
            return None
        return value
    if isinstance(value, list):
        if not value:
            return None
        parts = []
        for item in value:
            if isinstance(item, bool) or not isinstance(item, (str, int, float)):
                raise ValueError("lists may contain only strings and numbers")
            if isinstance(item, str) and not item.strip():
                raise ValueError("lists must not contain empty strings")
            parts.append(repr(item) if isinstance(item, float) else str(item))
        return "; ".join(parts)
    raise ValueError("values must be scalars or lists of scalars; flatten nested objects first")


def valid_source_url(url):
    if not isinstance(url, str) or not url or any(c.isspace() or ord(c) < 32 for c in url):
        return False
    try:
        parts = urlsplit(url)
    except ValueError:  # for example an unclosed IPv6 bracket
        return False
    return parts.scheme in ("http", "https") and bool(parts.netloc)


def clean_tokens(tokens):
    """Normalize missing-value tokens the same way for build and verify."""
    return sorted({t.strip().casefold() for t in (tokens or []) if t.strip()})


def _text_or_empty(value):
    return value if isinstance(value, str) else ""


def normalize(data, missing_tokens=(), columns=None):
    """Validate input and return the display model. Raises InputError with every problem."""
    tokens = set(clean_tokens(missing_tokens))
    problems = []
    if isinstance(data, list):
        data = {"records": data}
    if not isinstance(data, dict):
        raise InputError(["top level must be an object with 'records', or a list of records"])
    records = data.get("records")
    if not isinstance(records, list) or not records:
        raise InputError(["'records' must be a non-empty list"])

    model_records, seen_ids, first_seen = [], set(), []
    for index, record in enumerate(records, start=1):
        where = f"record {index}"
        if not isinstance(record, dict):
            problems.append(f"{where}: must be an object")
            continue
        rid = record.get("id")
        if not isinstance(rid, str) or not rid.strip():
            problems.append(f"{where}: 'id' must be a non-empty string")
            continue
        where = f"record {rid!r}"
        if rid in seen_ids:
            problems.append(f"{where}: duplicate id")
        seen_ids.add(rid)
        if not valid_source_url(record.get("source_url")):
            problems.append(f"{where}: 'source_url' is required and must be an http(s) link")
        fields = record.get("fields", {})
        if not isinstance(fields, dict):
            problems.append(f"{where}: 'fields' must be an object")
            continue
        cells = {}
        for name, value in fields.items():
            if not isinstance(name, str) or not name.strip():
                problems.append(f"{where}: field names must be non-empty strings")
                continue
            try:
                cells[name] = cell_text(value, tokens)
            except ValueError as exc:
                problems.append(f"{where}, field {name!r}: {exc}")
            if name not in first_seen:
                first_seen.append(name)
        for key in ("label", "source_tool", "retrieved_at"):
            if key in record and not isinstance(record[key], str):
                problems.append(f"{where}: {key!r} must be a string")
        label = _text_or_empty(record.get("label"))
        model_records.append({
            "id": rid,
            "label": label if label.strip() else rid,
            "source_url": record.get("source_url"),
            "source_tool": _text_or_empty(record.get("source_tool")),
            "retrieved_at": _text_or_empty(record.get("retrieved_at")),
            "cells": cells,
        })

    declared = columns if columns is not None else data.get("columns")
    labels = {}
    if declared is None:
        shown = list(first_seen)
    else:
        shown = []
        if not isinstance(declared, list) or not declared:
            problems.append("'columns' must be a non-empty list")
            declared = []
        for item in declared:
            if isinstance(item, str):
                field, label = item, item
            elif isinstance(item, dict) and isinstance(item.get("field"), str):
                field, label = item["field"], item.get("label") or item["field"]
            else:
                problems.append(f"invalid column entry {item!r}")
                continue
            if field in shown:
                problems.append(f"column {field!r} is listed twice")
                continue
            shown.append(field)
            labels[field] = str(label)
    if not shown and not problems:
        problems.append("no fields to display; records need a non-empty 'fields' object")
    if problems:
        raise InputError(problems)

    for record in model_records:
        record["cells"] = {f: record["cells"].get(f) for f in shown}
    return {
        "title": str(data.get("title") or "Evidence comparison"),
        "dataset": data.get("dataset") if isinstance(data.get("dataset"), dict) else {},
        "columns": [{"field": f, "label": labels.get(f, f)} for f in shown],
        "omitted_fields": [f for f in first_seen if f not in shown],
        "records": model_records,
    }


def _hash_token(text):
    return "'sha256-" + base64.b64encode(hashlib.sha256(text.encode("utf-8")).digest()).decode() + "'"


def esc(text):
    return html.escape(str(text), quote=True)


def coverage(model):
    total = len(model["records"])
    result = {}
    for column in model["columns"]:
        reported = sum(1 for r in model["records"] if r["cells"][column["field"]] is not None)
        result[column["field"]] = {"reported": reported, "missing": total - reported, "total": total}
    return result


def render(model, build_meta):
    columns, records = model["columns"], model["records"]
    dataset = model["dataset"]
    head = ['<th scope="col">Record (links to source)</th>']
    head += [f'<th scope="col" data-field="{esc(c["field"])}">{esc(c["label"])}</th>' for c in columns]
    head.append('<th scope="col">Provenance</th>')

    body = []
    for record in records:
        cells = [
            f'<th scope="row" data-role="record"><a href="{esc(record["source_url"])}" '
            f'rel="noopener noreferrer nofollow">{esc(record["label"])}</a></th>'
        ]
        for column in columns:
            text = record["cells"][column["field"]]
            field = esc(column["field"])
            if text is None:
                cells.append(f'<td class="missing" data-field="{field}" data-missing="true">{NOT_REPORTED}</td>')
            else:
                cells.append(f'<td data-field="{field}" data-missing="false">{esc(text)}</td>')
        tool = record["source_tool"] or NOT_RECORDED
        when = record["retrieved_at"] or NOT_RECORDED
        cells.append(f'<td data-role="provenance">{esc(tool)}; retrieved {esc(when)}</td>')
        body.append(f'<tr data-id="{esc(record["id"])}">{"".join(cells)}</tr>')

    controls = []
    for column in columns:
        column_values = [r["cells"][column["field"]] for r in records]
        values = sorted({v for v in column_values if v is not None})
        has_missing = any(v is None for v in column_values)
        if not values or len(values) > MAX_SELECT_VALUES or (len(values) < 2 and not has_missing):
            continue
        options = ['<option value="all">All</option>']
        options += [f'<option value="v:{esc(v)}">{esc(v)}</option>' for v in values]
        if has_missing:
            options.append(f'<option value="missing">({NOT_REPORTED})</option>')
        controls.append(
            f'<label>{esc(column["label"])}<select data-field="{esc(column["field"])}">'
            f'{"".join(options)}</select></label>'
        )

    stats = coverage(model)
    cov_rows = "".join(
        f'<tr><th scope="row">{esc(c["label"])}</th>'
        f'<td>{stats[c["field"]]["reported"]} of {stats[c["field"]]["total"]} reported</td>'
        f'<td>{stats[c["field"]]["missing"]} not reported</td></tr>'
        for c in columns
    )
    meta_json = json.dumps(build_meta, sort_keys=True, ensure_ascii=True)
    dataset_bits = []
    if dataset.get("name"):
        dataset_bits.append(f'Dataset: {esc(dataset["name"])}')
    if dataset.get("license"):
        dataset_bits.append(f'License: {esc(dataset["license"])}')
    if dataset.get("synthetic") is True:
        dataset_bits.append("<strong>Synthetic data for demonstration only</strong>")
    csp = f"default-src 'none'; style-src {_hash_token(STYLE)}; script-src {_hash_token(SCRIPT)}"
    omitted = ""
    if model["omitted_fields"]:
        omitted = f'<p class="note">Fields in the input but not shown: {esc(", ".join(model["omitted_fields"]))}.</p>\n'
    title = esc(model["title"])
    head_html = "".join(head)
    controls_html = "".join(controls)
    body_html = "\n".join(body)
    dataset_html = " | ".join(dataset_bits)

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="{esc(csp)}">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="evidence-build" content="{esc(meta_json)}">
<title>{title}</title>
<style>{STYLE}</style>
</head>
<body>
<h1>{title}</h1>
<p class="meta">{dataset_html}</p>
<p class="meta">{len(records)} records | input SHA-256 {esc(build_meta["input_sha256"])} | built {esc(build_meta["generated_at"])} by build_dashboard.py {VERSION}</p>
<p class="note">Values are shown exactly as supplied. "{NOT_REPORTED}" means the input had no value; nothing is estimated or filled in. Filters only hide rows.</p>
{omitted}<div class="controls">
<label>Search<input id="q" type="search" placeholder="Filter rows"></label>
{controls_html}
<label><span><input id="complete" type="checkbox"> Only rows with every shown field reported</span></label>
<span id="count" role="status"></span>
</div>
<noscript><p class="note">JavaScript is off: filters are unavailable and all rows are shown.</p></noscript>
<table>
<thead><tr>{head_html}</tr></thead>
<tbody>
{body_html}
</tbody>
</table>
<table class="coverage">
<caption>Coverage by field</caption>
<tbody>{cov_rows}</tbody>
</table>
<script>{SCRIPT}</script>
</body>
</html>
"""


class _Reader(HTMLParser):
    """Extracts rows, cells, links, and build metadata from a generated dashboard."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.build_meta = None
        self.headers = []
        self.rows = []
        self._row = None
        self._cell = None
        self._in_thead = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "meta" and a.get("name") == "evidence-build":
            self.build_meta = json.loads(a.get("content", "{}"))
        elif tag == "thead":
            self._in_thead = True
        elif tag == "tr" and "data-id" in a:
            self._row = {"id": a["data-id"], "label": None, "href": None, "cells": {}}
            self._cell = None
        elif tag == "th" and self._in_thead and "data-field" in a:
            self._cell = ("header", a["data-field"], a, [])
        elif tag == "th" and self._row is not None and a.get("data-role") == "record":
            self._cell = ("record", None, a, [])
        elif tag == "td" and self._row is not None and "data-field" in a:
            self._cell = ("cell", a["data-field"], a, [])
        elif tag == "a" and self._row is not None and self._cell is not None and self._cell[0] == "record":
            self._row["href"] = a.get("href")

    def handle_data(self, data):
        if self._cell is not None:
            self._cell[3].append(data)

    def handle_endtag(self, tag):
        if tag == "thead":
            self._in_thead = False
        elif tag in ("th", "td") and self._cell is not None:
            kind, field, attrs, parts = self._cell
            text = "".join(parts)
            if kind == "header":
                self.headers.append(field)
            elif self._row is not None and kind == "record":
                self._row["label"] = text
            elif self._row is not None:
                self._row["cells"][field] = (text, attrs.get("data-missing"))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None
            self._cell = None


def _first_difference(expected, actual):
    for number, (a, b) in enumerate(zip(expected.split("\n"), actual.split("\n")), start=1):
        if a != b:
            return number
    return min(expected.count("\n"), actual.count("\n")) + 2


def check_dashboard(input_path, html_path, missing_tokens=(), columns=None):
    """Compare a generated dashboard with its input. Returns (problems, model).

    The settings (missing tokens, columns) come from the caller, never from the page,
    so editing the page's own build metadata cannot change what is checked. Without a
    --missing-token or --columns flag the check assumes none were used for the build.
    """
    try:
        page = Path(html_path).read_bytes().decode("utf-8")
        reader = _Reader()
        reader.feed(page)
        reader.close()
    except (ValueError, RecursionError) as exc:  # includes bad UTF-8 and bad metadata JSON
        return [f"dashboard could not be read as a build_dashboard.py page: {exc}"], None
    meta = reader.build_meta
    if not isinstance(meta, dict):
        return ["dashboard has no build metadata; it was not produced by build_dashboard.py"], None
    if not all(isinstance(meta.get(key), str) for key in ("input_name", "input_sha256", "generated_at")):
        return ["dashboard build metadata is incomplete or malformed"], None

    data, sha = load_json(input_path)
    tokens = clean_tokens(missing_tokens)
    model = normalize(data, tokens, columns)
    fields = [c["field"] for c in model["columns"]]
    problems = []
    if meta["input_sha256"] != sha:
        problems.append("input file changed since the dashboard was built (SHA-256 differs)")
    settings = []
    if meta.get("missing_tokens") != tokens:
        settings.append(
            f"page was built with missing tokens {meta.get('missing_tokens')!r} but verify was given {tokens!r}; "
            "pass the same --missing-token flags that were used for build"
        )
    if meta.get("columns") != fields:
        settings.append(
            f"page shows columns {meta.get('columns')!r} but verify expects {fields!r}; "
            "pass the same --columns that was used for build (or none if build had none)"
        )
    if settings:
        return problems + settings, model
    if reader.headers != fields:
        problems.append("column headers differ from the expected columns")
    if [r["id"] for r in reader.rows] != [r["id"] for r in model["records"]]:
        problems.append("record ids or order differ from the input")
        return problems, model
    for expected, actual in zip(model["records"], reader.rows):
        rid = expected["id"]
        if actual["href"] != expected["source_url"]:
            problems.append(f"{rid}: source link differs from input")
        if actual["label"] != expected["label"]:
            problems.append(f"{rid}: record label differs from input")
        for column in model["columns"]:
            field = column["field"]
            want = expected["cells"][field]
            got = actual["cells"].get(field)
            want_pair = (NOT_REPORTED, "true") if want is None else (want, "false")
            if got != want_pair:
                problems.append(f"{rid}.{field}: shows {got!r}, input says {want_pair!r}")
    if problems:
        return problems, model

    fresh = render(model, {
        "version": VERSION,
        "input_name": meta["input_name"],
        "input_sha256": sha,
        "generated_at": meta["generated_at"],
        "missing_tokens": tokens,
        "columns": fields,
        "omitted_fields": model["omitted_fields"],
    })
    if fresh != page:
        problems.append(
            f"page is not identical to a fresh build of the input (first difference at line {_first_difference(fresh, page)}); "
            "its script, styles, filters, coverage table, title, banner or build metadata were edited"
            + (f", or it was built by version {meta.get('version')!r} and this is {VERSION!r}" if meta.get("version") != VERSION else "")
        )
    return problems, model


def verify(input_path, html_path, missing_tokens=(), columns=None):
    """Return a list of mismatches between the input file and the generated dashboard."""
    return check_dashboard(input_path, html_path, missing_tokens, columns)[0]


def _parse_columns(text):
    return [c.strip() for c in text.split(",") if c.strip()] if text else None


def _build_command(args):
    data, sha = load_json(args.input)
    columns = _parse_columns(args.columns)
    model = normalize(data, args.missing_token or [], columns)
    generated = args.generated_at or dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    build_meta = {
        "version": VERSION,
        "input_name": Path(args.input).name,
        "input_sha256": sha,
        "generated_at": generated,
        "missing_tokens": clean_tokens(args.missing_token),
        "columns": [c["field"] for c in model["columns"]],
        "omitted_fields": model["omitted_fields"],
    }
    out = Path(args.out)
    out.write_bytes(render(model, build_meta).encode("utf-8"))
    manifest_path = Path(args.manifest) if args.manifest else out.with_suffix(".provenance.json")
    manifest = dict(build_meta)
    manifest.update({
        "record_count": len(model["records"]),
        "coverage": coverage(model),
        "records": [
            {k: r[k] for k in ("id", "source_url", "source_tool", "retrieved_at")} for r in model["records"]
        ],
    })
    manifest_path.write_bytes((json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    print(f"Wrote {out} and {manifest_path} ({len(model['records'])} records).")
    if model["omitted_fields"]:
        print("Warning: input fields not shown: " + ", ".join(model["omitted_fields"]), file=sys.stderr)
    return 0


def _verify_command(args):
    problems, model = check_dashboard(args.input, args.dashboard, args.missing_token or [], _parse_columns(args.columns))
    if problems:
        print("VERIFY FAILED:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("VERIFY OK: every record, link, value, and missing flag matches the input, and the page is identical to a fresh build.")
    tokens = clean_tokens(args.missing_token)
    print(f"  Settings checked: missing tokens: {', '.join(tokens) or 'none'}; columns: {', '.join(c['field'] for c in model['columns'])}")
    if model["omitted_fields"]:
        print(f"  Input fields not shown: {', '.join(model['omitted_fields'])}")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build", help="build a dashboard from a JSON evidence file")
    build.add_argument("input")
    build.add_argument("--out", required=True, help="output .html path")
    build.add_argument("--manifest", help="provenance manifest path (default: <out>.provenance.json)")
    build.add_argument("--columns", help="comma-separated field names to show, in order")
    build.add_argument("--missing-token", action="append", help="extra text to treat as missing (repeatable), for example NA")
    build.add_argument("--generated-at", help="timestamp to embed instead of the current UTC time")
    build.set_defaults(func=_build_command)
    check = sub.add_parser("verify", help="check a dashboard still matches its input")
    check.add_argument("input")
    check.add_argument("dashboard")
    check.add_argument("--columns", help="the same --columns that was used for build (omit if build had none)")
    check.add_argument(
        "--missing-token", action="append",
        help="the same --missing-token flags that were used for build (repeatable); settings are never read from the page",
    )
    check.set_defaults(func=_verify_command)
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except InputError as exc:
        print("INPUT REJECTED:", file=sys.stderr)
        for problem in exc.problems:
            print(f"  - {problem}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"File error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
