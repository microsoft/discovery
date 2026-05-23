# Core Python Agent

A reusable worker agent for RDKit cheminformatics and general-purpose Python execution. Designed to be invoked by workflow orchestrators (such as [science-workflow](../science-workflow/) and [sciece-workflow-structured-input](../sciece-workflow-structured-input/)) or used standalone for molecular science tasks.

## Overview

The Core Python Agent solves the need for a shared, consistent Python execution agent across multiple Discovery Studio workflows. Rather than duplicating Python agent definitions in every workflow folder, this agent is defined once and referenced by name (`CorePythonAgent`) from any workflow that needs Python/RDKit capabilities.

- **Scenario:** Molecular manipulation, conformer generation, chemical property calculations, and general scientific computing
- **Intended users:** Researchers and scientists working with molecular data in Discovery Studio
- **Successful outcome:** Python scripts execute against RDKit and return structured results (files, computed properties, conformer coordinates)

## Architecture

```
Workflow Orchestrator (e.g., ScienceWorkflow)
    │
    ▼
┌─────────────────┐
│ CorePythonAgent  │  (prompt agent)
│   model: GPT     │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Discovery Python │  (platform tool)
│   Tool (RDKit)   │
└─────────────────┘
         │
         ▼
   Output files, stdout, computed results
```

- **Model:** Configurable via the `{CHAT-MODEL}` parameter (e.g., `gpt-5-2`)
- **External dependency:** Discovery Core Python tool — a platform-managed execution environment with RDKit and scientific Python libraries pre-installed
- **Data flow:** The agent receives a task description from the orchestrator, writes and executes a Python script via the tool, and returns results (stdout, generated files) back to the conversation

## Tools

### corepython

Core Python execution environment for cheminformatics and scientific computing. Pre-installed with RDKit, ASE, BioPython, PyMatGen, and other molecular science libraries. Executes Python scripts with input mounted at `/input` and output at `/output`.

## Prerequisites

- Azure subscription with access to a Discovery Studio workspace
- Azure AI Foundry project with a chat model deployment (e.g., `gpt-5-2`)
- Discovery Core Python tool provisioned in your workspace (provides the `{CORE-PYTHON-TOOL-ID}`)

## Configuration

| Parameter | Description | Example |
|---|---|---|
| `{CHAT-MODEL}` | Azure AI Foundry model deployment name | `gpt-5-2` |
| `{CORE-PYTHON-TOOL-ID}` | Resource ID of the Discovery Core Python tool | `tool-resource-id` |

## Usage

### Standalone deployment

```bash
# From the repository root
python .github/skills/discovery-deploy-test/deploy.py agents/microsoft/core-python-agent/agent.yaml
```

### As part of a workflow

This agent is referenced by name (`CorePythonAgent`) from the following workflows:

- [`science-workflow/ScienceWorkflow.yaml`](../science-workflow/ScienceWorkflow.yaml)
- [`sciece-workflow-structured-input/SIWorkflow.yaml`](../sciece-workflow-structured-input/SIWorkflow.yaml)

Deploy the Core Python Agent first, then deploy the workflow:

```bash
# Deploy the shared agent
python .github/skills/discovery-deploy-test/deploy.py agents/microsoft/core-python-agent/agent.yaml

# Deploy a workflow that uses it
python .github/skills/discovery-deploy-test/deploy.py agents/microsoft/science-workflow/
```

### Example interaction

**Input (from orchestrator):**
> Compute the 3D coordinates of aspirin (SMILES: CC(=O)Oc1ccccc1C(=O)O) in XYZ format.

**Output:**
```
11
Aspirin - 3D conformer
C    1.2345   0.6789   0.0000
C    0.0000   1.3579   0.0000
...
```

## Support

For issues or questions, open a GitHub issue:
https://github.com/microsoft/discovery-catalog/issues

## Known Limitations

No known limitations at this time. If you encounter issues, please report them via the support channel above.

## Contributing

This project welcomes contributions and suggestions. Please see the repository's top-level [CONTRIBUTING guidelines](https://github.com/microsoft/microsoft-discovery-samples/blob/main/CONTRIBUTING.md) for details on how to contribute.