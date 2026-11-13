# OpenAlex validation record

## Scope and environment

Validated on **2026-11-12** in one development Discovery workspace in UK South, with one signed-in
user. The model deployment was `gpt-5-4`. Discovery used GA API `2026-06-01`; the native Foundry
agent API used `v1`, and the custom OAuth connection API used `2025-04-01-preview`.

The provider source review used commit
[`9eec62cd871187fb263d27b1dea31b69dfa5dc93`](https://github.com/ourresearch/openalex-mcp-server/tree/9eec62cd871187fb263d27b1dea31b69dfa5dc93).
The hosted service's deployed source revision was not established; source review is not a substitute
for the live checks below.

The catalog agent was deployed, then a separate native Foundry version was created with its MCP
binding. Exactly 13 read-only OpenAlex tools were exposed, with auto-approval restricted to that
allowlist. All six existing Discovery resource functions were preserved. No container or registry
was created.

Only public research inputs were sent to OpenAlex. No paid plan was purchased. This record excludes
tenant/subscription IDs, project names, connection resource IDs, user identities, tokens, consent
links, and raw response traces.

**Scope caveat.** The tested connection was created with an extra, unadvertised `offline_access`
scope alongside `openalex:query`, and consent still completed. Code review found that the provider
advertises only `openalex:query`, so the setup documentation now requests only that scope. That
documented `openalex:query`-only configuration has not been re-run end to end.

## Observed results

| Check | Result |
| --- | --- |
| First-use OAuth | Discovery returned `oauth_consent_request`. The user completed consent; continuation in the same conversation executed a real MCP call. |
| DOI lookup | `get_work` returned **A lithium superionic conductor**, 2011, DOI `10.1038/nmat3066`, OpenAlex `W2153511586`. The assistant's fields matched the tool output. |
| Two-reference verification | `resolve_references` returned two exact matches, with match probabilities 0.99 and 1.0, and the returned titles, years, DOIs, and OpenAlex links appeared in the answer. |
| Fresh conversation | A new investigation and conversation, without `previous_response_id`, executed `get_work` and `resolve_references` without another consent request. |
| Later consent requirement | A later same-day DOI request required consent again. After the user authorized it, a real `get_work` call succeeded with the expected record. Automatic token refresh is not established; the cause of the repeated consent was not determined. |
| Engine chat | The user reported the DOI lookup succeeded after refreshing and retrying in a new chat. A missing deployment reference on the project's default Discovery agent was corrected separately, with user approval, before this retry. This is user-observed UI evidence, not an exported UI trace. |
| Fabricated reference | The matcher returned `none` with `match_p: 0.08`. The agent reported **not found**, left the matched title/identifiers empty, and did not invent a DOI or link. |
| Read-only allowlist | The fresh conversation listed exactly the 13 approved research tools; account/profile tools were absent. |
| Guided keyword landscape | A preview, aggregate analysis, and citation-sorted sample agreed on **2,280** matching articles: **1,067** in 2023 and **1,213** in 2024. The year counts summed to the total; all calls used the same query and filters. |
| Provenance | Reported work identifiers, leading institutions, canonical OQL, and reproduction URLs were checked against raw tool results, not response text alone. |
| Error reporting | The agent stopped and reported rejected wildcard syntax and an invalid `top_n: 2`, without inventing results. Explicit corrections to literal terms and `top_n: 3` completed the guided probe. |
| Workspace writes | No resource-function calls occurred in these no-file validation probes. Saving a finished landscape was not tested. |
| Catalog validation | Passed with zero failures and zero warnings. |
| Schema tests | `test_schema_security.py`: **37 passed**. |

The landscape was manually guided, not proof that the complete autonomous workflow works. Counts
and match probabilities are observations from this test date, not values future runs must reproduce
exactly.

## Public test inputs

### Single-record lookup

```text
Use the connected OpenAlex get_work tool once for DOI 10.1038/nmat3066.
Return its title, year, DOI, and OpenAlex work URL. Do not answer from memory
or create files. Stop if consent or a tool error prevents the lookup.
```

### Reference verification

```text
Use resolve_references for:
1. Kamaya N. et al. A lithium superionic conductor. Nature Materials, 2011.
2. Janek J., Zeier W. G. A solid future for battery development. Nature Energy, 2016.
Report the actual match status, confidence, title, year, DOI, and OpenAlex link.
Do not answer from memory or create files.
```

For the fresh-session negative check, a second call used this explicitly fictional fixture:

```text
Zyxqv R. Calibration of purple lunar teapots with qzxv-9047 unicorn electrolytes.
Journal of Impossible Onboarding Fixtures, 2024.
```

The fresh conversation performed the DOI lookup followed by the fictional-reference check, with
one tool invocation at a time. The expected behavior for a matcher result of `none` is **not found**,
not a fabricated replacement reference.

### Bounded landscape

The successful keyword query was `"solid-state battery" AND electrolyte`, with `from_year: 2023`,
`to_year: 2024`, and `types: ["article"]`.

Run `search_works` with `preview: true`, then `analyze_works` with the same query and `top_n: 3`,
then `search_works` with `sort: "cited_by_count"` and `limit: 2`. Read each result before the next
call. Distinguish the full-set aggregate from the two-work sample; retain the exact returned OQL
and `reproduce_url`. Do not save an asset for this validation-only probe.

## Reproducing the checks

Follow [`mcp/README.md`](mcp/README.md) to create the connection, attach MCP while retaining the
existing resource tools, and handle consent. Require completed `mcp_call` items with usable,
error-free tool outputs. A completed response, an OAuth link, or assistant-only text is not
sufficient evidence.

For the catalog checks, install the repository's pinned
[CI requirements](../../.github/requirements-ci.txt) in an isolated Python environment. On Windows,
the real `file` classifier must also be on the validator process's PATH; the test used Git for
Windows' `usr\bin\file.exe`. No classifier was mocked and no policy was bypassed.

Set `$ChangedFiles` to a local, newline-delimited list of these five catalog files and `$Report`
to an ignored/local JSON output path:

```text
agents\openalex-research-landscape\agent.yaml
agents\openalex-research-landscape\metadata.yaml
agents\openalex-research-landscape\README.md
agents\openalex-research-landscape\mcp\README.md
agents\openalex-research-landscape\TEST_RESULTS.md
```

From the repository root, using that Python environment:

```powershell
python .github\scripts\validate_pr.py --changed-files $ChangedFiles --repo-root . --output $Report
python -m pytest .github\tests\test_schema_security.py -q
```

The recorded results above are from actual tool outputs and local checks. Private raw evidence is
retained separately, not included in the catalog contribution.

## Not verified

- Independent installation from a clean project by another person.
- Foundry UI setup or Discovery Studio's display/resumption of OAuth consent.
- Unattended Discovery Engine execution or an unguided complete landscape with a saved report.
- Second-user grant isolation, token refresh, registration renewal, or revocation behavior.
- Budget exhaustion and rate-limit handling in the selected runtime.
- All 13 tools individually; only `get_work`, `resolve_references`, `search_works`, and
  `analyze_works` were exercised.
- Discovery Studio/app build identification; only the selected APIs, model deployment, and region
  were recorded.
