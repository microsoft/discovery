# Azure Container Registry (ACR) Creation

Azure Container Registry (ACR) is a critical component in the Microsoft Discovery platform that serves as the repository for your containerized tools images. This guide covers the creation and configuration of ACR for use with Microsoft Discovery.

## Overview

Azure Container Registry provides a secure, private container registry service where you can store and manage your Docker container images. In the Microsoft Discovery context, ACR is used to:

- Store containerized scientific tools and computational packages
- Host custom agent images with specialized capabilities
- Manage model containers for AI/ML workloads
- Provide version control for your containerized components

## Important Note

> **Note**: If you are following the tool publishing workflow described in [Create, Validate, and Publish Tools to ACR](../6-tools-models-agents/tools-publishing/d--create-validate-publish-tools-to-acr.md), the ACR creation steps may already be covered in that guide. You can skip this section if you have already created an ACR as part of the publishing process.

## Prerequisites

Before creating an Azure Container Registry, ensure you have:

### Required Access and Tools

1. **Azure Subscription**
   - Active Azure subscription with appropriate permissions
   - Contributor or Owner role on the target resource group
   - Sufficient quota for Container Registry resources

2. **Azure CLI** (recommended method)
   - Azure CLI installed and configured (`az --version`)
   - Logged into your Azure account (`az login`)

3. **Alternative Tools**
   - Azure Portal access (browser-based method)
   - Azure PowerShell (alternative CLI method)

### Required Permissions

Ensure your Azure account has the following minimum permissions:

- **Contributor** role on the target resource group
- **AcrPush** role for pushing images (can be assigned after creation)
- **AcrPull** role for pulling images (for service principals/managed identities)

## Method 1: Create ACR using Azure Portal

### Step 1: Navigate to Container Registry Service

