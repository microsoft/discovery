# AlphaFold Protein Structure Prediction Agent

## Overview

Predicting three-dimensional protein structures from amino acid sequences is a foundational challenge in computational biology. Experimental methods such as X-ray crystallography and cryo-EM are accurate but slow and expensive, creating a bottleneck for drug discovery, enzyme engineering, and functional annotation pipelines.

The AlphaFold agent wraps the AlphaFold deep-learning model inside a conversational interface so that researchers can submit sequences, run monomer or multimer folding jobs, and interpret quality metrics—all without writing pipeline code. The agent translates natural-language requests into tool calls, manages FASTA inputs, orchestrates GPU-accelerated predictions, and returns structure files together with per-residue pLDDT and Predicted Aligned Error (PAE) assessments.

### Key capabilities

| Capability | Description |
|---|---|
| **Monomer folding** | Predict the 3D structure of a single protein chain from its FASTA sequence. |
| **Multimer folding** | Model protein complexes composed of two or more chains. |
| **Quality metrics** | Report per-residue pLDDT confidence scores and PAE matrices. |
| **Structure analysis** | Extract secondary-structure assignments, contact maps, and domain boundaries. |
| **Visualization helpers** | Generate matplotlib plots of pLDDT profiles and PAE heat-maps. |

## Architecture

`
User prompt
    │
    ▼
┌──────────────┐
│  LLM Planner │  (model: {{CHAT-MODEL}})
│  (reasoning) │
└──────┬───────┘
       │  tool call: alphafold
       ▼
┌──────────────────────┐
│  Tool Container      │  GPU-accelerated
│  ┌────────────────┐  │
│  │ alphafold_utils │  │  /app helper library
│  │ BioPython       │  │  sequence I/O & alignment
│  │ gemmi           │  │  mmCIF / PDB parsing
│  │ numpy / pandas  │  │  numerical analysis
│  │ matplotlib      │  │  quality-metric plots
│  └────────────────┘  │
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│  AlphaFold Model     │
│  (weights + MSA DB)  │
└──────────┬───────────┘
           │
           ▼
  Predicted structure (.pdb / .cif)
  + pLDDT scores + PAE matrix
           │
           ▼
┌──────────────────────┐
│  LLM Planner         │
│  (summarise results) │
└──────────┬───────────┘
           │
           ▼
     User response
`

**Data flow:**

1. The user provides a protein sequence (FASTA) or UniProt accession in natural language.
2. The LLM planner parses the request and issues one or more `alphafold` tool calls.
3. The tool container validates the input, runs AlphaFold on a GPU node, and writes output files.
4. Quality metrics (pLDDT, PAE) are extracted and returned to the planner.
5. The planner summarises the results, highlights confident/disordered regions, and offers follow-up analysis.

## Prerequisites

| Requirement | Details |
|---|---|
| **Azure subscription** | An active Azure subscription with permissions to create resources. |
| **Azure AI Foundry project** | A deployed Azure AI Foundry project with agent capabilities enabled. |
| **Model deployment** | A chat-completion model deployed and referenced as `{{CHAT-MODEL}}`. |
| **GPU compute** | A GPU-enabled compute instance (NVIDIA T4 or better recommended) for the tool container. |
| **Network access** | The tool container must be able to reach the AlphaFold weights and MSA databases (or they must be pre-cached in the container image). |

## Configuration

Register the agent with the following parameters:

| Parameter | Value | Description |
|---|---|---|
| `name` | `alphafold` | Human-readable agent name. |
| `toolName` | `alphafold` | Tool identifier used in tool calls. |
| `toolId` | `{{alphafoldToolId}}` | Unique tool ID assigned during provisioning. |
| `model` | `{{CHAT-MODEL}}` | The backing LLM deployment name. |
| `container.gpu` | `true` | Enable GPU passthrough for the tool container. |
| `container.packages` | `alphafold_utils, BioPython, gemmi, numpy, pandas, matplotlib` | Python packages available inside the container. |
| `container.appPath` | `/app` | Root path for the `alphafold_utils` helper library. |

### Example agent definition (YAML snippet)

`yaml
name: alphafold
model: "{{CHAT-MODEL}}"
tools:
  - name: alphafold
    id: "{{alphafoldToolId}}"
    container:
      gpu: true
      packages:
        - alphafold_utils
        - BioPython
        - gemmi
        - numpy
        - pandas
        - matplotlib
`

## Usage

### Step 1 — Fold a single protein

Prompt the agent with a FASTA sequence:

`	ext
Predict the structure of the following sequence:

>my_protein
MVLSPADKTNVKAAWGKVGAHAGEYGAEALERMFLSFPTTKTYFPHFDLSH
`

**Expected output:** The agent returns a PDB/mmCIF file path, a pLDDT profile summary (e.g., "mean pLDDT 91.3, all residues above 70"), and a brief structural description.

### Step 2 — Evaluate quality metrics

`	ext
Show me the per-residue pLDDT plot and the PAE matrix for the prediction above.
`

**Expected output:** Two inline plots—a line chart of pLDDT per residue and a heat-map of PAE—plus a textual interpretation highlighting any low-confidence regions.

### Step 3 — Fold a multimer complex

`	ext
Predict the heterodimer structure of these two chains:

>chain_A
MVLSPADKTNVKAAWGKVGAHAGEYGAEALERMFLSFPTTKTYFPHFDLSH
>chain_B
MGHFTEEDKATITSLWGKVNVEDAGGETLGRLLVVYPWTQRFFDSFGNLSS
`

**Expected output:** A multimer structure file, interface residue list, pLDDT per chain, and an inter-chain PAE matrix indicating confidence in the predicted interface.

### Step 4 — Analyse contacts and domains

`	ext
Identify the secondary-structure elements and domain boundaries in the predicted structure.
`

**Expected output:** A table of helices, sheets, and loops with residue ranges, plus suggested domain boundaries based on PAE clustering.

## Support

If you encounter issues or have feature requests:

- **GitHub Issues:** Open an issue at [microsoft/discovery-samples](https://github.com/microsoft/discovery-samples/issues) with the label `agent/alphafold`.
- **Documentation:** Refer to the [Microsoft Discovery authoring guide](https://github.com/microsoft/discovery-samples/blob/main/docs/authoring-guide.md) for agent development best practices.
- **Community:** Join the discussion in the repository's Discussions tab for questions and tips.


## Tools

| Tool | Path | Description |
|---|---|---|
| `alphafold` | `tools/alphafold/` | Python code environment with ColabFold for AlphaFold2 protein structure prediction. |

## Known Limitations

No known limitations at this time. If you encounter issues, please report them via the support channel above.

## Contributing

This project welcomes contributions and suggestions. Please see the repository's top-level [CONTRIBUTING guidelines](https://github.com/microsoft/microsoft-discovery-samples/blob/main/CONTRIBUTING.md) for details on how to contribute.