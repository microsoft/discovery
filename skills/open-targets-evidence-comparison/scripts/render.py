"""Render a bounded evidence sample as a self-contained HTML report."""

import argparse
import html
import json
import re
import sys
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit


def fail(path, message):
    raise ValueError(f"{path}: {message}")


def obj(value, path, keys, optional=()):
    if not isinstance(value, dict):
        fail(path, "expected object")
    missing = set(keys) - value.keys()
    extra = value.keys() - set(keys) - set(optional)
    if missing or extra:
        fail(path, f"missing fields {sorted(missing)}; unexpected fields {sorted(extra)}")
    return value


def text(value, path, nullable=False):
    if nullable and value is None:
        return value
    if not isinstance(value, str) or not value.strip():
        fail(path, "expected nonempty string" + (" or null" if nullable else ""))
    return value


def number(value, path):
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        fail(path, "expected finite number or null")
    if isinstance(value, Decimal) and not value.is_finite():
        fail(path, "expected finite number or null")


def array(value, path):
    if not isinstance(value, list):
        fail(path, "expected array")
    return value


def metadata_json(value, path, depth=0):
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            fail(path, "expected string object keys")
        items = [f'{json.dumps(key, ensure_ascii=False)}: '
                 f'{metadata_json(item, path + "." + key, depth + 1)}'
                 for key, item in value.items()]
        opening, closing = "{", "}"
    elif isinstance(value, list):
        items = [metadata_json(item, f"{path}[{i}]", depth + 1)
                 for i, item in enumerate(value)]
        opening, closing = "[", "]"
    elif value is None or isinstance(value, (str, bool, int)):
        return json.dumps(value, ensure_ascii=False)
    elif isinstance(value, Decimal) and value.is_finite():
        return str(value)
    else:
        fail(path, "expected a JSON value with finite numbers")
    if not items:
        return opening + closing
    indent = "  " * (depth + 1)
    return opening + "\n" + indent + (",\n" + indent).join(items) + "\n" + "  " * depth + closing


def validate(data):
    obj(data, "input", ("disease", "provenance", "associations", "evidence"))
    disease = obj(data["disease"], "disease", ("id", "label"))
    for key in disease:
        text(disease[key], f"disease.{key}")
    provenance = obj(data["provenance"], "provenance", (
        "source", "retrieved", "release", "query", "scope", "propagation", "uncertainty"))
    for key in provenance:
        text(provenance[key], f"provenance.{key}", key in ("retrieved", "release"))
    ids = set()
    for i, row in enumerate(array(data["associations"], "associations")):
        path = f"associations[{i}]"
        obj(row, path, ("target_id", "target_label", "score"))
        target = text(row["target_id"], f"{path}.target_id")
        if target in ids:
            fail(path, "duplicate target_id")
        ids.add(target)
        text(row["target_label"], f"{path}.target_label", True)
        number(row["score"], f"{path}.score")
    for i, row in enumerate(array(data["evidence"], "evidence")):
        path = f"evidence[{i}]"
        obj(row, path, ("target_id", "evidence_id", "datasource", "datatype", "source_id",
                        "score", "release", "uncertainty", "links"), ("technical_metadata",))
        if text(row["target_id"], f"{path}.target_id") not in ids:
            fail(path, "target_id does not match an association")
        for key in ("evidence_id", "datasource", "datatype", "source_id", "release", "uncertainty"):
            text(row[key], f"{path}.{key}", True)
        number(row["score"], f"{path}.score")
        if "technical_metadata" in row:
            if not isinstance(row["technical_metadata"], dict):
                fail(f"{path}.technical_metadata", "expected object")
            metadata_json(row["technical_metadata"], f"{path}.technical_metadata")
        for j, link in enumerate(array(row["links"], f"{path}.links")):
            loc = f"{path}.links[{j}]"
            obj(link, loc, ("url", "origin", "verified"))
            url = text(link["url"], f"{loc}.url")
            try:
                parts = urlsplit(url)
                valid_url = (parts.scheme in ("http", "https") and parts.hostname and
                             parts.username is None and parts.password is None and
                             not re.search(r"""[\s\x00-\x1f\x7f<>"'\\]""", url))
                _ = parts.port
            except ValueError:
                valid_url = False
            if not valid_url:
                fail(f"{loc}.url", "expected safe HTTP(S) URL without credentials")
            if link["origin"] not in ("returned", "constructed", "independently_inspected"):
                fail(f"{loc}.origin", "expected returned, constructed, or independently_inspected")
            if not isinstance(link["verified"], bool):
                fail(f"{loc}.verified", "expected boolean")
    return data


