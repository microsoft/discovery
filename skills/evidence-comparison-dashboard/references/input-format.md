# Input format

The input is UTF-8 JSON without a byte order mark: an object with `records`, or a bare list of records.

| Key | Required | Notes |
| --- | --- | --- |
| `records` | Yes | Non-empty list. |
| `title` | No | Page title. |
| `dataset` | No | `{"name", "license", "synthetic"}`. `synthetic: true` adds a visible demo banner. |
| `columns` | No | List of field names, or `{"field", "label"}` objects. Controls which fields show and in what order. `--columns` overrides it. |

Each record:

| Key | Required | Notes |
| --- | --- | --- |
| `id` | Yes | Unique, non-empty string. |
| `source_url` | Yes | `http` or `https` link to where the record can be checked. |
| `label` | No | Link text; defaults to `id`. |
| `source_tool` | No | Tool or file the record came from, for example `openalex.get_work`. |
| `retrieved_at` | No | When it was retrieved, for example `2026-11-13`. |
| `fields` | No | Object of values to compare. |

Field values may be a string, number, boolean, `null`, or a list of strings and numbers (shown
joined with `; `). Nested objects, `NaN`, `Infinity`, and duplicate JSON keys are rejected.

## Rejections

The build lists every problem at once and writes nothing: missing or non-http(s) `source_url`,
duplicate `id`, invalid field values, invalid `columns`.

## Samples

- [`assets/sample-evidence.json`](../assets/sample-evidence.json): synthetic, includes missing
  values, a real zero, and a real `false`.
- [`assets/sample-catalysis.json`](../assets/sample-catalysis.json): a different synthetic dataset
  with different columns; pass `--missing-token NA` to `build` (not `verify`, which reads it from
  the page) to treat its `"NA"` as missing.
