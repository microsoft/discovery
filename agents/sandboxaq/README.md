# SandboxAQ Foundry Model Agent Deployment Guide

This guide provides step-by-step instructions for deploying the SandboxAQ
Foundry Model tool and its associated agent to the Microsoft Discovery
platform.

## Overview

This agent invokes a SandboxAQ model that your organization has subscribed to
through Azure AI Foundry, calling the OpenAI-compatible chat-completions
endpoint from a Discovery-managed tool container. This deployment includes:

- **Dockerfile**: Used for creation of the SandboxAQ model tool container image
- **Tool Definition**: Configuration for the `sandboxaq-model` tool
- **Agent Definition**: AI agent configuration for the SandboxAQ agent

## Prerequisites

Before starting the deployment, ensure you have:

1. Access to Microsoft Discovery platform
2. An active SandboxAQ model subscription deployed in Azure AI Foundry
3. Azure Container Registry (ACR) with appropriate permissions
4. Docker installed locally for image building
5. Azure CLI or PowerShell for resource management

## Build Docker Image

### Step 1: Build and Publish Docker Image

1. **Build the image** from this tool directory:

   ```bash
   docker build -t sandboxaq-model:latest .
   ```

2. **Tag the image** for your Azure Container Registry:

   ```bash
   docker tag sandboxaq-model:latest mycontainerregistry.azurecr.io/sandboxaq-model:latest
   ```

   > Replace `mycontainerregistry` with your actual ACR name

3. **Login to Azure Container Registry**:

   ```bash
   az acr login --name mycontainerregistry
   ```

4. **Push the image** to your container registry:

   ```bash
   docker push mycontainerregistry.azurecr.io/sandboxaq-model:latest
   ```

## File Structure

```text
sandboxaq/
├── agent.yaml                          # Agent configuration (YAML)
├── metadata.yaml                       # Catalog metadata
├── tools/
│   └── sandboxaq-model/
│       ├── Dockerfile                  # Container image definition
│       ├── tool.yaml                   # Tool configuration (YAML)
│       └── sandboxaq_utils.py          # Foundry client helper module
└── README.md                           # This deployment guide
```

## Key Configuration Details

### Agent Capabilities

The SandboxAQ agent provides:

- **Model Invocation**: Sends prompts to the subscribed SandboxAQ deployment
- **Structured Output**: Preserves JSON returned by the endpoint and writes
  results to `/output/final_results.json`
- **Sensitive-Data Handling**: Applies access, privacy, and human-review
  guidance when working with HR or other confidential business data

## Usage

### Basic Queries

| Prompt | Description |
|--------|-------------|
| "Run the SandboxAQ model on this prompt and return the result as JSON." | Direct invocation |
| "Summarize this HR policy using the subscribed SandboxAQ deployment." | Summarization |
| "Ask the SandboxAQ model to classify these support tickets." | Classification |

### Advanced Queries

| Prompt | Description |
|--------|-------------|
| "Run this prompt at temperature 0.7 and cap the output at 1000 tokens." | Tuned sampling parameters |
| "Use a system prompt of 'You are a concise policy analyst' for this request." | Custom system instruction |
| "Invoke the model on each of these five prompts and collect the results." | Batch invocation in one script |

## Architecture

This agent operates as a `kind: prompt` agent within Discovery Studio.

    User Input → SandboxAQ Agent (LLM) → sandboxaq-model Tool (Container) → Azure AI Foundry → Results

- **Model:** Configured via the `{{CHAT-MODEL}}` parameter at deploy time
- **Tool:** `sandboxaq-model` container exposing a `python3` code environment

The tool exposes a Python code environment rather than a fixed action. The
agent writes a script that imports `sandboxaq_utils` and calls
`invoke_model(prompt, system_prompt=..., temperature=..., max_tokens=...)`,
which returns a dict with `model`, `content`, `usage`, and `raw_response`.

Prompts therefore travel as Python string literals and are never interpolated
into a shell command, so text containing apostrophes, double quotes, `$`, or
newlines reaches the deployment unmodified.

## Configuration

| Parameter | Description | Example |
|---|---|---|
| `{{CHAT-MODEL}}` | Azure AI Foundry model deployment name for the agent | `gpt-4o` |

Configure these values on the deployed tool; do not commit them to the catalog:

| Environment variable | Required | Description |
|---|---:|---|
| `FOUNDRY_ENDPOINT` | Yes | Azure AI Foundry endpoint, including the `/openai` API base |
| `FOUNDRY_API_KEY` | Yes | Secret for the subscribed deployment |
| `FOUNDRY_DEPLOYMENT` | Yes | SandboxAQ model deployment name |
| `FOUNDRY_API_VERSION` | No | API version; defaults to `2024-10-21` |

The endpoint must be reachable from the Discovery tool container. Use the
Foundry deployment's supported API version and authentication method if it
differs from this default.

## Support

For issues or questions with this agent, contact SandboxAQ:
<https://www.sandboxaq.com/contact>

SandboxAQ contact: support@sandboxaq.com

For platform issues, open a GitHub issue:
<https://github.com/microsoft/discovery/issues>

## Tools

| Tool | Path | Description |
|---|---|---|
| `sandboxaq-model` | `tools/sandboxaq-model/` | Invokes a subscribed SandboxAQ model through its Azure AI Foundry OpenAI-compatible chat-completions endpoint. |

## Known Limitations

- Requires an existing SandboxAQ subscription in Azure AI Foundry; the agent
  cannot provision or discover deployments on your behalf.
- Supports the chat-completions API surface only. Embeddings, batch, and
  streaming endpoints are not exposed.
- Credentials are supplied as environment variables on the deployed tool, so
  rotating a key requires updating the tool configuration.
- For sensitive HR data, apply your organization's privacy, access-control,
  and human-review requirements. This agent does not make employment
  decisions.

## Contributing

This project welcomes contributions and suggestions. Please see the
repository's top-level [CONTRIBUTING guidelines](https://github.com/microsoft/discovery/blob/main/CONTRIBUTING.md)
for details on how to contribute.
