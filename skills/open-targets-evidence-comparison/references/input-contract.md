# Input contract

Use UTF-8 JSON. This is a visualization contract, not the Open Targets API
schema. Do not put credentials, private data, or sensitive query parameters in
the input or generated HTML. Every field shown below is required except
`technical_metadata`; nullable fields use JSON `null` when not returned or not
established.

```json
{
  "disease": {"id": "EXAMPLE:1", "label": "Synthetic disease"},
  "provenance": {
    "source": "Synthetic example, not Open Targets data",
    "retrieved": null,
    "release": null,
    "query": "Synthetic; no query",
    "scope": "Two synthetic associations; not a ranking",
    "propagation": "not established",
    "uncertainty": "Values and identifiers are invented for testing."
  },
  "associations": [
    {"target_id": "SYNTH:1", "target_label": "Example target", "score": 0}
  ],
  "evidence": [
    {
      "target_id": "SYNTH:1",
      "evidence_id": "SYNTH:E1",
      "datasource": "synthetic",
      "datatype": "synthetic",
      "source_id": null,
      "score": null,
      "release": null,
      "uncertainty": "Synthetic record",
      "technical_metadata": {"studyId": null, "literature": []},
      "links": [
        {"url": "https://example.org/record", "origin": "returned", "verified": false}
      ]
    }
  ]
}
```

Identifiers and labels are nonempty strings, except a target label can be
`null`. `source`, `query`, `scope`, `propagation`, and `uncertainty` are
nonempty strings; `retrieved` and `release` are strings or `null`. Association
and evidence scores are finite JSON numbers or `null`; numeric zero is never
treated as missing. Evidence strings other than `target_id` may be `null`.
Each evidence target must appear in `associations`, whose target IDs must be
unique. Empty associations and evidence arrays are valid.

Keep `provenance.source` and `provenance.scope` concise and factual. Put
the supplied query, variables, pagination and reproducibility or audit details
in `provenance.query`; the report displays this text in a collapsed section
without parsing or truncating it. Loaded association and evidence counts are
derived from the input arrays, not platform totals or completeness estimates.

For new inputs, use `uncertainty` for concise, readable limitations and
notes; these are agent-authored notes, not a provider confidence score.
Evidence may also contain `technical_metadata`, an optional JSON object for
raw returned fields, preserving their names and values. It is displayed
separately and does not imply source verification. Omit it if not supplied;
an empty object is permitted. Legacy `uncertainty` strings are displayed
unchanged, including any embedded JSON; the renderer does not extract or
rewrite them. Report-level `provenance.uncertainty` uses the same display label.

Links must be HTTP(S), without embedded credentials, whitespace, control
characters, quotes, angle brackets or backslashes;
`origin` is `returned`, `constructed`, or `independently_inspected`, and
`verified` is a boolean. The renderer does not verify links or fetch content.
An empty `links` array means no link was supplied to the renderer, not that no
source exists.
