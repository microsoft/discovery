# Managed Identities in Microsoft Discovery

This guide provides comprehensive information about creating and configuring User Assigned Managed Identities (UAMI) for Microsoft Discovery resources. Managed identities are essential for secure authentication and authorization within the Microsoft Discovery platform, enabling seamless access to Azure resources without storing credentials.

## Overview

User Assigned Managed Identities (UAMI) in Microsoft Discovery provide secure, credential-free authentication for various platform components. These identities are used by:

- **Supercomputers** - For accessing storage resources and executing computational workloads
- **Workspaces** - For platform-level resource access and coordination
- **Data Containers** - For reading and writing data to Azure Storage accounts
- **Tools** - For making secure API calls to external services

## Prerequisites

Before creating managed identities for Microsoft Discovery, ensure you have:

- An active Azure subscription with Microsoft Discovery resource provider registered
- Sufficient permissions to create and manage Azure resources
- **Contributor** or **Owner** role on the Azure subscription or resource group
- Understanding of your planned Microsoft Discovery infrastructure layout
- Virtual Network and Subnets already created for your Microsoft Discovery resources

> **Important**: You should create your User Assigned Managed Identities **before** creating your Microsoft Discovery infrastructure resources (Storage, Supercomputer, Workspace) as they will be required during the resource creation process.

## Creating User Assigned Managed Identities

### Step 1: Create the Managed Identity

You'll need to create a single User Assigned Managed Identity for your Microsoft Discovery deployment. For the private preview, you can use one identity across all Microsoft Discovery resources:

1. **Contoso Research Identity** - For all supercomputer, workspace, and data access operations

> **Note**: For simplicity in private preview, you can use the same UAMI for all Microsoft Discovery resources (supercomputer cluster identity, kubelet identity, workload identity, workspace identity, and data access identity). This simplifies management while maintaining security.

#### Using Azure Portal

