# Role Assignments in Microsoft Discovery

This guide helps Microsoft Discovery users understand role-based access control (RBAC) and how to work with role assignments within the Microsoft Discovery platform. Role assignments control who can access what resources and what actions they can perform.

## Understanding Azure Role Assignments

Role assignments are the fundamental building blocks of access control in Azure and Microsoft Discovery. When you grant access to resources, you create a role assignment, and when you revoke access, you remove a role assignment.

### Example Role Assignment

Here's what a typical role assignment looks like:

**Example:** "User Sarah Johnson has Microsoft Discovery Contributor access to the Microsoft Discovery workspace 'contoso-project-workspace' in the resource group 'contoso-discovery-rg'."

In this example:

- **Principal:** Sarah Johnson (user)
- **Role:** Microsoft Discovery Contributor
- **Scope:** 'contoso-discovery-rg'
- **Context:** Research project collaboration

For more information, please refer to the [Azure learn documentation](https://learn.microsoft.com/en-us/azure/role-based-access-control/role-assignments).

## Microsoft Discovery Roles and Permissions

Microsoft Discovery implements role-based access control through Azure RBAC, providing granular permissions for scientific research workflows. The platform includes Microsoft Discovery-specific roles designed around research personas and common use cases in scientific computing.

Microsoft Discovery provides three specialized roles designed for scientific research workflows, listed in order of decreasing permissions:

### Microsoft Discovery Platform Administrator (Preview)

**Target Persona:** Platform Admins (IT Administrators, DevOps Engineers)

**Description:** Platform Admins are typically found in most customer scenarios, especially among large enterprise customers. They are familiar with Azure and prioritize the security of their organization's assets, cost control, and governance. They seek efficiency, scalability, and reliability, and aim to automate as much as possible. They manage the infrastructure and are responsible to create resources which are required for users to work with Microsoft Discovery.

**Assignable scope:** Subscription or Resource Group

**Primary Interface:** Azure Portal, Microsoft Discovery Studio, REST APIs, CLIs, and SDKs

**Permissions:** Grants full access to manage all Microsoft Discovery resources including both control plane and data plane operations.

**Key Capabilities:**

- **Full administrative access** to all Microsoft Discovery resources
- **Infrastructure management:** Create, update, and delete workspaces, supercomputers, storages, and node pools
- **Project lifecycle management:** Complete control over project creation, management, and deletion
- **Research resource management:** Manage tools, models, agents, workflows, investigations, and bookshelves
- **Data management:** Full access to data containers and data assets
- **Platform governance:** Configure platform settings and manage access controls
- **User access management:** Manage user access to Microsoft Discovery resources via Role Based Access Control (RBAC)

| Permission | Reason |
| --- | --- |
| Microsoft.Discovery/locations/operationStatuses/read | To fetch status of ongoing API operations |
| Microsoft.Discovery/checkNameAvailability/action | To check name availability during workspace creation to make sure the name is unique globally |
| Microsoft.Discovery/* | To read, write and delete access to all Microsoft Discovery resource types including data resources such as investigations |
| Microsoft.Authorization/*/read | To check assigned permissions for each resource |
| Microsoft.Insights/alertRules/* | To read and modify alert rules on resources |
| Microsoft.Resources/deployments/* | To fetch deployment status of resources in the resource group |
| Microsoft.Resources/subscriptions/resourceGroups/read | To read resources within a resource group |
| Microsoft.Network/virtualNetworks/subnets/read | To read the configuration of subnets within a virtual network which is used to deploy Supercomputer node pools VMs |
| Microsoft.Network/virtualNetworks/read | To read the configuration of the virtual network during Supercomputer deployment (subnets are child resources of VNets) |
| Microsoft.Network/virtualNetworks/subnets/join/action | For linked access checks since Supercomputer resource references the subnet for node pool deployment |
| Microsoft.Support/* | To raise support tickets for the subscription in case of issues that require assistance |
| Microsoft.Authorization/roleAssignments/write | To assign access to platform users to resources created within the scope and to delegate access to managed identities |
| Microsoft.Authorization/roleAssignments/delete | To revoke access to any resources when there is a requirement |

> **⚠️ Note:** While Microsoft Discovery Platform Administrator (Preview) role also includes the permissions to assign other roles within the assigned scope so administrators don't explicitly need Owner or User Access Administrator roles assigned.

### Microsoft Discovery Platform Contributor (Preview)

**Target Persona:** Scientists and Researchers (Computational Scientists, Domain Experts, Research Teams)

**Description:** Contributors are end users of the platform, typically trained scientists/researchers working for large commercial enterprises. They are domain experts in specific science verticals (Chemistry, Physics, or Biology) and typically work on multiple early-stage R&D projects. They are highly aware of current research but may not be comfortable with coding or high-performance computing.

**Assignable scope:** Subscription or Resource Group

**Primary Interface:** Microsoft Discovery Studio

**Permissions:** Grants permissions to view and operate on most Discovery platform resources with full data plane access, but restricts creation/modification of core infrastructure resources.

**Key Capabilities:**

- **Research operations:** Full access to create, modify, and manage investigations, tools, models, agents, and workflows
- **Data management:** Complete control over data containers and data assets
- **Resource utilization:** Read access to workspaces, supercomputers, storages, bookshelves, and node pools
- **Collaboration:** Share and collaborate on research through conversations and shared investigations

**Key Limitations:**

- **Cannot create or modify infrastructure:** No permissions to create, update, or delete workspaces, supercomputers, storages, bookshelves, node pools, or projects
- **No administrative access:** Cannot manage platform configuration or assign roles to other users

| Permission | Reason |
| --- | --- |
| Microsoft.Discovery/locations/operationStatuses/read | To fetch status of ongoing API operations |
| Microsoft.Discovery/operations/read | To fetch operations and their details |
| Microsoft.Discovery/workspaces/read | To read workspace details, cannot write or delete the resource |
| Microsoft.Discovery/supercomputers/read | To read supercomputer details, cannot write or delete the resource |
| Microsoft.Discovery/storages/read | To read discovery storage details, cannot write or delete the resource |
| Microsoft.Discovery/agents/* | To read, write, and delete agents within the scope |
| Microsoft.Discovery/bookshelves/read | To read bookshelf, cannot write or delete the resource |
| Microsoft.Discovery/dataContainers/* | To read, write, and delete data container resources within the scope |
| Microsoft.Discovery/dataContainers/dataAssets/* | To read, write, and delete data container resources within data containers in the scope |
| Microsoft.Discovery/models/* | To read, write, and delete model resources within the scope |
| Microsoft.Discovery/supercomputers/nodePools/read | To read node pools within supercomputer resources in the scope |
| Microsoft.Discovery/tools/* | To read, write, and delete tool resources within the scope |
| Microsoft.Discovery/workflows/* | To read, write, and delete workflow resources within the scope |
| Microsoft.Discovery/workspaces/projects/read | To read details of projects, cannot write or delete the resource |
| Microsoft.Discovery/operations/read | To read operations for Microsoft Discovery resource types |
| Microsoft.Insights/AlertRules/* | To read and modify alert rules on resources |
| Microsoft.Authorization/*/read | To read role assignments for a resource |
| Microsoft.Resources/deployments/* | To fetch resource deployment details including status |
| Microsoft.Resources/subscriptions/resourceGroups/read | To read resource groups within the scope |
| Microsoft.Support/ | To create support tickets when assistance is required |

### Microsoft Discovery Platform Reader (Preview)

**Target Persona:** Observers and Reviewers (Guest Users, Internal Teams, Partners)

**Description:** Readers are end users of the platform with limited privileges to view and review information. They cannot create or update resources or interact with the platform for computational work.

**Assignable scope:** Subscription or Resource Group

**Primary Interface:** Microsoft Discovery Studio (Read-only access)

**Permissions:** Grants read-only access to all Microsoft Discovery resources for both control plane and data plane operations.

**Key Capabilities:**

- **View and review:** Read-only access to all resources including workspaces, projects, investigations, and research outputs
- **Monitor progress:** Observe research activities, workflow executions, and results
- **Knowledge access:** Read access to bookshelves, conversations, and shared research data
- **Resource inspection:** View tools, models, agents, and workflow configurations

**Key Limitations:**

- **No creation or modification rights:** Cannot create, update, or delete any resources
- **No execution permissions:** Cannot run workflows, start investigations, or perform computational work
- **No data uploads:** Cannot upload or modify data containers or data assets

| Permission | Reason |
| --- | --- |
| Microsoft.Discovery/*/read | To list and fetch details of all Microsoft Discovery resource types, but cannot write or delete any resource within the scope |
| Microsoft.Resources/deployments/* | To list and fetch deployments of resources within the scope |
| Microsoft.Resources/subscriptions/resourceGroups/read | To read resource group details within the scope |

## Role Assignment Prerequisites and Permissions

### Who Can Assign Microsoft Discovery Roles

To assign Microsoft Discovery roles (Administrator, Contributor, or Reader), you must have the appropriate Azure RBAC permissions at the desired scope level. The following Azure built-in roles have the necessary permissions to assign Microsoft Discovery roles:

**Owner:**

- Can assign any Microsoft Discovery role at subscription, resource group, or workspace level
- Has full access to all resources including the right to delegate access to others
- Recommended for initial platform setup and governance

**User Access Administrator:**

- Can assign any Microsoft Discovery role at subscription, resource group, or workspace level
- Specifically designed for managing user access without requiring full resource management permissions
- Ideal for dedicated identity and access management teams

### Understanding Assignment Scopes

Microsoft Discovery roles can be assigned at different scope levels to provide flexible access control:

**Subscription Level:**

- Grants access to all Microsoft Discovery resources within the subscription
- Ideal for platform administrators who need broad access
- Best practice: Use sparingly and only for trusted administrators

**Resource Group Level:**

- Grants access to all Microsoft Discovery resources within a specific resource group
- Perfect for team-based access where multiple workspaces exist in the same resource group
- Recommended: Assign roles after the resource group containing Discovery resources is created

## What other roles are required

Apart from the Microsoft Discovery roles mentioned above, the user might require a few other roles assigned depending on use-cases. You can find the list below:

| Role | Scenario | Scope |
| --- | --- | --- |
| Managed Identity Contributor | To create, read, update, and delete managed identity resources (UAMI) | Subscription, Resource Group |
| Managed Identity Operator | To assign roles to the managed identity resource | Subscription, Resource Group, Resource |
| Storage Account Contributor | To create, read, update, and delete Azure storage account resources including blob containers | Subscription, Resource Group |
| Storage Blob Data Contributor | To upload, manage, and delete files within Azure blob storage containers | Subscription, Resource Group, Resource |
| Network Contributor | To create, read, update, and delete Virtual Network resources | Subscription, Resource Group |
| AcrPush | To upload tool or model images to Azure Container Registry | Subscription, Resource Group, Resource |
| Reader | To read API operation status for deployments | Subscription |

> **💡 Best Practice:** Start with assigning least privilege roles and scope to users and expand as required.

## Roles required for the user persona

From the roles and permissions listed above, each user persona could be assigned a combination of some of the roles that can help the user achieve their goals based on their requirements. You can also assign additional roles as required. Note that the roles listed below can be assigned at Subscription or Resource Group scope.

| Platform/IT Administrator | Scientist/Researcher | Reader/Viewer |
| --- | --- | --- |
| Microsoft Discovery Platform Administrator (Preview) | Microsoft Discovery Platform Contributor (Preview) | Microsoft Discovery Platform Reader (Preview) |
| Managed Identity Contributor | Storage Account Contributor | Reader |
| Managed Identity Operator | Storage Blob Data Contributor | |
| Storage Account Contributor | AcrPush | |
| Storage Blob Data Contributor | Reader (Subscription level) | |
| Network Contributor | | |
| AcrPush | | |
| Reader | | |

## Finding Available Roles

To discover the specific Microsoft Discovery roles available in your environment:

### Discovering Available Roles via Azure Portal

The Azure portal provides a user-friendly interface for discovering role assignments:

1. Navigate to your Microsoft Discovery resource
2. Select **"Access control (IAM)"** from the left navigation
3. Click **"Add"** → **"Add role assignment"**
4. Browse the available roles in the **"Role"** tab
5. Look for roles with "Discovery" or "Microsoft.Discovery" in the name

### Discovering Available Roles via Azure CLI

For programmatic discovery and automation:

```bash
# List all roles available for Microsoft Discovery resources
az role definition list --custom-role-only false | grep -i discovery

# Get detailed information about a specific Discovery role
az role definition show --name "Microsoft.Discovery/[RoleName]"
```

### Discovering Available Roles via PowerShell

For Windows environments and automation scripts:

```powershell
# Find Microsoft Discovery roles
Get-AzRoleDefinition | Where-Object {$_.Name -like "*Discovery*"}

# Get detailed role permissions
Get-AzRoleDefinition -Name "Microsoft.Discovery/[RoleName]" | Format-List
```

## Role Assignment Methods

### Using Azure Portal

The Azure portal provides a user-friendly interface for managing role assignments:

1. Navigate to the appropriate scope level:
   - **For workspace-level assignments:** Go to the specific Microsoft Discovery workspace
   - **For resource group-level assignments:** Go to the resource group containing Discovery resources
   - **For subscription-level assignments:** Go to the subscription overview
2. Select "Access control (IAM)" from the left menu
3. Click "Add role assignment"
4. Select the appropriate Microsoft Discovery role (Contributor, Reader, or Administrator)
5. Choose the scope (inherited from step 1) and select the principal (user, group, or service principal)
6. Add a meaningful description explaining the business justification
7. Review and create the assignment

> **⚠️ Important:** Ensure that workspaces and resource groups are fully provisioned before assigning workspace or resource group-scoped roles to avoid access issues.

### Using Azure CLI

For programmatic access and automation:

```bash
# Assign Platform Contributor role to a user at WORKSPACE level
az role assignment create \
  --assignee user@contoso.com \
  --role "Microsoft Discovery Platform Contributor (Preview)" \
  --scope "/subscriptions/{subscription-id}/resourceGroups/{rg-name}/providers/Microsoft.Discovery/workspaces/{workspace-name}"

# Assign Platform Reader role to a group at RESOURCE GROUP level
az role assignment create \
  --assignee-object-id {group-object-id} \
  --role "Microsoft Discovery Platform Reader (Preview)" \
  --scope "/subscriptions/{subscription-id}/resourceGroups/{rg-name}"

# Assign Platform Administrator role to a user at SUBSCRIPTION level
az role assignment create \
  --assignee user@contoso.com \
  --role "Microsoft Discovery Platform Administrator (Preview)" \
  --scope "/subscriptions/{subscription-id}"
```

### Using PowerShell

For Windows environments and automation scripts:

```powershell
# Assign Platform Administrator role to a group at RESOURCE GROUP level
New-AzRoleAssignment -ObjectId {group-object-id} `
  -RoleDefinitionName "Microsoft Discovery Platform Administrator (Preview)" `
  -Scope "/subscriptions/{subscription-id}/resourceGroups/{rg-name}"

# Assign Platform Contributor role to a user at WORKSPACE level
New-AzRoleAssignment -SignInName user@contoso.com `
  -RoleDefinitionName "Microsoft Discovery Platform Contributor (Preview)" `
  -Scope "/subscriptions/{subscription-id}/resourceGroups/{rg-name}/providers/Microsoft.Discovery/workspaces/{workspace-name}"

# Assign Platform Reader role to a user at SUBSCRIPTION level
New-AzRoleAssignment -SignInName user@contoso.com `
  -RoleDefinitionName "Microsoft Discovery Platform Reader (Preview)" `
  -Scope "/subscriptions/{subscription-id}"
```

## Additional Resources

- [Azure RBAC Documentation](https://learn.microsoft.com/en-us/azure/role-based-access-control/)
