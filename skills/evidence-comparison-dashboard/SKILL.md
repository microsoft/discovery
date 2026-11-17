---
name: evidence-comparison-dashboard
description: "Turn sourced evidence records (for example works returned by a literature agent such as OpenAlexResearchLandscape, or any table of study results) into a self-contained, filterable comparison dashboard in which every row links to its source and every missing value is shown as not reported instead of being guessed. Includes a verify step that proves the dashboard still shows the input values. WHEN: compare studies or papers side by side, evidence table, comparison dashboard, filterable results table with source links, missing-data policy, literature comparison view, show provenance for each row. NOT for: searching literature (use a research agent), statistics or meta-analysis, charts of unsourced numbers, or estimating missing values."
license: MIT
compatibility: Requires Python 3.9+ (standard library only) and file read/write access. No network access, credentials, or installs needed to build a dashboard.
metadata:
  author: v-elniksic
  version: "1.0.0"
---

# evidence-comparison-dashboard

Builds one self-contained HTML page (search, per-field filters, source link on every row, coverage
table) from a JSON evidence file, plus a provenance manifest. It never fetches data itself: the
records come from tools the user is connected to, or from a file the user supplies.

## When to use

Use when the user wants several sourced records compared side by side and filtered, for example
after a literature or assay search. Do not use it to run the search: use the research agent first,
then this skill on its results.

## Inputs

A JSON file with a `records` list (full format in [input format](references/input-format.md)):

```json
{"records": [{"id": "W123", "label": "Paper title",
  "source_url": "https://openalex.org/W123", "source_tool": "openalex.get_work",
  "retrieved_at": "2026-11-13", "fields": {"year": 2011, "doi": null}}]}
```

- `id` and `source_url` (http or https) are **required** on every record. Records without a
  source link are rejected; do not invent or "reconstruct" a link.
- `fields` holds the values to compare. Use `null` or leave a field out when the source did not
  provide it.

## Procedure

1. **Collect records only from real sources.** Use tool results the user is connected to, or a file
   the user supplied. If a connection is unavailable (consent request, error, empty tool list,
   timeout), stop for that source, tell the user exactly what failed, and ask whether to continue
   with a user-supplied file. Never fill in records from memory.
2. **Write the input JSON programmatically from the tool output** where possible. Do not retype
   numbers. Copy values exactly; do not round, convert units, or normalise text. For a CSV or
   spreadsheet, map the id, title and source-link columns to `id`, `label` and `source_url`, and every
   other column to a field; keep cell text as given and leave the three mapped columns out of
   `columns` so they are not repeated. A row with no source link cannot be built: list those rows for
   the user and build the rest only if they agree.
3. **Record provenance per record:** `source_url`, plus `source_tool` and `retrieved_at` when known.
   Use the real tool name (for example `openalex.search_works`) when you know which call produced
   the data. Mark file-supplied records with `source_tool` set to the file name only when the tool
   is unknown, and leave `retrieved_at` `null` rather than guessing a date.
4. **Choose columns.** Default is every field seen, in first-seen order. Pass
   `--columns a,b,c` or a `columns` list to choose and order them. Fields left out are reported,
   never silently dropped.
5. **Build** (run from the skill folder or use its absolute path):

   ```sh
   python scripts/build_dashboard.py build evidence.json --out dashboard.html
   ```

   Add `--missing-token NA` (repeatable) only if the user confirms a literal such as `NA` means
   "unknown" in their data. If Python cannot be run in this environment, tell the user the
   dashboard cannot be built with verification. Do not hand-write the HTML and describe it as
   verified.
6. **Verify** and show the result to the user. Pass the same `--missing-token` and `--columns`
   flags you gave `build`; `verify` does not read them from the page:

   ```sh
   python scripts/build_dashboard.py verify evidence.json dashboard.html
   ```

   If it fails, do not hand over the dashboard; fix the cause and rebuild. A failure that mentions
   `--missing-token` or `--columns` means the flags differ from the build's; it is not a reason to
   change the page.
7. **Report:** record count, per-field coverage (reported vs not reported), omitted fields, the
   source tools and retrieval dates, and which sources failed or were skipped.

## Missing-data policy

| Input value | Treated as |
| --- | --- |
| `null`, field absent, empty or whitespace-only string, empty list | **Missing**: shown as "not reported" |
| `0`, `0.0`, `false`, the string `"0"`, the string `"N/A"` | A real value, shown exactly as given |
| Any string listed with `--missing-token` | Missing (explicit opt-in only) |

Placeholder text such as `not provided`, `n/a` or `-` in a user's table is kept as given, because
the skill cannot know it means "unknown". It then counts as reported in the coverage table, so ask
the user whether to treat it as missing (`--missing-token`). If you cannot ask, say in your report
that those cells were kept as given and are counted as reported.

Never impute, average over, or drop missing values. Do not compute totals, means, or rankings
across a field unless you state how many records were not reported for it. The row filter "Only
rows with every shown field reported" hides rows; it does not change or delete data.

## Provenance requirements

- Every row links to its source and shows tool and retrieval date (or "not recorded").
- The page embeds the SHA-256 of the input file and the build settings. `verify` fails if the input
  changed, a value or link was edited, or a real value was marked missing.
- State in your answer that the dashboard reflects the input as of `retrieved_at`.
- `verify` takes the missing tokens and columns from its command line, not from the page, so the
  page cannot vouch for its own settings. It then requires the whole page to match a fresh build of
  the input (rows, links, labels, cell text, missing flags, script, styles, dropdowns, coverage
  table, title and banner). It cannot prove the input file matches the original source; that is why
  step 2 requires copying tool output rather than retyping it.

## Permissions

Reads the input file; writes `dashboard.html` and `dashboard.provenance.json` next to the output
path. No network, credentials, or installs. The page has no external resources, and a
Content-Security-Policy pins its inline style and script; all text is HTML-escaped.

## Pitfalls

- A field present in only some records gets "not reported" for the rest. Say so rather than
  treating the column as complete.
- Lists must contain strings or numbers only; flatten nested objects before building.
- `NaN` and `Infinity` are rejected. Use `null` for unknown numbers.
- Filters need JavaScript; with it off, all rows are shown.
- A filter dropdown exists only for fields with 2 to 12 distinct values (or one value plus missing
  ones). Long-text fields such as titles, DOIs and authors are found with the search box instead.
- Write the input file as UTF-8 **without** a byte order mark. The build rejects one, and Windows
  PowerShell 5.1 `Set-Content -Encoding UTF8` and `Out-File -Encoding utf8` add it. Use Python's
  `json.dump` to write the file.
- Provider-specific field names differ. Use the names the tool actually returned and see the
  [OpenAlex mapping](references/openalex-mapping.md) for one worked example.
