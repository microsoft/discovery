# Microsoft Discovery Workspace Creation

This comprehensive guide walks you through creating a Microsoft Discovery workspace, which serves as the collaborative foundation for managing large-scale scientific initiatives. Workspaces enable research teams to organize experiments, analyze data, and leverage AI agents and tools within a shared, secure environment.

## What is a Microsoft Discovery Workspace?

A Microsoft Discovery workspace is a collaborative environment that provides:

- **Centralized resource management** for storage, supercomputers, and compute resources
- **Project organization** allowing multiple research projects under one workspace
- **Shared infrastructure** enabling cost-effective resource utilization across teams
- **Security boundaries** with role-based access control and managed identity integration
- **Data governance** through integrated data containers and asset management

Workspaces serve as the top-level organizational unit in Microsoft Discovery, containing projects that house your actual research investigations, experiments, and computational workflows.

## Prerequisites

Before creating a workspace, ensure you have completed the following foundational steps:

### 1. Resource Provider Registration

- Microsoft Discovery resource provider (`Microsoft.Discovery`) must be registered in your Azure subscription
- Your subscription must be enabled by the Microsoft Discovery team
- See [Resource Provider Registration Guide](../2-onboarding-experience/a--rp-registration.md) for detailed instructions

### 2. Permissions and Roles

- **Azure roles**: Contributor or Owner role on the target Azure subscription or resource group
- **Microsoft Discovery roles**: Microsoft Discovery Platform Administrator or Contributor role for ongoing workspace management
- See [Role Assignments Guide](../2-onboarding-experience/c--role-assignments.md) for comprehensive RBAC information

### 3. Infrastructure Prerequisites

The following infrastructure components must exist before workspace creation:

#### Networking Infrastructure

- **Virtual Network** with appropriate CIDR blocks (minimum /24, recommended /16 or /20)
- **Subnets** for storage, supercomputer, and other components
- See [Virtual Networks and Subnets Guide](../3-basic-building-blocks/a--virtual-network-subnets.md)

#### Storage Infrastructure

- **Microsoft Discovery Storage** resource (Azure NetApp Files or similar)
- **Azure Storage Blob accounts** (NFSv3 enabled) for data containers
- Proper CORS settings and virtual network access configured

#### Compute Infrastructure

- **Supercomputer** resource with associated node pools
- **User Assigned Managed Identities** with appropriate role assignments
- See [Managed Identities Guide](../3-basic-building-blocks/c--managed-identities.md)

### 4. Azure Quota and Capacity Planning

Ensure sufficient quota in your target region for:

- Azure NetApp Files capacity (if using Microsoft Discovery Storage)
- Virtual machine SKUs for supercomputer node pools
- Azure OpenAI or Azure AI Foundry quotas for AI models
- See [Quotas and Limits](../../5-management/resource-limits.md) for detailed requirements

## Creating a Microsoft Discovery Workspace

### Method 1: Azure Portal (Recommended)

#### Step 1: Navigate to Workspace Creation