1. Sign in to the [Azure Portal](https://portal.azure.com)
2. In the search bar, type "Container Registry" and select **Container registries**
3. Click **+ Create** to start the creation process

### Step 2: Configure Basic Settings

1. **Subscription**: Select your Azure subscription
2. **Resource Group**: Choose an existing resource group or create a new one
3. **Registry Name**: Enter a globally unique name (5-50 characters, alphanumeric only)
   - Example: `mydiscoveryacr2025`
4. **Location**: Select the same region where you are planning Microsoft Discovery workspace
5. **SKU**: Choose the appropriate tier:
   - **Basic**: For development and small-scale scenarios
   - **Standard**: Recommended for production workloads
   - **Premium**: For high-scale scenarios with geo-replication needs

### Step 3: Configure Networking

Proper network configuration is crucial for integrating ACR with Microsoft Discovery resources. You have several networking options:

#### Public Network Access

During ACR creation, you can choose:

1. **Enable public network access** (Default):
   - ACR is accessible from the internet with proper authentication
   - Suitable for development environments and when advanced networking isn't required initially

2. **Private access** (Premium SKU only):
   - ACR will only be accessible via private endpoints
   - Must configure private endpoints after creation for access
   - Most secure option but requires additional setup

### Step 4: Review and Create

1. Review all settings in the **Review + create** tab
2. Click **Create** to deploy the Container Registry
3. Wait for deployment to complete (typically 2-3 minutes)

### Step 5: Configure Advanced Networking (Post-Creation)

After ACR creation, you can configure advanced networking.

#### Virtual Network Integration

For true virtual network integration, you need to use **virtual network rules** or **private endpoints** (configured separately after ACR creation):

- **Virtual Network Rules**: Allow access from specific subnets (requires Standard or Premium SKU)
- **Service Endpoints**: Enable on subnets to allow secure access to ACR
- **Private Endpoints**: Create private IP address within your VNet (Premium SKU only)

#### Private Network Access

1. **Private endpoints**: Most secure option for production workloads
   - Creates a private IP address for ACR within your virtual network
   - Requires existing virtual network with appropriate subnets

**Note**: All advanced networking configurations (IP restrictions, virtual network rules, private endpoints) must be configured **after** ACR creation through the ACR resource's networking settings or using Azure CLI, as shown in the CLI examples below.

#### Configuration through Azure Portal

1. Navigate to your newly created ACR resource
2. In the left menu, select **Networking** under Settings
3. Here you can configure:
   - **Firewall and virtual networks**: Add IP ranges, virtual network rules
   - **Private endpoint connections**: Create private endpoints for VNet integration
   - **Public network access**: Modify the public access settings

## Method 2: Create ACR using Azure CLI

### Step 1: Set Variables

```bash
# Set your configuration variables
SUBSCRIPTION_ID="your-subscription-id"
RESOURCE_GROUP="your-resource-group"
ACR_NAME="your-unique-acr-name"
LOCATION="eastus"  # Use same region as your Discovery workspace
SKU="Standard"     # Basic, Standard, or Premium
```

### Step 2: Create Resource Group (if needed)

```bash
# Create resource group if it doesn't exist
az group create \
  --name $RESOURCE_GROUP \
  --location $LOCATION
```

### Step 3: Create Container Registry

```bash
# Create the Container Registry with public access (default)
az acr create \
  --resource-group $RESOURCE_GROUP \
  --name $ACR_NAME \
  --sku $SKU \
  --location $LOCATION \
  --admin-enabled true

# Create ACR with public access disabled (for private endpoint setup)
az acr create \
  --resource-group $RESOURCE_GROUP \
  --name $ACR_NAME \
  --sku Premium \
  --location $LOCATION \
  --admin-enabled true \
  --public-network-enabled false
```

### Step 3a: Configure Network Access (Optional)

If you want to restrict ACR access to your Microsoft Discovery virtual network:

First, get your virtual network and subnet information from [Virtual Networks and Subnets Guide](./a--virtual-network-subnets.md)

- VNET_NAME="vnet-discovery-prod"
- SUBNET_NAME="subnet-discovery-supercomputer"
- VNET_RESOURCE_GROUP="rg-discovery-networking"

#### Option 1: Configure Virtual Network Rules

```bash
# Allow access from specific subnet (requires Standard or Premium SKU)
az acr network-rule add \
  --name $ACR_NAME \
  --vnet-name $VNET_NAME \
  --subnet $SUBNET_NAME \
  --resource-group $VNET_RESOURCE_GROUP

# Add additional subnets based on Virtual Networks and Subnets Guide
# AKS subnet (if using separate AKS deployment)
az acr network-rule add \
  --name $ACR_NAME \
  --vnet-name $VNET_NAME \
  --subnet "subnet-discovery-aks" \
  --resource-group $VNET_RESOURCE_GROUP

# Allow access from Supercomputer subnet (required for node pools to pull images)
az acr network-rule add \
  --name $ACR_NAME \
  --vnet-name $VNET_NAME \
  --subnet "subnet-discovery-supercomputer" \
  --resource-group $VNET_RESOURCE_GROUP
```

#### Option 2: Create Private Endpoint (Premium SKU only)

```bash
# Create private endpoint for ACR
az network private-endpoint create \
  --name "pe-acr-$ACR_NAME" \
  --resource-group $RESOURCE_GROUP \
  --vnet-name $VNET_NAME \
  --subnet $SUBNET_NAME \
  --private-connection-resource-id "/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.ContainerRegistry/registries/$ACR_NAME" \
  --group-id registry \
  --connection-name "conn-acr-$ACR_NAME" \
  --location $LOCATION

# Create private DNS zone for ACR
az network private-dns zone create \
  --resource-group $RESOURCE_GROUP \
  --name "privatelink.azurecr.io"

# Link DNS zone to virtual network
az network private-dns link vnet create \
  --resource-group $RESOURCE_GROUP \
  --zone-name "privatelink.azurecr.io" \
  --name "link-acr-$ACR_NAME" \
  --virtual-network $VNET_NAME \
  --registration-enabled false
```

### Step 4: Verify Creation

```bash
# Verify the registry was created successfully
az acr show --name $ACR_NAME --resource-group $RESOURCE_GROUP

# Get the login server URL
az acr show --name $ACR_NAME --query loginServer --output tsv
```

## Integration with Microsoft Discovery

### For integration with Supercomputer

You need to enable appropriate pull access permissions to Supercomputer to enable autonomous deployment of tools on your behalf. Follow the instruction for [Supercomputer access to ACR](./c--managed-identities.md#container-registry-permissions-if-using-custom-tools)

### For Tool Publishers

If you're developing and publishing tools for Microsoft Discovery, your ACR will store the containerized versions of your tools. This is covered in detail in the [tool publishing workflow](../6-tools-models-agents/tools-publishing/d--create-validate-publish-tools-to-acr.md).

## Additional Resources

- [Virtual Networks and Subnets for Microsoft Discovery](./a--virtual-network-subnets.md)
- [Azure Container Registry Documentation](https://docs.microsoft.com/en-us/azure/container-registry/)
- [Azure Container Registry Network Rules](https://docs.microsoft.com/en-us/azure/container-registry/container-registry-access-selected-networks)
- [Azure Private Endpoints](https://docs.microsoft.com/en-us/azure/private-link/private-endpoint-overview)
- [Container Registry Best Practices](https://docs.microsoft.com/en-us/azure/container-registry/container-registry-best-practices)
- [Docker Documentation](https://docs.docker.com/)
