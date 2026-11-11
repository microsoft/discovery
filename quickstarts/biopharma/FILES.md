# BioPharma file accounting

Source guide revision 0.11 (113,732 bytes, SHA-256
`1f1046aedcc1d7a323ebf38ab5352b152071de690b967ac95bfec450fb08ec49`)
and operational v1 are the inspected authoring sources. The public entry here
is a focused frozen-mode adaptation; source originals remain unchanged.

| Source component | Delivery in this proposal |
| --- | --- |
| Frozen launch prompt | Exact text in `prompts/frozen.txt`, LF normalized, hash in scenario manifest. |
| Direct dependency pins | `requirements.txt`; same 14 requirements as the operational profile. Not a complete transitive lock. |
| Launcher, acceptance script, native profile, wrapper, offline guard | Within required operational ZIP, accounted by full archive hash; public hosting unresolved. Not replaced with improvised local scripts. |
| Original launcher/acceptance tests and validation records | Within the same operational ZIP; reference only, not tests executed by this PR. |
| Scientific source, inputs, saved model, docking and reference outputs | Within exact clean snapshot ZIP; public hosting and distribution approval unresolved. Saved models never loaded during packaging. |
| ZIP checksums, manifest and validation attachment | All inventoried in `assets.json` with source sizes/hashes; retain at publication. |
| Historical screenshot document/private evidence log | Not published. Historical observations summarized with their date/scope; no new execution claimed. |
| Full fresh-science extension | Not enabled by this frozen profile; separate owner review/run/package required. |

The large archive is not added as a normal Git object. No invented public
release or internal collaboration link substitutes for external availability.