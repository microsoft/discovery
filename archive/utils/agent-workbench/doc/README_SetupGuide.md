# Agent Workbench Setup Guide

This guide walks you through installing and configuring the Microsoft Discovery Agent Workbench.

---

## Prerequisites

### Automatically Installed

The startup scripts (`start_web_app.bat` / `start_web_app.sh`) attempt to install:

- **Python 3.9+** with required packages
- **Docker Desktop** (or equivalent container runtime)
- **Discovery CLI** for platform operations

### Required Before Starting

| Requirement | Purpose |
|-------------|---------|
| **[Azure OpenAI endpoint](https://ai.azure.com/)** | AI-powered agent generation and chat testing |
| **[Discovery workspace](https://studio.discovery.microsoft.com/)** | Publishing agents and running Supercomputer jobs |

### Required Azure RBAC Roles

Ensure you have these roles assigned in your Azure subscription or resource group:

| Role | Purpose |
|------|---------|
| **Microsoft Discovery Platform Contributor (Preview)** | Manage Discovery resources |
| **Contributor** | General Azure resource management |
| **AcrPush** | Push container images to Azure Container Registry |
| **Cognitive Services OpenAI User** | Call Azure OpenAI APIs (if using Entra ID auth) |

---

## Quick Start

```bash
# Windows
start_web_app.bat

# Linux / macOS
./start_web_app.sh
```

Open **http://localhost:8050** and configure your settings.

---

## Configuration

Configure the workbench through the **Settings Dialog** (recommended) or by editing `discovery_config.json` directly.

### 1. Azure Settings

| Setting | Description | Example |
|---------|-------------|---------|
| **Tenant ID** | Your Azure AD tenant ID | `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx` |
| **Subscription ID** | Azure subscription with Discovery resources | `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx` |
| **Resource Group** | Resource group containing your workspace | `my-discovery-rg` |
| **Location** | Azure region | `eastus`, `westus2` |
| **ACR Name** | Container registry name (without `.azurecr.io`) | `myacr` |

### 2. Azure OpenAI Settings

| Setting | Description | Example |
|---------|-------------|---------|
| **Endpoint URL** | Azure OpenAI service endpoint | `https://my-aoai.openai.azure.com/` |
| **Deployment Name** | Model deployment name (not model name) | `gpt-4o-deployment` |
| **API Version** | API version | `2024-12-01-preview` |
| **Authentication** | `api_key` or `azure_ad` | `api_key` |
| **API Key** | Your API key (if using key auth) | `xxxxxxxxxxxxxxxx` |

#### Using Entra ID (Azure AD) Authentication

For `azure_ad` authentication, you also need:

- **Subscription ID** of your Azure OpenAI resource
- **Resource Group** containing your Azure OpenAI resource
- **Cognitive Services OpenAI User** role assigned to your account

> **Note**: The OpenAI resource can be in a different subscription than your Discovery resources. Cross-tenant scenarios require guest user permissions.

### 3. Supercomputer Settings

Required for submitting jobs to the Discovery Supercomputer:

```json
{
  "azure_compute": {
    "discovery_supercomputer": "my-supercomputer",
    "workspace": "my-workspace",
    "project": "my-project",
    "data_container": "my-datacontainer",
    "storage_account": "/subscriptions/.../storageAccounts/myaccount",
    "discovery_storage": "/subscriptions/.../storages/mystorage",
    "inputs_asset": "/subscriptions/.../DataAssets/inputs",
    "outputs_asset": "/subscriptions/.../DataAssets/outputs",
    "auto_cleanup": true,
    "use_script_upload": true
  }
}
```

### 4. Conversation Settings

Fine-tune the LLM behavior (optional):

| Setting | Default | Description |
|---------|---------|-------------|
| **Max Tokens** | 64000 | Maximum context window |
| **Target Tokens** | 48000 | Target for conversation management |
| **Max Output Tokens** | 16384 | Maximum response length |
| **Temperature** | 0.3 | Model creativity (0.0-1.0) |
| **Max Retries** | 3 | Retry attempts for failed requests |

### 5. Directory Settings

Specify where to find and generate agent files:

| Setting | Default | Description |
|---------|---------|-------------|
| **Tool Agents Directory** | `../../` | Path to tool agent definitions |
| **KB Agents Directory** | `../../` | Path to knowledge base agents |
| **Workflow Agents Directory** | `../../` | Path to entry/workflow agents |

---

## Finding Azure Information

### Subscription & Resource Group

1. Go to **Azure Portal** → **Subscriptions**
2. Copy the Subscription ID
3. Navigate to **Resource Groups** to find your Discovery resource group

### Azure OpenAI

1. **Azure Portal** → Search "Azure OpenAI" → Select your resource
2. **Keys and Endpoint** → Copy endpoint and key
3. **Azure AI Foundry** → **Deployments** → Copy deployment name

### Container Registry

1. **Azure Portal** → Search "Container registries"
2. Copy the registry name (without `.azurecr.io`)

### Model Versions

1. **Azure AI Foundry** → **Model catalog**
2. Format: `azureml://registries/azure-openai/models/{model}/versions/{version}`

---

## Optional: Azure CLI Authentication

The workbench uses device-code authentication by default. To reuse an existing `az login` session:

```bash
# Linux / macOS
export AGENT_WORKBENCH_ENABLE_AZURE_CLI=1
./start_web_app.sh

# Windows
set AGENT_WORKBENCH_ENABLE_AZURE_CLI=1
start_web_app.bat
```

> **Warning**: Only enable this with a valid, fresh `az login`. Stale sessions (common in Codespaces) cause authentication failures.

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| **Port 8050 in use** | Kill the existing process or change the port in settings |
| **Docker not found** | Install Docker Desktop and ensure it's running |
| **Authentication fails** | Verify RBAC roles are assigned and propagated (1-5 min delay) |
| **Agent loading fails** | Check that agent files are in the configured directories |

---

## Next Steps

Once configured, proceed to the **[User Guide](./README_UserGuide.md)** to learn how to create and test agents.
