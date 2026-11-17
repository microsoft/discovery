# Mapping OpenAlex agent results to records

The OpenAlexResearchLandscape agent returns OpenAlex works. Map each work to one record. The field
names inside the tool output can differ from the examples below; use what the tool actually returned.

| Record key | Source |
| --- | --- |
| `id` | The OpenAlex work ID, for example `W2153511586` |
| `label` | The work title |
| `source_url` | `https://openalex.org/<work ID>` (`openalex_url` in `search_works` results) |
| `source_tool` | The tool that returned it, for example `openalex.get_work` or `openalex.search_works`. Use the file name only when the tool is unknown |
| `retrieved_at` | The date of the call. Use `null` if it was not recorded; do not guess |
| `fields` | Values the tool returned, such as year, DOI, and type. Leave out or `null` anything it did not return |

Worked example (a public record checked against the OpenAlex lookup for DOI `10.1038/nmat3066`):

```json
{
  "id": "W2153511586",
  "label": "A lithium superionic conductor",
  "source_url": "https://openalex.org/W2153511586",
  "source_tool": "openalex.get_work",
  "retrieved_at": "2026-11-12",
  "fields": {"year": 2011, "doi": "10.1038/nmat3066"}
}
```

## `search_works` results

A live `search_works` call (2026-11-16) returned an object whose `results` list holds one entry per
work, next to search metadata (`total_results`, `returned`, `page`, `query`, `filter`, `sort`).
Each entry had these keys: `id`, `title`, `year`, `type`, `is_traditional`, `venue`, `venue_id`,
`cited_by_count`, `fwci`, `is_oa`, `oa_url`, `openalex_url`, `authors`, `primary_topic`, and `doi`
when the work has one. Map `id` to `id`, `title` to `label`, `openalex_url` to `source_url`, and the
remaining keys to `fields`. Illustrative entry (made-up values, real key names):

```json
{"id": "W1000000001", "title": "Example title", "year": 2026, "type": "article",
 "cited_by_count": 0, "is_oa": false, "openalex_url": "https://openalex.org/W1000000001",
 "authors": ["First Author (Example University)", "Second Author"]}
```

What to expect:

- **Absent keys, not nulls.** A work with no DOI, `oa_url` or `fwci` simply lacks that key. Leave
  the field out of `fields`; the skill shows it as "not reported". Do not add a placeholder.
- **Real zeros.** `cited_by_count: 0` and `fwci: 0` are real values and stay values.
- **Authors** are strings, usually `"Name (Institution)"`, and the institution part can be absent.
  Keep each string as given and do not split or normalise them. If the user wants a separate
  institution column, say that it was parsed from the string.
- **No tool name or date** in the raw JSON. If the output was saved to a file, record
  `source_tool` as `openalex.search_works` only when you know the call that produced it, and set
  `retrieved_at` to the call date if known, otherwise `null`.
- **Wildcards.** `search_works` rejected a query containing `*` unless `mode` was `exact`. When
  the call fails, report the error and do not build from partial or remembered data.

Rules of thumb:

- Do not copy values from the assistant's prose summary. Use the tool result.
- If a lookup returns `match: none` or an error, there is no record. Do not add one.
- If the OpenAlex connection asks for consent or is unavailable, stop and report it; do not
  substitute remembered data.
