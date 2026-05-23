# PatentPro — Patent Prior-Art Stress Test Agent

An LLM-only Microsoft Discovery agent that performs rigorous, claim-chart-style patent prior-art stress tests. Designed for patent analysts, IP counsel, and R&D teams who need structured novelty assessments with evidence-backed coverage ratings.

## Overview

Evaluating the novelty of a patent claim requires systematic decomposition of the claim into atomic elements, broad prior-art searching, and careful mapping of evidence to each element. This process is time-intensive and demands both legal and technical expertise.

PatentPro automates the technical analysis portion of this workflow. Given a draft patent claim or invention description, it:

1. **Decomposes** claims into atomic, testable elements (E1, E2, …)
2. **Designs** targeted search strategies with synonym expansion and classification codes
3. **Extracts** verbatim evidence spans from candidate prior-art documents with location pointers
4. **Generates** claim charts mapping each element to evidence with Full 🟢 / Partial 🟡 / Missing 🔴 coverage ratings
5. **Produces** an executive risk summary with overall risk level (HIGH / MODERATE / LOW), weakest elements, and narrowing strategies

The intended user is a patent analyst, IP attorney, technology scout, or R&D engineer who needs a structured prior-art assessment. A successful outcome is a complete claim chart with evidence-backed ratings and an actionable risk summary.

> **Disclaimer:** PatentPro provides informational and technical analysis only. It does NOT constitute legal advice. Results should be reviewed by qualified patent counsel before making legal or business decisions.

## Architecture

`
User Input (claim text or invention description)
    → PatentPro Agent (LLM: {{CHAT-MODEL}}, temperature 0)
        → Claim decomposition (atomic elements)
        → Search strategy design (synonym expansion, CPC/IPC codes)
        → Evidence extraction (verbatim spans with location pointers)
        → Claim chart generation (element → evidence → coverage rating)
        → Executive risk summary
    → Structured output (claim chart + risk assessment)
`

**Agent type**: LLM-only — no Dockerfile, no tool container, no `tool.yaml`. All reasoning, decomposition, and analysis are performed by the language model.

**Model**: `{{CHAT-MODEL}}` — selected for strong structured-output and analytical reasoning capabilities. Temperature is set to 0 for deterministic, reproducible analysis.

**Data flow**:

1. The user provides a patent claim or invention description, optionally with CPC/IPC codes, keywords, assignees, jurisdictions, or date constraints
2. The LLM decomposes the claim into atomic elements and presents them for confirmation
3. The LLM designs a search strategy and retrieves candidate prior-art references
4. Evidence spans are extracted verbatim with source locations
5. Each element is mapped to evidence with a coverage rating and justification
6. An executive summary is produced with overall risk, weak elements, and narrowing directions
7. Key results are stored in `variable_store` for downstream pipeline use

**External dependencies**: None beyond the LLM deployment. No container, no external API calls from a tool.

## Prerequisites

- Microsoft Discovery workspace
- Azure AI Foundry project with a model deployment for `{{CHAT-MODEL}}`
- No compute node pool required (LLM-only agent)
- No container registry access required

## Configuration

### Agent parameters

| Parameter | Description | Example |
|---|---|---|
| `{{CHAT-MODEL}}` | Azure AI Foundry model deployment name | `gpt-4o-deployment` |

### Pipeline variables (stored after analysis)

| Variable | Type | Description |
|---|---|---|
| `patent_claim_text` | string | Original claim text analysed |
| `patent_claim_elements` | array | Parsed atomic elements with IDs, types, and parent references |
| `patent_coverage_ratings` | object | Element ID → {rating, justification} |
| `patent_prior_art_refs` | array | Identified prior-art references with metadata |
| `patent_risk_level` | string | Overall risk: `HIGH`, `MODERATE`, or `LOW` |
| `patent_risk_summary` | string | Executive summary text |

> **Note:** PatentPro has no tool container and no environment variables. The only configurable parameter is the model deployment name.

## Usage

### 1. Publish the agent

```bash
catalog_publish_agent(
  agent_yaml_path="patentpro-agent-definition.yaml"
)
```

> No `tool_yaml_path` is needed — PatentPro is an LLM-only agent.

### 2. Deploy via Discovery Studio

Navigate to the PatentPro agent card in Discovery Studio and click **Deploy**. Fill in the `{{CHAT-MODEL}}` parameter.

### 3. Example prompts

**Claim stress test:**

`
Here is my independent claim for a novel drug delivery system:

"A method for targeted delivery of a therapeutic agent comprising:
(a) encapsulating said agent in a lipid nanoparticle having a diameter of 50-200nm;
(b) conjugating a targeting moiety to the nanoparticle surface;
(c) administering the conjugated nanoparticle to a subject;
wherein the targeting moiety is an antibody fragment specific to CD44."

Stress-test this against prior art and produce a claim chart with evidence spans.
`

**Freedom-to-operate analysis:**

`
I need a freedom-to-operate analysis for this pharmaceutical formulation claim.
Identify existing patents that might cover each element.
`

**ML patent novelty check:**

`
Analyze this patent claim for a machine learning method applied to molecular
property prediction. What is the novelty risk?
`

### 4. Example output

| Element | Claim Language | Prior Art Reference | Evidence Span | Coverage | Justification |
|---------|---------------|-------------------|---------------|----------|---------------|
| E1 | "A method for targeted delivery…" | US10,123,456B2 | "[verbatim]" (para 42) | Full 🟢 | The reference explicitly describes… |
| E2 | "encapsulating said agent in a lipid nanoparticle…" | WO2020/123456 | "[verbatim]" (para 18) | Partial 🟡 | Discloses lipid nanoparticles but not the 50-200nm range… |
| E3 | "wherein the targeting moiety is an antibody fragment specific to CD44" | — | No relevant evidence found | Missing 🔴 | None of the reviewed references address CD44-specific antibody fragments… |

**Executive Summary:** MODERATE RISK — 1 of 3 body elements has full prior-art coverage. The CD44-targeting limitation (E3) provides the strongest novelty position. Consider narrowing E2 with specific lipid composition to strengthen the claim.

## Support

For issues or questions, open a GitHub issue:
https://github.com/microsoft/discovery-catalog/issues

## Known Limitations

No known limitations at this time. If you encounter issues, please report them via the support channel above.

## Contributing

This project welcomes contributions and suggestions. Please see the repository's top-level [CONTRIBUTING guidelines](https://github.com/microsoft/microsoft-discovery-samples/blob/main/CONTRIBUTING.md) for details on how to contribute.