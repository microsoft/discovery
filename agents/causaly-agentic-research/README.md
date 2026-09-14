# Causaly Agentic Research

Biomedical and life-sciences research agent powered by the Causaly Agentic Research platform. It delegates a natural-language biomedical question to Causaly, which searches, reads, and cross-checks evidence across a curated knowledge graph and the primary literature, then returns a narrative answer with per-claim inline citations, a continuable research thread, and — on request — a structured source list. Prefer over the default agent for biomedical interpretation.

The agent is deliberately a transport layer, not an author. It submits, waits, and renders. It does not compose biomedical prose of its own.

## Overview

Biomedical research questions rarely map to a single API call. "Which targets link IL-23 signalling to remission in Crohn's disease, and what is the strongest human data?" requires decomposition, retrieval across several sources, cross-checking of overlapping findings, and an evidence-quality judgement per claim. Causaly Agentic Research performs that whole loop server-side; this agent makes it available inside a Discovery task graph.

**Intended user.** Researchers, computational biologists, and competitive-intelligence teams in pharma and biotech who need answers that survive scrutiny — where the citation matters as much as the claim.

**Successful outcome.** Causaly's answer reproduced exactly as written, with per-claim inline citations intact, a `chatId` that lets the user or a downstream agent continue the same line of inquiry, and — on request — a mechanically-derived source list.

## Architecture

A `kind: prompt` agent with **no containerised tools**. All capability arrives over Causaly's remote MCP server, declared as a Foundry-native `kind: mcp` tool — a standard remote MCP server over Streamable HTTP, authenticated with OAuth 2.1.

```
User question
    │
    ▼
Discovery prompt agent  ({{CHAT-MODEL}})
    │   Streamable HTTP + OAuth 2.1 (per-user, agentic_research scope only)
    ▼
https://med.causaly.com/mcp/v1/agentic-research
    │
    ├─ causaly_research({ query[, chatId] })                → { chatId, messageId, status }   (async)
    ├─ causaly_wait_for_research({ chatId, messageId })     → bounded wait; poll to completion
    ├─ causaly_list_research_chats()                        → past chats, most recent first
    └─ causaly_get_research_chat({ chatId })                → turns, oldest first
    │
    ▼
Causaly extended reasoning: query planning → multi-step retrieval across the
knowledge graph and primary literature → cross-checking → synthesis → citation resolution
    │
    ▼
content.markdown (resolved inline citations) + content.evidence (keyed bibliography)
```

**Why the two-call contract dominates the instructions.** `causaly_research` returns identifiers, not an answer. `causaly_wait_for_research` performs a bounded server-side wait, so a single call usually returns while the run is still in flight. Five to twenty poll calls is normal, and a five-to-ten-minute run is not a stall. The instructions treat `running`/`queued` as the expected interim state and distinguish it from two genuinely different failures: a terminal `message.status === 'failed'` (report `message.error`, stop) and a transport-level error with no `message` at all — 401, 5xx — which is retried once and then reported with its status code. Polling also stops after roughly twenty polls or fifteen minutes, reporting elapsed time and the `chatId`. In no case does the agent substitute its own answer.

**Citation fidelity.** `content.markdown` ships with citations already resolved as inline numbered links — `[1](url)` single, `([1](url1); [2](url2))` grouped. The body is relayed verbatim because Agentic Research's inline numbers are its *verified* claim-to-source bindings; rewriting a sentence silently rebinds a citation to text Causaly never attributed it to. The bibliography is deliberately not in the markdown — it lives in `content.evidence`, keyed by `citationId` and carrying `number`, `title`, `externalUrl`, and `internalUrl`. A `**Sources**` block joins it on `number`, preferring `internalUrl` and falling back to `externalUrl`, and is produced **only when the user asks for one** — the trigger is an explicit request in the prompt, never the agent's own judgement about answer length. A light integrity check runs only when that block is produced: an inline `[N]` with no matching `evidence` entry is noted in one line and nothing else is altered — no renumbering, no dropped sentences, and no re-render, since a verbatim re-render is byte-identical and could not fix anything anyway.

**Model role.** The model orchestrates and renders; it is explicitly instructed not to contribute biomedical claims. No sampling options are set — reasoning-model deployments reject `temperature` and `topP`, and relay fidelity is enforced by the instructions rather than by decoding parameters. Any agent output beyond the verbatim block is limited to a single procedural line (status, error, next step).

## Prerequisites

**Azure / Discovery**

