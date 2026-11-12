# Open Targets Evidence test results

## Scope and environment

These are bounded, read-only diagnostic checks, not clinical advice or a scientific ranking. The psoriasis examples were chosen for testing, not as a final research phenotype. Discovery Preview App 0.15.21 task-agent and custom-chat tests are distinct from a manually configured Discovery Studio agent opened in Foundry. They used earlier agent definitions and do not demonstrate deployment or a runtime retest of the current catalog `agent.yaml`.

The [provider-hosted MCP](https://mcp.platform.opentargets.org/mcp) was accessed without credentials in a limited local test. The catalog definition requests an anonymous connection, five allowed tools, per-call approval and disabling Discovery-injected and data-handling tools; runtime support and enforcement must be assessed separately. See the [MCP guide](mcp/README.md).

## Observed results

| Check | Result |
| --- | --- |
| Preview task agent: positive, 10 November 2026 | Local raw audit retained one entity search and 15 GraphQL calls, including schema discovery and bounded queries. Psoriasis `MONDO_0005083` returned two direct associations, IL12B `ENSG00000113302` and TYK2 `ENSG00000105397`, and one evidence record per target. Platform release was 26.09. This was the first requested page, not an exhaustive or proven ranking. |
| Preview task agent: no match, 10 November 2026 | Raw audit showed an empty search result for the invented input below. The agent stopped without assigning an ID or inferring that a real disease lacks evidence. |
| Preview task agent: invalid GraphQL, 10 November 2026 | Raw audit showed one query for the nonexistent field below. The provider returned `status: error`, `data: null` and `TransportQueryError`; the agent reported the error and stopped. The error label does not prove a network failure. |
| Discovery Preview custom chat, 12 November 2026 | A user-provided activity trace records one search and 11 GraphQL calls, followed by a bounded psoriasis sample. The user separately confirmed the custom agent selected. The complete raw association and evidence responses were not independently accessible. |
| Manual Studio and Foundry | The user created an agent in Studio and opened it in Foundry. Screenshots showed a `search_entities` request for psoriasis, approval and a result containing `MONDO_0005083` as a disease. A later invented-disease search was reported as empty and the agent stopped; its exact input was not retained. The user also supplied a bounded two-target Playground answer, but complete raw responses were not preserved. These are user-observed smoke tests, not independent full-response audits or catalog-YAML deployment tests. |
| Catalog validation | GitHub's [Validate PR](https://github.com/microsoft/discovery/actions/runs/43324601407/job/131553831859) passed for commit `a99bc88506cb149fc039307a30e08ef656fc3c97` and the four agent files in PR #323; this report was not included in that run. The local documentation and TAG-001 checks passed, but the full validator could not run locally because `jsonschema` was unavailable; no dependency was installed. |

The task-agent positive run returned association scores `0.7956555552997787` for IL12B and `0.7396814174441884` for TYK2; association scores are not probabilities, causal effects or evidence scores. The agent labelled a ClinicalTrials.gov link constructed from a returned identifier as unverified. Missing source fields do not establish absence, and original-source rights require review.

## Public test inputs

The following are the actual Preview task descriptions; they do not represent the separate Foundry no-match input.

**Positive**

```text
Diagnostic example only, not a selected clinical phenotype: use psoriasis MONDO_0005083. Independently discover the current schema; no GraphQL query is supplied. Search at most two target associations with no indirect disease propagation and at most one individual evidence record per target. Record stable identifiers, source record IDs and links when returned or constructible, data release if available, variables, uncertainty, and missing data. At most 18 Open Targets MCP calls, one at a time; stop on permission, tool, or schema errors. No file, shell, web, local bridge, unrelated tool, or external write. Do not select or recommend a treatment. Respond in English.
```

**No match**

```text
Diagnostic negative test only: search Open Targets for the deliberately invented disease string "qzvx-8472 fictional disease sentinel" using the available read-only provider MCP. Do not invent a disease identifier, do not claim that a real disease lacks evidence, and do not select a different disease. Report the actual search results and uncertainty. Stop if the query or tool fails. At most two Open Targets calls, one at a time; no files, shell, web, local bridge, unrelated tools, writes, or treatment recommendations. Respond in English.
```

**Invalid GraphQL**

```text
Diagnostic error-handling exercise only. Make at most one read-only Open Targets query_open_targets_graphql call against the existing hosted MCP. Construct a query yourself containing the deliberately nonexistent root field nonexistent_field_for_validation_20261110, so that validation should fail; do not query or infer scientific data. Report the exact returned error and whether any data was returned. If there is a permission, transport, MCP or GraphQL error, stop immediately; no retries or alternatives. Do not invent a successful response. Do not use files, shell, web, local bridges, unrelated tools, writes, or new permissions. Respond in English.
```

## Reproducing the checks

In an authorized Preview project, configure the existing hosted MCP and an agent with the intended permissions, then submit the diagnostic inputs above separately. Inspect actual tool requests, responses, errors and scope; a generated answer alone is not evidence of a successful call. The [MCP guide](mcp/README.md) describes the separate Studio/Foundry test path and its prerequisites. Do not disable approvals or use an alternate connection to bypass an error.

To repeat catalog validation locally, use an approved environment with the repository's [CI requirements](https://github.com/microsoft/discovery/blob/main/.github/requirements-ci.txt) and [validator](https://github.com/microsoft/discovery/blob/main/.github/scripts/validate_pr.py). Supply the changed-file list using the validator's `--changed-files` argument. This local execution remains unperformed.

## Partially verified

- Provider connectivity and MCP calls succeeded in the specific local, Preview and manual Foundry tests described above; these do not establish endpoint access in every environment.
- An approval was observed in one manual Foundry search. Comprehensive per-call approval enforcement has not been established.

## Not tested

- Catalog YAML deployment and connection binding, its effective tool allowlist, and runtime enforcement of the new tool-disabling flags.
- Other error modes, clean-machine installation, multi-user access and enterprise readiness.

## Out of scope

- Hard execution ceilings are not implemented: sample, query and batch budgets are prompt instructions, not runtime-enforced limits. Enforcing ceilings requires provider or runtime capabilities outside this prompt-agent contribution.
- These technical checks do not establish exhaustive evidence, clinical causality or rights clearance. Review Open Targets [licensing and terms](https://platform-docs.opentargets.org/licence) and underlying sources for the intended use.
