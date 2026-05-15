# Model Deployment Guide for Microsoft Discovery

This comprehensive guide walks you through deploying machine learning models in Microsoft Discovery, covering both Azure Portal experience and ARM template deployment approaches. Models in Microsoft Discovery serve as the foundation for creating intelligent tools and agents that power scientific research workflows.

## Model Deployment Overview

Microsoft Discovery models are AI/ML resources that provide inference capabilities for scientific workflows.

### Model Types Supported

Microsoft DIscovery just supports **MaaP (Model as a Platform)** based models in Private Preview which offers dedicated compute deployments.

**Assumption**:

This guide assumes your model is already published in Azure Foundry Model Catalog. If your model is not yet published, please follow the [Publisher Guide](models-publishing/) first.

## Prerequisites

Before deploying models in Microsoft Discovery, ensure you have the following:

### 1. Platform Prerequisites

- **Active Azure subscription** with Microsoft Discovery resource provider registered
- **Sufficient permissions** to create and manage Microsoft Discovery resources

### 2. Published Model Requirements

- **Published model** in Azure ML Model Catalog with format:

  ```text
  azureml://registries/azureml/models/{model-name}/versions/{version}
  ```

- **Model validation** completed and model ready for deployment
- **Appropriate licenses** and compliance for model usage

### 3. Resource Group Organization

Models and related resources can be organized in resource groups following these patterns:

- **Development**: `contoso-discovery-dev-rg`
- **Testing**: `contoso-discovery-test-rg`  
- **Production**: `contoso-discovery-prod-rg`

Each resource group should contain the complete set of related resources for that environment:

```text
contoso-discovery-prod-rg/
├── contoso-chemistry-workspace-prod
├── chemistry-model-v1-prod
├── chemistry-tool-client-prod
├── chemistry-agent-prod
└── supporting-infrastructure
```

### 4. Azure Quota Requirements

Ensure sufficient quota in your target region for:

- **Azure ML compute instances** (for MaaP deployments)
- **Azure OpenAI quota** (if using OpenAI models for agents)
- **VM SKUs** specified in model definitions
- See [Quotas and Limits](../../5-management/resource-limits.md) for detailed requirements

### 5. Model, Tool and Agent Defintions

User has already created Model, Tool and Agent definition YAML artifacts.

## Model Deployment via Azure Portal

### Step 1: Navigate to Model Creation

1. **Sign in to the Azure Portal**
   - Navigate to [Azure Portal](https://portal.azure.com)
   - Authenticate with your Azure credentials

2. **Access Microsoft Discovery Models**
   - In the Azure Portal search bar, type "Microsoft Discovery Models"
   - Select **Microsoft Discovery Models** from the search results
   - Click **"Create"** to start the model deployment process

### Step 2: Configure Basic Model Settings

Configure the fundamental model properties:

- **Subscription**: Select the Azure subscription containing your Discovery workspace
- **Resource Group**: Choose the resource group for organizing your model resources
  - **Recommended**: Use environment-specific resource groups (dev, test, prod)
- **Model Name**: Enter a descriptive name for your model resource
  - **Format**: `{purpose}-{model-type}-{version}` (e.g., `medimage-parse-v1`)
- **Region**: Select the Azure region where your workspace is deployed
  - **Important**: Must match your workspace region for optimal performance
- **Workspace Id**: Enter the resource id of workspace to which this model shall be associated

   ```text
   /subscriptions/{subscription-id}/resourceGroups/{rg-name}/providers/Microsoft.Discovery/workspaces/{workspace-name}
   ```

### Step 3: Upload Model Definition

1. **Prepare Model Definition File**
   - Create a YAML file defining your model configuration
   - **For MaaP models**, use this template:

      **Modeldefinition.yaml**

```yaml
name: model1
description: Description of Model.
version: "1.0.0"
category: Machine Learning model
license: MIT
infra:
  - name: worker
    infra_type: maap
    image:
      model_id: azureml://registries/azureml/models/model1/versions/1
    compute:
      vm_skus: Standard_NC40ads_H100_v5
      pool_type: static
      pool_size: 1
```

2. **Convert YAML to JSON**

    Use the utility for [definition content creator](../../utils/README.md) to generate a JSON file.

3. **Upload Definition**
   - **Definition Content File**: Upload your model definition YAML file
   - **Definition Content Version**: Enter `2025-05-15-preview`

### Step 4: Review and Create

1. **Review Configuration**
   - Verify all model settings are correct
   - Confirm workspace and region alignment
   - Check model asset ID format

2. **Create Model Resource**
   - Click **"Review + create"**
   - Review the terms and conditions
   - Click **"Create"** to deploy the model resource

The model deployment typically takes 10-20 minutes depending on the model size and compute requirements.

### Step 5: Create Associated Tool and Agent

After the model resource is created, you'll need to create the associated tool and agent resources to complete the deployment workflow.

#### Create Model Tool Client

Follow the instructions on [how to deploy a Tools resource](./b--tool-deployment.md).

#### Create Model Agent

Follow the instructions on [how to deploy a Agents resource](./c--agent-deployment.md).

## Model Deployment via ARM Templates

For automated deployments and infrastructure-as-code scenarios, you can create custom ARM templates or use the Azure CLI for scripted deployments.

### Automated Deployment Overview

When creating automated deployments, you should create three interconnected resources with proper dependencies.

The model deployment process creates three interconnected resources:

```text
1. Model Resource (Microsoft.Discovery/models)
   └── Defines the ML model configuration and workspace integration
   
2. Tool Resource (Microsoft.Discovery/tools)
   ├── Depends on: Model Resource
   ├── Environment Variables: MODEL_ENDPOINT → Model Resource ID
   └── Acts as client interface to the model
   
3. Agent Resource (Microsoft.Discovery/agents)
   ├── Depends on: Tool Resource
   ├── Tools Array: References Tool Resource
   └── Provides intelligent workflow orchestration
```

For deployment instructions, refer to the Microsoft Discovery documentation or use the Azure CLI for resource creation.

## Post-Deployment Configuration

### 1. Verify Resource Creation

After deployment, verify all resources are created successfully:

```bash
# List model resources
az resource list --resource-type "Microsoft.Discovery/models" --output table

# List tool resources
az resource list --resource-type "Microsoft.Discovery/tools" --output table

# List agent resources
az resource list --resource-type "Microsoft.Discovery/agents" --output table
```

## Next Steps

After successfully deploying your model:

1. **[Create Projects](../7-projects/)** - Organize research using your deployed model
2. **[Run Investigations](../8-investigations/)** - Test model functionality in research workflows  

## Related Documentation

- [Microsoft Discovery Models Overview](../../3-concepts/models.md)
- [Publisher Guide for Models](models-publishing/)
