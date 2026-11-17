---
name: open-targets-evidence-comparison
description: Create a traceable, filterable comparison of Open Targets disease-target associations and individual evidence. Use for an evidence dashboard, target comparison, or visual review of a bounded Open Targets sample.
compatibility: Python 3.9 or later and a host that permits reading inputs, running a bundled script, and saving an HTML artifact.
---

# Open Targets evidence comparison

Produce a small, reproducible evidence dashboard from a structured evidence
sample. This skill visualizes data; it does not fetch it, choose a disease or
perform clinical prioritization.

## Procedure

1. Establish the user's disease, requested scope, and permission to use the
   input. If data are not supplied, obtain a bounded sample using the existing
   authorized Open Targets agent and its MCP tools. Respect its approvals and
   report failures; do not install or bypass a connection.
2. Convert only observed fields to the JSON contract in
   [input-contract](references/input-contract.md). Preserve disease and target
   identifiers, separate association scores from evidence, source IDs, query
   parameters, release, link provenance and uncertainty. Record absent fields
   as `null`; do not infer missing records, counts, links or zeros. Ask for
   clarification if identity, source or sample scope cannot be established.
   Put concise agent-authored limitations in `uncertainty`, not a provider
   confidence score; put supplied raw evidence metadata in the optional
   `technical_metadata` object, preserving names and values separately.
   Keep provenance source and scope concise; place query, variables,
   pagination and reproducibility details in `provenance.query`.
3. Use a host that can access the entire skill package and run Python 3.9 or
   later. Before rendering, actually run the following preflight in that host
   for each candidate until one exits successfully:

   ```text
   python3 -c "import sys; print(sys.executable, sys.version); sys.exit(sys.version_info < (3, 9))"
   python -c "import sys; print(sys.executable, sys.version); sys.exit(sys.version_info < (3, 9))"
   ```

   On Windows also try `py -3` in place of `python` with the same `-c`
   argument. A missing command, Windows Store alias, failed execution, or
   nonzero exit is not a usable interpreter; continue to the next candidate
   and report failures. Use the first candidate that exits with code zero,
   retaining its launcher arguments (for example `py -3`), to run
   `scripts/render.py --input INPUT.json --output OUTPUT.html` from the skill
   directory. Use host-supported paths and quoting.

   If none succeeds, report the attempted commands and ask for an accessible
   Python 3.9+ interpreter or setup; an explicitly supplied executable can be
   checked with the same preflight. Do not install Python or change settings
   without approval. The renderer uses only the standard library and makes no
   network requests. If execution or file access is unavailable, report that
   the dashboard cannot be generated in this runtime.
4. Inspect the output and compare the rows, numeric values, filters, source
   links and provenance against the input. Return the HTML and scope limits.
   The report is a bounded sample, not a ranking, proof of causation or
   treatment recommendation. Association scores and individual evidence are
   different measures. Missing or empty results do not prove absence.
   The target filter applies to both sections; the datasource filter applies
   only to evidence. Reset restores both. Counts show the visible records.
   The evidence comparison table provides expandable per-row details retaining
   identifiers, source and limitations; it scrolls horizontally when needed.
   Scope and provenance shows loaded record counts, not platform totals; the
   complete supplied query is in a collapsed reproducibility section.
   Filters need JavaScript; all records remain accessible without it.

Only link to HTTP(S) sources supplied in the input, with their actual origin
(`returned`, `constructed`, or `independently_inspected`) and verification
status. Do not equate registries, regulatory assessments, abstracts and
peer-reviewed papers. Review original-source rights before publication.
