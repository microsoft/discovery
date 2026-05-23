# ZINC Agent for Microsoft Discovery

Search and retrieve molecular structures from the ZINC22 / CartBlanche database of 37B+ commercially available compounds for virtual screening and drug discovery.

## Overview

The ZINC agent provides conversational access to [CartBlanche](https://cartblanche.docking.org/), the successor to ZINC15 and one of the largest curated collections of commercially available compounds for computational drug discovery. It enables medicinal chemists, computational biologists, and drug-discovery researchers to query molecular structures, retrieve physicochemical properties, check vendor availability, and run SMILES-based similarity searches -- all through natural-language prompts.

**Key capabilities:**

- **ZINC ID lookup** -- retrieve any compound by its ZINC identifier (all formats accepted); the single response includes SMILES, molecular formula, physicochemical properties, and vendor catalogs
- **SMILES search** -- exact-match or Tanimoto similarity search by SMILES string (asynchronous with automatic polling)
- **Batch lookup** -- look up multiple ZINC IDs in one asynchronous request
- **Vendor availability** -- vendor catalog entries (catalog_name, price, quantity, shipping, supplier_code, unit, url) are included inline with every substance response

**Not available (CartBlanche limitations vs ZINC15):**

- Name-based search (resolve names to SMILES via PubChem first)
- Curated subset browsing (fda, in-stock, natural-products, etc.)
- Random molecule sampling

## Architecture

```
+---------------------+
|   User Prompt        |
+---------+-----------+
          |
          v
+---------------------+
|   LLM ({{CHAT-MODEL}})| Interprets the query and selects
|   agent.yaml prompt  | the appropriate zinc_utils function
+---------+-----------+
          |  tool call via {{zincToolId}}
          v
+---------------------+
|   Code Environment   | python:3.11-slim container
|   (zinc tool)        | requests==2.33.0
|                      |
|  +-----------------+ |
|  |  zinc_utils.py  | | Bootstrapped at runtime to /tmp
|  |  (helper lib)   | | and imported by generated scripts
|  +--------+--------+ |
|           |          |
|           v          |
|  +-----------------+ |
|  | CartBlanche API | | cartblanche.docking.org
|  +-----------------+ |
+---------------------+
          |
          v
+---------------------+
|  Structured Response | JSON results formatted by the LLM
|  returned to user    | into readable tables / summaries
+---------------------+
```

**Data flow:**

1. The user submits a natural-language prompt.
2. The LLM parses the intent and generates a Python script that calls `zinc_utils` functions.
3. The script executes inside a lightweight container (CPU-only, no GPU required).
4. `zinc_utils` issues HTTP requests to the CartBlanche REST API. For async endpoints (SMILES search, bulk lookup), it submits the task and automatically polls `/search/result/{task_id}` until completion.
5. The LLM formats the results into a human-readable response.

**Runtime bootstrap:** On first tool invocation the agent writes `zinc_utils.py` to `/tmp` inside the container and adds it to `sys.path`. All subsequent scripts import from this bootstrapped copy.

## Prerequisites

| Requirement | Details |
|---|---|
| **Microsoft Discovery platform** | Active workspace with agent deployment permissions |
| **Azure subscription** | Subscription with access to the Discovery resource provider |
| **Container registry** | Image published to an accessible ACR (see `tool.yaml` for the default registry) |
| **Network access** | Outbound HTTPS to `cartblanche.docking.org` from the container |
| **GPU** | **Not required** -- this agent is CPU-only |

No local Python environment is needed; all dependencies (`requests==2.33.0`) are baked into the container image.

## Configuration

### Parameterized values

These placeholders in `agent.yaml` and `tool.yaml` must be resolved at deployment time:

| Placeholder | File | Description | Example |
|---|---|---|---|
| `{{CHAT-MODEL}}` | agent.yaml | Language model identifier used for reasoning | `gpt-4o`, `gpt-4.1` |
| `{{zincToolId}}` | agent.yaml | Tool ID assigned by the platform when the zinc tool is registered | (auto-generated at registration) |
| `{{scriptName}}` | tool.yaml | Filename of the generated Python script executed in the container | (set by the platform runtime) |

### Model options

| Parameter | Value | Notes |
|---|---|---|
| `temperature` | `0` | Deterministic output for reproducible queries |
| `topP` | `0` | Greedy decoding |

### Compute resources (tool.yaml)

| Resource | Minimum | Maximum |
|---|---|---|
| CPU | 1 | 2 |
| RAM | 4 Gi | 8 Gi |
| Storage | 8 Gi | 32 Gi |
| GPU | 0 | 0 |

Pool type is **static** with a pool size of **1**.

## Usage

### Deployment

1. **Register the tool** -- publish the container image and register the zinc tool with the Discovery platform. Note the assigned `{{zincToolId}}`.
2. **Deploy the agent** -- upload `agent.yaml` and `metadata.yaml`, supplying values for `{{CHAT-MODEL}}` and `{{zincToolId}}`.
3. **Verify** -- send a test prompt (see examples below) and confirm a structured response is returned.

### Example prompts and expected outputs

#### 1. Look up a compound by ZINC ID

**Prompt:**

> Get the full details for ZINC000000000053.

**What the agent does:** Calls `get_substance("ZINC000000000053")`

**Expected output:**

```
Substance: ZINC000000000053

Structure
  SMILES:    CC(=O)Oc1ccccc1C(=O)O
  InChIKey:  BSYNRYMUTXBXSQ-UHFFFAOYSA-N

Properties (from tranche_details)
  Molecular Weight : 180.16
  LogP             : 1.24
  Heavy Atoms      : 13

Vendor Catalogs
  Sigma-Aldrich    : $25/5g, ships 2-3 days
  Enamine          : $18/1g, ships 5 days
  ...
```

---

#### 2. SMILES exact-match search

**Prompt:**

> Search CartBlanche for the exact SMILES CC(=O)Oc1ccccc1C(=O)O.

**What the agent does:** Calls `smiles_search("CC(=O)Oc1ccccc1C(=O)O", dist=0)`

**Expected output:**

```
SMILES exact search (dist=0):

Found 1 match:
  ZINC ID: ZINC000000000053
  SMILES:  CC(=O)Oc1ccccc1C(=O)O
```

---

#### 3. SMILES similarity search

**Prompt:**

> Find compounds similar to aspirin (CC(=O)Oc1ccccc1C(=O)O) with Tanimoto distance up to 2.

**What the agent does:** Calls `smiles_search("CC(=O)Oc1ccccc1C(=O)O", dist=2)`

**Expected output:**

```
Similarity search (dist=2): Found 47 hits

| #  | ZINC ID          | SMILES                       |
|----|------------------|------------------------------|
| 1  | ZINC000000000053 | CC(=O)Oc1ccccc1C(=O)O        |
| 2  | ZINC000001530778 | OC(=O)c1ccccc1O              |
| ...| ...              | ...                          |
```

---

#### 4. Batch lookup of multiple compounds

**Prompt:**

> Look up ZINC000000000053 and ZINC000003807804.

**What the agent does:** Calls `bulk_lookup(["ZINC000000000053", "ZINC000003807804"])`

**Expected output:**

```
Batch results (2 compounds):

| ZINC ID          | SMILES                     | MW     | Vendors |
|------------------|----------------------------|--------|---------|
| ZINC000000000053 | CC(=O)Oc1ccccc1C(=O)O      | 180.16 | 4       |
| ZINC000003807804 | CC(C)Cc1ccc(cc1)C(C)C(=O)O | 206.28 | 5       |
```

---

### Tips for effective prompts

- **Use ZINC IDs when you have them** -- direct ID lookups are synchronous and return full detail instantly.
- **Resolve names via PubChem first** -- CartBlanche has no name search. Ask the PubChem agent for the SMILES, then use `smiles_search()`.
- **Use dist=0 for exact match** -- exact SMILES search completes in about 3 seconds. Similarity search (dist > 0) can take 30+ seconds.
- **Batch when possible** -- `bulk_lookup()` handles multiple IDs in one async request, which is more efficient than individual lookups.

| Function | Type | Returns |
|---|---|---|
| `get_substance(zinc_id)` | Sync | Dict with keys `zinc_id, smiles, tranche_details, catalogs, mol_formula, rings, hetero_atoms, db`. None if not found. |
| `smiles_search(smiles, dist=0, db="zinc22-2D")` | Async | Dict with keys `zinc22` (list of hits), `zinc22_missing`, `hostname`, `logs`. Access hits via `result["zinc22"]`. |
| `bulk_lookup(zinc_ids)` | Async | Dict with keys `zinc20` (list of substance dicts), `missing` (list of not-found IDs). Access results via `result["zinc20"]`. |
| `smiles_search(smiles, dist=0, db="zinc22-2D")` | Async | Exact or similarity SMILES search. Returns list of matches. |
| `bulk_lookup(zinc_ids)` | Async | Batch lookup of multiple ZINC IDs. Returns list of full records. |

Internal helpers: `_normalize_zinc_id()`, `_get()`, `_post()`, `_poll_task()`.

## Support

| Channel | Details |
|---|---|
| **Issue tracker** | File an issue in the [discovery-catalog](https://github.com/microsoft/discovery-catalog) repository |
| **Publisher** | Microsoft |
| **Contact email** | [discovery-catalog@microsoft.com](mailto:discovery-catalog@microsoft.com) |
| **CartBlanche** | [https://cartblanche.docking.org/](https://cartblanche.docking.org/) |

### Additional resources

- [ZINC22 -- Irwin et al., J. Chem. Inf. Model. 2020](https://pubs.acs.org/doi/10.1021/acs.jcim.0c00675)
- [CartBlanche documentation](https://wiki.docking.org/index.php/CartBlanche)
- [Microsoft Discovery documentation](https://www.microsoft.com/)
- [Authoring guide](../../../docs/authoring-guide.md)


## Tools

| Tool | Path | Description |
|---|---|---|
| `zinc` | `tools/zinc/` | Python code environment for searching and retrieving molecular structures from the ZINC22 / CartBlanche database of commercially available compounds. |

## Known Limitations

- **No name search** -- CartBlanche does not support searching by drug/compound name. Resolve names to SMILES using PubChem first.
- **No subset browsing** -- curated subsets (fda, in-stock, natural-products) are not exposed via the CartBlanche API.
- **Async latency** -- SMILES similarity search (dist > 0) and bulk lookup are asynchronous and may take 10-60 seconds to complete.
- **No random molecule endpoint** -- the CartBlanche random molecule API is unreliable and not supported.

## Contributing

This project welcomes contributions and suggestions. Please see the repository's top-level [CONTRIBUTING guidelines](https://github.com/microsoft/microsoft-discovery-samples/blob/main/CONTRIBUTING.md) for details on how to contribute.