# Quota Reservations for Microsoft Discovery

This guide provides comprehensive instructions for securing the necessary Azure quotas and capacity required for Microsoft Discovery deployments. Proper quota planning ensures optimal performance and prevents deployment failures during infrastructure setup.

## Overview

Microsoft Discovery requires specific quotas across multiple Azure services to function effectively. These quotas must be secured before attempting to deploy Microsoft Discovery infrastructure components. The primary quota categories include:

- **Virtual Machine SKUs** - For supercomputer node pools and computational workloads
- **Azure NetApp Files capacity** - For the Discovery storage resource
- **Azure Cosmos DB throughput (RU/s)** - For Discovery workspace and Discovery project resources
- **Chat Completion and Text Embedding Models** - For Azure OpenAI and Azure AI Foundry services

## Prerequisites

Before requesting quota increases, ensure you have:

- An active Azure subscription with Microsoft Discovery resource provider registered
- **Contributor** or **Owner** role on the Azure subscription
- Understanding of your planned Microsoft Discovery deployment scale and requirements
- Access to Azure Portal and Azure CLI (if using programmatic quota requests)
- Knowledge of your target Azure regions for deployment

## Virtual Machine SKU Quota Requirements

Standard VM SKUs are required for Microsoft Discovery infrastructure components including supercomputer node pools, storage systems, and management services.

### Required VM SKU Families

