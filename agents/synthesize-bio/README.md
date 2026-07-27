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

Authentication to the MCP endpoint uses the caller's Synthesize Bio account (OAuth). Usage and budget limits are enforced by the Synthesize Bio API.

## Prerequisites

- A Microsoft Discovery workspace (cloud) or Microsoft Discovery app environment with a chat model deployment for `{{CHAT-MODEL}}`.
- A Synthesize Bio account — register at https://www.synthesize.bio/.
- Network access from the Discovery runtime to `https://app.synthesize.bio/api/mcp`.
- For raw counts downloads via `get_counts_data_url`, an environment with shell or Python network access.

## Configuration

| Parameter | Description | Example |
|---|---|---|
| `{{CHAT-MODEL}}` | Azure AI Foundry / Discovery chat model deployment name | `gpt-4o-deployment` |

| Setting | Required | Description |
|---|---|---|
| MCP endpoint | ✅ | `https://app.synthesize.bio/api/mcp` (declared on the MCP tool connection) |
| Synthesize Bio OAuth | ✅ | User signs in with their Synthesize Bio account when prompted |

No container image, ACR, or Discovery-managed `tools/` package is required for this agent.

## Usage

1. Deploy or enable the agent from the Discovery Catalog / Discovery Studio.
2. Ensure the chat model parameter `{{CHAT-MODEL}}` points at your deployment.
3. Authenticate to Synthesize Bio when the MCP connection prompts for OAuth.
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
- MCP OAuth is user-interactive; enterprise deployments may need additional connector / network configuration in Azure.

## Contributing

See [CONTRIBUTING.md](../../CONTRIBUTING.md) for the Discovery Catalog contribution workflow.

For product support, contact support@synthesize.bio or visit https://www.synthesize.bio/.

Privacy policy: https://www.synthesize.bio/privacy