- Azure subscription with Contributor role.
- An Azure AI Foundry project with a chat model deployment for `{{CHAT-MODEL}}`.
- Permission to create project connections and configure agents.
- **Every end user needs at least the `Foundry Agent Consumer` role on the project** — OAuth identity passthrough requires it. Prefer it over `Foundry User`, which is intended for agent developers.
- **Every end user must be in the same Microsoft Entra tenant as the Foundry project.** Cross-tenant token exchange is not supported for OAuth identity passthrough, so a CRO or partner-tenant collaborator cannot use this agent from your project.

**Causaly**

- A **Causaly account with Agentic Research enabled**. The MCP server acts on your behalf using your own account and its entitlements — you get exactly the data sources and capabilities you have in the web app.
- The server URL below is the same for everyone, and authentication is interactive OAuth.

If you cannot connect, contact <support@causaly.com>.

## Configuration

### Deploy-time parameters

| Parameter | Description | Value |
|---|---|---|
| `{{CHAT-MODEL}}` | Foundry chat model deployment name | e.g. `gpt-5.5` |
| `{{CAUSALY-CONNECTION-NAME}}` | Name of the Foundry project connection holding the OAuth grant | e.g. `causaly-ar-mcp-server` |

The MCP server URL is **not** parameterised — it is a single fixed public endpoint, hardcoded in `agent.yaml`:

```
https://med.causaly.com/mcp/v1/agentic-research
```

### Authentication — OAuth identity passthrough

Causaly's MCP server is authenticated with OAuth 2.1, user-delegated. The matching Foundry method is **OAuth identity passthrough** — the only one of Foundry's five auth methods that preserves per-user context, which this agent requires: each person consents individually, everyone sees only their own Causaly research, and the grant covers Agentic Research alone. Adding the connection once for a project does not share research chats between colleagues.

Foundry offers two OAuth variants. Causaly's server supports **dynamic client registration (DCR)**. Foundry, however, never initiates DCR — it supports only *managed OAuth* (where Microsoft or the MCP server publisher owns the app registration) or *custom OAuth* (where you bring your own). So DCR support on Causaly's side does not remove the registration step on Foundry's side.

**Custom OAuth — the path available today.** Configure the connection in the Foundry portal (**Tools** → **Custom** → **MCP** → **OAuth Identity Passthrough**) or via the CLI, supplying:

| Field | Required | Value |
|---|---|---|
| Client ID | ✅ | From your registered Causaly OAuth client |
| Client secret | optional | Depends on the OAuth app; a PKCE public client may not need one |
| Auth URL | ✅ | Causaly authorization endpoint |
| Token URL | ✅ | Causaly token endpoint |
| Refresh URL | ✅ | The token URL is acceptable if there is no separate refresh endpoint |
| Scopes | recommended | `agentic_research offline_access` — **space-separated**, per the OAuth 2.0 spec |

Include `offline_access`. Without it tokens are not auto-refreshed and users hit "Your session has expired. Please reauthenticate" once the access token lapses.

Because Causaly's OAuth 2.1 flow is authorization-code + PKCE, the client secret may be omissible — worth testing before requesting one. Request a registered OAuth client for your Foundry project from Causaly (<support@causaly.com>).

After configuring, Foundry hands you a **redirect URL**. It must be added to the Causaly OAuth app before the flow can complete, so pass it back to Causaly as part of the registration request.

Set `{{CAUSALY-CONNECTION-NAME}}` to the connection name; it is referenced as `project_connection_id` on the MCP tool. If the connection and `server_url` disagree on the endpoint, the connection wins.

**Managed OAuth — the frictionless path, if Causaly pursues it.** Managed OAuth removes the client registration entirely, but requires the MCP server publisher to be onboarded with Microsoft. If Causaly registers as a publisher, this agent's configuration collapses to the URL plus a sign-in.

### First-run consent

OAuth identity passthrough is per connection, per user, per project. The first time a given user triggers the tool, the run returns an `oauth_consent_request` item carrying a `consent_link` instead of an answer; the user opens it, signs in to Causaly, and approves. The call is then resubmitted with the previous response ID. Subsequent calls for that user succeed without prompting. If a user declines, the tool call fails and must be handled as an error — not substituted with a model-authored answer.

### Tool-approval policy

`require_approval: never` is set for the four allowed tools. Three are read-only; `causaly_research` is not — it creates a chat turn in the user's own Causaly history and consumes their entitlement. None of the four touches anything outside that user's account. If your governance model requires a human in the loop, note that `always` (the Foundry default) prompts on *every* poll call, which is impractical when a run legitimately needs twenty of them. Prefer approving submission but not polling:

```yaml
require_approval:
  always: [causaly_research]
```

That gates question submission only; the three read operations proceed unprompted. Foundry documents four accepted values — `always`, `never`, `{"never": [...]}` and `{"always": [...]}` — so use one key, not both.

Note that approval is a separate gate from OAuth consent — a user may need to clear both on their first call.

## Usage

1. Create the Foundry project connection (see [Authentication](#authentication--oauth-identity-passthrough)).
2. Deploy the agent via Discovery Studio, supplying `{{CHAT-MODEL}}` and `{{CAUSALY-CONNECTION-NAME}}`.
3. Complete the OAuth sign-in on first invocation.
4. Ask a biomedical question.

### Sample prompts

| Prompt | What it exercises |
|---|---|
| "What is the evidence linking IL-23 inhibition to remission in Crohn's disease? Summarise by mechanism and give me the strongest human data." | Mechanistic synthesis with evidence tiering |
| "What are the reported safety signals for GLP-1 receptor agonists in patients with a history of pancreatitis, and where is the evidence conflicting?" | Safety signal review, conflict surfacing |
| "Research the competitive landscape for TREM2 agonists in Alzheimer's disease, then put the results in a table with mechanism, stage, and sponsor." | Landscape scan with structured output |
| "Which novel NASH targets have entered clinical development since 2023, and what is the biological rationale for each?" | Time-bounded target discovery |
| "Summarise the genetic evidence supporting PCSK9 as a cardiovascular target, and list the references." | Target validation **with** an explicit source-list request |

The last row matters: the `**Sources**` block is produced only when the prompt asks for it. Without a phrase like "list the references" or "with sources", the answer arrives with inline citations but no appended bibliography.

### Multi-turn research

Every answer carries its `chatId`. Passing it back continues the thread with full context, which is materially better than restating the question — Causaly folds prior turns into its reasoning. **A chat runs one question at a time**; a second turn submitted while the first is still running is rejected with a conflict, so the agent polls the first to completion and then resubmits. For a genuinely parallel question it omits `chatId` and starts a separate chat.

Research started here appears in the user's history at [med.causaly.com](https://med.causaly.com), and the agent can read chats started in the web app. It is one research history, reachable from both.

### Use in a Discovery task graph

The agent is designed to be the evidence-gathering step upstream of computation:

| Pipeline | Role |
|---|---|
| Target identification → structure prediction | Establish and cite target rationale before `alphafold` / `boltztwo` |
| Lead assessment → docking | Gather known SAR and safety evidence before `autodock` / `chemprop` |
| Indication expansion → trial design | Assemble mechanistic evidence before `clinical-trials` |

Downstream agents need the citations and the `chatId` as much as the prose, and must never be handed a summary in place of the verbatim block.

## Known Limitations

- **Requires a Causaly account with Agentic Research.** There is no free or public tier, and no key-based service-account path for the MCP server — access is per-user OAuth.
- **Latency is inherent, not incidental.** Runs take minutes and many poll calls; budget for it in task-graph timeouts. A single wait returning "still running" is expected.
- **Polling stops after roughly twenty polls or fifteen minutes.** The agent then reports the elapsed time and the `chatId` rather than answering, so a very long run needs to be resumed deliberately.
- **Same-tenant only.** End users must share the Foundry project's Entra tenant; cross-tenant passthrough is unsupported.
- **Interactive first-run authorization.** OAuth consent needs a human with a browser once per user, per connection, per project — so fully unattended first use is impossible, and an unattended scheduled task will fail for any user who has not already consented.
- **Foundry requires a pre-registered OAuth client.** Causaly's server supports dynamic client registration, but Foundry never initiates DCR, so a client ID (and possibly a secret) must be obtained from Causaly and Foundry's redirect URL registered against it. This is the one setup step that is materially heavier here than in Claude, ChatGPT, or Cursor.
- **`offline_access` is effectively mandatory.** Omit it from the scopes and users get session-expiry failures once the access token lapses.
- **One question at a time per chat.** Parallelism requires separate chats.

## Support

For the Causaly platform or connection problems, contact <support@causaly.com>.

## Contributing

See the catalog's [CONTRIBUTING.md](../../CONTRIBUTING.md) for the contribution workflow, and the [Agent authoring guide](../../docs/authoring-guides/agent-authoring-guide.md) for the schema contract.