1. **Sign in to the Azure Portal**
   - Navigate to [https://portal.azure.com](https://portal.azure.com)
   - Authenticate with your Entra ID credentials

2. **Access Microsoft Discovery Workspaces**
   - In the Azure Portal search bar, type "Microsoft Discovery Workspaces"
   - Select **Microsoft Discovery Workspaces** from the search results
   - Click **"Create"** to start the workspace creation process

#### Step 2: Configure Basic Settings

Configure the fundamental workspace properties:

- **Subscription**: Select the Azure subscription where the workspace will be created
- **Resource Group**: Choose an existing resource group or create a new one
  - Recommended naming: `{organization}-discovery-{environment}-rg` (e.g., `contoso-discovery-prod-rg`)
- **Workspace Name**: Enter a descriptive name following naming conventions
  - Recommended format: `{organization}-{purpose}-workspace-{environment}` (e.g., `contoso-chemistry-workspace-prod`)
- **Region**: Select the Azure region where your infrastructure components are deployed
  - **Important**: All associated resources (storage, supercomputer) must be in the same region

**Click "Next" to proceed to storage configuration.**

#### Step 3: Configure Discovery Storage

Associate your Microsoft Discovery Storage resources with the workspace:

1. **Add Discovery Storage**
   > **Note:** While the platform supports associating multiple Discovery Storage resources with a workspace, a known issue in the Private Preview release currently requires that only one Discovery Storage resource be associated per workspace.

   - Click **"Add Discovery Storage"**
   - **Subscription**: Select the subscription containing your storage resource
   - **Resource Group**: Choose the resource group containing your Microsoft Discovery Storage
   - **Storage Resource**: Select your pre-created Microsoft Discovery Storage resource

2. **Storage Validation**
   - Ensure the storage resource is in the same region as your workspace
   - Verify the storage is properly configured and accessible
   - Confirm virtual network connectivity between storage and planned supercomputer resources

**Click "Next" to proceed to supercomputer configuration.**

#### Step 4: Configure Supercomputer Resources

> **Note:** While the platform supports associating multiple Discovery Storage resources with a workspace, a known issue in the Private Preview release currently requires that only one Supercomputer resource be associated per workspace.

Associate supercomputer resources that will provide compute capacity for your workspace:

1. **Add Supercomputer**
   - Click **"Add Supercomputer"**
   - **Subscription**: Select the subscription containing your supercomputer
   - **Resource Group**: Choose the resource group with your supercomputer resource
   - **Supercomputer**: Select your pre-created supercomputer resource

2. **Supercomputer Requirements Verification**
   - Confirm the supercomputer has at least one configured node pool
   - Verify proper networking configuration (same virtual network as storage)
   - Ensure managed identities are properly configured with required permissions

**Click "Next" to proceed to identity configuration.**

#### Step 5: Configure Workspace Identity

> **Note:** While the platform supports associating System Assigned Managed Identity with a workspace, a known issue in the Private Preview release currently requires that you create and associate a single User Assigned Managed Identity with workspace.

Set up the managed identity that will be used by the workspace for resource access:

1. **Add User Assigned Managed Identity (UAMI)**
   - Click **"Add"** under User Assigned Managed Identity section
   - **Subscription**: Select the subscription containing your managed identity
   - **Resource Group**: Choose the resource group with your managed identity
   - **Managed Identity**: Select your pre-configured managed identity

2. **Identity Permissions Verification**
   Ensure your managed identity has the following role assignments:
   - **Storage permissions**: Storage Blob Data Contributor on associated storage accounts
   - **Compute permissions**: Appropriate access to supercomputer resources
   - **Networking permissions**: Access to virtual network resources

**Click "Next" to review and create.**

#### Step 6: Review and Create

1. **Review Configuration**
   - Verify all selected resources are correct
   - Confirm resource locations and networking alignment
   - Check managed identity permissions and role assignments

2. **Accept Terms and Conditions**
   - Review the Microsoft Discovery terms and conditions
   - Accept the agreement to proceed with workspace creation

3. **Create Workspace**
   - Click **"Create"** to initiate workspace deployment
   - Monitor the deployment progress in the Azure Portal
   - Workspace creation typically takes 5-15 minutes

### Method 2: Azure CLI

For automation and infrastructure-as-code scenarios, you can create workspaces using Azure CLI:

```azurecli
# Create workspace using Azure CLI
az discovery workspace create \
  --resource-group "contoso-discovery-prod-rg" \
  --name "contoso-chemistry-workspace-prod" \
  --location "eastus2" \
  --storage-resources '[{
    "id": "/subscriptions/{subscription-id}/resourceGroups/{rg-name}/providers/Microsoft.Discovery/storages/{storage-name}"
  }]' \
  --supercomputer-resources '[{
    "id": "/subscriptions/{subscription-id}/resourceGroups/{rg-name}/providers/Microsoft.Discovery/supercomputers/{supercomputer-name}"
  }]' \
  --managed-identity '{
    "userAssignedIdentities": {
      "/subscriptions/{subscription-id}/resourceGroups/{rg-name}/providers/Microsoft.ManagedIdentity/userAssignedIdentities/{identity-name}": {}
    }
  }'
```

## Post-Creation Configuration

### 1. Access Control Configuration

After workspace creation, configure role-based access control:

#### Assign Microsoft Discovery Roles

1. **Navigate to workspace IAM**
   - Open your newly created workspace in the Azure Portal
   - Select **"Access control (IAM)"** from the left navigation

2. **Add role assignments**
   - Click **"Add"** > **"Add role assignment"**
   - Select appropriate Microsoft Discovery roles:
     - **Microsoft Discovery Platform Contributor**: For researchers and scientists
     - **Microsoft Discovery Platform Reader**: For observers and reviewers

3. **Assign to users and groups**
   - Select users, groups, or service principals
   - Ensure assignments align with your organization's access policies

#### Role Assignment Examples

```azurecli
# Assign Contributor role to research team
az role assignment create \
  --role "Microsoft Discovery Platform Contributor" \
  --assignee-object-id "{user-object-id}" \
  --scope "/subscriptions/{subscription-id}/resourceGroups/{rg-name}/providers/Microsoft.Discovery/workspaces/{workspace-name}"

# Assign Reader role to stakeholders
az role assignment create \
  --role "Microsoft Discovery Platform Reader" \
  --assignee-object-id "{group-object-id}" \
  --scope "/subscriptions/{subscription-id}/resourceGroups/{rg-name}/providers/Microsoft.Discovery/workspaces/{workspace-name}"
```

### 2. Connect to Microsoft Discovery Studio

Once your workspace is created and validated:

1. **Access Studio**
   - Navigate to [Microsoft Discovery Studio](https://studio.discovery.microsoft.com)
   - Sign in with your Entra ID credentials

2. **Workspace Selection**
   - Your newly created workspace should appear in the workspace list
   - Select the workspace to begin using Microsoft Discovery

3. **Initial Configuration**
   - Configure data containers for your projects
   - Import any existing tools, models, or agents
   - Create your first project within the workspace

## Important Notes

### Workspace Updates and Stability

When updating an existing workspace resource, please be aware of the following considerations:

> **⚠️ Temporary Message Processing Impact**: Updating a workspace (re-PUT operation) may cause temporary disruptions to in-flight messages being processed. If you experience intermittent failures during or immediately after a workspace update, this is expected behavior that should resolve automatically.

**Best Practices for Workspace Updates:**

1. **Schedule updates during low-activity periods** - When possible, perform workspace updates during times when fewer investigations are actively running to minimize impact.

2. **Update related resources together** - If you encounter recurring errors after updating a workspace, we recommend updating the associated projects, agents, and workspaces as a group. This ensures maximum compatibility across all resources and helps prevent version mismatches.

3. **Monitor after updates** - After updating a workspace, monitor your investigations and workflows for a few minutes to ensure normal operations have resumed.

> **💡 Platform Improvement Note**: We are actively working on improving the workspace update experience by implementing versioning for workspace functions. This enhancement will provide smoother updates with zero impact on running workloads in future releases.

## Next Steps

After successfully creating your workspace:

1. **[Import Tools and Models](../6-tools-models-agents/)** - Add computational capabilities
2. **[Create Projects](../7-projects/a--creating-project.md)** - Organize your research initiatives
3. **[Create Investigations](../8-investigations/)** - Start your research workflows

## Related Documentation

- [Supercomputer Creation Guide](./b--supercomputer-creation.md)
- [Virtual Networks and Subnets](../3-basic-building-blocks/a--virtual-network-subnets.md)
- [Managed Identities](../3-basic-building-blocks/c--managed-identities.md)
- [Role Assignments](../2-onboarding-experience/c--role-assignments.md)
- [Cost Management](../../5-management/cost-management.md)
