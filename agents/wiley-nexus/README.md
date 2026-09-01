# Wiley Nexus — Scholarly Research Agents

Research agents grounded in Wiley's peer-reviewed scholarly corpus, reached through the
[Wiley Nexus](https://nexus.wiley.com/playground/docs/v1/getting-started/overview) MCP server. The agent is
instructed to ground every factual claim in a publication it retrieved during the conversation, rather
than in model memory, and to end with IEEE-numbered references linked to Wiley Online Library.

## Overview

**NexusResearcher** is the agent defined in this folder's `agent.yaml`. It answers a scientific or technical
question end to end: it plans the query, searches the Nexus corpus from several distinct angles
(letting each result set sharpen the next), optionally reads the most on-point papers in full, and
returns a citation-backed synthesis. It then stays in the conversation to handle follow-ups from the
evidence already gathered, without re-running the whole search.

It works in two modes:

| Mode | When it applies | What you get |
| --- | --- | --- |
| **Research** | A new substantive question needing an evidence base from scratch | A structured, IEEE-cited answer — or a results table if you only asked for the papers |
| **Follow-up** | A question building on an answer already given in the conversation | A short conversational reply, grounded in papers already in play, with at most a targeted single retrieval |

Alongside the interactive agent, this folder ships an optional **three-agent Discovery Engine
pipeline** for autonomous literature reviews, where each shortlisted paper is analyzed in its own
parallel task. See [`tasks/`](tasks/README.md).

## Architecture

`NexusResearcher` is a prompt agent — no containerized tools, no custom compute. It calls two remote
tools over the Wiley Nexus MCP server, plus Discovery's built-in resource tools to persist its
finished answer.

```mermaid
flowchart LR
    U(["Research question"]) --> R["NexusResearcher<br/>(prompt agent)"]
    R -->|search_publications| N[("Wiley Nexus<br/>MCP server")]
    R -->|download_publication| N
    R --> A(["IEEE-cited answer<br/>(saved as an asset for substantive reviews)"])
```

The optional pipeline splits the same work across three specialists so that each paper is read in an
isolated context, in parallel:

```mermaid
flowchart LR
    S["NexusSearch<br/>gather evidence"] --> F["NexusFullTextAnalyzer<br/>one task per paper"]
    F --> W["NexusWriter<br/>compose the answer"]
    S -.->|passages| W
```

## Prerequisites

- A Microsoft Discovery workspace and project, with a chat model deployment available to the project.
- **A reasoning model.** These agents are written for and tested with a reasoning model
  (`gpt-5-5`). Reasoning models do not accept `temperature` or `topP`, which is why `agent.yaml` sets
  no model `options`.
- **A Wiley Nexus API key**, for the MCP connection. Nexus is a Wiley commercial service; see the
  [Wiley Nexus documentation](https://nexus.wiley.com/playground/docs/v1/getting-started/overview)
  for access.
- Permission to add a tool in the Microsoft Foundry project behind your Discovery workspace.

## Configuration

`agent.yaml` uses the `{{CHAT-MODEL}}` placeholder for the model deployment — supply your own
deployment name at deploy time, and leave the model options unset.

Deploy the agent to your project (or create it in Discovery Studio from `agent.yaml`) and **save** it
before connecting the tool — the *Open in Foundry* button appears only on a saved agent.

The agent declares no `tools:` array. Nexus is reached through a remote MCP connection that carries a
per-customer API key, so it cannot be described in the catalog and is connected per project instead:

| Setting | Value |
| --- | --- |
| Name | `nexus-domains` |
| Remote MCP Server endpoint | `https://nexus.wiley.com/mcp/` |
| Authentication | Key-based |
| Credential | Key `X-Api-Key`, value = your Wiley Nexus API key |
| Approval | **Always auto-approve all tools** |

> Approval must be set to auto-approve. The default asks for confirmation before every single tool
> call, which interrupts an interactive session constantly — and in an autonomous task run there is
> nobody to confirm at all, so the agent stalls indefinitely.

**[`mcp/README.md`](mcp/README.md) is the full walkthrough**, with a screenshot for each step. The API
key lives only in that Foundry connection — never in an agent definition, a task description, or this
repository.

## Usage

Once the MCP tool is connected, address the agent in a Discovery Studio session:

```text
@NexusResearcher What is the evidence on influenza vaccine effectiveness for preventing
influenza illness in adults?
```

It will search, optionally read a couple of papers in full, and answer with numbered citations. Then
follow up conversationally:

```text
What about adults over 65?
Which of those studies was largest?
Give me the full text of #2.
```

Ask for papers rather than prose and you get a table instead:

```text
@NexusResearcher Find recent papers on microplastic toxicity in freshwater invertebrates.
```

For autonomous, multi-paper literature reviews driven by the Discovery Engine, use the pipeline in
[`tasks/`](tasks/README.md) — it includes the three specialist agent definitions and the task field
values to transcribe.

## Known Limitations

- **Full text is not always available.** A search hit without a download token has no retrievable
  full text; the agent cites such papers from their passages instead and flags the limitation.
- **Download tokens are short-lived** and belong to the search that produced them. The agent runs a
  fresh search to obtain a new token when one has expired.
- **Full-text reads are capped** — at most two per question in interactive mode, because full-text
  HTML is large and consumes context quickly. The pipeline in [`tasks/`](tasks/README.md) exists
  precisely to lift that ceiling by giving each paper its own task.

## Support

For questions about the Wiley Nexus service, corpus coverage, or API access, see the
[Wiley Nexus documentation](https://nexus.wiley.com/playground/docs/v1/getting-started/overview) or
contact `nexus@wiley.com`.

For issues with this catalog entry, open a discussion in the
[Microsoft Discovery repository](https://github.com/microsoft/discovery/discussions).

## Contributing

Improvements to these agent definitions are welcome. Please read
[CONTRIBUTING.md](../../CONTRIBUTING.md) in the repository root for the catalog's submission flow,
schema requirements, and PR checks.