1. Sign in to the [Azure Portal](https://portal.azure.com)
2. Search for "Managed Identities" and select the service
3. Click **"Create"**
4. Fill in the required details:
   - **Subscription**: Select your target subscription
   - **Resource Group**: Choose or create a resource group for identities (e.g., `contoso-discovery-rg`)
   - **Region**: Select the same region as your Microsoft Discovery resources
   - **Name**: Use a descriptive name (e.g., `contoso-research-identity`)
5. Click **"Review + Create"** and then **"Create"**

#### Using Azure CLI

```bash
# Create a resource group for managed identities (if needed)
az group create --name contoso-discovery-rg --location eastus2

# Create managed identity for all Microsoft Discovery resources
az identity create \
  --resource-group contoso-discovery-rg \
  --name contoso-research-identity \
  --location eastus2
```

#### Using PowerShell

```powershell
# Create managed identity for all Microsoft Discovery resources
New-AzUserAssignedIdentity `
  -ResourceGroupName "contoso-discovery-rg" `
  -Name "contoso-research-identity" `
  -Location "East US 2"
```

### Step 2: Record Identity Information

After creating the managed identity, record the following information for later use:

- **Client ID** (Application ID)
- **Principal ID** (Object ID)
- **Resource ID** (Full Azure Resource Manager ID)

You can find this information in the Azure Portal under the managed identity resource properties.

## Required Permissions and Role Assignments

To enable successful investigations in Microsoft Discovery, your managed identity requires specific permissions across various Azure resources. The following sections detail the minimum required permissions.

### Azure Storage Account Permissions

For data containers backed by Azure Storage accounts, assign these roles to your **contoso-research-identity**:

#### Storage Account Required Roles

| Role | Purpose | Scope |
|------|---------|-------|
| **Storage Blob Data Contributor** | Read/write access to blob containers and data | Storage Account or specific containers |

#### Storage Account Assignment Commands

```bash
# Get the managed identity principal ID
IDENTITY_PRINCIPAL_ID=$(az identity show \
  --resource-group contoso-discovery-rg \
  --name contoso-research-identity \
  --query principalId -o tsv)

# Get the storage account resource ID
STORAGE_ACCOUNT_ID=$(az storage account show \
  --name contosoresearchstorage \
  --resource-group contoso-discovery-rg \
  --query id -o tsv)

# Assign Storage Blob Data Contributor role
az role assignment create \
  --assignee $IDENTITY_PRINCIPAL_ID \
  --role "Storage Blob Data Contributor" \
  --scope $STORAGE_ACCOUNT_ID
```

### Container Registry Permissions (If Using Custom Tools)

For supercomputers to pull custom tool containers, assign these roles to your **contoso-research-identity**:

#### Container Registry Required Roles

| Role | Purpose | Scope |
|------|---------|-------|
| **AcrPull** | Pull container images from Azure Container Registry | Container Registry |

#### Container Registry Assignment Commands

```bash
# Get the managed identity principal ID
IDENTITY_PRINCIPAL_ID=$(az identity show \
  --resource-group contoso-discovery-rg \
  --name contoso-research-identity \
  --query principalId -o tsv)

# Get container registry resource ID
# Update registry name before you run the command below.

ACR_ID=$(az acr show \
  --name contosoresearchregistry \ 
  --query id -o tsv)

# Assign AcrPull role to managed identity
az role assignment create \
  --assignee $IDENTITY_PRINCIPAL_ID \
  --role "AcrPull" \
  --scope $ACR_ID
```

### Microsoft Discovery Resource Permissions

For workspace and platform operations, assign these roles to your **contoso-research-identity**:

#### Discovery Resource Required Roles

| Role | Purpose | Scope |
|------|---------|-------|
| **Microsoft Discovery Platform Contributor (Preview)** | Access to other Azure resources | Resource Group or Workspace |

#### Discovery Resource Assignment Commands

```bash
# Get the managed identity principal ID
IDENTITY_PRINCIPAL_ID=$(az identity show \
  --resource-group contoso-discovery-rg \
  --name contoso-research-identity \
  --query principalId -o tsv)

# Get the resource group scope
RESOURCE_GROUP_SCOPE="/subscriptions/$(az account show --query id -o tsv)/resourceGroups/contoso-discovery-rg"

# Assign TBD role
az role assignment create \
  --assignee $IDENTITY_PRINCIPAL_ID \
  --role "Microsoft Discovery Platform Contributor (Preview)" \
  --scope $RESOURCE_GROUP_SCOPE
```

## Configuring Managed Identities in Microsoft Discovery Resources

### Supercomputer Configuration

When creating a supercomputer, you need to assign managed identities for three different purposes:

1. **Cluster Identity** - Overall cluster management
2. **Kubelet Identity** - Node-level operations  
3. **Workload Identity** - Application workload authentication

**Best Practice**: For private preview, you can use the same UAMI (`contoso-research-identity`) for all three purposes to simplify management.

#### During Supercomputer Creation

1. In the Azure Portal, navigate to **Microsoft Discovery Supercomputers**
2. Click **"Create"** and fill in basic details
3. Navigate through the networking configuration
4. In the **"Identity"** section:
   - Select **"User Assigned"** for each identity type (cluster, kubelet, workload)
   - Choose your `contoso-research-identity` for all three
   - This identity will be used to access storage resources and execute computational workloads
5. Complete the creation process

> **Important**: Ensure your managed identity has the required role assignments (Network Contributor, Storage access, etc.) before creating the supercomputer.

### Workspace Configuration

The workspace requires a User Assigned Managed Identity to provide access to the workspace resource and enable platform-level operations.

#### During Workspace Creation

1. Navigate to **Microsoft Discovery Workspaces** in Azure Portal
2. Click **"Create"** and fill in basic details
3. Configure your Discovery Storages and Supercomputers
4. In the **"Workspace Identity"** tab:
   - Click **"Add"** under User Assigned Managed Identity (UAMI)
   - Select your `contoso-research-identity`
   - This identity provides access to the workspace resource and coordinates platform operations
5. Complete the workspace creation

> **Note**: The workspace identity should have the appropriate role assignments for Discovery Platform operations and monitoring access.

### Data Container Configuration

Data containers require managed identity authentication to access Azure Storage accounts securely.

#### During Data Container Creation

1. In Microsoft Discovery Studio, navigate to **Data Containers**
2. Click **"Create Data Container"**
3. Enter the container details (name, subscription, resource group, location)
4. Select **Azure Storage Blob** as the data store type and choose your storage account
5. In the authentication section:
   - Choose **"Managed Identity"** authentication  
   - Select your `contoso-research-identity`
   - This identity must have Storage Blob Data Contributor access to read/write files
6. Complete the container creation

> **Important**: Ensure your managed identity has the required storage permissions (Storage Blob Data Contributor, Reader) before creating data containers.

## Related Resources

- [Azure Managed Identities Documentation](https://learn.microsoft.com/entra/identity/managed-identities-azure-resources/)
- [Azure RBAC Best Practices](https://learn.microsoft.com/azure/role-based-access-control/best-practices)