Microsoft Discovery supports various VM SKU families for different computational workloads. More details about VM SKUs is here [Azure VM SKU Families](https://learn.microsoft.com/en-us/azure/virtual-machines/sizes/overview?tabs=breakdownseries%2Cgeneralsizelist%2Ccomputesizelist%2Cmemorysizelist%2Cstoragesizelist%2Cgpusizelist%2Cfpgasizelist%2Chpcsizelist#general-purpose)

Below are the **sample VM SKU families** which are supported in PriviatePreview :

| VM SKU Family | Recommended SKUs | Use Case |
|---------------|------------------|-----------|
| **D-series v5/v6** | Standard_D4s_v5, Standard_D4s_v6 | Enterprise-grade applications, relational databases, in-memory caching, data analytics |
| **NC-family (GPU)** | Standard_NC4as_T4_v3, Standard_NC8as_T4_v3, Standard_NC16as_T4_v3, Standard_NC64as_T4_v3, Standard_NC24ads_A100_v4, Standard_NC48ads_A100_v4, Standard_NC96ads_A100_v4 | Compute-intensive AI/ML workloads, graphics-intensive applications, visualization, deep learning training |
| **NV-family (GPU)** | Standard_NV6ads_A10_v5, Standard_NV12ads_A10_v5, Standard_NV24ads_A10_v5, Standard_NV36ads_A10_v5, Standard_NV36adms_A10_v5, Standard_NV72ads_A10_v5 | Virtual desktop (VDI), single-precision compute, video encoding and rendering, remote visualization |
| **ND-family (GPU)** | Standard_ND40rs_v2 | Large memory compute-intensive workloads, large memory graphics-intensive applications, large memory visualization, distributed deep learning |

VM vCPU quota is reserved per subscription.
You can check the vCPU quota following the guidance [Check vCPU quotas](https://learn.microsoft.com/en-us/azure/virtual-machines/quotas?tabs=cli)

Depending on the resources you plan to create in your subscription, you can follow the guidance to allocate vCPU quotas. If you need GPU support for your tools, follow the same process to allocate the quota with the VM SKUs that includes GPU support. All the supported VM SKUs are listed in the table above.

[Increase VM-family vCPU quotas](https://learn.microsoft.com/en-us/azure/quotas/per-vm-quota-requests)



## Azure NetApp Files Capacity Quota (Discovery Storage)

Microsoft Discovery uses **Azure NetApp Files** for the [Discovery Storage resource](../4-discovery-infra-resources/a--discovery-storage.md). Ensure that your target subscription and region have sufficient **Azure NetApp Files capacity quota** before deploying.

Each Discovery workspace requires its own dedicated Discovery Storage resource. The storage can be shared across all projects within that workspace.

### Required capacity

- Reserve **4 TiB** of Azure NetApp Files capacity per Discovery workspace in the region where you deploy Microsoft Discovery.

### Regional capacity limits

Azure NetApp Files capacity is constrained by **regional subscription limits**. The **standard capacity limit** for each subscription is **25 TiB, per region, across all service levels**.

### Requesting a limit increase

If your planned deployment (including other workloads in the same region) requires more capacity than your current regional limit, request an increase using a **Service and subscription limits (quotas)** support request:

- [Request limit increase](https://learn.microsoft.com/en-us/azure/azure-netapp-files/azure-netapp-files-resource-limits#request-limit-increase)
- [Learn more about Azure NetApp Files limits](https://learn.microsoft.com/en-us/azure/azure-netapp-files/azure-netapp-files-resource-limits)


## Azure Cosmos DB Throughput Quota (Discovery Workspace and Project)

Microsoft Discovery uses **Azure Cosmos DB**. Cosmos DB throughput is measured in **RU/s (Request Units per second)** and should be planned to ensure both successful resource creation and steady runtime performance.

To learn more about Request Units (RU), see [Request units in Azure Cosmos DB](https://learn.microsoft.com/en-us/azure/cosmos-db/request-units).

### Cosmos DB account quota behavior

- There is **no per-subscription quota limit on RU/s**.
- Throughput availability is managed **per Cosmos DB account**.
- The Cosmos DB used by the Discovery platform is **managed by the Discovery platform**, and the platform uses throughput within the **default assignment range**.
- If there is a quota issue due to **region-level restrictions** (for example, a high-demand region), [raise a support ticket](https://learn.microsoft.com/en-us/azure/cosmos-db/nosql/create-support-request-quota-increase) to request the appropriate extension.

For more details, see [Azure Cosmos DB service quotas](https://learn.microsoft.com/en-us/azure/cosmos-db/concepts-limits?source=recommendations).

### Required throughput

Both the **Discovery workspace** resource and each **Discovery project** resource require autoscale throughput to be available.

| Resource | Minimum RU/s required | Maximum RU/s (autoscale) | Notes |
|----------|------------------------|---------------------------|-------|
| **Discovery workspace** | 2,400 RU/s | 4,000 RU/s | Autoscale is triggered automatically by Cosmos DB |
| **Discovery project** | 400 RU/s | 4,000 RU/s | Autoscale is triggered automatically by Cosmos DB |

### Operational guidance

- If the **minimum RU/s** is not available, you may see **resource creation failures**.
- If the **maximum RU/s** cannot be fulfilled, the platform may experience **performance degradation** under load.

### Example sizing

For a workspace with **10 projects**:

- **Minimum**: 2,400 + (400 × 10) = **6,400 RU/s**
- **Maximum**: 4,000 + (4,000 × 10) = **44,000 RU/s**


## Chat Completion and Text Embedding Models Quota 

Azure OpenAI and Azure AI Foundry quotas are essential for Microsoft Discovery's AI-powered features including Copilot, agents, Bookshelf, and natural language processing.

### Required Azure OpenAI Models

Microsoft Discovery Platform uses the following AOAI model configurations.

#### GPT Models for Copilot Service, Discovery Engine, and Bookshelf 

| Model | Version | Default TPM | Recommended TPM | Purpose | Used by |
|-------|---------|-------------|-----------------|---------|---------|
| **GPT-4o** | 2024-11-20 | 200,000 | 4,000,000 | Conversation model for | Copilot Service |
| **GPT-o3-mini** | 2025-01-31 | 1,000,000 | 2,000,000 | Model for better reasoning capability | Copilot Service |
| **GPT-4.1** | 2025-04-14 | 1,100,000 | 5,000,000 | Advanced Conversation model | Copilot Service, Discovery Engine, Bookshelf |
| **Text-Embedding-3-Small** | 1 | 50,000 | 2,000,000 | Embeddings generation during indexing | Bookshelf |

##### GPT-4o Model
| Configuration | Value | Notes |
|---------------|-------|-------|
| **Version** | 2024-11-20 | Latest stable version |
| **Deployment Type** | Standard | Local data zone deployment |
| **Default TPM (Tokens Per Minute)** | 200,000 | Minimum required capacity per Workspace |
| **Recommended TPM (Tokens Per Minute)** | 4,000,000 | |
| **Default RPM (Requests Per Minute)** | 1,200 | TPM/(1000/6) |
| **Recommended RPM (Requests Per Minute)** | 24,000 | TPM/(1000/6) |

##### GPT-4.1 Model
| Configuration | Value | Notes |
|---------------|-------|-------|
| **Version** | 2025-04-14 | Latest stable version |
| **Deployment Type** | Standard | Local data zone deployment |
| **Minimum TPM (Tokens Per Minute)** | 1,100,000 | 1M per workspace, 100k per Bookshelf |
| **Recommended TPM (Tokens Per Minute)** | 5,000,000 | |
| **Minimum RPM (Requests Per Minute)** | 1,000 | TPM/1000 |
| **Recommended RPM (Requests Per Minute)** | 4,000 | TPM/1000 |

##### Text-Embedding-3-Small Model
| Configuration | Value | Notes |
|---------------|-------|-------|
| **Version** | 1 | Consistent with Copilot service |
| **Dynamic Quota** | Enabled | Automatic scaling based on bandwidth availability |
| **Default TPM (Tokens Per Minute)** | 50,000 | Minimum required capacity per Bookshelf |
| **Recommended TPM (Tokens Per Minute)** | 2,000,000 | |
| **Default RPM (Requests Per Minute)** | 3,600 | TPM/(1000/6) |
| **Recommended RPM (Requests Per Minute)** | 30,000 | TPM/(1000/6) |

**Notes:** 
- You need to ensure that for each **workspace** you have a minimum of "Default TPM". For better performance, ensure quota is set per "Recommended TPM".
- Workspace deployment defaults to 250,000 TPM for the model deployment dedicated to Discovery Engine. This default is to ensure workspace creation completes successfully. Increasing TPM to the minimum is highly recommended. Learn [how to update quota assigned to a model deployment](https://learn.microsoft.com/azure/ai-foundry/openai/how-to/quota).
- You need to ensure that for each **Bookshelf** you have a minimum of "Default TPM". For better performance, ensure quota is set per "Recommended TPM".
- As of Discovery release 2.1, Bookshelf uses GPT-4.1 by default. Bookshelf deployments created prior to 2.1 using GPT-4o will continue to be supported. Similarly, the default AOAI model will continue to evolve. Please keep an eye on Discovery release notes for information on deprecation timelines and upgrade recommendations. 


### Requesting Azure OpenAI Quota

#### Using Azure Portal for OpenAI Models

1. **Navigate to Azure AI Foundry**
   - Sign in to the [Azure AI Foundry Portal](https://ai.azure.com)
   - Click **"Create"** or navigate to an existing AI Foundry resource

2. **Access Quota Management**
   - In your AI Foundry Portal, select **"Management Center"** from the left navigation
   - Select **"Quota"** from the left navigation
   - Select the right **"subscription"** 
   - For each different model, Select the region where you plan to deploy Microsoft Discovery to view current allocations

3. **Request Model Quota**
   - Click **"Request quota"** for the desired model
   - Fill in the quota request form:
    - **Model**: Select from the required models (GPT-4o, GPT-o3-mini, GPT-4.1, text-embedding-3-small)
    - **Deployment type**: Choose "Standard" for most scenarios
    - **Tokens per minute (TPM)**: Use recommended values from the table above
    - **Business justification**: "Microsoft Discovery platform deployment for scientific research and AI-powered workflows"
    - **Model Deployment Quota or Fine Tuning Quota**: Select Model Deployment (PTU/RPM/TPM)

4. **Submit and Track Request**
   - Review request details and submit
   - Track request status in the Azure Portal under Support tickets

More information on quota requests is available here

[Request quota for AOAI Models](https://learn.microsoft.com/en-us/azure/ai-foundry/openai/quotas-limits?tabs=REST#how-to-request-quota-increases)

### Azure AI Foundry Quota Planning

**Note:** Quota requirements per workspace or bookshelf. Please refer to the sections above for more details.

#### Development Environment

- **GPT-4o**: 200,000-500,000 TPM
- **GPT-o3-mini**: 500,000-1,000,000 TPM
- **GPT-4.1**: 500,000-1,000,000 TPM (for agents)
- **GPT-4.1**: 1,000,000 TPM (for Discovery Engine)
- **text-embedding-3-small**: 2,000,000-5,000,000 TPM

#### Production Environment (Small-Medium)

- **GPT-4o**: 1,000,000-2,000,000 TPM
- **GPT-o3-mini**: 1,000,000-2,000,000 TPM
- **GPT-4.1**: 1,000,000-2,000,000 TPM (for agents)
- **GPT-4.1**: 2,000,000 TPM (for Discovery Engine)
- **text-embedding-3-small**: 7,000,000-10,000,000 TPM

#### Production Environment (Large Scale)

- **GPT-4o**: 4,000,000+ TPM
- **GPT-o3-mini**: 2,000,000+ TPM
- **GPT-4.1**: 4,000,000+ TPM (for agents)
- **GPT-4.1**: 5,000,000+ TPM (for Discovery Engine)
- **text-embedding-3-small**: 14,000,000+ TPM

## Regional Quota Considerations

### Recommended Azure Regions

Choose regions based on quota availability and proximity to your users and the locations where the platform is available.

#### Quota Availability Check

Before requesting quotas, verify regional availability:

```azurecli
# Check VM quota availability by region
az vm list-usage --location "eastus2" --query "[?contains(name.value, 'cores')]"

# Check Azure OpenAI model availability
az cognitiveservices model list --location "eastus2" --kind "OpenAI"
```

## Quota Request Best Practices

### Timing and Planning

- **Request quotas 2-4 weeks before deployment** to allow for processing time
- **Standard requests**: 1-3 business days processing
- **Large quota requests**: 5-10 business days processing
- **Plan for multiple regions** in case primary region quotas are unavailable

#### Set Up Quota Alerts

1. **Azure Monitor Alerts**
   - Configure alerts at 80% quota utilization
   - Set up notifications to platform administrators
   - Create automated quota increase workflows

2. **Cost Management Integration**
   - Link quota monitoring with cost management
   - Set up spending alerts for Azure OpenAI usage
   - Implement budget controls for quota-intensive resources

## Related Documentation

- [Azure AI Foundry Documentation](https://docs.microsoft.com/azure/ai-services/openai/)
- [Azure OpenAI Service Quotas and Limits](https://learn.microsoft.com/azure/ai-services/openai/quotas-limits)
- [Manage Azure OpenAI Quotas](https://learn.microsoft.com/azure/ai-services/openai/how-to/quota)
- [Provisioned Throughput Units (PTU)](https://learn.microsoft.com/azure/ai-services/openai/concepts/provisioned-throughput)
- [Microsoft Discovery Platform Documentation](../README.md)
