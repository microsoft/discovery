# Open Targets Evidence

## Overview

This draft prompt agent targets the Discovery Studio and Microsoft Foundry workflow. It retrieves a small, traceable sample of Open Targets disease-target associations and individual evidence for research triage, not clinical advice or treatment selection. The disease, phenotype, and research question are user decisions. The supplied psoriasis example is only a diagnostic exercise. A manually configured Studio/Foundry agent has undergone limited user-observed smoke tests; deployment from this catalog YAML remains unverified.

## Architecture

The agent uses a model deployment and the provider-maintained [Open Targets Platform MCP](https://github.com/opentargets/platform-mcp) at `https://mcp.platform.opentargets.org/mcp`. Its instructions request small read-only GraphQL queries and separate association scores from individual evidence. The MCP server is external and experimental; the catalog definition does not provision, host, or license the service. No custom wrapper or container is included.

The output includes disease and target identifiers, retrieved evidence identifiers and source links, query parameters, date when available, data release when actually returned, and explicit uncertainties. If the user omits a target or evidence limit, the agent defaults respectively to at most two target associations or one individual evidence record per selected target. It reports successful earlier results as partial if a later call fails. The agent cannot guarantee source verification or scientific completeness.

## Prerequisites

Use an authorized Discovery Studio and Foundry environment, an existing compatible model deployment, network access to the hosted endpoint, and a way to review MCP calls. The draft requests anonymous access and per-call approval; actual support, tool restrictions and approval enforcement must be verified in the target runtime. The Microsoft publisher block in `metadata.yaml` is provisional and needs owner confirmation before submission.

## Configuration

Set `{{CHAT-MODEL}}` to an existing model deployment. See the [MCP connection and testing guide](mcp/README.md) for all five tools, connection details, rights, setup, runtime distinctions and limitations, and [test results](TEST_RESULTS.md) for observed checks and gaps. The guide is included in this package; it does not add a server or wrapper.

## Usage

Provide a disease and a clear phenotype and research question. For a diagnostic test only:

> Using the Open Targets MCP, investigate psoriasis `MONDO_0005083`. Retrieve at most two target associations with indirect disease propagation disabled and at most one individual evidence record per target. Discover the schema yourself, report the data release if available, retain source identifiers and links, and clearly identify missing or unverified information. Do not make a treatment recommendation.

No scientific GraphQL query is supplied. Inspect actual tool calls, output, and errors; a fluent answer alone is not proof of a call. The diagnostic sample is not an exhaustive evidence review or scientific prioritization.

## Known Limitations

- The scope and disease phenotype must be agreed with a scientist before a real comparison. A small first page is not exhaustive and may not establish a ranking.
- Retrieval sizes, call counts and batch sizes are prompt-level instructions, not runtime-enforced ceilings. The GraphQL tools can accept larger queries and batches; use a runtime or service-side limiter if hard resource bounds are required. The MCP tool allowlist and requested per-call approval are separate controls whose effective behavior must be verified in the target runtime.
- Schema fields and results may change; live introspection, permission and network failures must be surfaced rather than guessed. When a data release or citation is unavailable, state that it was not returned.
- Registry records, regulatory assessments, conference abstracts and individual primary research publications are different evidence types. A link constructed from an identifier is not independent verification. An association score is not a probability, causal effect, or clinical benefit.
- The definition requests disabling Discovery-injected and data-handling tools. Actual runtime enforcement and complete isolation from other host capabilities have not been verified; the flags and prompt instructions do not establish a sandbox.
- The provider labels Platform data CC0 and describes permissions for listed data sources; its terms also note original-owner and third-party rights. Independently check the rights and attribution of any original publication or dataset before redistribution.
- Publishing this definition will not provision the external MCP server, a model, access rights, or a separately published skill. A manually configured Studio agent was opened in Foundry, where the user observed a basic approved MCP search and a no-match test; full enforcement of tool restrictions and approvals remains unverified. In Discovery Preview App, a user-confirmed custom chat agent made bounded native MCP calls and produced a technical evidence sample. Complete raw responses were not independently verified for these interactive tests. They do not establish deployment from catalog YAML or enterprise readiness.

## Contributing

Follow the [Discovery agent authoring guide](../../docs/authoring-guides/agent-authoring-guide.md) and [contribution guidance](../../CONTRIBUTING.md). The provisional publisher details require confirmation by the responsible owner.