def esc(value):
    return html.escape("Not returned / not established" if value is None else str(value), quote=True)


def display(value):
    if value is None:
        return '<span class="missing" aria-label="Not returned or not established">—</span>'
    return esc(value)


def cell(value):
    return f"<td>{display(value)}</td>"


def association_score(value):
    if value is None:
        return cell(value)
    if 0 <= value <= 1:
        width = Decimal(value) * 100
        return (f'<td>{esc(value)}<div class="score-track" aria-hidden="true">'
                f'<span style="width:{width}%"></span></div></td>')
    return cell(value)


def render(data):
    disease, prov = data["disease"], data["provenance"]
    associations, evidence = data["associations"], data["evidence"]
    labels = {row["target_id"]: row["target_label"] for row in associations}
    options = '<option value="">All targets</option>' + "".join(
        f'<option value="{esc(row["target_id"])}">{esc(row["target_label"])} ({esc(row["target_id"])})</option>'
        for row in associations)
    sources = sorted({row["datasource"] for row in evidence if row["datasource"] is not None})
    source_options = '<option value="">All sources</option><option value="missing:">Not returned</option>' + "".join(
        f'<option value="value:{esc(source)}">{esc(source)}</option>' for source in sources)
    assoc_rows = "".join(
        f'<tr data-target="{esc(row["target_id"])}"><td><strong>{display(row["target_label"])}</strong>'
        f'<span class="identifier">{esc(row["target_id"])}</span></td>{association_score(row["score"])}</tr>'
        for row in associations)
    evidence_rows = []
    for row in evidence:
        links = "".join(
            f'<li><a href="{esc(link["url"])}" rel="noopener noreferrer" target="_blank">{esc(link["url"])}</a>'
            f'<span class="link-meta">{esc(link["origin"])}, '
            f'{"verified" if link["verified"] else "not independently verified"}</span></li>'
            for link in row["links"])
        links = f'<ul class="links">{links}</ul>' if links else "No link supplied"
        source = "value:" + row["datasource"] if row["datasource"] is not None else "missing:"
        fields = (
            ("Target ID", row["target_id"]), ("Evidence ID", row["evidence_id"]),
            ("Datasource", row["datasource"]), ("Datatype", row["datatype"]),
            ("Source ID", row["source_id"]), ("Evidence score", row["score"]),
            ("Record release", row["release"]), ("Limitations & notes", row["uncertainty"]),
        )
        details = "".join(f"<dt>{esc(label)}</dt><dd>{display(value)}</dd>" for label, value in fields)
        metadata = ""
        if "technical_metadata" in row:
            raw = metadata_json(row["technical_metadata"], "technical_metadata")
            metadata = f'<details class="metadata"><summary>Technical metadata</summary><pre>{esc(raw)}</pre></details>'
        evidence_rows.append(
            f'<tr class="evidence-record" data-target="{esc(row["target_id"])}" data-source="{esc(source)}">'
            f'<td><strong>{display(labels[row["target_id"]])}</strong></td>'
            f'{cell(row["datasource"])}{cell(row["datatype"])}{cell(row["score"])}'
            f'<td><details><summary>View details</summary>'
            f'<dl class="record-details">{details}<dt>Source links and provenance</dt><dd>{links}</dd></dl>{metadata}'
            f'</details></td></tr>')
    provenance = "".join(f"<dt>{esc(label)}</dt><dd>{display(prov[key])}</dd>" for key, label in (
        ("source", "Source"), ("retrieved", "Retrieved"), ("release", "Release"),
        ("scope", "Scope"), ("propagation", "Propagation"), ("uncertainty", "Limitations & notes")))
    query = esc(prov["query"]).replace("\r", "&#13;")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Open Targets evidence comparison</title>
