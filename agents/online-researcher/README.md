# onlineResearcher — LLM-Only Scientific Research Agent

## Overview

**onlineResearcher** is an LLM-only agent (no compute tools) for the Microsoft Discovery platform.
It conducts state-of-the-art research analyses in scientific, engineering, and medical fields,
providing comprehensive answers with:

- **Full citations** — numbered inline references [1], [2] with a complete reference list
- **Confidence assessments** — explicit 5-tier ★ rating for every major finding
- **Critical evaluation** — source quality assessment, conflict identification, gap analysis
- **Domain expertise** — scientific, engineering, medical, and interdisciplinary research

## Agent Type

| Property | Value |
|----------|-------|
| Type | LLM-only (no compute tools) |
| Dockerfile | None |
| Tool definition | None |
| Container | None |
| Execution | Entirely via LLM reasoning |

## Key Capabilities

| Capability | Description |
|-----------|-------------|
| Literature review | Systematic review of a topic with tiered source quality assessment |
| Comparative analysis | Structured comparisons of therapies, materials, methods with per-cell citations |
| Trend analysis | Timeline of milestones, inflection points, emerging directions |
| Gap analysis | Map known vs. unknown, classify and prioritize research gaps |
| Confidence quantification | 5-tier framework from ★★★★★ VERY HIGH to ★☆☆☆☆ SPECULATIVE |
| Cross-domain synthesis | Bridge terminology and methods across scientific disciplines |

## Confidence Framework

| Level | Label | Range | When Used |
|-------|-------|-------|-----------|
| ★★★★★ | VERY HIGH | >95% | Textbook consensus, fundamental laws, meta-analyses |
| ★★★★☆ | HIGH | 80–95% | Multiple RCTs, well-replicated studies |
| ★★★☆☆ | MODERATE | 50–80% | Single studies, preliminary data, validated predictions |
| ★★☆☆☆ | LOW | 20–50% | Pilot studies, limited evidence, significant conflicts |
| ★☆☆☆☆ | SPECULATIVE | <20% | Extrapolations, emerging hypotheses, minimal evidence |

## Usage

### Basic Research Questions

| Prompt | Description |
|--------|-------------|
| "What are the current best practices for PROTAC design in targeted protein degradation?" | Focused medicinal chemistry review |
| "Compare CRISPR-Cas9 vs. base editing vs. prime editing for therapeutic gene editing" | Structured comparison with evidence tiers |
| "What is the current state of solid-state battery electrolytes for EV applications?" | Materials engineering review |

### Advanced Research Questions

| Prompt | Description |
|--------|-------------|
| "Identify research gaps in using machine learning for antibiotic resistance prediction" | Gap analysis with prioritized opportunities |
| "Review the evolution of checkpoint inhibitor therapy from 2011 to present" | Trend analysis with timeline and milestones |
| "What are the safety concerns and regulatory landscape for AI-designed drug candidates?" | Cross-domain (regulatory + AI + pharma) analysis |

### Integration with Other Agents

onlineResearcher is designed to work as the "research brain" in multi-agent pipelines:

| Workflow | Role |
|----------|------|
| Drug discovery pipeline | Research target biology, mechanism of action, competitive landscape before docking |
| Materials design | Review literature on target properties and known candidates before DFT/MD simulations |
| Clinical study design | Review existing evidence and guidelines before querying ClinicalTrials agent |

## Deployment

Since this is an LLM-only agent, deployment only requires publishing the agent definition:

```bash
# No Docker build needed
# No tool definition needed
# Just publish the agent definition
catalog_publish_agent(agent_key="onlineResearcher", ...)
```

## File Structure

```
onlineResearcher/
├── onlineResearcher-agent-definition.yaml   # Agent definition with instructions
└── README.md                                 # This file
```

## Known Limitations

- **No live internet access** — relies on LLM training data; cannot perform real-time database queries
- **Knowledge cutoff** — findings may not reflect the very latest publications
- **Citation precision** — some citation details may be approximate; always verify critical references
- **No computation** — cannot run simulations, calculations, or data analysis; use companion compute agents for those tasks

## Architecture

This agent operates as a `kind: prompt` LLM-only agent within Discovery Studio — no containerized tools are required.

    User Input → Online Researcher (LLM + Web Search) → Structured Research Output

- **Model:** Configured via the `{{model}}` parameter at deploy time
- **Tools:** Built-in web search for real-time literature retrieval

## Prerequisites

- Azure subscription with Contributor role
- Azure AI Foundry project with a model deployment (e.g. GPT-4o)

## Configuration

| Parameter | Description | Example |
|---|---|---|
| `{{model}}` | Azure AI Foundry model deployment name | `gpt-4o` |

## Support

For issues or questions, open a GitHub issue:
<https://github.com/microsoft/discovery-catalog/issues>

Microsoft Discovery team contact: discovery-catalog@microsoft.com

## Contributing

This project welcomes contributions and suggestions. Please see the repository's top-level [CONTRIBUTING guidelines](https://github.com/microsoft/microsoft-discovery-samples/blob/main/CONTRIBUTING.md) for details on how to contribute.