# Test results

Checks ran on Windows with Python 3.14.10. The Agent Skills reference validator
was `skills-ref` 0.1.0, upstream revision
`83021e2be457a9b6679148719c1f6074f0ad975e`.

## Checks

| Date (2026) | Check | Result |
|---|---|---|
| 17 Nov | Reference validator | `Valid skill` |
| 17 Nov | Renderer tests | 11 passed |
| 17 Nov | Offline synthetic render | HTML generated; input is fictional |
| 16 Nov | Copilot CLI, fresh session | Natural prompt activated the skill and generated synthetic HTML in a disposable workspace on the same machine, with refreshed user and machine PATH |
| 16 Nov | Discovery, restarted app and new chat | User observed skill activation, native search, GraphQL and batch calls, and HTML generation with `python` after the `python3` alias failed; five associations and 25 evidence records |
| 16 Nov | Discovery report browser | User confirmed manual filter use; separate browser check used JavaScript change events for filters, a browser click for Reset, and JavaScript for details and query expansion |

From the skill directory, the local package checks can be repeated:

```powershell
skills-ref validate .
python -m unittest discover -s tests -p test_renderer.py -v
python scripts\render.py --input tests\example.json --output report.html
```

The renderer makes no network requests and refuses to overwrite an existing
output file.

## Live MCP fidelity — 17 November 2026

| Item | Scope or result |
|---|---|
| Runtime | Local Copilot session on Windows, not Discovery; official hosted Open Targets MCP, read-only |
| Disease | Psoriasis, resolved by search to `MONDO_0005083` |
| Selection | First three direct associations and first three direct evidence records per target; `enableIndirect: false` |
| Release and time | Platform data `26.09`; association and evidence responses at 15:47 UTC |
| Records | Three associations and nine evidence records, three per target |
| Datasources | `clinical_precedence` (6), `uniprot_literature` (1), `gwas_credible_sets` (2) |
| Capture | Full MCP response bodies and exact requests saved programmatically, then converted to skill JSON and rendered with the current PR renderer |
| Fidelity | Independent checker compared saved responses, JSON and parsed HTML DOM; IDs, labels, unrounded scores, datasource, datatype, source IDs, record releases, metadata, link presence and per-target counts matched |
| Missing and zero | All nine record releases were null; no evidence score was zero and no source URLs were returned. Synthetic tests cover missing and zero scores |
| Browser | JavaScript change events exercised target and datasource filters; JavaScript clicks exercised Reset and record details |

## Limits

The live check covers a bounded first page, not a complete review or independent
inspection of source records. The earlier Discovery trace did not retain
complete raw MCP responses for an independent scientific numerical audit.
Neither test establishes clean-machine installation or provisioning. A bounded
report is not an exhaustive evidence review, target ranking, proof of
causation or clinical recommendation.
