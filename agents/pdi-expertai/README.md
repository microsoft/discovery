# Protocol Design Intelligence (PDI) Agent

Connect protocols, trials, and scientific evidence to guide evidence-based clinical study design.

Published by [expert.ai](https://www.expert.ai/).

## Overview

The Protocol Design Intelligence (PDI) Agent discovers and analyzes historical clinical trials and related scientific publications to identify the most relevant precedents for a proposed study.

The agent combines protocol similarity analysis, clinical outcomes assessment, and scientific evidence retrieval to evaluate protocol characteristics, patient populations, biomarkers, investigational therapies, endpoints, operational design, and clinical outcomes. By incorporating evidence from peer-reviewed publications, the agent explains similarities and differences, surfaces supporting evidence, and generates actionable insights to help optimize study design, assess feasibility, and improve the likelihood of success.

The PDI Agent uses the PDI repository to perform protocol benchmarking, similarity analysis, publication retrieval, and evidence-based study design recommendations.

### Why this agent?

Clinical trial teams often spend significant time reviewing protocols, trial registries, and scientific publications to identify relevant precedent studies and supporting evidence.

The PDI Agent accelerates this process by combining protocol similarity analysis, clinical outcomes assessment, and scientific evidence retrieval into a single explainable workflow. By connecting protocol design decisions with historical trial experience and published evidence, the agent helps study teams make more informed, evidence-based decisions during clinical trial planning and optimization.

### Key differentiators

- Combines clinical trial protocols, outcomes, and scientific publications in a single workflow
- Uses multidimensional similarity assessment rather than keyword matching
- Provides explainable similarity reasoning and supporting evidence
- Connects protocol design decisions with historical trial outcomes
- Designed for Microsoft Discovery and MCP-based scientific workflows
- Extensible to additional therapeutic areas through ontology and data expansion

### What the agent returns

Given a proposed clinical trial protocol, the agent returns:

- Similar historical studies
- Supporting scientific publications
- Similarity explanations
- Relevant clinical outcomes
- Evidence-based protocol design insights

### Data sources

The current dataset includes:

- Global clinical trial registry data
- Peer-reviewed scientific publications
- Life Sciences ontologies and controlled vocabularies
- expert.ai normalized protocol and clinical concept models

## Architecture

The PDI Agent leverages:

- Curated clinical trial data from major registries
- Peer-reviewed scientific publications
- expert.ai normalized clinical concepts, protocol attributes, and ontology-driven data harmonization
- Protocol similarity services across disease, biomarker, therapy, endpoint, population, operational, and outcome dimensions
- Similarity and evidence-analysis services exposed through MCP interfaces

This is a prompt agent wired to the hosted PDI MCP server. Data and search run on expert.ai infrastructure; Discovery only holds the catalog metadata and this definition. The tools are read-only.

```text
User prompt
  → get_trial / get_medline             (exact lookup by registry id or PMID)
  → describe_search_fields              (field names, types, vocabulary)
  → search_documents                    (structured Elasticsearch query, counts, aggregations)
  → find_similar_documents              (similar trials/publications to an id or a draft protocol)
  → compare_documents                   (per-dimension similarity of 2–5 studies)
  → find_drugs_for_disease              (drugs used for a condition)
  → find_combination_drugs_for_drug     (drugs combined with a drug, phase/status breakdown)
```

Similarity is scored by two models, and the agent reports their per-category scores as the evidence for each match:

- **Protocol Similarity** compares study design: disease, biomarker, drug/class, endpoint, population, phase/design, inclusion and exclusion criteria, geography.
- **Clinical Evidence Similarity** compares reported results: efficacy, safety, and success/failure. It is available only when both documents have reported results.

Authentication to the MCP endpoint uses a static PDI access token sent as an `Authorization` Bearer header.

## Prerequisites

- A Microsoft Discovery workspace (cloud) or Microsoft Discovery app environment with a chat model deployment for `{{CHAT-MODEL}}`.
- A PDI access token. Request one from expert.ai at CRN@expert.ai.
- Network access from the Discovery runtime to `https://pdi.expertcustomers.ai/mcp/pdi` (HTTPS, port 443).

## Configuration

| Parameter | Description | Example |
|---|---|---|
| `{{CHAT-MODEL}}` | Azure AI Foundry / Discovery chat model deployment name | `gpt-4o-deployment` |

| Setting | Required | Description |
|---|---|---|
| MCP endpoint | ✅ | `https://pdi.expertcustomers.ai/mcp/pdi` (declared on the MCP tool connection) |
| PDI access token | ✅ | Token issued by expert.ai, sent as an `Authorization` Bearer header (see below) |

If Discovery (or the MCP host) asks for a key name and key value, enter:

```text
Key name:  Authorization
Key value: Bearer YOUR_PDI_TOKEN
```

The key name must be `Authorization`, and the key value must include the `Bearer ` prefix. A missing or wrong token makes the server answer `401`; some hosts then try an OAuth sign-in, which the PDI server does not support.

Keep the token secret and store it in your host's secret store. Do not commit it to version control.

No container image, ACR, or Discovery-managed `tools/` package is required for this agent.

## Usage

1. Deploy or enable the agent from the Discovery Catalog / Discovery Studio.
2. Point the chat model parameter `{{CHAT-MODEL}}` at your deployment.
3. Configure the MCP connection with your PDI token (`Authorization: Bearer YOUR_PDI_TOKEN`).
4. Ask a question.

### Example questions

- What completed breast cancer trials are most similar to my proposed protocol?
- Which studies evaluated comparable patient populations and biomarkers?
- What endpoints were used in similar Phase II and Phase III trials?
- Which publications reported outcomes from these studies?
- What protocol design choices were associated with successful clinical outcomes?
- How does this protocol compare with historical studies in terms of efficacy, safety, and operational feasibility?
- Which published studies provide evidence supporting the use of these biomarkers and endpoints?
- What historical evidence suggests that this protocol design is likely to succeed or face enrollment and operational challenges?

Prompts on specific studies, with the tools they use:

| Prompt | Tools used |
|---|---|
| Find trials and publications similar to NCT02000622. | `find_similar_documents` |
| Compare NCT01740427 and NCT02422615 on eligibility and endpoints. | `compare_documents` |
| What does PMID 28578601 report? | `get_medline` |
| Which drugs are most used in HER2-positive breast cancer trials? | `find_drugs_for_disease` |
| How many phase II trials of pembrolizumab exist, by recruitment status? | `describe_search_fields`, `search_documents` |

Trials are cited by registry id and publications by PMID, linked to their registry record or PubMed page, so every result can be verified at the source. Answers state how many documents matched and how many were examined.

### Deployment options

The Protocol Design Intelligence (PDI) Agent can be deployed:

- As a standalone agent for protocol benchmarking and evidence analysis.
- As part of Microsoft Discovery scientific workflows.
- As a composable component within larger clinical research and trial design solutions.

## Known Limitations

The initial implementation focuses on breast cancer clinical research and leverages clinical trial registry data and scientific publications in oncology. The architecture is designed to support additional therapeutic areas through extension of the underlying data, ontologies, and evidence sources.

- Questions about other diseases return no results, apart from incidental matches such as basket trials that also enrol breast cancer patients.
- For Medline publications, inclusion and exclusion criteria are LLM-derived from the abstract, not taken from a real eligibility section.
- `find_similar_documents` ranks by design fields only and has no overall score; `compare_documents` provides an overall 0–1 score per similarity model.
- Clinical Evidence Similarity is unavailable for draft protocols and for trials that have not reported results.
- Structured searches use controlled vocabulary (phases, patient segments, mechanisms of action); a value not used in the data matches nothing rather than erroring.
- The tools are read-only.
- The endpoint uses a static bearer token; OAuth is not supported.

## Disclaimer

This agent is intended to support clinical research, protocol development, and study planning activities. Results and recommendations are derived from historical clinical trial data and scientific publications and should be reviewed by qualified teams before making study design decisions.

## Support

This agent is published and supported by [expert.ai](https://www.expert.ai/).

For access details, endpoint information, authentication requirements, and support contacts, see the [Support Page](https://pdi.expertcustomers.ai/support).

- Contact, including access token requests: CRN@expert.ai

## Contributing

See [CONTRIBUTING.md](../../CONTRIBUTING.md) for the Discovery Catalog contribution workflow.
