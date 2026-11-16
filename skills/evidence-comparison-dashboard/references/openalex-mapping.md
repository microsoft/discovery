# Mapping OpenAlex agent results to records

The OpenAlexResearchLandscape agent returns OpenAlex works. Map each work to one record. The field
names inside the tool output can differ from the examples below; use what the tool actually returned.

| Record key | Source |
| --- | --- |
| `id` | The OpenAlex work ID, for example `W2153511586` |
| `label` | The work title |
| `source_url` | `https://openalex.org/<work ID>` |
| `source_tool` | The tool that returned it, for example `openalex.get_work` |
| `retrieved_at` | The date of the call |
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

Rules of thumb:

- Do not copy values from the assistant's prose summary. Use the tool result.
- If a lookup returns `match: none` or an error, there is no record. Do not add one.
- If the OpenAlex connection asks for consent or is unavailable, stop and report it; do not
  substitute remembered data.
