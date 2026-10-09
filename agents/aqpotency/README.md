# SandboxAQ AQPotency Agent

Predicts small-molecule binding potency with uncertainty against protein targets using SandboxAQ **AQPotency**, scans molecules against predefined safety, kinome, and proteome panels, and checks selectivity against explicitly named off-targets. Intended for hit triage and lead prioritization ahead of experimental work.

## Overview

Medicinal chemistry programs decide which compounds to make next, repeatedly, under uncertainty. AQPotency supports that decision with a proteochemometric model that predicts potency for a molecule-target pair and reports how much confidence the prediction deserves.

This agent gives Discovery users conversational access to three framings of that question: one compound against one target, one compound against a predefined panel, and one compound against a target and named off-targets. It submits the job to the SandboxAQ AI Simulation Platform, tracks it, and returns per-compound results with uncertainty attached.

**Intended user:** medicinal chemists, computational chemists, and computational biologists prioritizing compounds and assessing off-target liabilities.

**Related agents.** [`aqcat`](../aqcat/README.md) covers catalysis and surface reactivity on the same platform and the same connection.

**Successful outcome:** predicted potencies with uncertainty, correctly attributed to molecule and target, with weakly-supported predictions clearly marked so they are not ranked as though they were confident.

## Architecture

```
Discovery agent (prompt, {{CHAT-MODEL}})
        │
        │  Foundry-native MCP tool (kind: mcp)
        ▼
SandboxAQ AI Simulation Platform MCP server  ({{AQ_MCP_SERVER_URL}})
        │
        ├── AqpotencyPotency      — one molecule, one target (pIC50 + uncertainty)
        ├── AqpotencyScan         — one molecule vs. a predefined panel
        ├── AqpotencySelectivity  — one molecule, target vs. named off-targets
        └── list_jobs / check_job_status / get_job_results / get_credit_balance
```

The agent holds no compute of its own and ships no container. It is a prompt agent with a single Foundry-native MCP tool, scoped by `allowedTools` to the AQPotency prediction and job-management tools. All prediction happens on SandboxAQ infrastructure.

**Data flow.** Molecules enter as SMILES and targets as UniProt accessions. Each prediction tool takes one molecule per call.

**Asynchronous by design.** Predictions are jobs. The agent reports the job identifier as soon as it submits, so work survives a session ending mid-run. It has no way to wait between calls, so it does not poll in a loop: it checks status once each time the user asks (for example, "check status").

## Prerequisites

- An Azure AI Foundry project with a chat model deployment, supplied as `{{CHAT-MODEL}}`.
- Access to a SandboxAQ AI Simulation Platform tenant with AQPotency enabled. Contact <support@sandboxaq.com> if your organization does not have one.
- The MCP server URL for your tenant, and a credential that server accepts as a **request header**, stored as a connection in your Azure AI Foundry project. The agent references that connection by name; the credential never enters the agent definition.
- Awareness of your organization's data-handling policy for proprietary chemical matter: the SMILES you submit are sent to the platform.

> **Authentication note.** Foundry's MCP tool authenticates with a stored connection or static headers; it cannot complete an interactive browser OAuth flow. If your tenant is configured for interactive consent only, request a service token or equivalent header credential from your platform administrator before deploying.

## Configuration

| Parameter | Description | Example |
|---|---|---|
| `{{CHAT-MODEL}}` | Azure AI Foundry chat model deployment name | `gpt-4o-deployment` |
| `{{AQ_MCP_SERVER_URL}}` | Base URL of your tenant's SandboxAQ AI Simulation Platform MCP server | `https://mcp.demo.aisim.sandboxaq.com` |
| `{{AQ_MCP_CONNECTION}}` | Name of the connection in your Foundry project holding the MCP server credential | `sandboxaq-aisim` |

Create the connection in your own Azure AI Foundry project before deploying. The agent definition references it by name and never carries the credential itself, so no secret appears in this catalog entry or in your deployed agent's configuration.

## Usage

