# SandboxAQ AQCat Catalysis Agent

Calculates adsorption and binding energies and surface reactivity for adsorbate-surface systems using SandboxAQ **AQCat**, and ranks how strongly an adsorbate binds across a set of candidate surfaces. Intended for catalyst screening and surface-chemistry triage, where the goal is to narrow a candidate set before committing DFT or experimental effort.

## Overview

Catalyst discovery spends most of its budget on candidates that were never viable. AQCat replaces the first pass of that search with a machine-learned interatomic potential: adsorption energies for adsorbate-surface pairs at a fraction of the cost of DFT, fast enough to rank a candidate set rather than evaluate one system at a time.

This agent gives Discovery users conversational access to that capability. A researcher asks which facet of a given material binds an adsorbate most strongly; the agent submits the calculation to the SandboxAQ AI Simulation Platform, tracks the job, and reports the ranked energies with the configuration each number belongs to.

**Intended user:** computational chemists, catalysis researchers, and materials scientists doing candidate triage.

**Related agents.** [`aqpotency`](../aqpotency/README.md) covers small-molecule potency and selectivity on the same platform and the same connection. [`sandboxaq`](../sandboxaq/README.md) is separate — it prompts a SandboxAQ model you have subscribed to in Azure AI Foundry, and needs no platform tenant.

**Successful outcome:** a ranked, correctly-attributed set of adsorption energies with units intact, each reported with its convergence status and the resolved bulk identifier, plus an explicit statement of which systems fall outside the model's applicability.

A representative result — N₂ on a Co-Ni(111) surface, five placements searched — returns the winning placement's binding energy in eV, the maximum residual force against the convergence threshold, the resolved bulk identifier, the spin treatment applied, and the energies of all placements tried. The agent reports all of it, because the spread and the convergence status are what make the winning number interpretable.

## Architecture

```
Discovery agent (prompt, {{CHAT-MODEL}})
        │
        │  Foundry-native MCP tool (kind: mcp)
        ▼
SandboxAQ AI Simulation Platform MCP server  ({{AQ_MCP_SERVER_URL}})
        │
        ├── AQCat            — adsorption / binding energy, surface reactivity
        ├── aqcat_compare    — cross-surface binding ranking
        └── list_jobs / check_job_status / get_job_results
```

The agent holds no compute of its own and ships no container. It is a prompt agent with a single Foundry-native MCP tool, scoped by `allowedTools` to the AQCat and job-management tools on the platform's MCP server. All calculation happens on SandboxAQ infrastructure.

**Data flow.** The user's request goes in as natural language; the agent maps it to a tool call, receives a job identifier, polls until the job completes, and retrieves results. Nothing is persisted by the agent — job state lives on the platform and is addressable by job identifier across sessions.

**Asynchronous by design.** AQCat submissions are jobs, not synchronous calls. The agent reports the job identifier before it starts polling so work is recoverable if a session ends mid-calculation, and it stops polling and hands the identifier back rather than holding a turn open indefinitely.

## Prerequisites

- An Azure AI Foundry project with a chat model deployment, supplied as `{{CHAT-MODEL}}`.
- Access to a SandboxAQ AI Simulation Platform tenant with AQCat enabled. Contact <support@sandboxaq.com> if your organization does not have one.
- The MCP server URL for your tenant, and a credential that server accepts as a **request header**, stored as a connection in your Azure AI Foundry project. The agent references that connection by name; the credential never enters the agent definition.

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

**Single system**

```
What is the adsorption energy of CO on the Pt(111) surface?
```

**Comparative ranking**

```
Rank CO binding strength across Pt(111), Pt(100), and Pd(111).
```

**Resuming a submitted job**

```
Check on job <job-id> and give me the results if it's finished.
```

## Tools

Provided by the SandboxAQ AI Simulation Platform MCP server; no container images or `tools/` directory are contributed here.

| Tool | Purpose |
|---|---|
| `AQCat` | Adsorption / binding energy and surface reactivity for an adsorbate on a surface |
| `aqcat_compare` | Ranks adsorbate binding strength across multiple candidate surfaces |
| `list_jobs` | Lists jobs submitted from the tenant |
| `check_job_status` | Polls a submitted job |
| `get_job_results` | Retrieves results for a completed job |

The agent prefers `aqcat_compare` for comparative questions rather than assembling its own comparison from separate `AQCat` runs, which are not guaranteed to be commensurable.

## Known Limitations

- **Calculations are metered.** Each submission consumes Relaxation Units on your SandboxAQ account. The agent runs with human-in-the-loop enabled and states the resolved plan and estimated cost for approval before submitting, so a misread request costs a conversation turn rather than compute.
- **Alloy requests are inherently ambiguous.** "Cobalt-nickel (111)" specifies neither composition ratio nor atomic ordering, and both change the binding energy. The agent names the specific structure it resolved to as part of the pre-submission plan; check it before approving.
- **Predictions are from a machine-learned potential, not DFT.** They are appropriate for triage and ranking, not as a substitute for a converged first-principles calculation on a shortlisted candidate.
- **Applicability is bounded by training data.** Unusual elements, heavily distorted cells, and exotic oxidation states may produce confident-looking numbers with no basis. The agent flags these where it can recognize them, but the boundary is not sharply defined and the check is not exhaustive.
- **Asynchronous jobs may outlive a conversation.** Long relaxations will not complete within a single turn; the agent returns a job identifier for later retrieval.
- **No offline mode.** Every calculation requires network access to the platform, and the agent has no local fallback.
- **Interactive-OAuth tenants are not supported** without a header credential — see the authentication note under Prerequisites.
- **The `aqcat-adsorption-spin` skill does not transfer.** Discovery has no skill loader; the workflow it encodes is reproduced in this agent's `instructions` block and may diverge from the skill over time.

## Support

For issues with the agent definition or the platform, contact <support@sandboxaq.com> or use the support channels at <https://www.sandboxaq.com/contact>.

## Contributing

See [CONTRIBUTING.md](../../CONTRIBUTING.md) for the catalog's contribution workflow.