<style>
*{{box-sizing:border-box}} body{{margin:0;background:#f4f7fb;color:#21324a;font:15px/1.5 system-ui,sans-serif}}
main{{max-width:1120px;margin:auto;padding:2.5rem 1.5rem 4rem}} h1,h2,p,dl{{margin:0}}
h1{{font-size:clamp(2rem,4vw,2.7rem);line-height:1.15;letter-spacing:-.03em;color:#142c4c}}
h2{{font-size:1.25rem;color:#193555}} a{{color:#125a9d}} a:focus-visible,select:focus-visible,button:focus-visible,summary:focus-visible{{outline:3px solid #6aa9ea;outline-offset:3px}}
.eyebrow{{font-size:.75rem;font-weight:750;letter-spacing:.11em;text-transform:uppercase;color:#386b9e}}
.hero{{display:grid;gap:.75rem;margin-bottom:1.5rem}} .subtitle{{font-size:1.1rem;color:#425b79}}
.notice{{background:#e8f2ff;color:#294a6b;border:1px solid #c8dff8;border-radius:12px;padding:.85rem 1rem}}
.card{{background:white;border:1px solid #dce5ef;border-radius:16px;box-shadow:0 4px 16px #28496a0d;padding:1.35rem;margin-top:1rem}}
.section-head{{display:flex;align-items:baseline;justify-content:space-between;gap:1rem;flex-wrap:wrap;margin-bottom:.6rem}}
.help{{color:#536b85;font-size:.9rem}} .count{{color:#405f80;font-size:.85rem;font-weight:650}}
.field-grid{{display:grid;grid-template-columns:minmax(8rem,11rem) minmax(0,1fr);gap:.45rem 1rem;margin-top:.8rem}}
dt{{color:#536b85;font-weight:650}}dd{{margin:0;min-width:0;overflow-wrap:anywhere;white-space:pre-wrap}}
.filters{{display:flex;align-items:end;gap:1rem;flex-wrap:wrap}} .filter-field{{display:grid;gap:.35rem;flex:1 1 14rem}}
label{{font-weight:650;color:#354e6a}} select,button{{font:inherit;border:1px solid #b7c8da;border-radius:8px;background:#fff;color:#203a59;padding:.65rem .8rem}}
select{{width:100%;min-width:0}}button{{cursor:pointer;font-weight:650}}button:hover{{background:#f0f6fc}} .filter-note{{margin-top:.7rem}}
.scroll{{overflow-x:auto}}table{{border-collapse:collapse;width:100%;table-layout:fixed}}th,td{{padding:.8rem .65rem;text-align:left;border-bottom:1px solid #e6edf4;vertical-align:top}}
th{{color:#59708a;font-size:.75rem;letter-spacing:.05em;text-transform:uppercase}}.associations-table th:last-child{{width:38%}}
td{{overflow-wrap:anywhere}} .identifier{{display:block;font:0.83rem/1.45 ui-monospace,monospace;color:#617991;margin-top:.15rem;overflow-wrap:anywhere}}
.score-track{{height:.45rem;background:#e4edf7;border-radius:1rem;margin-top:.4rem;max-width:12rem;overflow:hidden}}.score-track span{{display:block;height:100%;background:#4284c6}}
.evidence-table{{min-width:720px}}.evidence-table th:nth-child(1){{width:16%}}.evidence-table th:nth-child(2){{width:16%}}
.evidence-table th:nth-child(3){{width:15%}}.evidence-table th:nth-child(4){{width:15%}}.evidence-table th:nth-child(5){{width:38%}}
.evidence-record:hover{{background:#f8fbff}}summary{{cursor:pointer;color:#266aa9;font-weight:700}}summary:hover{{color:#174c7c}}
.record-details{{margin-top:.7rem;font-size:.88rem}}.record-details dt{{margin-top:.55rem}}.record-details dd{{margin-top:.1rem}}
.metadata{{margin-top:.8rem;font-size:.88rem}}.metadata pre{{padding:.7rem;background:#edf3f9;border-radius:8px;white-space:pre-wrap;overflow-wrap:anywhere}}
.query-details{{margin-top:1rem}}.query-text{{margin-top:.7rem;padding:.8rem;background:#edf3f9;border-radius:8px;white-space:pre-wrap;overflow-wrap:anywhere}}
.links{{margin:0;padding-left:1.2rem}}.links li+li{{margin-top:.5rem}}.link-meta{{display:block;color:#59708a;font-size:.85rem}}
.missing{{color:#71849a}} .empty{{color:#536b85;padding:1rem 0}} [hidden]{{display:none!important}}
@media(max-width:600px){{main{{padding:1.4rem .8rem 3rem}}.card{{padding:1rem}}.field-grid{{grid-template-columns:1fr;gap:.15rem}}.field-grid dd{{margin-bottom:.55rem}}}}
</style></head><body>
<main><header class="hero"><p class="eyebrow">Open Targets · Evidence comparison</p><h1>{esc(disease["label"])}</h1>
<p class="subtitle">{esc(disease["id"])} · {esc(prov["scope"])}</p>
<p class="notice">A bounded sample, not a ranking or clinical recommendation. Association scores and individual evidence are distinct. Missing data are not zero and do not prove absence.</p></header>
<section class="card" aria-labelledby="filters-heading"><div class="section-head"><h2 id="filters-heading">Explore the sample</h2></div>
<div class="filters"><div class="filter-field"><label for="target">Target</label><select id="target">{options}</select></div>
<div class="filter-field"><label for="source">Evidence datasource</label><select id="source">{source_options}</select></div>
<button id="reset" type="button">Reset filters</button></div>
<p class="help filter-note">Target filters both sections; datasource filters evidence only. — means not returned or not established.</p>
<noscript><p class="help">Filters require JavaScript. All provided records remain available.</p></noscript></section>
<section class="card" aria-labelledby="associations-heading"><div class="section-head"><h2 id="associations-heading">Associations</h2><p class="count" id="assoc-count" aria-live="polite">{len(associations)} of {len(associations)} shown</p></div>
<p class="help">Bars show returned scores on a 0 to 1 scale; other values are displayed as text only.</p>
<div class="scroll"><table class="associations-table"><thead><tr><th>Target</th><th>Association score</th></tr></thead><tbody id="associations">{assoc_rows}</tbody></table></div>
<p id="assoc-empty" class="empty"{" hidden" if associations else ""}>No associations match the current filter.</p></section>
<section class="card" aria-labelledby="evidence-heading"><div class="section-head"><h2 id="evidence-heading">Individual evidence</h2><p class="count" id="evidence-count" aria-live="polite">{len(evidence)} of {len(evidence)} shown</p></div>
<p class="help">Open details to inspect identifiers, source links and limitations. Scroll horizontally on narrow screens.</p>
<div class="scroll" role="region" aria-label="Evidence comparison table" tabindex="0"><table class="evidence-table">
<thead><tr><th scope="col">Target</th><th scope="col">Datasource</th><th scope="col">Datatype</th><th scope="col">Evidence score</th><th scope="col">Details</th></tr></thead>
<tbody id="evidence">{"".join(evidence_rows)}</tbody></table></div>
<p id="evidence-empty" class="empty"{" hidden" if evidence else ""}>No evidence records match the current filters. This does not establish absence of evidence.</p></section>
<section class="card" aria-labelledby="provenance-heading"><div class="section-head"><h2 id="provenance-heading">Scope and provenance</h2></div>
<p class="help">Loaded in this report: {len(associations)} association records and {len(evidence)} evidence records; these are not platform totals.</p>
<dl class="field-grid">{provenance}</dl>
<details class="query-details"><summary>Query details &amp; reproducibility</summary><div class="query-text">{query}</div></details></section>
</main>
<script>
const target = document.getElementById('target'), source = document.getElementById('source');
function filter() {{
  for (const [section, selector, empty, count] of [['associations','tr','assoc-empty','assoc-count'],['evidence','.evidence-record','evidence-empty','evidence-count']]) {{
    const rows = [...document.getElementById(section).querySelectorAll(selector)];
    for (const row of rows) row.hidden = Boolean((target.value && row.dataset.target !== target.value) || (section === 'evidence' && source.value && row.dataset.source !== source.value));
    const shown = rows.filter(row => !row.hidden).length;
    document.getElementById(empty).hidden = shown > 0;
    document.getElementById(count).textContent = `${{shown}} of ${{rows.length}} shown`;
  }}
}}
target.addEventListener('change', filter); source.addEventListener('change', filter); filter();
document.getElementById('reset').addEventListener('click', () => {{ target.value = ''; source.value = ''; filter(); }});
</script></body></html>"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.input.resolve() == args.output.resolve():
            raise ValueError("input and output must be different files")
        def reject_constant(value):
            raise ValueError(f"invalid JSON number: {value}")
        data = json.loads(args.input.read_text(encoding="utf-8-sig"), parse_float=Decimal,
                          parse_constant=reject_constant)
        output = render(validate(data))
        with args.output.open("x", encoding="utf-8", newline="\n") as result:
            result.write(output)
    except (OSError, ValueError, UnicodeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    print(f"Created {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
