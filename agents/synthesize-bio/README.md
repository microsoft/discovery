# Synthesize Bio

Generate gene expression from a virtual human.

## Overview

Synthesize Bio lets Microsoft Discovery generate and analyze gene expression data from a virtual human from a natural language prompt. Describe any experiment — "tumor vs normal lung tissue" or "KRAS knockout vs control" — and the platform generates realistic human expression profiles using its Gene Expression Model (GEM). You can use this gene expression data just as if you had done a laboratory experiment on human samples. Supports both bulk and single-cell RNA-seq modalities.

See https://www.synthesize.bio/ to learn more about virtual humans, GEM, and to register for an account.

You can use Synthesize Bio to:

- **Analyze tumor vs normal tissue:** "Use Synthesize Bio to analyze lung adenocarcinoma tumor vs normal lung tissue."
- **Compare cell types in single-cell mode:** "Analyze CD4+ T cells vs CD8+ T cells in single-cell RNA-seq mode using Synthesize Bio."
- **Compare drug toxicity signatures:** "Use Synthesize Bio to predict how hepatocytes respond to doxorubicin vs. valproic acid and compare their toxicity signatures."
- **Find druggable targets:** "Use Synthesize Bio to find druggable targets in idiopathic pulmonary fibrosis by comparing fibrotic vs. healthy alveolar epithelial cells."

## Architecture

This agent is a prompt agent wired to the hosted Synthesize Bio MCP server. Agent code and model weights stay on Synthesize Bio infrastructure; Discovery only holds the catalog metadata and this definition.

```text
User prompt
  → get_metadata_schema
  → (host LLM builds structured sample groups)
  → resolve_sample_metadata  (ontology harmonization; user confirms)
  → analyze_gene_expression  (GEM inference + DESeq2 differential expression)
  → get_analysis_results     (poll until complete)
  → optional get_counts_data_url  (presigned raw counts download)
```

Pipeline steps after confirmation:

1. **GEM** — AI-powered gene expression model inference for each sample group.
2. **Differential expression** — GPU-accelerated DESeq2 (negative-binomial GLM, Wald test, Cook's filter, Benjamini–Hochberg padj).

Authentication to the MCP endpoint uses a Synthesize Bio **platform API key** (Bearer token). Microsoft Discovery does not currently support OAuth for this connector. Usage and budget limits are enforced by the Synthesize Bio API. Full auth reference: https://docs.synthesize.bio/platform/authentication

## Prerequisites

- A Microsoft Discovery workspace (cloud) or Microsoft Discovery app environment with a chat model deployment for `{{CHAT-MODEL}}`.
- A Synthesize Bio account — register at https://www.synthesize.bio/.
- A Synthesize Bio platform API key (see Configuration below).
- Network access from the Discovery runtime to `https://app.synthesize.bio/api/mcp`.
- For raw counts downloads via `get_counts_data_url`, an environment with shell or Python network access.

## Configuration

| Parameter | Description | Example |
|---|---|---|
| `{{CHAT-MODEL}}` | Azure AI Foundry / Discovery chat model deployment name | `gpt-4o-deployment` |

| Setting | Required | Description |
|---|---|---|
| MCP endpoint | ✅ | `https://app.synthesize.bio/api/mcp` (declared on the MCP tool connection) |
| Synthesize Bio API key | ✅ | Platform API key sent as an `Authorization` Bearer token (see below) |

### API key setup

1. Sign in to https://app.synthesize.bio
2. Go to **Account → API Keys**
3. Create a new key and copy it immediately — it is only shown once

MCP URL:

```text
https://app.synthesize.bio/api/mcp
```

If Discovery (or the MCP host) asks for a key name and key value, enter:

```text
Key name:  Authorization
Key value: Bearer YOUR_API_KEY
```

The key name must be `Authorization`. The key value must include the `Bearer ` prefix before the API key. See https://docs.synthesize.bio/platform/authentication#using-the-key

Keep the API key secret. Do not commit it to version control. Rotate keys from the API Keys page as needed.

No container image, ACR, or Discovery-managed `tools/` package is required for this agent.

## Usage

1. Deploy or enable the agent from the Discovery Catalog / Discovery Studio.
2. Ensure the chat model parameter `{{CHAT-MODEL}}` points at your deployment.
3. Configure the MCP connection with your Synthesize Bio API key (`Authorization: Bearer YOUR_API_KEY`).
4. Ask for an experiment in natural language, for example:

| Prompt | Mode |
|---|---|
| Analyze lung adenocarcinoma tumor vs normal lung tissue. | Bulk |
| Analyze CD4+ T cells vs CD8+ T cells in single-cell RNA-seq mode. | Single-cell |
| Predict how hepatocytes respond to doxorubicin vs. valproic acid and compare their toxicity signatures. | Bulk / toxicity |
| Find druggable targets in idiopathic pulmonary fibrosis by comparing fibrotic vs. healthy alveolar epithelial cells. | Target discovery |

5. Review the resolved sample-group table the agent presents, then confirm before analysis starts.
6. When complete, use the ranked gene results, volcano-ready `plot_results`, and the platform `dataset_link`.

## Known Limitations

- Requires a Synthesize Bio account and remaining usage quota; quota errors include a request-higher-limits URL.
- Public models cover a defined set of tissues, diseases, and perturbations. Out-of-coverage requests surface partnership guidance rather than silent invention of vocabulary.
- `get_counts_data_url` returns multi-megabyte artifacts; only fetch them from environments with direct network and shell/Python tooling.
- This catalog entry does not ship a Discovery-managed container tool — compute runs on Synthesize Bio's hosted MCP service.
- Microsoft Discovery currently requires API key auth for this MCP connection (OAuth is not supported by Discovery for this integration yet). Store keys in your host's secret store; never embed them in catalog YAML.

## Contributing

See [CONTRIBUTING.md](../../CONTRIBUTING.md) for the Discovery Catalog contribution workflow.

For product support, contact support@synthesize.bio or visit https://www.synthesize.bio/.

Privacy policy: https://www.synthesize.bio/privacy
