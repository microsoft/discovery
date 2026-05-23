# COCONUT — Natural Products Database Agent

A Microsoft Discovery agent for searching and retrieving natural product data from the COCONUT (COlleCtion of Open NatUral producTs) database. Enables researchers and cheminformatics specialists to query over 400,000 natural product molecules by structure, molecular properties, organism, and taxonomic classification.

## Overview

Natural product discovery requires efficient access to large, curated molecular databases. COCONUT is one of the largest open collections of natural products, but navigating its API and interpreting results demands domain expertise.

This agent solves that problem by providing a conversational interface to the COCONUT v2.0.0 REST API. It enables:

- **Structure search** — query by SMILES, InChI, InChIKey, substructure, or Tanimoto similarity
- **Property-based filtering** — filter by molecular weight, LogP, TPSA, Lipinski parameters, sugar content, and NP-likeness
- **Taxonomic browsing** — search by source organism, NP Classifier pathway/class/superclass, or ClassyFire taxonomy
- **Citation and collection lookup** — find molecules by DOI, publication title, or data source (e.g., ChEMBL NPs, NPAtlas)
- **Batch operations** — paginate large result sets and search multiple molecules in a single script

The intended user is a medicinal chemist, natural product researcher, or cheminformatics analyst who needs rapid, programmatic access to COCONUT data for lead identification, scaffold analysis, or literature review.

A successful outcome is a structured dataset (CSV/JSON) of natural product hits with molecular properties, organism data, and citation counts, ready for downstream analysis.

## Architecture

`
User Prompt
    → COCONUT Agent (LLM: {{CHAT-MODEL}}, temperature 0)
        → coconut tool container (Python 3)
            → coconut_utils library
                → COCONUT v2.0.0 REST API (https://coconut.naturalproducts.net)
        → Structured output (CSV / JSON / DataFrame)
`

**Model**: `{{CHAT-MODEL}}` — used for query planning, script generation, and result interpretation. Temperature is set to 0 for deterministic, reproducible outputs.

**Tool container**: A Docker image running Python 3 with the `coconut_utils` helper library, `requests`, `pandas`, and the Python standard library. The agent generates a single Python script that the container executes against the COCONUT public API.

**Data flow**:

1. The user describes a natural product query in natural language
2. The LLM generates a Python script using `coconut_utils` functions
3. The script runs inside the tool container, calling the COCONUT REST API
4. Results are saved via `save_final_results()` and exported as CSV/JSON to `/output/`
5. The LLM summarises findings and returns them to the user

**External dependencies**: COCONUT v2.0.0 public API (no authentication required). No GPU needed — CPU-only compute.

## Prerequisites

- Microsoft Discovery workspace with Azure Container Registry (ACR) access
- Azure AI Foundry project with a model deployment for `{{CHAT-MODEL}}`
- CPU compute node pool (e.g., `Standard_D4s_v3` or equivalent) — no GPU required
- Network access from the container to `https://coconut.naturalproducts.net` (COCONUT public API)

## Configuration

### Agent parameters

| Parameter | Description | Example |
|---|---|---|
| `{{CHAT-MODEL}}` | Azure AI Foundry model deployment name | `gpt-4o-deployment` |
| `{{coconutToolId}}` | Tool ID for the COCONUT tool definition | `coconut-tool-v1` |

### Tool container resources

| Resource | Minimum | Maximum |
|---|---|---|
| CPU | 1 core | 2 cores |
| RAM | 4 Gi | 8 Gi |
| GPU | 0 | 0 |

### Container packages

| Package | Description |
|---|---|
| `coconut_utils` | Custom helper library wrapping the COCONUT v2.0.0 API |
| `requests` | HTTP client for REST API calls |
| `pandas` | Data manipulation and export |
| Python stdlib | `json`, `logging`, etc. |

> **Note:** `rdkit`, `matplotlib`, `scipy`, `numpy`, and `biopython` are **not** available in this container.

## Usage

### 1. Build the Docker image

```bash
catalog_publish_image(image_name="coconut:latest", dockerfile_path="Dockerfile", build_context=".")
```

### 2. Publish the agent and tool

```bash
catalog_publish_agent(
  agent_yaml_path="coconut-agent-definition.yaml",
  tool_yaml_path="coconut-tool-definition.yaml"
)
```

### 3. Deploy via Discovery Studio

Navigate to the COCONUT agent card in Discovery Studio and click **Deploy**. Fill in the configuration parameters listed above.

### 4. Example prompts

**Search by molecule name:**

`
Search for caffeine in the COCONUT database and return its molecular properties,
source organisms, and citation count.
`

**Filter by drug-likeness:**

`
Find all natural products in COCONUT that satisfy Lipinski's Rule of Five
with molecular weight under 400 Da. Export results as CSV.
`

**Substructure search:**

`
Search for natural products containing the indole scaffold (SMILES: c1ccc2[nH]ccc2c1).
Return the top 50 hits with their SMILES, names, and organism counts.
`

**Organism-based search:**

`
Find all natural products in COCONUT from Artemisia annua. Include molecular
properties and NP Classifier pathway annotations.
`

### 5. Example output

`json
{
  "total_hits": 42,
  "exported_file": "/output/artemisia_annua_natural_products.csv",
  "summary": {
    "unique_np_pathways": ["Terpenoids", "Flavonoids", "Alkaloids"],
    "mw_range": "150.2 - 582.7 Da",
    "mean_alogp": 2.34
  }
}
`

## Support

For issues or questions, open a GitHub issue:
https://github.com/microsoft/discovery-catalog/issues


## Tools

| Tool | Path | Description |
|---|---|---|
| `coconut` | `tools/coconut/` | COCONUT (COlleCtion of Open NatUral producTs) database access tool for |

## Known Limitations

No known limitations at this time. If you encounter issues, please report them via the support channel above.

## Contributing

This project welcomes contributions and suggestions. Please see the repository's top-level [CONTRIBUTING guidelines](https://github.com/microsoft/microsoft-discovery-samples/blob/main/CONTRIBUTING.md) for details on how to contribute.