1. Deploy the agent from Discovery Studio.
2. Supply the three configuration parameters above.
3. Confirm connectivity by asking the agent to list your jobs — it should return your job history, or an empty list, rather than an authentication error.
4. Ask a question in natural language.

**Single prediction**

```
Predict the potency of CC(=O)Oc1ccccc1C(=O)O against P00533.
```

**Off-target liabilities**

```
Scan this compound against the safety panel: <SMILES>
```

**Selectivity across named targets**

```
Is <SMILES> selective for P00533 over P04626 and P00519?
```

**Retrieving a screen run elsewhere**

```
Show me the top 25 hits from my latest AQPotency screen job.
```

## Tools

Provided by the SandboxAQ AI Simulation Platform MCP server; no container images or `tools/` directory are contributed here.

| Tool | Purpose |
|---|---|
| `AqpotencyPotency` | Predicted potency (pIC50) with uncertainty for one molecule against one target |
| `AqpotencyScan` | Scans one molecule against a predefined panel: `bowes_safety_panel`, `human_kinome`, or `proteome` |
| `AqpotencySelectivity` | Fold-selectivity of one molecule for a target versus explicitly named off-targets |
| `list_jobs`, `check_job_status`, `get_job_results` | Job management |
| `get_credit_balance` | Reports remaining credit when the user asks |

`AqpotencyScan` panels have fixed members; `AqpotencySelectivity` is the tool for a caller-specified set of off-targets. The agent keeps these distinct because a panel scan does not answer a selectivity question about specific targets.

## Known Limitations

- **Library screening is not available from this agent.** `AqpotencyScreen` needs the library uploaded through an interactive upload panel or a shell, and a Foundry agent has neither. Run screens from Claude Desktop or claude.ai; this agent can retrieve and interpret their results by job ID. For a handful of molecules it can call `AqpotencyPotency` once per molecule, which is billed per call and costs more than a screen.
- **Submissions are metered.** The agent's instructions require it to state its plan — tool, molecules, panel, and resolved accessions — and wait for your approval before submitting. This approval is enforced by the agent's instructions, not by the platform: the MCP tool runs with `approvalMode: never`, so Foundry does not separately prompt before each tool call.
- **Predictions are model output, not measurements.** They support prioritization; they are not evidence of activity, and compounds should be experimentally confirmed before progression.
- **Uncertainty is part of the result, not a footnote.** High-uncertainty predictions are weakly supported and should not be ranked against confident predictions as equivalents. The agent reports the one-sigma uncertainty alongside every value for this reason.
- **Ligand similarity bounds what a prediction means.** Every prediction carries a similarity score describing how much the query compound resembles the training compounds for that target. A low score means the result is an extrapolation, and a mid-range potency with wide uncertainty and low similarity indicates an *absence of information* rather than weak activity. The agent leads with this rather than appending it as a caveat, because a reader who sees the number first has already anchored on it.
- **A clean panel scan is not a safety claim.** It is one in-silico signal, over a fixed panel, and says nothing about targets outside that panel.
- **Not for clinical use.** The agent provides no clinical, medical, or dosing advice and its output is not evidence of human safety or efficacy.
- **Accession mapping is a failure mode.** Prose target names must be resolved to accessions; the agent confirms its intended accession rather than assuming, but a wrong accession produces a plausible number for the wrong protein.
- **Jobs can outlive a conversation.** Panel scans in particular may not complete within a turn; the agent returns a job identifier for later retrieval.
- **Submitted molecules leave your environment.** Every prediction sends chemical matter to the platform. Confirm this is permitted under your organization's data-handling policy before submitting proprietary structures.
- **Interactive-OAuth tenants are not supported** without a header credential — see the authentication note under Prerequisites.

## Support

For issues with the agent definition or the platform, contact <support@sandboxaq.com> or use the support channels at <https://www.sandboxaq.com/contact>.

## Contributing

See [CONTRIBUTING.md](../../CONTRIBUTING.md) for the catalog's contribution workflow.
